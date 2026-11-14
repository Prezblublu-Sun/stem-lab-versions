"""手动把一样东西挂到某个 case 下面，或者摘下来。

只影响在哪里看得到，不是来路。挂和摘都是往 links.jsonl 追加一条，不改以前的。
"""
from __future__ import annotations

from stemlab.contract import Refused, entries, layout
from stemlab.registry import lookup, register


def attach(item_id: str, case_id: str) -> dict:
    """把一样东西挂到一个 case 下面。"""
    return _link("attach", item_id, case_id)


def detach(item_id: str, case_id: str) -> dict:
    """把一样东西从一个 case 下面摘下来。"""
    return _link("detach", item_id, case_id)


def _link(op: str, item_id: str, case_id: str) -> dict:
    try:
        lookup.get(item_id)
        lookup.get(case_id)             # 它是不是一个 case，由 check_link 看编号
    except LookupError as error:
        raise Refused(str(error)) from None

    def build(seq: int, existing: list[dict]) -> dict:
        ops = [link["op"] for link in existing if link["item"] == item_id and link["case"] == case_id]
        hanging = bool(ops) and ops[-1] == "attach"
        if op == "attach" and hanging:
            raise Refused(f"{item_id} 已经挂在 {case_id} 下面了")
        if op == "detach" and not hanging:
            raise Refused(f"{item_id} 没有挂在 {case_id} 下面")
        return {"op": op, "item": item_id, "case": case_id}

    return register.append(layout.links_file(), "links", build, entries.check_link)
