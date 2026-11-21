"""【自由】对一批点出预测。超出适用范围的点不出数、记一条问题，别的点照常。

哪些点在适用范围里由冻结的 predictor.in_range 判，插件判完把在范围里的点交到这里。这里只管把它们交给预测器的包
（脱离出去跑，经 hooks.predict），等它跑完把各行读回来。包自己也会再核一遍范围，核出来不在的写在 skipped 里。
"""
from __future__ import annotations

import json
from pathlib import Path

import psutil

from stemlab import hooks


def _home(handle) -> Path:
    return handle.work_dir / "predict" / f"r{handle.round.number}"


def begin(handle, points: list[dict]) -> None:
    home = _home(handle)
    (home / "ask").mkdir(parents=True, exist_ok=True)
    (home / "ask" / "job.json").write_bytes(json.dumps({"points": points}, ensure_ascii=False).encode("utf-8"))
    process = hooks.predict(handle.input_info("predictor").id, home / "ask", home / "out", wait=False)
    (home / "state.json").write_bytes(json.dumps({"process": process}).encode("utf-8"))


def advance(handle) -> dict:
    home = _home(handle)
    try:
        process = json.loads((home / "state.json").read_bytes())["process"]
    except (OSError, ValueError, KeyError):
        return {"stage": "done", "result": {"status": "error", "reason": "预测器没有起来"}}
    if hooks.alive(process):
        return {"stage": "predicting", "result": None}
    try:
        said = json.loads((home / "out" / "result.json").read_bytes())
        return {"stage": "done", "result": {"status": "ok", "reason": "", "rows": said["rows"], "skipped": said.get("skipped", []),
                                            "folder": str(home / "out")}}     # 预测了场的，场的文件在这个文件夹下面
    except (OSError, ValueError, KeyError):
        log = home / "out" / "log.txt"
        said = log.read_bytes()[-600:].decode("utf-8", "replace") if log.exists() else ""
        restarted = psutil.boot_time() > process["created"]
        return {"stage": "done", "result": {"status": "env" if restarted else "error",
                                            "reason": "机器重启过，预测器的进程没了" if restarted else f"预测器没有留下结果：{said}"}}


def halt(handle) -> None:
    try:
        hooks.kill(json.loads((_home(handle) / "state.json").read_bytes())["process"])
    except (OSError, ValueError, KeyError):
        pass
