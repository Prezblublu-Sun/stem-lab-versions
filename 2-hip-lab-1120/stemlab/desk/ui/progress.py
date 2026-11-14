"""一个实验的实时进展：每个任务的阶段和用时、最近的问题、已发布的产物；这个类型提供的图表。只读。

这是展示层，可以整个重写。读直接用 registry.lookup 和 experiments.view；图表经操作台核心取。
取图表出错只显示出来，不进记录。这里不拿状态名做判断：状态叫什么、现在能做什么，都问契约。
"""
from __future__ import annotations

import time
from datetime import datetime

from stemlab.contract import states
from stemlab.desk.core import query
from stemlab.experiments import view
from stemlab.registry import lookup

RECENT = 20


def _age(stamp, now: float):
    """这个时刻到现在过了多少秒。读不出来就是 None。"""
    try:
        return max(0.0, now - datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def _item(item_id: str) -> dict:
    try:
        item = lookup.get(item_id)
    except LookupError:
        return {"id": item_id, "kind": "?", "name": "（登记里找不到）", "version": 0, "bone_id": None}
    return {key: item[key] for key in ("id", "kind", "name", "version", "bone_id")}


def progress(experiment: str, now: float | None = None) -> dict:
    """这个实验现在的样子，写成一份可以直接转成 JSON 的字典。没有这个实验就报 LookupError。"""
    status = view.view(experiment)
    now = time.time() if now is None else now
    outcomes = {row["name"]: row for row in status.outcomes}
    frozen = status.frozen or {}
    inputs = []
    for row in status.inputs:
        ids = [info["id"] for info in frozen.get(row["name"], [])] or status.filled.get(row["name"], [])
        inputs.append({"name": row["name"], "label": row.get("label", ""), "kinds": row["kinds"], "many": row["many"],
                       "required": row["required"], "items": [_item(item_id) for item_id in ids]})
    tasks = [{"name": task.name, "state": task.state, "outcome": task.outcome, "stage": task.stage, "machine": task.machine,
              "round": task.round, "reported": task.time, "seconds_since": _age(task.time, now),
              "outcome_label": outcomes.get(task.outcome, {}).get("label", ""),
              "category": outcomes.get(task.outcome, {}).get("category")} for task in status.tasks.values()]
    rounds, problems = [], []
    for one in status.rounds:
        rounds.append({"number": one.number, "opened": one.opened, "closed": one.closed, "result": one.result,
                       "result_label": states.LABELS[one.result] if one.result else "还没结束", "reason": one.reason,
                       "rerun": list(one.rerun), "provenance": one.provenance, "extra": one.extra,
                       "outputs": {name: _item(made["item"]) for name, made in one.outputs.items()},
                       "seconds": (_age(one.opened, now) or 0.0) - (_age(one.closed, now) or 0.0)})     # 这一轮用了（或已经用了）多久
        problems += [dict(problem, round=one.number) for problem in one.problems]
    actions = query.types()
    kind = actions.kinds.get(status.type)
    written = tuple(name for name in ("check", "start", "poll", "stop") if kind is not None and callable(getattr(kind, name, None)))
    return {"id": experiment, "type": status.type, "state": status.state, "label": states.LABELS[status.state], "note": status.note,
            "tags": list(status.tags), "notes": status.notes, "clone_of": status.clone_of, "created": status.created,
            "frozen": status.frozen is not None, "inputs": inputs, "tasks": tasks, "rounds": rounds,
            "problems": problems[-RECENT:], "charts": query.charts(experiment),
            "can": {op: states.can(op, status, written) for op in ("fill", "start", "stop")},
            "plugin_missing": kind is None}


def chart(experiment: str, name: str) -> dict:
    """一张图：{"name", "form", "label", "data"}。取不出来就带 error，说为什么；这不进记录。"""
    listed = {one["name"]: one for one in query.charts(experiment)}
    if name not in listed:
        return {"name": name, "form": None, "label": name, "error": "这个类型没有这张图（或者插件现在装不上）"}
    try:
        return dict(listed[name], data=query.chart(experiment, name))
    except Exception as error:  # noqa: BLE001  图表的代码出什么错都只显示出来
        return dict(listed[name], error=f"{type(error).__name__}: {error}")


def text(experiment: str) -> str:
    """命令行上看的进展。"""
    found = progress(experiment)
    lines = [f"{found['id']}  {found['type']}  {found['label']}  {found['note']}".rstrip()]
    for task in found["tasks"]:
        since = f"{task['seconds_since']:.0f} 秒前" if task["seconds_since"] is not None else ""
        detail = "  ".join(part for part in (task["outcome_label"] or task["outcome"], task["stage"], task["machine"], since) if part)
        lines.append(f"  任务 {task['name']}  {task['state']}  {detail}".rstrip())
    if found["rounds"]:
        last = found["rounds"][-1]
        lines.append(f"  第 {last['number']} 轮：{last['result_label']}" + (f"（{last['reason']}）" if last["reason"] else ""))
        lines += [f"  产物 {name} → {item['id']}（{item['kind']}）" for name, item in last["outputs"].items()]
    lines += [f"  问题（第 {problem['round']} 轮）{problem['error']}" for problem in found["problems"][-5:]]
    lines += [f"  图 {one['name']}（{one['form']}）{one['label']}" for one in found["charts"]]
    return "\n".join(lines)
