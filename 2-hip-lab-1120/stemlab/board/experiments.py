"""全部实验现在的样子。只读两条链，不叫插件；记录文件没变就不重读。

    cards()      每个实验一张卡片
    running()    在跑和排队的：类型、哪根骨、第几轮、每个任务的状态和阶段
    recent()     刚结束的和结局
    problems()   最近的问题
    waiting()    还没启动的
    broken()     记录读不出来的
"""
from __future__ import annotations

from collections import Counter

from stemlab.contract import layout, states
from stemlab.experiments import reader, view
from stemlab.registry import lookup

_SEEN: dict[str, tuple[tuple, dict]] = {}       # 实验 -> (记录文件的大小和修改时间, 卡片)


def card(experiment: str) -> dict | None:
    """一个实验的卡片。记录文件没变就用上次算好的。发了号还没有记录的是 None。"""
    try:
        stat = layout.record_file(experiment).stat()
    except OSError:
        return None
    stamp = (stat.st_size, stat.st_mtime_ns)
    seen = _SEEN.get(experiment)
    if seen is None or seen[0] != stamp:
        try:
            made = _card(experiment, view.view(experiment))
        except (LookupError, ValueError, KeyError, TypeError) as error:     # 读不出来只说出来，不拦别的实验
            made = {"id": experiment, "broken": f"记录读不出来：{error}"}
        _SEEN[experiment] = seen = (stamp, made)
    return dict(seen[1], touched=stat.st_mtime)


def _bone(item_id: str) -> str | None:
    try:
        return lookup.get(item_id)["bone_id"]
    except (LookupError, ValueError):
        return None


def _card(experiment: str, status: states.Status) -> dict:
    last = status.rounds[-1] if status.rounds else None
    if status.frozen is not None:
        bones = [info["bone_id"] for infos in status.frozen.values() for info in infos]
    else:
        bones = [_bone(item_id) for items in status.filled.values() for item_id in items]
    names = {row["name"]: row for row in status.outcomes}
    tasks = [{"name": task.name, "state": task.state, "stage": task.stage, "machine": task.machine,
              "outcome": task.outcome, "outcome_label": names.get(task.outcome, {}).get("label") or task.outcome,
              "category": names.get(task.outcome, {}).get("category"), "round": task.round, "time": task.time}
             for task in status.tasks.values()]
    problems = [{"experiment": experiment, "round": one.number, "time": problem.get("time"),
                 "error": problem.get("error"), "task": problem.get("task"), "count": problem.get("count")}
                for one in status.rounds for problem in one.problems]
    return {
        "id": experiment, "type": status.type, "note": status.note, "tags": list(status.tags),
        "state": status.state, "label": states.LABELS.get(status.state, status.state),
        "live": states.can("report", status),           # 启动中或运行中
        "starting": bool(last) and states.can("report", status) and not last.calls,    # 插件的启动还没有回来
        "started": bool(status.rounds),
        "round": last.number if last else 0,
        "opened": last.opened if last else None, "closed": last.closed if last else None,
        "result": last.result if last else None,
        "result_label": states.LABELS.get(last.result, last.result) if last else None,
        "reason": last.reason if last else None,
        "bones": sorted({bone for bone in bones if bone}),
        "tasks": tasks, "counts": dict(Counter(task["state"] for task in tasks)),
        "problems": problems, "outputs": sorted(last.outputs) if last else [],
        "created": status.created,
    }


def cards() -> list[dict]:
    """每个有记录的实验一张卡片，先建的在前。"""
    return [made for made in map(card, reader.all_ids()) if made is not None]


def running(listed=None) -> list[dict]:
    """在跑和排队的：启动中和运行中的实验。"""
    return [one for one in (cards() if listed is None else listed) if one.get("live")]


def recent(limit: int = 20, listed=None) -> list[dict]:
    """刚结束的，后结束的在前。"""
    ended = [one for one in (cards() if listed is None else listed) if one.get("started") and not one.get("live")]
    return sorted(ended, key=lambda one: one.get("closed") or "", reverse=True)[:limit]


def waiting(listed=None) -> list[dict]:
    """新建了还没启动的。"""
    return [one for one in (cards() if listed is None else listed) if "broken" not in one and not one["started"]]


def broken(listed=None) -> list[dict]:
    """记录读不出来的。"""
    return [one for one in (cards() if listed is None else listed) if "broken" in one]


def problems(limit: int = 30, listed=None) -> list[dict]:
    """最近的问题，后出的在前。"""
    found = [problem for one in (cards() if listed is None else listed) for problem in one.get("problems", ())]
    return sorted(found, key=lambda problem: problem.get("time") or "", reverse=True)[:limit]
