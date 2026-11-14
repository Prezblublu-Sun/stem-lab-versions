"""【冻结】一个作业留下什么：网格、每一步的场、求解过程、求解设置。失败前算出来的步也留。写归档清单。

留下的文件分四类（what）：
    mesh       网格
    fields     每一步的场
    process    求解过程：求解器的日志，内核两次调用的日志和它说的话
    settings   求解设置：交给求解器的输入
哪些文件属于哪一类由内核的后处理说（result 里的 keep）。内核两次调用自己的日志和 result 一律留。
求解过了、后处理却没说该留什么（比如它自己崩了）的作业，求解文件夹里的东西全留：宁可多留，不丢失败前算出来的步。

留下的文件复制到归档的地方：默认在这个实验的 work/archive/ 下；导出设定里写了 archive_root 就放到那里。
归档清单（index.jsonl）一行一个文件：哪个任务、哪一轮、哪个点、输入指纹、哪一类、相对归档根目录的位置、大小、SHA-256。
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from plugins.fea import export

INDEX, MANIFEST = "index.jsonl", "manifest.json"
WHAT = ("mesh", "fields", "process", "settings")
OWN = ("result.json", "log.txt")        # 内核每次调用自己留下的两样


def root(handle, setting: dict) -> Path:
    """归档放在哪。"""
    given = setting.get("archive_root")
    return Path(given) / handle.experiment if given else handle.work_dir / "archive"


def ledger(handle) -> Path:
    return handle.work_dir / "ledger" / "kept"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def wanted(result: dict) -> list[tuple[str, Path, str]]:
    """这个作业该留哪些文件：（哪一类，盘上的文件，留下时叫什么）。"""
    dirs = result.get("dirs") or {}
    found = []
    for stage in ("build", "post", "derive"):
        if dirs.get(stage):
            found += [("process", Path(dirs[stage]) / name, f"{stage}-{name}") for name in OWN]
    solve = Path(dirs["solve"]) if dirs.get("solve") else None
    said = (result.get("post") or {}).get("keep")
    if solve is not None and isinstance(said, dict):
        found += [(what, solve / rel, rel) for what in WHAT for rel in said.get(what) or [] if isinstance(rel, str)]
    elif solve is not None and solve.is_dir():
        found += [("process", path, path.relative_to(solve).as_posix()) for path in sorted(solve.rglob("*")) if path.is_file()]
    return [(what, path, name) for what, path, name in found if path.is_file()]


def keep(handle, job: dict, number: int, result: dict, setting: dict) -> list[dict]:
    """把一个结束了的作业该留的文件复制到归档的地方，记下每个文件的哈希。返回它在归档清单里的各行。"""
    base = root(handle, setting)
    rows = []
    for what, source, name in wanted(result):
        rel = f"r{number}/{job['task']}/{what}/{name}"
        target = base / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        rows.append({"task": job["task"], "round": number, "point": job["point"]["hash"], "fingerprint": job["fingerprint"],
                     "what": what, "file": rel, "size": target.stat().st_size, "sha256": _sha256(target)})
    ledger(handle).mkdir(parents=True, exist_ok=True)
    (ledger(handle) / f"{job['task']}-r{number}.json").write_bytes(export.dumps(rows))
    return rows


def write(folder: Path, handle, setting: dict, bone_id: str) -> Path:
    """写归档清单：到现在为止这个实验留下的全部文件。"""
    folder = Path(folder)
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    rows = [row for path in sorted(ledger(handle).glob("*.json")) for row in json.loads(path.read_bytes())]
    (folder / INDEX).write_bytes(b"".join(export.dumps(row) for row in rows))
    manifest = {"format": 1, "kind": "archive", "files": [INDEX], "bone_id": bone_id,
                "root": str(root(handle, setting)), "count": len(rows), "what": list(WHAT)}
    (folder / MANIFEST).write_bytes(export.dumps(manifest))
    return folder
