"""【自由】把活交给重建方法包——另一种写法（测试用）。

和 plugins/recon/rebuild.py 的接口一样，写法全不一样：不起脱离出去的进程，一轮开头当场等方法包干完，结果放在一个文件里。
用来验蓝图的那一条：把 rebuild.py 整个换一份写法，格式核对和检查门照过。
"""
from __future__ import annotations

import json
from pathlib import Path

from plugins.recon import review
from stemlab import hooks

REWRITTEN = True


def _kept(handle, mode: str) -> Path:
    return handle.work_dir / "redone" / f"{mode}-round{handle.round.number}"


def check(handle, mode: str) -> str | None:
    given = handle.input("edits") if mode == "finalize" else None
    wrong = review.edit_problems(Path(given)) if given is not None else []
    return ("人工修改写得不对：" + "；".join(wrong)) if wrong else None


def begin(handle, mode: str, job: dict) -> None:
    kept = _kept(handle, mode)
    (kept / "ask").mkdir(parents=True, exist_ok=True)
    (kept / "ask" / "job.json").write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    try:
        result = hooks.run_recon(handle.input_info("method").id, kept / "ask", kept / "out")
    except Exception as error:  # noqa: BLE001
        result = {"status": "error", "reason": f"{type(error).__name__}: {error}"}
    (kept / "result.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


def advance(handle, mode: str) -> dict:
    here = next(machine.name for machine in handle.machines if machine.role == "desk")
    try:
        result = json.loads((_kept(handle, mode) / "result.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        result = {"status": "error", "reason": "找不到方法包的结果"}
    return {"stage": "done", "machine": here, "result": result}


def halt(handle, mode: str) -> None:
    """当场干完的，没有在跑的东西可停。"""
