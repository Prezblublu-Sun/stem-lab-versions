"""【冻结】从作业的结果导出数据：标签、界面场、整体场，推导量经 derive 算。写数据说明：每列的名字、单位、含义。
每行带点的哈希、骨标识、轮号、输入指纹、结局。清单里另记是哪个内核、哪份推导量定义算的（made_by）。

数据说明从两个包的清单里来：设计、条件、建模时就有的量、FE 算出的标量、场，由内核的清单说；
推导量由推导量定义的清单说。包没说清楚的，启动的检查里就不过。

一个作业一结束，它那一行就记进 work/ledger/rows/ 里；一轮收尾时把该进数据的各行合成一份数据。
以前的轮算出来、这一轮没有重排的行原样带进来，行上的轮号还是算它的那一轮。

推导量只从 derive() 这一处来：自由代码不算推导量，也不叫推导量定义。
导出设定里的 derive_timeout_s 是算一次推导量最多等多久，默认 600 秒。
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from plugins.fea import outcomes
from stemlab import hooks

ROWS, FIELDS, MANIFEST = "rows.jsonl", "fields", "manifest.json"
# 包的清单里的哪一项 -> 数据说明里的 role
GROUPS = (("design", "design"), ("conditions", "condition"), ("pre", "pre"), ("labels", "label"), ("fields", "field"))
DERIVED = ("columns", "derived")


def dumps(obj) -> bytes:
    """一行固定的字节：键排序、UTF-8、无空白、LF。"""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"


def read_manifest(folder) -> dict:
    return json.loads((Path(folder) / MANIFEST).read_bytes())


def described(listed) -> bool:
    """包清单里的一组列说明写得对不对：每列有名字、单位、含义。"""
    return isinstance(listed, list) and all(
        isinstance(column, dict) and all(isinstance(column.get(key), str) and column[key].strip() for key in ("name", "unit", "meaning"))
        for column in listed)


def problems(kernel: dict, derive: dict) -> list[str]:
    """两个包的清单能不能拼出一份数据说明。返回哪里不行；空列表就是行。"""
    found = [f"内核的清单里 {group} 要写成一组列的说明（name、unit、meaning）" for group, _ in GROUPS if not described(kernel.get(group))]
    if not described(derive.get("columns")) or not derive.get("columns"):
        found.append("推导量定义的清单要带 columns：它算出的各个量的说明（name、unit、meaning）")
    if found:
        return found
    names = [column["name"] for column in columns(kernel, derive)]
    return [f"列名重复了：{name}" for name in sorted({name for name in names if names.count(name) > 1})]


def maker(handle) -> dict:
    """这份数据是哪个内核、哪份推导量定义算的：写进数据的清单（made_by）。用数据的地方靠它拦住不同内核的数混在一起。"""
    return hooks.made_by(read_manifest(handle.input("kernel")), handle.input_info("kernel").hash,
                         read_manifest(handle.input("derive")), handle.input_info("derive").hash)


def columns(kernel: dict, derive: dict) -> list[dict]:
    """数据说明：每列的名字、单位、含义、role。"""
    listed = [dict(name=column["name"], unit=column["unit"], meaning=column["meaning"], role=role)
              for group, role in GROUPS for column in kernel[group]]
    return listed + [dict(name=column["name"], unit=column["unit"], meaning=column["meaning"], role=DERIVED[1])
                     for column in derive[DERIVED[0]]]


def row(job: dict, bone_id: str, number: int, outcome: str, result: dict, listed: list[dict]) -> dict:
    """一个作业的那一行。场的位置先记成盘上的文件，合成数据时才复制过去。"""
    point = job["point"]
    sources = {"design": point["design"], "condition": point["conditions"],
               "pre": (result.get("build") or {}).get("pre") or {},
               "label": (result.get("post") or {}).get("labels") or {} if outcome == "finished" else {},
               "derived": (result.get("derived") or {}) if outcome == "finished" else {}}
    values = {column["name"]: _plain(sources[column["role"]].get(column["name"])) for column in listed if column["role"] != "field"}
    fields = {}
    if outcome == "finished":
        given = (result.get("post") or {}).get("fields") or {}
        fields = {column["name"]: str(Path(result["dirs"]["post"]) / given[column["name"]])
                  for column in listed if column["role"] == "field" and column["name"] in given}
    return {"point": point["hash"], "bone_id": bone_id, "round": number, "fingerprint": job["fingerprint"],
            "outcome": outcome, "values": values, "fields": fields}


def _plain(value):
    """内核给的一个数。不是有限的数（NaN、无穷大）就当没有：数据里写 null，不写一个假的数。"""
    if isinstance(value, float) and value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def ledger(handle) -> Path:
    return handle.work_dir / "ledger" / "rows"


def keep(handle, job: dict, made: dict) -> None:
    """把一个结束了的作业的那一行记下来，它的场也抄一份放在旁边：之后作业自己的文件夹可以清掉。"""
    held = ledger(handle).parent / FIELDS / job["task"]
    if held.exists():
        shutil.rmtree(held)
    placed = {}
    for name, source in made["fields"].items():
        held.mkdir(parents=True, exist_ok=True)
        placed[name] = str(held / f"{name}{Path(source).suffix}")
        shutil.copyfile(source, placed[name])
    ledger(handle).mkdir(parents=True, exist_ok=True)
    (ledger(handle) / f"{job['task']}.json").write_bytes(dumps(dict(made, fields=placed)))


def remember(handle, job: dict, number: int, outcome: str, reason: str) -> None:
    """记下一个作业是怎么结束的、为什么。给图表看；判断不靠它。"""
    where = ledger(handle).parent / "why"
    where.mkdir(parents=True, exist_ok=True)
    (where / f"{job['task']}.json").write_bytes(dumps({"task": job["task"], "round": number, "outcome": outcome, "reason": reason}))


def collect(handle) -> dict:
    """现在该进数据的各行：任务名 -> 行。只要现状是进数据的结局的任务；行上的轮号是算出它的那一轮。"""
    rows = {}
    for name, task in sorted(handle.tasks().items()):
        path = ledger(handle) / f"{name}.json"
        if outcomes.in_data(task.outcome) and path.exists():
            made = json.loads(path.read_bytes())
            if made["round"] == task.round and made["outcome"] == task.outcome:
                rows[name] = made
    return rows


def write(folder: Path, rows: dict, listed: list[dict], bone_id: str, made_by: dict | None = None) -> Path:
    """把各行写成一份符合格式的数据：rows.jsonl、fields/ 下的场、清单。写完自己先核一遍。made_by 见 maker。"""
    folder = Path(folder)
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    files, lines = [ROWS], []
    for task, made in rows.items():
        placed = {}
        for name, source in made["fields"].items():
            rel = f"{FIELDS}/{task}/{name}{Path(source).suffix}"
            (folder / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, folder / rel)
            placed[name] = rel
            files.append(rel)
        lines.append(dumps(dict(made, fields=placed)))
    (folder / ROWS).write_bytes(b"".join(lines))
    manifest = {"format": 1, "kind": "data", "files": sorted(files, key=lambda rel: rel.encode("utf-8")),
                "count": len(rows), "columns": listed, "bone_id": bone_id}
    if made_by is not None:
        manifest["made_by"] = made_by
    (folder / MANIFEST).write_bytes(dumps(manifest))
    wrong = hooks.check_format("data", folder)
    if wrong:
        raise ValueError("导出的数据不符合格式：" + "；".join(wrong[:5]))
    return folder


# ---------------------------------------------------------------- 推导量

def _derive_home(handle, job: dict) -> Path:
    return handle.work_dir / "derive" / job["task"] / f"r{handle.round.number}"


def derive(handle, job: dict, result: dict, setting: dict) -> dict:
    """算这个作业的推导量：把内核后处理给的场、标签和建模时的量交给登记的推导量定义，等它算完。

    返回补上了 derived 的结果。只有后处理成了的作业才算；没算出来 derived 是 None，这个作业归成出错，
    原因留在推导量定义的输出文件夹的 log.txt 里（那个文件夹记进 dirs["derive"]，归档时留下）。
    自由代码交上来的结果里即使带着 derived，也不作数。
    """
    result = dict(result, derived=None)
    post, dirs = result.get("post") or {}, dict(result.get("dirs") or {})
    if result.get("lost") or post.get("status") != "ok" or not dirs.get("post"):
        return result
    home = _derive_home(handle, job)
    shutil.rmtree(home, ignore_errors=True)
    (home / "ask").mkdir(parents=True)
    asked = {"fields": {name: str(Path(dirs["post"]) / rel) for name, rel in (post.get("fields") or {}).items()},
             "labels": post.get("labels") or {}, "pre": (result.get("build") or {}).get("pre") or {}, "point": job["point"]}
    try:
        (home / "ask" / "job.json").write_bytes(json.dumps(asked, ensure_ascii=False).encode("utf-8"))
        answer = hooks.derive(handle.input_info("derive").id, home / "ask", home / "out", wait=True,
                              timeout=float(setting.get("derive_timeout_s", 600)))
        result["derived"] = answer.get("derived") if isinstance(answer, dict) else None
    except Exception as error:  # noqa: BLE001  推导量没算出来：FE 的结果还在，这个作业归成出错
        (home / "out").mkdir(parents=True, exist_ok=True)
        with open(home / "out" / "log.txt", "ab") as stream:
            stream.write(f"{type(error).__name__}: {error}\n".encode("utf-8"))
    result["dirs"] = dict(dirs, derive=str(home / "out"))
    return result


def release(handle, job: dict) -> None:
    """这个作业该留的都留好了：把算推导量用的文件夹清掉。"""
    shutil.rmtree(_derive_home(handle, job), ignore_errors=True)
