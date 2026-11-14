"""告警。线写在 board.json 的 alerts 里（见 machines.DEFAULTS）。只显示，不动作。

    alerts(设置, 各台机器的数, 各实验的卡片)   现在有哪些告警

每条告警：level 是 warn（要你看一眼）或 info（知道就行），what 是哪一类，text 是给人看的一句话。
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import psutil

from stemlab.contract import layout


def seconds(stamp) -> float | None:
    """记录里的时间写法 -> 从 1970 年起的秒数。读不懂就是 None。"""
    try:
        return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


def watching() -> bool:
    """现在有没有一处在值守：值守的锁文件里记着的那个进程还在不在。"""
    try:
        note = json.loads(layout.watch_lock().read_bytes().strip() or b"null")
        found = psutil.Process(int(note["pid"]))
        return abs(found.create_time() - float(note["created"])) < 0.001
    except (OSError, ValueError, TypeError, KeyError, psutil.Error):
        return False


def last_backup() -> float | None:
    """上次备份是什么时候。还没备份过、或者读不出来，就是 None。"""
    try:
        return seconds(json.loads(layout.backup_file().read_bytes())["time"])
    except (OSError, ValueError, TypeError, KeyError):
        return None


def alerts(config: dict, rows, listed, now: float | None = None, notes=()) -> list[dict]:
    """现在有哪些告警。rows 是各台机器的数，listed 是各实验的卡片，notes 是读设置和清单时说的话。"""
    now = time.time() if now is None else now
    lines = config["alerts"]
    found = [{"level": "warn", "what": "config", "text": text} for text in notes if text]

    for row in rows:
        name = row["name"]
        if row.get("watched") and not row.get("here"):
            age = row.get("age")
            if age is None or age > lines["unreachable_seconds"]:
                waited = "一直没有读到数" if age is None else f"已经 {int(age)} 秒没有读到数"
                found.append({"level": "warn", "what": "unreachable",
                              "text": f"{name} 连不上：{waited}" + (f"（{row['error']}）" if row.get("error") else "")})
        for disk in row.get("disks") or ():
            if disk["free_gb"] < lines["disk_free_gb"]:
                found.append({"level": "warn", "what": "disk",
                              "text": f"{name} 的 {disk['path']} 只剩 {disk['free_gb']} GB（线是 {lines['disk_free_gb']} GB）"})
        memory = row.get("memory")
        if memory and memory["percent"] > lines["memory_percent"]:
            found.append({"level": "warn", "what": "memory",
                          "text": f"{name} 的内存用了 {memory['percent']}%（线是 {lines['memory_percent']}%）"})

    live = [one for one in listed if one.get("live")]
    if live and not watching():
        found.append({"level": "warn", "what": "watch",
                      "text": f"有 {len(live)} 个实验在跑，但没有值守开着：任务不会自己往前走。开值守：python -m stemlab.desk watch"})
    for one in live:
        opened = seconds(one.get("opened"))
        if one.get("starting") and opened and now - opened > lines["starting_minutes"] * 60:
            found.append({"level": "warn", "what": "starting",
                          "text": f"{one['id']} 启动了 {int((now - opened) / 60)} 分钟还没有回来。"
                                  "启动卡死要你去结束那个进程，值守下一遍会把这一轮记成启动失败"})
    for one in listed:
        if "broken" in one:
            found.append({"level": "warn", "what": "record", "text": f"{one['id']}：{one['broken']}"})

    backed = last_backup()
    if backed is None:
        found.append({"level": "info", "what": "backup", "text": "还没有备份过"})
    elif now - backed > lines["backup_days"] * 86400:
        found.append({"level": "warn", "what": "backup",
                      "text": f"上次备份是 {int((now - backed) / 86400)} 天前（线是 {lines['backup_days']} 天）"})
    return found
