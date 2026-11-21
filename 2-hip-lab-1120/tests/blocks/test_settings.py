"""核心启动时照声明核验设定（改格式的 D3）：照声明写的设定，启动前照它照的那个包里的那份声明核。
不合的被拒，说出是哪一样输入、哪一项、哪一条，记录里不多一条；老写法的设定照旧。规矩本身见 tests/contract/test_declaration.py。"""
from __future__ import annotations

import itertools

import pytest

from stemlab.contract import Refused
from stemlab.contract.formats import declaration as d
from stemlab.desk.core import actions, start
from stemlab.experiments import view
from tests import helpers

DECLARATION = {"name": "strategy", "groups": ["选点"], "items": [
    {"name": "count", "label": "点数", "meaning": "一批选几个点", "group": "选点", "type": "integer",
     "range": {"min": 1, "max": 50}, "per_point": False, "required": True, "test": 4, "test_source": "示范"},
    {"name": "spread", "label": "铺开的程度", "meaning": "候选在设计范围里铺得多开", "group": "选点", "type": "number",
     "unit": "1", "range": {"min": 0, "max": 1}, "per_point": False, "required": False, "test": 0.5, "test_source": "示范"}]}
_NAMES = itertools.count(1)


def declared_package(tmp_path) -> str:
    """登记一个带声明的包（策略），返回它的编号。"""
    folder = helpers.make_package(tmp_path / f"pkg-{next(_NAMES)}", "strategy", declarations=[DECLARATION])
    return actions.register("strategy", f"declared-strategy-{next(_NAMES)}", source=folder, note="带声明的包")["id"]


def formal(of: str, **change) -> dict:
    setting = d.test_setting(DECLARATION, of)
    return {**setting, "use": "formal", "sources": {name: "示范" for name in setting["values"]}, **change}


def experiment(value, tool: str) -> str:
    item = helpers.setting(f"declared-setting-{next(_NAMES)}", value)
    made = actions.new("demo.pack", note="照声明核验设定")
    actions.fill(made, "setting", [item["id"]])
    actions.fill(made, "tool", [tool])
    return made


def refused(made: str, data) -> str:
    """启动被拒，记录里不多一条。返回被拒的原因。"""
    before = helpers.snapshot(data)
    with pytest.raises(Refused) as caught:
        start.start(made)
    assert helpers.snapshot(data) == before, "被拒的启动什么都没写下"
    return str(caught.value)


def test_a_setting_that_keeps_its_declaration_starts(lab, data, tmp_path):
    tool = declared_package(tmp_path)
    made = experiment(formal(tool), tool)
    assert start.start(made).ok and view.view(made).state == "running"


@pytest.mark.parametrize("values,rule,item", [
    ({"count": 0, "spread": 0.5}, 4, "'count'"),
    ({"count": 4, "spread": 1.5}, 4, "'spread'"),
    ({"spread": 0.5}, 3, "'count'"),
    ({"count": 4, "spread": 0.5, "seed": 7}, 2, "'seed'"),
])
def test_a_setting_that_breaks_its_declaration_is_refused_and_named(lab, data, tmp_path, values, rule, item):
    tool = declared_package(tmp_path)
    said = refused(experiment(formal(tool, values=values, sources={k: "示范" for k in values}), tool), data)
    assert f"规则 {rule}：" in said and item in said and "输入 setting" in said, said


def test_rule_1_the_package_must_be_filled_and_hold_that_declaration(lab, data, tmp_path):
    tool, other = declared_package(tmp_path), declared_package(tmp_path)
    assert "这个实验没有填它" in refused(experiment(formal(other), tool), data)
    renamed = formal(tool, declaration=dict(formal(tool)["declaration"], name="placement"))
    assert "里没有它" in refused(experiment(renamed, tool), data)
    stale = formal(tool, declaration=dict(formal(tool)["declaration"], hash="0" * 64))
    assert "规则 1：" in refused(experiment(stale, tool), data), "声明的哈希对不上：包的声明改过了"


def test_rule_7_a_test_setting_is_not_taken_by_a_formal_round(lab, data, tmp_path):
    tool = declared_package(tmp_path)
    assert "规则 7：" in refused(experiment(d.test_setting(DECLARATION, tool), tool), data)


def test_rule_9_a_formal_setting_says_where_each_value_came_from(lab, data, tmp_path):
    tool = declared_package(tmp_path)
    said = refused(experiment(formal(tool, sources={"count": "示范"}), tool), data)
    assert "规则 9：" in said and "'spread'" in said


def test_a_setting_of_another_format_version_is_refused(lab, data, tmp_path):
    tool = declared_package(tmp_path)
    assert "第 2 版" in refused(experiment(formal(tool, format=2), tool), data)


def test_a_setting_may_follow_what_the_experiment_type_itself_declares(lab, data, tmp_path):
    """运行设定这类，照的是这种实验自己声明的（Kind.settings）：of 写类型名。照它核，规矩一样。"""
    from tests.plugins.demo.plugin import RUN

    tool = declared_package(tmp_path)
    own = {**d.test_setting(RUN, "demo.pack"), "use": "formal", "sources": {"slots": "示范"}}
    assert start.start(experiment(own, tool)).ok
    assert "规则 4：" in refused(experiment(dict(own, values={"slots": 0}), tool), data)
    renamed = dict(own, declaration=dict(own["declaration"], name="other"))
    assert "没有声明这一份" in refused(experiment(renamed, tool), data)
    stale = dict(own, declaration=dict(own["declaration"], hash="0" * 64))
    assert "规则 1：" in refused(experiment(stale, tool), data), "类型的声明改过了，照旧声明写的设定对不上"
    assert "这个实验没有填它" in refused(experiment(dict(own, declaration=dict(own["declaration"], of="demo.echo")), tool), data), \
        "照别的类型的声明写的，不收"


def test_settings_written_the_old_way_are_left_alone(lab, data, tmp_path):
    """老写法的设定是随意的 JSON：核心不核它，照旧启动。"""
    tool = declared_package(tmp_path)
    made = experiment({"x": 3, "declaration_note": "不是新写法"}, tool)
    assert start.start(made).ok
