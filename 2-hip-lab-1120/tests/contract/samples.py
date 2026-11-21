"""契约测试共用的样本：每种条目一条对的，和走到各个状态的几串记录。"""
from __future__ import annotations

from stemlab.contract.chain import GENESIS, Head, link

T0 = "2026-01-01T00:00:00.000Z"
H1 = "1" * 64
H2 = "2" * 64

INPUTS = [
    {"name": "setting", "kinds": ["setting"], "many": False, "required": True, "label": "设定"},
    {"name": "extra", "kinds": ["report", "edits"], "many": True, "required": False, "label": "附带的"},
]
OUTPUTS = [{"name": "report", "kind": "report", "label": "报告"}]
OUTCOMES = [
    {"name": "finished", "category": "ok", "label": "算完"},
    {"name": "misfit", "category": "conclusion", "label": "放不进去"},
    {"name": "env", "category": "retryable", "label": "环境问题"},
    {"name": "diverged", "category": "unclear", "label": "不收敛"},
]
PROVENANCE = {
    "commit": "0123abc", "clean": True, "frozen": H1, "plugin": "demo", "plugin_hash": H1,
    "plugin_frozen": H2, "plugin_dirty": False, "contract": 1, "python": "3.12.10", "lock": H2, "host": "win",
}
EXTERNAL = {"from": "external", "note": "手写的示范设定", "by": "tester"}
INFO = {"id": "R0001", "kind": "setting", "name": "demo-setting", "version": 1, "hash": H1,
        "origin": EXTERNAL, "bone_id": None}


def entry(name: str, **fields) -> dict:
    return {"format": 1, "time": T0, "entry": name, **fields}


def created(**over) -> dict:
    return entry("created", **{"type": "demo.echo", "inputs": INPUTS, "outputs": OUTPUTS, "outcomes": OUTCOMES,
                               "note": "示范", "tags": ["示范"], **over})


def filled(name="setting", items=("R0001",)) -> dict:
    return entry("filled", input=name, items=list(items))


def frozen() -> dict:
    return entry("frozen", inputs={"setting": [INFO], "extra": []}, register_head={"seq": 1, "this": H1})


def round_opened(number=1, rerun=()) -> dict:
    return entry("round_opened", round=number, provenance=dict(PROVENANCE), rerun=list(rerun))


def called(number=1, action="start", ok=True) -> dict:
    return entry("called", round=number, action=action, ok=ok, error=None if ok else "RuntimeError: 出错了")


def task(number=1, name="p1", state="queued", outcome=None, stage=None) -> dict:
    return entry("task", round=number, task=name, state=state, outcome=outcome, stage=stage,
                 machine=None, fingerprint=None)


def output(number=1, name="report", item="R0002") -> dict:
    return entry("output", round=number, output=name, item=item, hash=H2)


def problem(number=1, error="ValueError: 坏了", **over) -> dict:
    return entry("problem", round=number, error=error, task=None, raw=None, **over)


def provenance(number=1) -> dict:
    return entry("provenance", round=number, source="plugin", info={"solver": "demo 1.0"})


def round_closed(number=1, result="done") -> dict:
    return entry("round_closed", round=number, result=result, reason="")


def noted() -> dict:
    return entry("noted", text="一条备注")


def tagged() -> dict:
    return entry("tagged", add=["重要"], remove=[])


# 每种条目一条对的
GOOD = {
    "created": created(), "filled": filled(), "frozen": frozen(), "round_opened": round_opened(),
    "called": called(), "task": task(), "output": output(), "problem": problem(),
    "provenance": provenance(), "round_closed": round_closed(), "noted": noted(), "tagged": tagged(),
}

_OPEN = [created(), filled(), frozen(), round_opened()]
_RUN = _OPEN + [called()]

# 走到各个状态的记录
HISTORIES = {
    "none": [],
    "new": [created(), filled()],
    "new_frozen": [created(), filled(), frozen()],
    "starting": _OPEN,
    "starting_erred": _OPEN + [called(ok=False)],
    "running": _RUN,
    "running_stop_called": _RUN + [called(action="stop")],
    "ended_done": _RUN + [task(state="done", outcome="finished"), round_closed()],
    "ended_done_retry": _RUN + [task(state="failed", outcome="env"), round_closed()],
    "ended_done_unclear": _RUN + [task(state="failed", outcome="diverged"), round_closed()],
    "ended_failed": _RUN + [round_closed(result="failed")],
    "ended_stopped": _RUN + [called(action="stop"), round_closed(result="stopped")],
    "ended_start_failed": _OPEN + [called(ok=False), round_closed(result="start_failed")],
}


def chained(bodies) -> list[dict]:
    """把一串条目接成链。"""
    head, out = GENESIS, []
    for body in bodies:
        linked = link(body, head)
        head = Head(linked["seq"], linked["this"])
        out.append(linked)
    return out
