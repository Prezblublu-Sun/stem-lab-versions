"""十二种条目：每种一条对的能过；缺任何一项必填的都被拒。"""
from __future__ import annotations

import copy

import pytest

from stemlab.contract.entries import (CHAIN, COMMON, ENTRIES, PROVENANCE_SOURCES, ROUND_PROVENANCE,
                                      check_entry, check_issued, check_link, check_tables)
from tests.contract import samples as s

REQUIRED = [(name, key) for name, (required, _) in ENTRIES.items() for key in {**COMMON, **required}]


def test_there_are_twelve_entries_and_a_good_sample_of_each():
    assert len(ENTRIES) == 12
    assert set(s.GOOD) == set(ENTRIES)


@pytest.mark.parametrize("name", list(ENTRIES))
def test_good_samples_pass(name):
    assert check_entry(s.GOOD[name]) == []


@pytest.mark.parametrize("name", list(ENTRIES))
def test_good_samples_pass_after_linking(name):
    assert check_entry(s.chained([s.GOOD[name]])[0]) == []


@pytest.mark.parametrize("name,key", REQUIRED)
def test_missing_any_required_field_is_rejected(name, key):
    body = copy.deepcopy(s.GOOD[name])
    del body[key]
    problems = check_entry(body)
    assert problems, f"{name} 缺 {key} 应该被拒"
    if key != "entry":
        assert any(key in text for text in problems), "要点名缺的是哪一项"


@pytest.mark.parametrize("name", list(ENTRIES))
def test_unknown_field_is_rejected(name):
    assert any("多了" in text for text in check_entry(dict(s.GOOD[name], surprise=1)))


@pytest.mark.parametrize("key", list(ROUND_PROVENANCE))
def test_every_round_must_record_each_piece_of_provenance(key):
    body = s.round_opened()
    del body["provenance"][key]
    assert any(key in text for text in check_entry(body))


def test_round_scoped_entries_are_exactly_the_seven():
    scoped = {name for name, (required, _) in ENTRIES.items() if "round" in required}
    assert scoped == {"round_opened", "called", "task", "output", "problem", "provenance", "round_closed"}


def test_chain_fields_are_optional_but_typed():
    assert set(CHAIN) == {"seq", "prev", "this"}
    assert check_entry(dict(s.noted(), seq="1")) != []


BAD = [
    ("不是对象", ["created"]),
    ("没有这种条目", s.entry("paused")),
    ("格式版本不对", dict(s.noted(), format=2)),
    ("时间写法不对", dict(s.noted(), time="2026-01-01 00:00:00")),
    ("轮号从 1 起", s.task(number=0)),
    ("bool 不是整数", dict(s.task(), round=True)),
    ("类型名", s.created(type="demo")),
    ("输入收的种类", s.created(inputs=[dict(s.INPUTS[0], kinds=["nothing"])])),
    ("输入名重复", s.created(inputs=[s.INPUTS[0], s.INPUTS[0]])),
    ("产物不能是值", s.created(outputs=[{"name": "x", "kind": "setting", "label": ""}])),
    ("结局的类别", s.created(outcomes=[{"name": "x", "category": "maybe", "label": ""}])),
    ("结局表是空的", s.created(outcomes=[])),
    ("标签带空格", s.created(tags=["a b"])),
    ("克隆的来源", s.created(clone_of="E1")),
    ("填的不是编号", s.filled(items=("demo-setting",))),
    ("同一样填两次", s.filled(items=("R0001", "R0001"))),
    ("存定缺链头", dict(s.frozen(), register_head={"seq": 1})),
    ("存定的一样缺项", dict(s.frozen(), inputs={"setting": [{"id": "R0001"}]})),
    ("重排的任务重复", s.round_opened(rerun=["a", "a"])),
    ("called 的动作", s.called(action="poll")),
    ("成了却带报错", dict(s.called(), error="x")),
    ("出错不写报错", dict(s.called(ok=False), error=None)),
    ("任务状态", s.task(state="paused")),
    ("完成没带结局", s.task(state="done")),
    ("排队带了结局", s.task(state="queued", outcome="finished")),
    ("指纹不是哈希", dict(s.task(), fingerprint="abc")),
    ("产物的编号", s.output(item="E0001")),
    ("产物的哈希", dict(s.output(), hash="abc")),
    ("报错是空的", s.problem(error="  ")),
    ("次数小于 2", s.problem(count=1)),
    ("补来历的来源", dict(s.provenance(), source="someone")),
    ("补的来历是空的", dict(s.provenance(), info={})),
    ("远端的来历缺项", dict(s.provenance(), source="remote", info={"host": "linux"})),
    ("轮的结局", s.round_closed(result="paused")),
    ("备注是空的", dict(s.noted(), text=" ")),
    ("标签没有增减", dict(s.tagged(), add=[], remove=[])),
]


@pytest.mark.parametrize("why,body", BAD, ids=[why for why, _ in BAD])
def test_bad_samples_are_named(why, body):
    problems = check_entry(body)
    assert problems and all(isinstance(text, str) and text for text in problems), why


def test_provenance_sources():
    assert set(PROVENANCE_SOURCES) == {"remote", "package", "code", "plugin"}
    code = {"plugin_hash": s.H1, "commit": "0123abc", "plugin_dirty": True}
    assert check_entry(dict(s.provenance(), source="code", info=code)) == []
    for key in code:
        missing = {name: value for name, value in code.items() if name != key}
        assert any(key in text for text in check_entry(dict(s.provenance(), source="code", info=missing)))
    remote = {"host": "linux", "python": "3.12.3", "libs": {}, "cuda": "12", "driver": "580", "gpu": "RTX"}
    assert check_entry(dict(s.provenance(), source="remote", info=remote)) == []
    assert check_entry(dict(s.provenance(), source="package", info={"id": "R0003", "hash": s.H1})) == []


def test_tables_are_checked_on_their_own():
    assert check_tables(s.INPUTS, s.OUTPUTS, s.OUTCOMES) == []
    assert check_tables([{"name": "Bad Name", "kinds": ["data"], "many": False, "required": True, "label": ""}],
                        s.OUTPUTS, s.OUTCOMES)


# ---- 另外两条小链 ----

def test_issued_entries():
    good = {"format": 1, "time": s.T0, "id": "E0001", "type": "demo.echo"}
    assert check_issued(good) == []
    assert check_issued(dict(good, seq=1, prev="0" * 64, this=s.H1)) == []
    assert check_issued(dict(good, seq=2, prev="0" * 64, this=s.H1)), "编号要和序号对得上"
    assert check_issued(dict(good, id="R0001"))
    assert check_issued(dict(good, type="demo"))
    assert check_issued({key: value for key, value in good.items() if key != "type"})


def test_link_entries():
    good = {"format": 1, "time": s.T0, "op": "attach", "item": "R0002", "case": "C0001"}
    assert check_link(good) == []
    assert check_link(dict(good, op="detach")) == []
    assert check_link(dict(good, op="move"))
    assert check_link(dict(good, case="R0001")), "只能挂到 case 下面"
    assert check_link(dict(good, item="x"))
