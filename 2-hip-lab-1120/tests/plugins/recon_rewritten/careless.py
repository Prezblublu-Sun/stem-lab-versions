"""【自由】把活交给重建方法包——一份写得马虎的（测试用）。

接口是对的，活干得不对：不叫方法包，自己编一份结果。出候选时少找一个标志点；定稿时把候选原样递上去，什么都不量。
用来验蓝图那一条的后一半：把 rebuild.py 整个换一份写法，……或者如实不过。
冻结的写出格式（model.py）和检查门（gate.py）不让它混过去。
"""
from __future__ import annotations

from pathlib import Path

from stemlab import hooks

REWRITTEN = "careless"
PARTS = ("cortical", "cancellous")
FOUND = ("head_center", "neck_center", "shaft_proximal", "shaft_distal")        # 小转子忘了找


def check(handle, mode: str) -> None:
    return None


def begin(handle, mode: str, job: dict) -> None:
    pass


def advance(handle, mode: str) -> dict:
    here = next(machine.name for machine in handle.machines if machine.role == "desk")
    if mode == "draft":
        source = Path(handle.input("source"))
        regions = [{"name": part, "role": part, "geometry": {"kind": "solid", "format": "step", "file": str(source / f"{part}.step")},
                    "volume_mm3": 1.0, "material": {"model": "elastic", "E": 1000.0, "nu": 0.3}} for part in PARTS]
        marks = {name: {"xyz": [0.0, 0.0, 10.0 * number], "definition": {"method": "guess", "version": "1", "params": {}}, "fit": {}}
                 for number, name in enumerate(FOUND)}
        result = {"how": "cad", "side": "right", "bone_type": "real", "coverage": {"extent": "whole", "proximal_mm": 1.0, "distal_mm": 1.0},
                  "frame": {"file": "随手估的"}, "regions": regions, "landmarks": marks, "history": [{"step": "import", "what": "原样拿来"}]}
    else:
        draft = Path(handle.input("draft"))
        listed = hooks.read_bone_model(draft)
        regions = [dict(region, geometry=dict(region["geometry"], file=str(draft / region["geometry"]["file"]))) for region in listed["regions"]]
        result = {"how": listed["source"]["how"], "side": listed["side"], "bone_type": listed["bone_type"], "coverage": listed["coverage"],
                  "frame": {"file": listed["frame"]["file"]}, "regions": regions, "landmarks": listed["landmarks"],
                  "history": listed["history"]}
    return {"stage": "done", "machine": here, "result": dict(result, status="ok", reason="", measures={}, todo=[], timings={})}


def halt(handle, mode: str) -> None:
    pass
