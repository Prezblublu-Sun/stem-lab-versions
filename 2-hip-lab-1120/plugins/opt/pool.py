"""【自由】在设计范围里取设计，经 run_kernel 做模板化，记下每个设计可不可行。

怎么取由设计范围里的 method 说，不写就是 lhs。只取几个值的项（{"values": [...]}）哪种取法都是随机挑一个。
    lhs      拉丁超立方：每一项把范围切成 count 段，各段取一个，打乱了配对。每一项上都铺得匀
    sobol    Sobol 序列（打乱过的）：整个范围里铺得匀，以后想加点可以接着往下取
    random   每一项各自在范围里随机取
    around   围着给的几个设计取：另写 centers（一组设计）和 spread（默认 0.1）。
             每个数值项在“中心 ± spread × 这一项的范围宽度”里随机取，出了范围的截回来；只取几个值的项照中心的。
             中心自己排在最前面，也进候选池。用在已经有了好设计、想在它附近细找的时候
随机只用设计范围里的 seed，所以同一份设计范围取出来的是同一批设计。
模板化交给内核的 template 做法，脱离出去跑；可不可行由内核说，插件直接读内核的结果。
"""
from __future__ import annotations

import json
import random
import warnings
from pathlib import Path

import psutil

from stemlab import hooks

METHODS = ("lhs", "sobol", "random", "around")


def _home(handle) -> Path:
    return handle.work_dir / "pool" / f"r{handle.round.number}"


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def problems(space: dict) -> list[str]:
    """设计范围里“怎么取”那几项写得对不对。范围本身（design、count、seed）由冻结的代码核，不在这里。"""
    method = space.get("method", "lhs")
    if method not in METHODS:
        return [f"设计范围的 method 只有 {list(METHODS)}，写的是 {method!r}"]
    if method != "around":
        return []
    found, centers, width = [], space.get("centers"), space.get("spread", 0.1)
    if not _number(width) or not 0 < width <= 1:
        found.append("method 是 around 时，spread 要在 0 和 1 之间：围着中心取多宽，按这一项范围宽度的比例算")
    if not isinstance(centers, list) or not centers:
        return found + ["method 是 around 时要写 centers：围着哪几个设计取，至少一个"]
    for number, center in enumerate(centers, start=1):
        if not isinstance(center, dict) or sorted(center) != sorted(space["design"]):
            found.append(f"centers 的第 {number} 个，设计项要和设计范围里的一样：{sorted(space['design'])}")
            continue
        for name, limits in space["design"].items():
            inside = center[name] in limits["values"] if isinstance(limits, dict) else _number(center[name]) and limits[0] <= center[name] <= limits[1]
            if not inside:
                found.append(f"centers 的第 {number} 个，{name}={center[name]!r} 不在设计范围里")
    return found


def check(handle) -> str | None:
    found = problems(handle.input("range"))
    return "；".join(found) if found else None


def _named(rows: list) -> list[dict]:
    return [{"name": f"c{index + 1:04d}", "design": design} for index, design in enumerate(rows)]


def _around(space: dict, rng: random.Random, count: int) -> list[dict]:
    centers, width = space["centers"], space.get("spread", 0.1)
    rows = [dict(center) for center in centers[:count]]
    for index in range(count - len(rows)):
        center, design = centers[index % len(centers)], {}
        for name in sorted(space["design"]):
            limits = space["design"][name]
            if isinstance(limits, dict):
                design[name] = center[name]
            else:
                low, high = limits
                half = width * (high - low)
                design[name] = round(rng.uniform(max(low, center[name] - half), min(high, center[name] + half)), 6)
        rows.append(design)
    return _named(rows)


def designs(space: dict) -> list[dict]:
    """照设计范围取 count 个设计：[{"name", "design"}]。"""
    rng, count, method = random.Random(space["seed"]), space["count"], space.get("method", "lhs")
    if method == "around":
        return _around(space, rng, count)
    ranged = [name for name in sorted(space["design"]) if not isinstance(space["design"][name], dict)]
    sequence = None
    if method == "sobol" and ranged:
        from scipy.stats import qmc

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")                 # count 不是 2 的整数次幂时它会提醒“铺得没那么匀”，照取
            sequence = qmc.Sobol(d=len(ranged), scramble=True, seed=space["seed"]).random(count)
    columns = {}
    for name in sorted(space["design"]):
        limits = space["design"][name]
        if isinstance(limits, dict):
            columns[name] = [rng.choice(limits["values"]) for _ in range(count)]
            continue
        low, high = limits
        if method == "sobol":
            cells = [low + (high - low) * float(unit) for unit in sequence[:, ranged.index(name)]]
        elif method == "random":
            cells = [rng.uniform(low, high) for _ in range(count)]
        else:
            cells = [low + (high - low) * (index + rng.random()) / count for index in range(count)]
            rng.shuffle(cells)
        columns[name] = [round(value, 6) for value in cells]
    return _named([{name: columns[name][index] for name in columns} for index in range(count)])


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
