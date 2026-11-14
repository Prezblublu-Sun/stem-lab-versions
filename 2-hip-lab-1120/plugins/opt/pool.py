"""【自由】在设计范围里取设计，经 run_kernel 做模板化，记下每个设计可不可行。

取设计：连续的项用拉丁超立方（每一项把范围切成 count 段，各段取一个，打乱了配对），只取几个值的项随机挑。
随机只用设计范围里的 seed，所以同一份设计范围取出来的是同一批设计。
模板化交给内核的 template 做法，脱离出去跑；可不可行由内核说，插件直接读内核的结果。
"""
from __future__ import annotations

import json
import random
from pathlib import Path

import psutil

from stemlab import hooks


def _home(handle) -> Path:
    return handle.work_dir / "pool" / f"r{handle.round.number}"


def check(handle) -> None:
    return None


def designs(space: dict) -> list[dict]:
    """照设计范围取 count 个设计：[{"name", "design"}]。"""
    rng, count = random.Random(space["seed"]), space["count"]
    columns = {}
    for name in sorted(space["design"]):
        limits = space["design"][name]
        if isinstance(limits, dict):
            columns[name] = [rng.choice(limits["values"]) for _ in range(count)]
        else:
            low, high = limits
            cells = [low + (high - low) * (index + rng.random()) / count for index in range(count)]
            rng.shuffle(cells)
            columns[name] = [round(value, 6) for value in cells]
    return [{"name": f"c{index + 1:04d}", "design": {name: columns[name][index] for name in columns}} for index in range(count)]


def begin(handle) -> None:
    home = _home(handle)
    (home / "ask").mkdir(parents=True, exist_ok=True)
    made = designs(handle.input("range"))
    job = {"mode": "template", "bone_model": str(handle.input("bone")), "bone_id": handle.input_info("bone").bone_id,
           "designs": made, "settings": handle.input("range").get("settings") or {}}
    (home / "ask" / "job.json").write_bytes(json.dumps(job, ensure_ascii=False).encode("utf-8"))
    process = hooks.run_kernel(handle.input_info("kernel").id, home / "ask", home / "out", wait=False)
    (home / "state.json").write_bytes(json.dumps({"process": process, "designs": made}).encode("utf-8"))


def advance(handle) -> dict:
    home = _home(handle)
    try:
        state = json.loads((home / "state.json").read_bytes())
    except (OSError, ValueError):
        return {"stage": "done", "result": {"status": "error", "reason": "模板化没有派出去"}}
    if hooks.alive(state["process"]):
        return {"stage": "templating", "result": None}
    if (home / "out" / "result.json").is_file():
        return {"stage": "done", "result": {"status": "ok", "reason": "", "designs": state["designs"], "template": str(home / "out")}}
    log = home / "out" / "log.txt"
    said = log.read_bytes()[-600:].decode("utf-8", "replace") if log.exists() else ""
    restarted = psutil.boot_time() > state["process"]["created"]
    return {"stage": "done", "result": {"status": "env" if restarted else "error",
                                        "reason": "机器重启过，模板化的进程没了" if restarted else f"内核没有留下结果：{said}"}}


def halt(handle) -> None:
    try:
        hooks.kill(json.loads((_home(handle) / "state.json").read_bytes())["process"])
    except (OSError, ValueError, KeyError):
        pass
