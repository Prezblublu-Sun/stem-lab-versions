"""【自由】自动重建——一份写得马虎的（测试用）。

接口是对的，活干得不对：出候选时少找一个标志点；定稿时把候选原样递上去，什么都不量。
用来验蓝图那一条的后一半：把 rebuild.py 整个换一份写法，……或者如实不过。
冻结的写出格式（model.py）和检查门（gate.py）不让它混过去。
"""
from __future__ import annotations

import json
from pathlib import Path

REWRITTEN = "careless"
PARTS = ("cortical", "cancellous")
FOUND = ("head_center", "neck_center", "shaft_proximal", "shaft_distal")        # 小转子忘了找


def check(handle, mode: str) -> None:
    return None


def begin(handle, mode: str) -> None:
    pass


def advance(handle, mode: str) -> dict:
    here = next(machine.name for machine in handle.machines if machine.role == "desk")
    if mode == "draft":
        source, named = Path(handle.input("source")), handle.input("setting")["source"]
        marks = {name: {"xyz": [0.0, 0.0, 10.0 * number], "definition": "随手估的"} for number, name in enumerate(FOUND)}
        result = {"solids": {part: str(source / named[part]) for part in PARTS}, "landmarks": marks,
                  "history": [{"step": "import", "what": "原样拿来"}]}
    else:
        draft = Path(handle.input("draft"))
        listed = json.loads((draft / "manifest.json").read_bytes())
        result = {"solids": {part: str(draft / listed["solids"][part]["file"]) for part in PARTS}, "landmarks": listed["landmarks"],
                  "history": listed["history"]}
    return {"stage": "done", "machine": here, "result": dict(result, status="ok", reason="", measures={}, todo=[], timings={})}


def halt(handle, mode: str) -> None:
    pass
