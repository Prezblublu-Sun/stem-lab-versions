"""所有文件夹形态的东西共用的清单，和落盘名字的规矩。

除了值，登记的东西都是一个文件夹，里面带一份 manifest.json：

    {"format": 1, "kind": "report", "files": ["summary.json", "plots/a.png"], ...这种格式自己的项}

    format   这种格式的版本号。用哪种格式由种类定，见 kinds.ITEM_KINDS
    kind     种类
    files    文件夹里除清单之外的全部文件：相对路径、正斜杠
    bone_id  骨标识。骨模型和候选骨模型必带，别的可以不带
    made_by  里面的数是哪个内核（和哪份推导量定义）算的。数据、一份预测、候选池、预测器带它，别的不用：
                 {"kernel": 内核是哪一个, "derive": 推导量定义是哪一个，没有推导量就是 null}
             内核的清单里写了 model（带 name），记的就是 model 原样，比如 {"name": "M1-3406-v1", "code_hash": …}；
             没写就记 {"package": 内核包的哈希}。推导量定义记 {"package": 它的包的哈希}。见 made_by()
             不同内核算出来的数不放在一起用：几样合起来用（几份数据一起训练、一起选点）的，见 mixed_makers()；
             两样一起用、但不合并的（预测器和候选池、一份预测和拿来复核的数据），见 maker_clash()

契约只核清单，和清单列的文件是不是都在。内容和清单对不对得上，由写它的那个冻结文件负责。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from stemlab.contract.hashing import canonical, list_tree
from stemlab.contract.kinds import ITEM_KINDS, VALUE
from stemlab.contract.layout import is_key, is_label
from stemlab.contract.versions import FORMATS, CannotUpcast, upcast

MANIFEST = "manifest.json"
MAX_PATH = 150      # 相对路径最长多少个字符。Windows 的路径默认有长度上限

_ALLOWED = re.compile(r"[A-Za-z0-9 !#$%&'()+,\-.;=@\[\]^_`{}~]+")       # ASCII 里 Windows 允许的那些
_DEVICES = {"con", "prn", "aux", "nul"} | {f"{name}{n}" for name in ("com", "lpt") for n in range(1, 10)}


def check_name(rel) -> str | None:
    """核对一个落盘的名字：ASCII、相对路径、正斜杠、不太长。对就返回 None，不对返回原因。"""
    if not isinstance(rel, str) or not rel:
        return f"名字必须是非空的字符串：{rel!r}"
    if len(rel) > MAX_PATH:
        return f"路径太长（{len(rel)} 个字符，最多 {MAX_PATH}）：{rel}"
    for part in rel.split("/"):
        if not _ALLOWED.fullmatch(part):
            return f"名字只能用 ASCII，不能用 \\ : * ? \" < > | 这些字符，也不能有空的一段：{rel!r}"
        if part in (".", "..") or part != part.strip() or part.endswith("."):
            return f"名字的每一段不能是 . 或 ..，不能以空格开头或结尾，不能以点结尾：{rel!r}"
        if part.split(".")[0].lower() in _DEVICES:
            return f"{part} 是 Windows 的保留名：{rel!r}"
    return None


def check_names(paths) -> list[str]:
    """核对一组落盘的名字：逐个核，再不分大小写查重。"""
    problems = [why for why in map(check_name, paths) if why]
    seen: dict[str, str] = {}
    for rel in paths:
        if not isinstance(rel, str):
            continue
        if rel.lower() in seen:
            problems.append(f"名字重复（不分大小写）：{seen[rel.lower()]!r} 和 {rel!r}")
        else:
            seen[rel.lower()] = rel
    return problems


def make_manifest(kind: str, files, **extra) -> dict:
    """写一份清单。extra 是这种格式自己的项。"""
    form = ITEM_KINDS[kind].format
    return {"format": FORMATS[form], "kind": kind, "files": sorted(files, key=lambda rel: rel.encode("utf-8")), **extra}


def write_manifest(folder, manifest: dict) -> None:
    """把清单按固定的字节写进文件夹。"""
    with open(Path(folder) / MANIFEST, "wb") as stream:
        stream.write(canonical(manifest) + b"\n")


def read_manifest(folder) -> dict:
    """读文件夹里的清单。没有清单、或清单不是一个 JSON 对象，报 ValueError。"""
    path = Path(folder) / MANIFEST
    try:
        manifest = json.loads(path.read_bytes().decode("utf-8"))
    except FileNotFoundError:
        raise ValueError(f"文件夹里没有 {MANIFEST}：{folder}") from None
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{MANIFEST} 读不出来：{error}") from None
    if not isinstance(manifest, dict):
        raise ValueError(f"{MANIFEST} 必须是一个 JSON 对象")
    return manifest


def check_manifest(kind: str, manifest: dict) -> list[str]:
    """核对清单里各种格式共用的那几项。"""
    problems = [f"清单缺 {key}" for key in ("format", "kind", "files") if key not in manifest]
    problems += [f"清单里的键要用小写字母、数字和下划线：{key!r}" for key in manifest if not is_key(key)]
    if problems:
        return problems
    form = ITEM_KINDS[kind].format
    if manifest["format"] != FORMATS[form]:
        problems.append(f"清单的格式版本是 {manifest['format']!r}，{form} 现在是第 {FORMATS[form]} 版")
    if manifest["kind"] != kind:
        problems.append(f"清单写的种类是 {manifest['kind']!r}，这里要的是 {kind}")
    files = manifest["files"]
    if not isinstance(files, list):
        return problems + ["清单的 files 必须是一个列表"]
    problems += check_names(files)
    if MANIFEST in files:
        problems.append(f"files 里不用列 {MANIFEST} 自己")
    bone_id = manifest.get("bone_id")
    if bone_id is not None and not is_label(bone_id):
        problems.append(f"骨标识要用 ASCII 的字母、数字和 . _ -：{bone_id!r}")
    if "made_by" in manifest:
        problems += _maker_problems(manifest["made_by"])
    return problems


# ---------------------------------------------------------------- 是哪个内核算的

def made_by(kernel: dict, kernel_hash: str, derive: dict | None = None, derive_hash: str | None = None) -> dict:
    """写进清单的 made_by。kernel、derive 是两个包的清单，kernel_hash、derive_hash 是它们登记时的哈希。"""
    model = kernel.get("model") if isinstance(kernel, dict) else None
    named = isinstance(model, dict) and isinstance(model.get("name"), str) and model["name"].strip()
    return {"kernel": dict(model) if named else {"package": kernel_hash},
            "derive": {"package": derive_hash} if derive_hash else None}


def _maker_problems(value) -> list[str]:
    if not isinstance(value, dict) or set(value) != {"kernel", "derive"}:
        return ['清单的 made_by 要写成 {"kernel": 内核是哪一个, "derive": 推导量定义是哪一个，没有就是 null}']
    found = []
    if not isinstance(value["kernel"], dict) or not value["kernel"]:
        found.append("清单的 made_by 里 kernel 要写成一个不空的对象")
    if value["derive"] is not None and (not isinstance(value["derive"], dict) or not value["derive"]):
        found.append("清单的 made_by 里 derive 要写成一个不空的对象，没有推导量定义就写 null")
    return found


def _said(made: dict) -> str:
    """说给人听的：内核的名字，或者内核包哈希的前 12 位。"""
    kernel = made["kernel"]
    if isinstance(kernel.get("name"), str):
        return kernel["name"]
    if isinstance(kernel.get("package"), str):
        return f"内核包 {kernel['package'][:12]}"
    return json.dumps(kernel, ensure_ascii=False, sort_keys=True)


def mixed_makers(items) -> list[str]:
    """几样东西里的数要合在一起用（几份数据一起训练、一起选点）：得是同一个内核算的；推导量定义也得是同一份
    （记了推导量定义的那几样之间比，没有推导量的不比）。只有一样就不用比。

    items 是 [(怎么称呼它, 它清单里的 made_by，没记就是 None)]。返回为什么不行；空列表就是行。
    """
    items = list(items)
    if len(items) < 2:
        return []
    found = [f"{what}没有记是哪个内核算的，不能和别的放在一起用" for what, made in items if made is None]
    if found:
        return found
    (first_what, first), derived = items[0], [(what, made["derive"]) for what, made in items if made["derive"] is not None]
    found = [f"{what}是 {_said(made)} 算的，{first_what}是 {_said(first)} 算的：不同内核算出来的数不能放在一起用"
             for what, made in items[1:] if made["kernel"] != first["kernel"]]
    found += [f"{what}和{derived[0][0]}的推导量不是同一份推导量定义算的，不能放在一起用"
              for what, derive in derived[1:] if derive != derived[0][1]]
    return found


def maker_clash(one, other) -> str | None:
    """两样东西一起用、但不合并（预测器和候选池、一份预测和拿来复核的数据）：两边都记了，又不是同一个内核，就不行；
    两边都有推导量、又不是同一份推导量定义算的，也不行。有一边没记，就没法比，不拦。
    one、other 是 (怎么称呼它, made_by 或 None)。行就返回 None，不行返回为什么。"""
    (what, made), (other_what, theirs) = one, other
    if made is None or theirs is None:
        return None
    if made["kernel"] != theirs["kernel"]:
        return f"{what}是 {_said(made)} 算的，{other_what}是 {_said(theirs)} 算的：不是同一个内核，不能一起用"
    if made["derive"] is not None and theirs["derive"] is not None and made["derive"] != theirs["derive"]:
        return f"{what}和{other_what}的推导量不是同一份推导量定义算的，不能一起用"
    return None


def check_format(kind: str, folder) -> list[str]:
    """核对一个文件夹是不是这个种类该有的样子。返回哪里不符；空列表就是对的。

    读到比自己新的格式版本时报 versions.NewerFormat，不当成坏数据。
    """
    from stemlab.contract.formats import bone_model, data, package, points     # 它们都用到这个文件，所以在这里才 import

    item_kind = ITEM_KINDS.get(kind)
    if item_kind is None:
        return [f"登记的种类里没有 {kind!r}"]
    if item_kind.form == VALUE:
        return [f"{kind} 是一个值，不是文件夹"]
    if not Path(folder).is_dir():
        return [f"不是文件夹：{folder}"]
    try:
        manifest = read_manifest(folder)
    except ValueError as error:
        return [str(error)]
    try:
        manifest = upcast(item_kind.format, manifest)
    except CannotUpcast as error:
        return [str(error)]
    problems = check_manifest(kind, manifest)
    if problems:
        return problems

    try:
        listed, present = set(manifest["files"]), set(list_tree(folder)) - {MANIFEST}
    except (ValueError, OSError) as error:          # 里面有链接或交接点，或者有读不了的地方
        return [str(error)]
    problems += [f"清单列了但文件夹里没有：{rel}" for rel in sorted(listed - present)]
    problems += [f"文件夹里有但清单没列：{rel}" for rel in sorted(present - listed)]
    if problems:
        return problems
    specific = {"points": points.check, "bone_model": bone_model.check, "data": data.check, "package": package.check}
    check = specific.get(item_kind.format)
    return check(kind, manifest, folder) if check else []
