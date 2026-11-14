"""【自由】自动重建——另一种写法（测试用）。

和 plugins/recon/rebuild.py 的接口一样，写法全不一样：不起进程，一轮开头当场把活干完，结果放在一个文件里。
用来验蓝图的那一条：把 rebuild.py 整个换一份写法，格式核对和检查门照过。
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from plugins.recon import landmarks, review, solids, sources

REWRITTEN = True
PARTS = ("cortical", "cancellous")


def _kept(handle, mode: str) -> Path:
    return handle.work_dir / "redone" / f"{mode}-round{handle.round.number}.json"


def check(handle, mode: str) -> str | None:
    if mode != "draft":
        given = handle.input("edits")
        wrong = review.edit_problems(Path(given)) if given is not None else []
        return ("人工修改写得不对：" + "；".join(wrong)) if wrong else None
    folder, named = Path(handle.input("source")), handle.input("setting").get("source")
    what = sources.kind_of(folder)
    if what == "ct":
        return "这份骨源是 CT，1.0 不重建 CT 骨源，只重建 CAD 的"
    if what != "cad":
        return "这份骨源里没有 STEP 文件，认不出来"
    if not isinstance(named, dict) or sorted(named) != sorted(PARTS):
        return f"重建设定的 source 要写 {list(PARTS)} 各是骨源里的哪个文件"
    absent = [str(named[part]) for part in PARTS if not (folder / str(named[part])).is_file()]
    return f"骨源里找不到这几个文件：{absent}" if absent else None


def _measured(meshes: dict, found: dict) -> dict:
    numbers = dict(found["measures"], neck_axis_converged=found["neck_converged"])
    for part in PARTS:
        numbers[f"{part}_volume_mm3"] = meshes[part]["volume"]
        numbers[f"{part}_solids"] = meshes[part]["solids"]
        numbers[f"{part}_watertight"] = sources.watertight(meshes[part])
    centre = found["landmarks"]["neck_center"]["xyz"]
    wall = landmarks.wall_thickness(meshes["cortical"], centre, found["neck_axis"], centre)
    if wall:
        numbers["neck_wall_min_mm"], numbers["neck_wall_median_mm"] = wall["min_mm"], wall["median_mm"]
    return numbers


def _work(handle, mode: str) -> dict:
    setting = handle.input("setting")
    size = float(setting.get("tessellation_mm", 4.0))
    if mode == "draft":
        files = solids.from_cad(Path(handle.input("source")), setting["source"])
        marks, history, before = None, [{"step": "import", "what": "CAD 骨源的两个实体，原样拿来"},
                                        {"step": "landmarks", "what": "五个标志点是自动找的"}], {}
    else:
        draft = Path(handle.input("draft"))
        listed = json.loads((draft / "manifest.json").read_bytes())
        given = handle.input("edits")
        files, marks, history = review.apply(listed, draft, None if given is None else Path(given))
        before = listed.get("measures") or {}
    meshes = {part: sources.read_step(files[part], size) for part in PARTS}
    found = landmarks.find(meshes["cortical"], setting["side"])
    numbers = _measured(meshes, found)
    if marks is None:
        marks, todo = found["landmarks"], review.todo(found, numbers)
    else:
        todo = []
        for part in PARTS:
            old = before.get(f"{part}_volume_mm3")
            numbers[f"{part}_volume_change"] = abs(numbers[f"{part}_volume_mm3"] - old) / old if old else None
        apart = {name: math.dist(marks[name]["xyz"], point["xyz"]) for name, point in found["landmarks"].items() if name in marks}
        numbers["landmark_shift_max_mm"] = max(apart.values())
        numbers.update({f"{name}_shift_mm": value for name, value in apart.items()})
    return {"status": "ok", "reason": "", "solids": {part: str(files[part]) for part in PARTS}, "landmarks": marks,
            "measures": numbers, "history": history, "todo": todo, "timings": {}}


def begin(handle, mode: str) -> None:
    try:
        result = _work(handle, mode)
    except Exception as error:  # noqa: BLE001
        result = {"status": "error", "reason": f"{type(error).__name__}: {error}"}
    kept = _kept(handle, mode)
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_text(json.dumps(result, ensure_ascii=False, default=float), encoding="utf-8")


def advance(handle, mode: str) -> dict:
    here = next(machine.name for machine in handle.machines if machine.role == "desk")
    try:
        result = json.loads(_kept(handle, mode).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        result = {"status": "error", "reason": "找不到重建的结果"}
    return {"stage": "done", "machine": here, "result": result}


def halt(handle, mode: str) -> None:
    """当场干完的，没有在跑的东西可停。"""
