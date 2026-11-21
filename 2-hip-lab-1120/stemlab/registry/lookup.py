"""查登记的东西：按编号、种类和名字、骨标识、来路。只读。"""
from __future__ import annotations

import copy
from pathlib import Path

from stemlab.contract import kinds, layout
from stemlab.registry import reader


def get(item_id: str) -> dict:
    """按编号取一条。没有就报 LookupError。"""
    entries = reader.items()
    if layout.is_item_id(item_id):
        seq = layout.id_seq(item_id)
        if 1 <= seq <= len(entries) and entries[seq - 1]["id"] == item_id:
            return entries[seq - 1]
    raise LookupError(f"登记里没有 {item_id!r}")


def find(kind: str | None = None, name: str | None = None) -> list[dict]:
    """这个种类、这个名字的全部版本，旧的在前。哪个不给就不按哪个筛。"""
    return [item for item in reader.items()
            if (kind is None or item["kind"] == kind) and (name is None or item["name"] == name)]


def latest(name: str) -> dict | None:
    """这个名字最新的一版。没有就是 None。"""
    versions = find(name=name)
    return versions[-1] if versions else None


def cases() -> list[dict]:
    """全部的 case：骨源和骨模型。"""
    return [item for item in reader.items() if kinds.ITEM_KINDS[item["kind"]].case]


def bone(bone_id: str) -> list[dict]:
    """带这个骨标识的全部东西。同一根骨的所有版本共用一个骨标识。"""
    return [item for item in reader.items() if item["bone_id"] == bone_id]


def bones() -> list[str]:
    """登记里见过的全部骨标识，先见到的在前。"""
    return list(dict.fromkeys(item["bone_id"] for item in reader.items() if item["bone_id"] is not None))


def content(item_id: str):
    """一样东西的内容：值就是那个值，文件夹就是它的位置。"""
    item = get(item_id)
    if item["storage"] == kinds.STORE_VALUE:
        return copy.deepcopy(item["content"])
    if item["storage"] == kinds.STORE_COPY:
        return layout.locate(item["content"])
    return Path(item["content"])


def by_origin(experiment: str, round: int | None = None) -> list[dict]:  # noqa: A002  round 是来路里的键名
    """某个实验（某一轮）发布的全部产物。"""
    return [item for item in reader.items()
            if item["origin"].get("experiment") == experiment
            and (round is None or item["origin"].get("round") == round)]


def attached(case_id: str) -> list[str]:
    """手动挂在这个 case 下面的东西的编号。挂了又摘掉的不算。"""
    now: dict[str, None] = {}
    for link in reader.links():
        if link["case"] != case_id:
            continue
        if link["op"] == "attach":
            now[link["item"]] = None
        else:
            now.pop(link["item"], None)
    return list(now)
