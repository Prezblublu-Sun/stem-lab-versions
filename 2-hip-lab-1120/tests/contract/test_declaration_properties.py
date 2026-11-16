"""设定的声明的属性测试：随机生成合规矩的声明，看四件事永远成立。属性测试是什么，见 tests/properties.py。

    拼出来的测试轮设定一定过核验
    把哪一项改成类型不对的值，只报第 4 条，说的就是那一项
    删掉一项必填的，只报第 3 条；多写一项声明里没有的，只报第 2 条
    每个点给的项，照测试轮的取值逐个点给，过；少给一项，报第 6 条
"""
from __future__ import annotations

from hypothesis import assume, example, given
from hypothesis import strategies as st

from stemlab.contract.formats import declaration as d
from stemlab.contract.kinds import ITEM_KINDS
from tests import properties  # noqa: F401  载入 Hypothesis 的设置

NAMES = st.from_regex(r"[a-z][a-z0-9_]{0,6}", fullmatch=True)
GROUPS = ["材料", "网格"]
PLACES = [f"{where}.{what}" for where, whats in d.REFERABLE.items() for what in whats]
WRONG = {"number": "x", "integer": 0.5, "bool": 1, "choice": "zz_not_a_choice", "choices": "zz", "text": 5,
         "vector3": [1, 2], "item": "not-an-id", "ref": "plain", "table": {"not": "a list"}}


@st.composite
def one_item(draw, name: str) -> dict:
    kind = draw(st.sampled_from(d.TYPES))
    required = draw(st.booleans())
    found = {"name": name, "label": f"{name} 的叫法", "meaning": f"{name} 是什么", "group": draw(st.sampled_from(GROUPS)),
             "type": kind, "per_point": draw(st.booleans()), "required": required, "test_source": "文献"}
    if kind == "number":
        low = draw(st.floats(-1e3, 1e3))
        high = low + draw(st.floats(0.01, 1e3))
        min_open, max_open = draw(st.booleans()), draw(st.booleans())
        found.update(unit=draw(st.sampled_from(sorted(d.UNITS))),
                     range={"min": low, "max": high, "min_open": min_open, "max_open": max_open},
                     test=draw(st.floats(low, high, exclude_min=min_open, exclude_max=max_open)))
    elif kind == "integer":
        low = draw(st.integers(-100, 100))
        high = low + draw(st.integers(0, 100))
        found.update(range={"min": low, "max": high}, test=draw(st.integers(low, high)))
    elif kind == "bool":
        found["test"] = draw(st.booleans())
    elif kind in ("choice", "choices"):
        values = draw(st.lists(NAMES, min_size=1, max_size=4, unique=True))
        found["choices"] = [{"value": value, "label": value} for value in values]
        found["test"] = draw(st.sampled_from(values) if kind == "choice" else st.lists(st.sampled_from(values), unique=True))
    elif kind == "text":
        found["test"] = draw(st.text(max_size=5))
    elif kind == "vector3":
        found["unit"] = draw(st.sampled_from(sorted(d.UNITS)))
        if draw(st.booleans()):
            found.update(unit_length=True, test=draw(st.sampled_from([[0, 0, 1], [1, 0, 0], [0.6, 0.8, 0]])))
        else:
            found["test"] = draw(st.lists(st.floats(-1e3, 1e3), min_size=3, max_size=3))
    elif kind == "item":
        found.update(kind=draw(st.sampled_from(sorted(ITEM_KINDS))), test=draw(st.sampled_from(["R0001", "C0042"])))
    elif kind == "ref":
        refers = draw(st.lists(st.sampled_from(PLACES), min_size=1, max_size=3, unique=True))
        found.update(refers=refers, test={"ref": f"{draw(st.sampled_from(refers))}.{draw(NAMES)}"})
    else:
        found["columns"] = [{"name": "tag", "label": "标签", "meaning": "这一行叫什么", "type": "text", "required": True},
                            {"name": "size", "label": "大小", "meaning": "多大", "type": "number", "required": False,
                             "unit": "mm", "range": {"min": 0, "max": 10}}]
        found["test"] = draw(st.lists(st.fixed_dictionaries({"tag": NAMES}, optional={"size": st.floats(0, 10)}), max_size=3))
    if not required and draw(st.booleans()):
        found["test"] = None
    return found


