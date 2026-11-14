"""只读的追溯。登记和实验记录互不相用，这里是两边唯一的汇合处。

东西之间的关系不存，由两处算出：登记里的来路，和实验存定的输入。

    upstream(编号)      往上追：它是哪个实验哪一轮的产物，那个实验用了什么，一直追到“外面拿来的”为止
    downstream(编号)    往下追：哪些实验用了它，它们又产出了什么
    under_case(case)    这个 case 下面有什么，每样写着原因
    same_bone(骨标识)   同一根骨的全部东西，和用到它们的实验
    types()             现在装着的实验类型
    charts(实验)、chart(实验, 图表名)   这个类型能给的图，和一张图的数据
"""
from __future__ import annotations

from stemlab.contract import Refused
from stemlab.experiments import reader, view
from stemlab.hooks import call, load
from stemlab.registry import lookup

DIRECT, INDIRECT, PRODUCT, ATTACHED = "直接用了", "经别的产物用了", "是它的产物", "手动挂的"


def _used() -> dict[str, list[str]]:
    """每样登记的东西被哪些实验存定成了输入：编号 -> 实验的列表。"""
    used: dict[str, list[str]] = {}
    for experiment in reader.all_ids():
        try:
            frozen = view.view(experiment).frozen or {}
        except LookupError:
            continue                                    # 发了号却没有记录的空号
        for listed in frozen.values():
            for info in listed:
                used.setdefault(info["id"], []).append(experiment)
    return used


def upstream(item_id: str) -> dict:
    """往上追一样东西的来历。

    外面拿来的：{"item": 那一条}
    产物：另加 experiment、round、type、provenance（那一轮的来历）、inputs（输入名 -> 各样输入再往上追）
    """
    try:
        item = lookup.get(item_id)
    except LookupError as error:
        raise Refused(str(error)) from None
    node = {"item": item}
    origin = item["origin"]
    if origin["from"] == "product":
        status = view.view(origin["experiment"])
        made = status.rounds[origin["round"] - 1]
        node.update(experiment=origin["experiment"], round=origin["round"], type=status.type,
                    provenance=made.provenance, extra=made.extra,
                    inputs={name: [upstream(info["id"]) for info in listed] for name, listed in status.frozen.items()})
    return node


def downstream(item_id: str) -> list[dict]:
    """往下追：用了这样东西的每个实验，和它各轮的产物（产物再往下追）。"""
    try:
        lookup.get(item_id)
    except LookupError as error:
        raise Refused(str(error)) from None
    return _downstream(item_id, _used())


def _downstream(item_id: str, used: dict) -> list[dict]:
    found = []
    for experiment in used.get(item_id, []):
        status = view.view(experiment)
        via = [name for name, listed in status.frozen.items() if any(info["id"] == item_id for info in listed)]
        products = [{"item": product, "users": _downstream(product["id"], used)}
                    for product in lookup.by_origin(experiment)]
        found.append({"experiment": experiment, "type": status.type, "as": via, "products": products})
    return found


def under_case(case_id: str) -> list[dict]:
    """这个 case 下面有什么。每样是 {"item" 或 "experiment", "why"}，why 写着原因：
    直接用了、经别的产物用了、是它的产物、手动挂的。"""
    try:
        lookup.get(case_id)
    except LookupError as error:
        raise Refused(str(error)) from None
    found: list[dict] = []
    seen: set[str] = set()
    users = downstream(case_id)
    direct = {user["experiment"] for user in users}     # 直接用了它的，不管在别的路上又碰到几次，都算直接用了

    def walk(users: list[dict]) -> None:
        for user in users:
            if user["experiment"] not in seen:
                seen.add(user["experiment"])
                why = DIRECT if user["experiment"] in direct else INDIRECT
                found.append({"experiment": user["experiment"], "type": user["type"], "why": why})
            for product in user["products"]:
                if product["item"]["id"] not in seen:
                    seen.add(product["item"]["id"])
                    found.append({"item": product["item"], "why": PRODUCT})
                walk(product["users"])

    walk(users)
    found += [{"item": lookup.get(item_id), "why": ATTACHED} for item_id in lookup.attached(case_id)
              if item_id not in seen]
    return found


def same_bone(bone_id: str) -> dict:
    """同一根骨：带这个骨标识的全部东西，和把它们存定成输入的实验。"""
    items = lookup.bone(bone_id)
    used = _used()
    experiments = list(dict.fromkeys(experiment for item in items for experiment in used.get(item["id"], [])))
    return {"bone_id": bone_id, "items": items, "experiments": experiments}


def types():
    """现在装着的实验类型（kinds、owners），和装不上的插件（errors）。界面看类型经这里，不直接碰挂点。"""
    return load.load()


def charts(experiment: str) -> list[dict]:
    """这个实验的类型能给哪几张图。插件装不上就是空的。"""
    try:
        kind, _ = call.find(view.view(experiment).type)
    except (Refused, LookupError):
        return []
    return [{"name": chart.name, "form": chart.form, "label": chart.label} for chart in kind.charts]


def chart(experiment: str, name: str):
    """一张图的数据。取图表出错往外抛，由界面显示在页面上，不进记录。"""
    return call.call_chart(view.view(experiment).type, experiment, name)
