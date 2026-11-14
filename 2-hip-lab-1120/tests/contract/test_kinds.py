"""十六种种类，和登记的一条记录长什么样。"""
from __future__ import annotations

import pytest

from stemlab.contract.kinds import (FOLDER, ITEM_FIELDS, ITEM_KINDS, PACKAGE, TABLE, VALUE, check_item, storages)
from tests.contract import samples as s

# 蓝图里的表，写死在这里
EXPECTED = {
    "bone_source": (FOLDER, True), "bone_model": (FOLDER, True), "bone_draft": (FOLDER, False),
    "edits": (FOLDER, False), "archive": (FOLDER, False), "report": (FOLDER, False),
    "points": (TABLE, False), "pool": (TABLE, False), "data": (TABLE, False), "prediction": (TABLE, False),
    "kernel": (PACKAGE, False), "strategy": (PACKAGE, False), "derive_def": (PACKAGE, False), "predictor": (PACKAGE, False),
    "objective": (VALUE, False), "setting": (VALUE, False),
}

VALUE_ITEM = {"format": 1, "time": s.T0, "id": "R0001", "kind": "setting", "name": "demo-setting", "version": 1,
              "storage": "value", "content": {"scale": 2}, "hash": s.H1, "origin": s.EXTERNAL, "bone_id": None}
CASE_ITEM = {"format": 1, "time": s.T0, "id": "C0002", "kind": "bone_source", "name": "femur042-ct", "version": 1,
             "storage": "copy", "content": "registry/store/C0002", "hash": s.H1, "origin": s.EXTERNAL,
             "bone_id": "femur042"}
PRODUCT_ITEM = {"format": 1, "time": s.T0, "id": "R0003", "kind": "report", "name": "E0001.report", "version": 2,
                "storage": "copy", "content": "experiments/E0001/rounds/2/outputs/report", "hash": s.H2,
                "origin": {"from": "product", "experiment": "E0001", "round": 2, "output": "report"}, "bone_id": None}


def test_there_are_sixteen_kinds_in_four_forms():
    assert len(ITEM_KINDS) == 16
    assert {name: (kind.form, kind.case) for name, kind in ITEM_KINDS.items()} == EXPECTED
    assert all(kind.name == name and kind.label for name, kind in ITEM_KINDS.items())
    assert [name for name, kind in ITEM_KINDS.items() if kind.case] == ["bone_source", "bone_model"]


def test_storage_follows_the_form():
    for name, kind in ITEM_KINDS.items():
        assert storages(name) == (("value",) if kind.form == VALUE else ("copy", "ref"))


@pytest.mark.parametrize("item", [VALUE_ITEM, CASE_ITEM, PRODUCT_ITEM], ids=["值", "case", "产物"])
def test_good_items_pass(item):
    assert check_item(item) == []
    assert check_item(s.chained([item] * int(item["id"][1:]))[-1]) == [], "接上链之后编号和序号对得上"


def test_the_fields_are_the_blueprint_table():
    assert set(ITEM_FIELDS) == {"id", "kind", "name", "version", "storage", "content", "hash", "origin",
                                "bone_id", "time", "format"}


@pytest.mark.parametrize("key", ITEM_FIELDS)
def test_missing_field_is_rejected(key):
    assert any(key in text for text in check_item({k: v for k, v in VALUE_ITEM.items() if k != key}))


BAD = [
    ("清单外的种类", dict(VALUE_ITEM, kind="notes"), "十六种"),
    ("多了一项", dict(VALUE_ITEM, surprise=1), "多了"),
    ("case 没给骨标识", dict(CASE_ITEM, bone_id=None), "骨标识"),
    ("case 的编号不以 C 开头", dict(CASE_ITEM, id="R0002"), "编号"),
    ("不是 case 却以 C 开头", dict(VALUE_ITEM, id="C0001"), "编号"),
    ("编号和序号对不上", dict(VALUE_ITEM, seq=7, prev=s.H1, this=s.H2), "序号"),
    ("名字不是 ASCII", dict(VALUE_ITEM, name="示范设定"), "名字"),
    ("版本从 1 起", dict(VALUE_ITEM, version=0), "version"),
    ("哈希不完整", dict(VALUE_ITEM, hash="abc"), "hash"),
    ("值不能复制", dict(VALUE_ITEM, storage="copy", content="x"), "不能存成"),
    ("文件夹不能存成值", dict(CASE_ITEM, storage="value", content={}), "不能存成"),
    ("值必须是对象", dict(VALUE_ITEM, content=[1, 2]), "JSON 对象"),
    ("文件夹要写位置", dict(CASE_ITEM, content=""), "位置"),
    ("来路的形状不对", dict(VALUE_ITEM, origin={"from": "copied"}), "来路"),
    ("产物只记位置", dict(PRODUCT_ITEM, storage="ref"), "copy"),
    ("骨标识不合规矩", dict(VALUE_ITEM, bone_id="骨 1"), "骨标识"),
    ("时间写法", dict(VALUE_ITEM, time="yesterday"), "time"),
    ("不是对象", "R0001", "JSON 对象"),
]


@pytest.mark.parametrize("why,item,word", BAD, ids=[row[0] for row in BAD])
def test_bad_items_are_named(why, item, word):
    problems = check_item(item)
    assert problems and any(word in text for text in problems), f"{why}：{problems}"
