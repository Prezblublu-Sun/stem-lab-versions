"""插件接口：一个类型报的三张表和它写了哪几个动作，都读得出。"""
from __future__ import annotations

import inspect
from dataclasses import replace

import pytest

from stemlab.contract.entries import check_tables
from stemlab.contract.plugin_api import (ACTIONS, Chart, Handle, Input, InputInfo, Kind, Outcome, Output, RoundInfo,
                                         actions, check_kind, tables)


def nothing(handle):
    return None


KIND = Kind(
    name="demo.echo",
    inputs=(Input("setting", ("setting",), label="设定"), Input("extra", ("report", "edits"), many=True, required=False)),
    outputs=(Output("report", "report", label="报告"),),
    outcomes=(Outcome("finished", "ok", "算完"), Outcome("env", "retryable")),
    check=nothing, start=nothing, poll=nothing,
)


def test_the_three_tables_can_be_read_and_fit_the_created_entry():
    three = tables(KIND)
    assert set(three) == {"inputs", "outputs", "outcomes"}
    assert three["inputs"][1] == {"name": "extra", "kinds": ["report", "edits"], "many": True, "required": False, "label": ""}
    assert three["outputs"] == [{"name": "report", "kind": "report", "label": "报告"}]
    assert three["outcomes"][0] == {"name": "finished", "category": "ok", "label": "算完"}
    assert check_tables(**three) == []


def test_which_actions_were_written_can_be_read():
    assert ACTIONS == ("check", "start", "poll", "stop")
    assert actions(KIND) == ("check", "start", "poll")
    assert actions(replace(KIND, stop=nothing)) == ("check", "start", "poll", "stop")


def test_a_good_kind_passes():
    assert check_kind(KIND) == []
    with_chart = replace(KIND, charts=(Chart("progress", "line", "进展"),), chart=lambda handle, name: {}, where="worker")
    assert check_kind(with_chart) == []


BAD = [
    ("不是 Kind", {"name": "demo.echo"}),
    ("类型名", replace(KIND, name="echo")),
    ("类型名带大写", replace(KIND, name="Demo.Echo")),
    ("没写 poll", replace(KIND, poll=None)),
    ("没写 check", replace(KIND, check=None)),
    ("stop 不是函数", replace(KIND, stop="stop")),
    ("输入的种类", replace(KIND, inputs=(Input("x", ("nothing",)),))),
    ("输入没说收哪种", replace(KIND, inputs=(Input("x", ()),))),
    ("输入重名", replace(KIND, inputs=(Input("x", ("data",)), Input("x", ("report",))))),
    ("表里不是 Input", replace(KIND, inputs=({"name": "x"},))),
    ("产物是值", replace(KIND, outputs=(Output("x", "setting"),))),
    ("结局的类别", replace(KIND, outcomes=(Outcome("x", "maybe"),))),
    ("没有结局", replace(KIND, outcomes=())),
    ("在哪跑", replace(KIND, where="cloud")),
    ("图的种类", replace(KIND, charts=(Chart("p", "pie"),), chart=nothing)),
    ("图表重名", replace(KIND, charts=(Chart("p", "line"), Chart("p", "bar")), chart=nothing)),
    ("报了图表没写 chart", replace(KIND, charts=(Chart("p", "line"),))),
]


@pytest.mark.parametrize("why,kind", BAD, ids=[row[0] for row in BAD])
def test_bad_kinds_are_named(why, kind):
    problems = check_kind(kind)
    assert problems and all(isinstance(text, str) and text for text in problems), why


def test_handle_lists_exactly_what_a_call_can_do():
    members = {name for name, value in vars(Handle).items() if inspect.isfunction(value) and not name.startswith("_")}
    assert members == {"input", "input_info", "tasks", "task", "output", "problem", "provenance", "finish", "fail"}
    assert set(Handle.__annotations__) == {"experiment", "round", "work_dir", "machines"}
    assert list(inspect.signature(Handle.task).parameters) == ["self", "task", "state", "outcome", "stage", "machine", "fingerprint"]
    assert list(inspect.signature(Handle.problem).parameters) == ["self", "error", "task", "raw"]


def test_info_shapes():
    assert [f for f in InputInfo.__dataclass_fields__] == ["id", "kind", "name", "version", "hash", "origin", "bone_id", "time"]
    assert [f for f in RoundInfo.__dataclass_fields__] == ["number", "rerun", "provenance", "opened"]
    assert RoundInfo(1, (), {}).opened is None, "检查的时候轮还没开"
