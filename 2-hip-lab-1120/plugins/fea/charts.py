"""【展示】作业走到哪、一个作业的求解过程、已算完的点、没算出来的和原因、每个作业留下了多少。只读，可以整个重写。

图表只给数据，画由界面统一画。数据的样子：
    table   {"columns": [列名…], "rows": [[一行的各格]…]}
    bar     {"labels": [每根柱的名字…], "values": [数…], "unit": 单位}
"""
from __future__ import annotations

import fnmatch
import json
from pathlib import Path

from plugins.fea import archive, outcomes, run

STATES = {"queued": "排队", "running": "运行", "done": "完成", "failed": "失败", "stopped": "停止"}
STAGES = {"queued": "排队", "build": "建模", "ready": "等求解槽", "solve": "求解", "post": "后处理"}
PROGRESS = ("*.sta", "solver-output.txt", "*.log")      # 求解器边算边写的文件：Abaqus 的 .sta、求解命令自己的输出、日志
TAIL = 8                                                 # 每个文件看最后几行


def _tail(path: Path) -> list[str]:
    try:
        return path.read_bytes()[-4000:].decode("utf-8", "replace").splitlines()[-TAIL:]
    except OSError:
        return []


def _solving(handle, tasks) -> list:
    """每个作业的求解过程：还在算的看它求解用的文件夹，算完了的看归档里留下的那一份。一行是文件末尾的一行。"""
    rows = []
    where = getattr(run, "folder_of", None)             # run.py 自己的布局；它换了写法、没有这个函数，就只看归档里的
    for task in tasks.values() if where else ():        # 还在算的
        folder = where(handle, task.name) / "solve"
        files = [path for pattern in PROGRESS for path in folder.glob(pattern)] if folder.is_dir() else []
        if files:
            newest = max(files, key=lambda path: path.stat().st_mtime)
            rows += [[task.name, STAGES.get(task.stage, task.stage or ""), newest.name, line] for line in _tail(newest)]
    live = {row[0] for row in rows}
    try:
        base = archive.root(handle, handle.input("export"))
    except (TypeError, KeyError, ValueError, OSError):
        return rows
    for kept in _ledger(handle, "kept"):                # 算完了的。归档清单里记着每个作业留下了哪些文件
        for row in kept:
            name = row["file"].rsplit("/", 1)[-1]
            if row["what"] == "process" and row["task"] not in live and any(fnmatch.fnmatch(name, pattern) for pattern in PROGRESS):
                rows += [[row["task"], f"第 {row['round']} 轮，已结束", name, line] for line in _tail(Path(base) / row["file"])]
    return rows


def _ledger(handle, what: str) -> list:
    folder = handle.work_dir / "ledger" / what
    return [json.loads(path.read_bytes()) for path in sorted(folder.glob("*.json"))] if folder.is_dir() else []


def chart(handle, name: str):
    tasks = handle.tasks()
    if name == "progress":
        return {"columns": ["任务", "状态", "阶段", "机器", "结局", "轮", "更新"],
                "rows": [[task.name, STATES.get(task.state, task.state), STAGES.get(task.stage, task.stage or ""),
                          task.machine or "", outcomes.LABEL.get(task.outcome, task.outcome or ""), task.round, task.time]
                         for task in tasks.values()]}
    if name == "solving":
        return {"columns": ["任务", "阶段", "文件", "求解器写的（末尾几行）"], "rows": _solving(handle, tasks)}
    if name == "results":
        rows = [row for row in _ledger(handle, "rows") if row["outcome"] == "finished"]
        names = sorted({key for row in rows for key in row["values"]})
        return {"columns": ["轮", *names], "rows": [[row["round"], *(row["values"].get(key) for key in names)] for row in rows]}
    if name == "failures":
        why = {row["task"]: row for row in _ledger(handle, "why")}
        return {"columns": ["任务", "结局", "原因", "轮"],
                "rows": [[task.name, outcomes.LABEL.get(task.outcome, task.outcome), why.get(task.name, {}).get("reason", ""), task.round]
                         for task in tasks.values() if task.outcome and task.outcome != "finished"]}
    if name == "kept":
        sizes: dict[str, float] = {}
        for rows in _ledger(handle, "kept"):
            for row in rows:
                sizes[row["task"]] = sizes.get(row["task"], 0.0) + row["size"] / 1e6
        return {"labels": list(sizes), "values": [round(size, 3) for size in sizes.values()], "unit": "MB"}
    raise ValueError(f"没有叫 {name} 的图")
