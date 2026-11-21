"""看——另一种写法：都给成可以转成 JSON 的东西，不排成句子。读直接用登记和实验记录，追溯经操作台核心。"""
from __future__ import annotations

from stemlab.contract import states
from stemlab.desk.core import query
from stemlab.experiments import reader, view
from stemlab.registry import lookup


def experiments() -> list:
    found = []
    for name in reader.all_ids():
        try:
            found.append(view.summary(name))
        except LookupError:
            found.append({"id": name, "empty": True})
    return found


def one(experiment: str) -> dict:
    status = view.view(experiment)
    return {"id": experiment, "kind": status.type, "now": states.LABELS[status.state], "rounds": len(status.rounds),
            "tasks": {name: [task.state, task.outcome] for name, task in status.tasks.items()},
            "filled": status.filled, "pictures": query.charts(experiment)}


def thing(item_id: str) -> dict:
    return {"item": lookup.get(item_id), "from": query.upstream(item_id), "used_by": query.downstream(item_id)}


def under(case_id: str) -> list:
    return [row.get("experiment") or row["item"]["id"] for row in query.under_case(case_id)]


def registered() -> list:
    return [item["id"] for item in lookup.find()]


def kinds() -> dict:
    loaded = query.types()
    return {"kinds": sorted(loaded.kinds), "broken": dict(loaded.errors)}