@st.composite
def declarations(draw) -> dict:
    names = draw(st.lists(NAMES, min_size=1, max_size=6, unique_by=str.lower))
    items = [draw(one_item(name)) for name in names]
    for position, item in enumerate(items):           # 有的项只在前面某一项取某几个值时才有
        controls = [other for other in items[:position] if other["type"] in ("choice", "bool") and not other["per_point"]]
        if controls and draw(st.booleans()):
            other = draw(st.sampled_from(controls))
            allowed = [c["value"] for c in other["choices"]] if other["type"] == "choice" else [True, False]
            item["when"] = {other["name"]: draw(st.lists(st.sampled_from(allowed), min_size=1, unique=True))}
    return {"name": "made", "groups": GROUPS, "items": items}


def formal(declaration: dict) -> dict:
    setting = d.test_setting(declaration, "R0001")
    return dict(setting, use="formal", sources={name: "照测试轮的取值" for name in setting["values"]})


def rules_in(problems) -> set[int]:
    return {rule for rule in d.RULES if any(f"规则 {rule}：" in text for text in problems)}


def _chain() -> dict:
    """属性测试 2026-11-16 找到的反例：c 只在 a 为真时有，d 只在 c 取 'a' 时有。测试轮里 a 是假的：c 不在，d 也不该在。"""
    def item(name, kind, **more):
        return {"name": name, "label": name, "meaning": name, "group": "材料", "type": kind, "per_point": False,
                "required": False, "test_source": "文献", **more}
    return {"name": "made", "groups": GROUPS, "items": [
        item("a", "bool", test=False),
        item("c", "choice", required=True, choices=[{"value": "a", "label": "a"}], test="a", when={"a": [True]}),
        item("d", "number", unit="1", range={"min": 0.0, "max": 1.0}, test=0.0, when={"c": ["a"]})]}


@example(_chain())
@given(declarations())
def test_a_declaration_that_keeps_the_rules_gives_a_test_setting_that_passes(declaration):
    assert d.check_declaration(declaration) == []
    assert d.check_setting(d.test_setting(declaration, "R0001"), declaration, of="R0001", use="test") == []
    assert d.check_setting(formal(declaration), declaration, of="R0001", use="formal") == []


@given(declarations(), st.data())
def test_a_value_of_the_wrong_type_is_refused_by_rule_4_and_names_the_item(declaration, data):
    setting = formal(declaration)
    assume(setting["values"])
    name = data.draw(st.sampled_from(sorted(setting["values"])))
    kind = next(item["type"] for item in declaration["items"] if item["name"] == name)
    setting["values"][name] = WRONG[kind]
    problems = d.check_setting(setting, declaration)
    assert rules_in(problems) == {4} and all(f"'{name}'" in text for text in problems), problems


@given(declarations(), st.data())
def test_a_missing_required_item_is_refused_by_rule_3_and_an_unknown_one_by_rule_2(declaration, data):
    setting = formal(declaration)
    required = [item["name"] for item in declaration["items"] if item["required"] and item["name"] in setting["values"]]
    if required:
        dropped = dict(setting, values=dict(setting["values"]))
        del dropped["values"][data.draw(st.sampled_from(required))]
        assert rules_in(d.check_setting(dropped, declaration)) == {3}
    extra = dict(setting, values=dict(setting["values"], zz_unknown_item=1))
    assert rules_in(d.check_setting(extra, declaration)) == {2}


@given(declarations(), st.data())
def test_per_point_items_given_point_by_point_pass_and_a_missing_one_is_rule_6(declaration, data):
    setting = formal(declaration)
    each = [item["name"] for item in declaration["items"] if item["per_point"] and item["name"] in setting["values"]]
    assume(each)
    point = {name: setting["values"][name] for name in each}
    setting["values"].update({name: dict(d.PER_POINT) for name in each})
    assert d.check_setting(setting, declaration) == [] and d.per_point_items(setting) == sorted(each)
    assert d.check_point(point, setting, declaration) == []
    del point[data.draw(st.sampled_from(each))]
    assert rules_in(d.check_point(point, setting, declaration)) == {6}
