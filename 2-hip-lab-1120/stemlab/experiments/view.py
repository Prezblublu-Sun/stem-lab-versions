"""实验的现状。只由记录重放得出，没有第二份状态，也不往盘上存缓存。

    view(实验)       现状：状态、输入、轮、任务、产物、问题
    rounds(实验)     各轮
    required(实验)   还缺哪几样输入
    summary(实验)    一行摘要
"""
from __future__ import annotations

from collections import Counter

from stemlab.contract import states
from stemlab.experiments import reader


def view(experiment: str) -> states.Status:
    """这个实验的现状。没有这个实验就报 LookupError。"""
    entries = reader.read(experiment)
    if not entries:
        raise LookupError(f"没有实验 {experiment!r}，或者它的记录是空的")
    return states.fold(entries)


def rounds(experiment: str) -> list[states.Round]:
    """这个实验的各轮，先开的在前。"""
    return view(experiment).rounds


def required(experiment: str) -> list[str]:
    """还缺哪几样必须的输入。看的是新建时抄下的输入表，所以插件拔掉了也答得出。"""
    status = view(experiment)
    return [row["name"] for row in status.inputs if row["required"] and not status.filled.get(row["name"])]


def summary(experiment: str) -> dict:
    """一行摘要。"""
    status = view(experiment)
    last = status.rounds[-1] if status.rounds else None
    bones = [info["bone_id"] for infos in (status.frozen or {}).values() for info in infos if info["bone_id"]]
    return {
        "id": experiment,
        "type": status.type,
        "state": status.state,
        "label": states.LABELS[status.state],
        "round": last.number if last else 0,
        "result": last.result if last else None,
        "tasks": dict(Counter(task.state for task in status.tasks.values())),
        "problems": sum(len(one.problems) for one in status.rounds),
        "outputs": sorted(last.outputs) if last else [],
        "bones": list(dict.fromkeys(bones)),
        "created": status.created,
        "note": status.note,
        "tags": list(status.tags),
    }
