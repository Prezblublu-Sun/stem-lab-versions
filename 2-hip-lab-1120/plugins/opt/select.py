"""【自由】一次选点：经 run_strategy 跑策略，过可行性，写理由，补全条件，经 write_points 写出。

这里做前半截：把交给策略的那份作业备好，跑策略，把它选的交回去。后半截（过可行性、补全条件、写出、记下来好重放）
在冻结的 plugin.py、feasible.py、replay.py 里，这样换一份策略、换一种写法，那几条规矩都还在。

走两步，都脱离出去跑：
    predict     填了预测器才有：让它对候选池里可行的候选（配上条件默认）出预测
    strategy    把目标、候选、条件默认、个数、种子、数据的位置、预测交给策略，等它选
交给策略的作业长什么样，写在 stemlab/contract/formats/package.py 里。
"""
from __future__ import annotations

import json
from pathlib import Path

import psutil

from plugins.opt import inputs
from stemlab import hooks


def _home(handle) -> Path:
    return handle.work_dir / "select" / f"r{handle.round.number}"


def _save(home: Path, state: dict) -> None:
    (home / "state.json").write_bytes(json.dumps(state).encode("utf-8"))


def _strategy(handle, home: Path, predictions) -> dict:
    how = handle.input("defaults")
    job = {"objective": handle.input("objective"), "candidates": inputs.candidates(handle), "conditions": how["conditions"],
           "count": how["count"], "seed": how["seed"], "data": [str(folder) for folder in handle.input("data")],
           "predictions": predictions}
    (home / "ask").mkdir(parents=True, exist_ok=True)
    (home / "ask" / "job.json").write_bytes(json.dumps(job, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    return {"step": "strategy", "process": hooks.run_strategy(handle.input_info("strategy").id, home / "ask", home / "out", wait=False)}


def begin(handle) -> None:
    home = _home(handle)
    home.mkdir(parents=True, exist_ok=True)
    if handle.input("predictor") is None:
        _save(home, _strategy(handle, home, None))
        return
    conditions = handle.input("defaults")["conditions"]
    points = [{"hash": row["name"], "bone_id": row["bone_id"], "design": row["design"], "conditions": conditions}
              for row in inputs.candidates(handle) if row["feasible"]]
    (home / "predict-ask").mkdir(parents=True, exist_ok=True)
    (home / "predict-ask" / "job.json").write_bytes(json.dumps({"points": points}, ensure_ascii=False).encode("utf-8"))
    process = hooks.predict(handle.input_info("predictor").id, home / "predict-ask", home / "predict-out", wait=False)
    _save(home, {"step": "predict", "process": process})


def _lost(out: Path, process: dict, what: str) -> dict:
    said = (out / "log.txt").read_bytes()[-600:].decode("utf-8", "replace") if (out / "log.txt").exists() else ""
    restarted = psutil.boot_time() > process["created"]
    return {"status": "env" if restarted else "error",
            "reason": f"机器重启过，{what}的进程没了" if restarted else f"{what}没有留下结果：{said}"}


def advance(handle) -> dict:
    home = _home(handle)
    try:
        state = json.loads((home / "state.json").read_bytes())
    except (OSError, ValueError):
        return {"stage": "done", "result": {"status": "error", "reason": "选点没有派出去"}}
    if hooks.alive(state["process"]):
        return {"stage": state["step"], "result": None}
    if state["step"] == "predict":
        try:
            rows = json.loads((home / "predict-out" / "result.json").read_bytes())["rows"]
        except (OSError, ValueError, KeyError):
            return {"stage": "done", "result": _lost(home / "predict-out", state["process"], "预测器")}
        predictions = [{"name": row["point"], "values": row["values"], "lower": row["lower"], "upper": row["upper"]} for row in rows]
        _save(home, _strategy(handle, home, predictions))
        return {"stage": "strategy", "result": None}
    try:
        said = json.loads((home / "out" / "result.json").read_bytes())
    except (OSError, ValueError):
        return {"stage": "done", "result": _lost(home / "out", state["process"], "策略")}
    return {"stage": "done", "result": {"status": "ok", "reason": "", "chosen": said.get("chosen"), "model": said.get("model"),
                                        "job": str(home / "ask" / "job.json")}}


def halt(handle) -> None:
    try:
        hooks.kill(json.loads((_home(handle) / "state.json").read_bytes())["process"])
    except (OSError, ValueError, KeyError):
        pass
