"""【冻结】记下策略的编号、种子、每样输入的编号；replay(实验, 轮) 拿这些重放出同一批点。

选点是一个纯的过程：交给策略的那份作业（job.json）定了，选出来的点就定了——种子也在那份作业里。
所以重放只要三样：哪份策略（登记的编号，核心照样核它的哈希）；那份作业（留一份在 work/ 里，它的哈希记进这一轮的来历，
被动过就认得出）；选完之后这里做的那几步（拦下不可行的、补全条件、算点的哈希，都是冻结的代码）。

重放是只读的：不往记录里写，策略跑在一个临时文件夹里。
"""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from plugins.opt import feasible
from stemlab import hooks

JOB = "job.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _kept(work_dir: Path, number: int) -> Path:
    return work_dir / "replay" / f"r{number}" / JOB


def hashes(rows, scratch: Path) -> list[str]:
    """这批点的哈希，按顺序。哈希由核心的 write_points 算，这里不另写一份算法。"""
    shutil.rmtree(scratch, ignore_errors=True)
    hooks.write_points(scratch, [dict(row, reason=row.get("reason") or "replay") for row in rows])
    return [row["hash"] for row in hooks.read_points(scratch)]


def record(handle, *, job: Path, strategy, seed: int, count: int, points: list[str]) -> dict:
    """选完点记一笔：哪份策略、种子、每样输入的编号、交给策略的那份作业的哈希、选出来的各点的哈希。"""
    kept = _kept(handle.work_dir, handle.round.number)
    kept.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(job, kept)
    inputs = {}
    for name in ("objective", "strategy", "pool", "defaults", "data", "predictor"):
        found = handle.input_info(name)
        inputs[name] = [info.id for info in (found if isinstance(found, list) else [found] if found is not None else [])]
    info = {"strategy": {"id": strategy.id, "hash": strategy.hash}, "seed": seed, "count": count, "job_sha256": _sha(kept),
            "inputs": inputs, "points": points}
    handle.provenance(replay=info)
    return info


def replay(experiment: str, number: int | None = None) -> dict:
    """把这个实验某一轮（默认最后一轮）的选点重放一遍。

    返回 {"same": 重放出来的是不是同一批点, "points": 重放出来的各点的哈希, "recorded": 当时记下的, "why": 不一样或重放不了的原因}。
    """
    given = hooks.look(experiment, number)
    try:
        info = next((extra["info"]["replay"] for extra in reversed(given.recorded)
                     if extra["source"] == "plugin" and "replay" in extra["info"]), None)
        if info is None:
            return {"same": False, "points": [], "recorded": [], "why": "这一轮没有记下选点：它没有选出点来"}
        job = _kept(given.work_dir, given.round.number)
        if not job.is_file() or _sha(job) != info["job_sha256"]:
            return {"same": False, "points": [], "recorded": info["points"], "why": "交给策略的那份作业不在了，或者被改过：重放不了"}
        asked = json.loads(job.read_bytes())
        with tempfile.TemporaryDirectory() as scratch:
            (Path(scratch) / "ask").mkdir()
            shutil.copyfile(job, Path(scratch) / "ask" / JOB)
            said = hooks.rerun(given, info["strategy"]["id"], Path(scratch) / "ask", Path(scratch) / "out")
            made, _ = feasible.points(said.get("chosen"), asked["candidates"], asked["objective"], asked["conditions"],
                                      asked["count"])
            again = hashes(made, Path(scratch) / "points") if made else []
        same = again == info["points"]
        return {"same": same, "points": again, "recorded": info["points"],
                "why": "" if same else "同一份策略、同一份作业，两次选出的点不一样：这份策略不可重放（多半是没用作业里的种子）"}
    finally:
        given.close()
