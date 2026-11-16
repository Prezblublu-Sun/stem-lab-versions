"""设定的声明和登记的设定（《设定的声明和包的清单》第二、三节）：声明自己要合规矩；设定的九条规矩，每条一个只违它的情形，
被拒，说出是哪一项、哪一条。"""
from __future__ import annotations

import copy

import pytest

from stemlab.contract.formats import declaration as d

OF = "R0007"


def item(name, of_type, **more):
    base = {"name": name, "label": f"{name} 的叫法", "meaning": f"{name} 是什么", "group": "相互作用", "type": of_type,
            "per_point": False, "required": True, "test_source": "文献"}
    return {**base, **more}


def sample() -> dict:
    """一份照 Abaqus 分组写的有限元设定的声明：各种类型都有，有“只在什么时候有”，有大小关系，有表，有名字引用。"""
    choices = [{"value": v, "label": v} for v in ("frictionless", "penalty", "lagrange")]
    return {
        "name": "fea",
        "groups": ["相互作用", "网格", "分析步", "载荷"],
        "items": [
            item("tangential", "choice", choices=choices, test="penalty", abaqus="*FRICTION"),
            item("mu", "number", unit="1", range={"min": 0, "max": 1}, when={"tangential": ["penalty", "lagrange"]},
                 per_point=True, test=0.3),
            item("mesh_mm", "number", group="网格", unit="mm", range={"min": 0, "max": 10, "min_open": True}, test=1.0),
            item("refine_mm", "number", group="网格", unit="mm", range={"min": 0, "max": 10, "min_open": True},
                 required=False, test=0.5),
            item("threads", "integer", group="网格", range={"min": 1, "max": 64}, test=4),
            item("nlgeom", "bool", group="分析步", test=True),
            item("outputs", "choices", group="分析步", choices=[{"value": v, "label": v} for v in ("S", "U", "CSTRESS")],
                 test=["S", "U"]),
            item("tag", "text", group="分析步", pattern="[A-Za-z0-9]+", required=False, test="run1"),
            item("steps", "table", group="分析步", test=[{"name": "release", "what": "release", "seconds": 1.0},
                                                        {"name": "load", "what": "load"}],
                 columns=[{"name": "name", "label": "步名", "meaning": "这一步叫什么", "type": "text", "required": True},
                          {"name": "what", "label": "做什么", "meaning": "这一步做什么", "type": "choice", "required": True,
                           "choices": [{"value": "release", "label": "消过盈"}, {"value": "load", "label": "加载"}]},
                          {"name": "seconds", "label": "时长", "meaning": "这一步多长", "type": "number", "required": False,
                           "unit": "s", "range": {"min": 0, "max": 100, "min_open": True}}]),
            item("direction", "vector3", group="载荷", unit="1", unit_length=True, per_point=True, test=[0, 0, 1]),
            item("load_point", "ref", group="载荷", refers=["stem.feature"], test={"ref": "stem.feature.taper_center"}),
            item("bone", "item", group="载荷", kind="bone_model", test="C0001"),
        ],
        "relations": [{"less": "refine_mm", "than": "mesh_mm"}],
    }


def formal(declaration=None) -> dict:
    """照声明的测试轮取值拼一份正式的设定，每项写了来路。"""
    declaration = declaration or sample()
    setting = d.test_setting(declaration, OF)
    return dict(setting, use="formal", sources={name: "照测试轮的取值" for name in setting["values"]})


def rules_in(problems) -> set[int]:
    return {rule for rule in d.RULES if any(f"规则 {rule}：" in text for text in problems)}


# ---------------------------------------------------------------- 声明自己

def test_the_sample_declaration_and_its_test_setting_pass():
    declaration = sample()
    assert d.check_declaration(declaration) == []
    assert d.check_setting(d.test_setting(declaration, OF), declaration, of=OF, use="test") == []
    assert d.check_setting(formal(), declaration, of=OF, use="formal") == []


@pytest.mark.parametrize("change,said", [
    (lambda x: x["items"][1].pop("unit"), "要写 unit"),
    (lambda x: x["items"][1].update(unit="毫米"), "单位要从单位表里选"),
    (lambda x: x["items"][1].update(range={"min": 2, "max": 1}), "min 不大于 max"),
    (lambda x: x["items"][4].update(range={"min": 1.5, "max": 64}), "两头要是整数"),
    (lambda x: x["items"][0].update(choices=[{"value": "a", "label": "甲"}, {"value": "a", "label": "乙"}]), "value 有重复"),
    (lambda x: x["items"][5].update(unit="1"), "bool 不写 unit"),
    (lambda x: x["items"][1].update(when={"threads": [4]}), "只能看一项每个点都一样的几选一或是否"),
    (lambda x: x["items"][1].update(when={"tangential": ["sticky"]}), "取值要从"),
    (lambda x: x["items"][1].update(test=2.0), "测试轮的取值不合规矩"),
    (lambda x: x["items"][2].update(test=None), "必填的项，测试轮也要有取值"),
    (lambda x: x["items"][1].update(test={"per_point": True}), "不能写“每个点给”"),
    (lambda x: x["items"][0].update(group="没有这一组"), "不在 groups 里"),
    (lambda x: x["items"][0].update(test_source=" "), "来路要写"),
    (lambda x: x["items"].append(item("Mu", "bool", test=True)), "只差大小写"),
    (lambda x: x["items"][8]["columns"].append({"name": "sub", "label": "子表", "meaning": "表里套表", "type": "table",
                                               "required": False}), "类型要是"),
    (lambda x: x["items"][8]["columns"].append({"name": "sub", "label": "子表", "meaning": "多写了", "type": "text",
                                               "required": False, "per_point": True}), "多了 per_point"),
    (lambda x: x["items"][10].update(refers=["stem.colour"]), "refers 要从"),
    (lambda x: x["items"][11].update(kind="ct_scan"), "kind 要是登记的一种东西"),
    (lambda x: x.update(relations=[{"less": "refine_mm", "than": "threads"}]), "单位相同"),
    (lambda x: x["items"][3].update(test=2.0), "拼出来的测试轮设定不过核验"),
    (lambda x: x.update(name="FEA"), "小写字母"),
    (lambda x: x["items"][0].update(meaning=""), "label 和 meaning 要写清楚"),
    (lambda x: x["items"][1].update(range={"min": 0, "max": 1, "step": 0.1}), "range 要写成"),
    (lambda x: x["items"][1].update(range={"min": 0, "max": 1, "min_open": "yes"}), "min_open、max_open 要是"),
    (lambda x: x["items"][0].update(choices=[]), "choices 要是"),
    (lambda x: x["items"][0].update(choices=[{"value": "penalty"}]), "choices 要是"),
    (lambda x: x["items"][8].update(columns=[]), "columns 要是"),
    (lambda x: x["items"][8]["columns"].append(dict(x["items"][8]["columns"][0])), "列的名字要字母开头、不重复"),
    (lambda x: x["items"][1].update(when={}), "when 要写成"),
    (lambda x: x["items"][1].update(when={"mu": [0.3]}), "不是这份声明里别的一项"),
    (lambda x: x.update(relations={}), "relations 要是一个列表"),
    (lambda x: x.update(relations=[{"less": "refine_mm"}]), "大小关系要写成"),
    (lambda x: x.update(relations=[{"less": "mesh_mm", "than": "mesh_mm"}]), "不同的两项"),
    (lambda x: x.update(groups=["网格", "网格"]), "groups 要是不重复的组名列表"),
    (lambda x: x.update(items={}), "items 要是项的列表"),
    (lambda x: x["items"][0].update(name="1st"), "项的名字要字母开头"),
    (lambda x: x["items"].append(dict(x["items"][0])), "项的名字有重复的"),
    (lambda x: x.pop("groups"), "声明缺 groups"),
])
def test_a_declaration_that_breaks_a_rule_says_where(change, said):
    declaration = sample()
    change(declaration)
    problems = d.check_declaration(declaration)
    assert problems and any(said in text for text in problems), problems


# ---------------------------------------------------------------- 设定的九条规矩

def test_rule_1_the_declaration_must_be_the_one_filled_and_unchanged():
    declaration, setting = sample(), formal()
    changed = copy.deepcopy(declaration)
    changed["items"][1]["range"]["max"] = 0.9                   # 包的新版本改了声明：旧的设定对不上
    assert rules_in(d.check_setting(setting, changed)) == {1}
    assert rules_in(d.check_setting(setting, declaration, of="R0008")) == {1}


def test_rule_2_items_outside_the_declaration_are_refused():
    setting = formal()
    setting["values"]["friction"] = 0.2
    problems = d.check_setting(setting, sample())
    assert rules_in(problems) == {2} and any("'friction'" in text for text in problems)


def test_rule_3_required_items_are_there_and_conditional_ones_only_when_they_apply():
    declaration = sample()
    missing = formal()
    del missing["values"]["mesh_mm"], missing["sources"]["mesh_mm"]
    assert rules_in(d.check_setting(missing, declaration)) == {3}

    frictionless = formal()
    frictionless["values"]["tangential"] = "frictionless"       # 无摩擦时没有摩擦系数
    problems = d.check_setting(frictionless, declaration)
    assert rules_in(problems) == {3} and any("'mu'" in text for text in problems)
    del frictionless["values"]["mu"], frictionless["sources"]["mu"]
    assert d.check_setting(frictionless, declaration) == [], "条件不满足时不写它，才对"


@pytest.mark.parametrize("name,value", [
    ("mu", "0.3"), ("mu", 1.5), ("mesh_mm", 0), ("threads", 4.5), ("nlgeom", 1), ("tangential", "sticky"),
    ("outputs", ["S", "S"]), ("tag", "has space"), ("direction", [0, 0, 2]), ("steps", [{"name": "load"}]),
    ("steps", [{"name": "x", "what": "load", "seconds": 0}]), ("load_point", {"ref": "bone.region.cortical"}),
    ("load_point", "stem.feature.taper_center"), ("bone", "femur042"), ("tangential", {"per_point": True}),
    ("load_point", {"ref": "stem.feature.taper_center", "side": "left"}), ("outputs", ["S", "X"]),
    ("steps", ["release"]), ("steps", [{"name": "x", "what": "load", "colour": "red"}]), ("mesh_mm", True),
])
def test_rule_4_type_range_and_choices(name, value):
    setting = formal()
    setting["values"][name] = value
    problems = d.check_setting(setting, sample())
    assert rules_in(problems) == {4} and all(f"'{name}'" in text for text in problems), problems


@pytest.mark.parametrize("refine", [2.0, 1.0])                 # 加密的网格比整体的还粗；一样粗也不算加密
def test_rule_5_relations_between_items_hold(refine):
    setting = formal()
    setting["values"]["refine_mm"] = refine
    problems = d.check_setting(setting, sample())
    assert rules_in(problems) == {5} and "'refine_mm'" in problems[0]


def test_a_vector_needs_three_numbers_even_when_it_is_not_a_direction():
    declaration = sample()
    declaration["items"][9].pop("unit_length")
    setting = formal(declaration)
    setting["values"]["direction"] = [1, 2]
    assert rules_in(d.check_setting(setting, declaration)) == {4}


def test_rule_6_per_point_items_are_given_by_every_point_and_checked_the_same_way():
    declaration, setting = sample(), formal()
    setting["values"]["mu"] = {"per_point": True}
    setting["values"]["direction"] = {"per_point": True}
    assert d.check_setting(setting, declaration) == [] and d.per_point_items(setting) == ["direction", "mu"]
    assert d.check_point({"mu": 0.2, "direction": [1, 0, 0]}, setting, declaration) == []
    assert d.merged(setting, {"mu": 0.2, "direction": [1, 0, 0]})["mu"] == 0.2
    assert rules_in(d.check_point({"mu": 0.2}, setting, declaration)) == {6}, "设定说每个点给，这个点没给"
    assert rules_in(d.check_point({"mu": 0.2, "direction": [1, 0, 0], "threads": 8}, setting, declaration)) == {6}
    assert rules_in(d.check_point({"mu": 2.0, "direction": [1, 0, 0]}, setting, declaration)) == {4}, "每个点给的照同一份声明核"


def test_rule_6_relations_are_checked_on_each_point_when_one_side_is_per_point():
    declaration = sample()
    declaration["items"][3]["per_point"] = True                 # 加密的尺寸每个点能变
    setting = formal(declaration)
    setting["values"]["refine_mm"] = {"per_point": True}
    assert d.check_setting(setting, declaration) == []
    assert d.check_point({"refine_mm": 0.5}, setting, declaration) == []
    assert rules_in(d.check_point({"refine_mm": 3.0}, setting, declaration)) == {5}


def test_rule_6_a_design_is_given_point_by_point_item_by_item():
    """柄空间包的设计项没有设定：每一项都由一批点逐个给（check_design）。"""
    choices = [{"value": v, "label": v} for v in ("collared", "collarless")]
    declaration = {"name": "design", "groups": ["形状"], "items": [
        item("length", "number", group="形状", unit="mm", range={"min": 80, "max": 200}, per_point=True, test=140.0),
        item("collar", "choice", group="形状", choices=choices, per_point=True, test="collared"),
        item("tip", "number", group="形状", unit="mm", range={"min": 0, "max": 20}, per_point=True, test=6.0),
        item("shoulder", "number", group="形状", unit="mm", range={"min": 0, "max": 40}, per_point=True, test=18.0)],
        "relations": [{"less": "tip", "than": "shoulder"}]}
    assert d.check_declaration(declaration) == []
    assert d.check_design({"length": 140.0, "collar": "collarless", "tip": 6.0, "shoulder": 18.0}, declaration) == []
    assert rules_in(d.check_design({"length": 140.0, "collar": "collared", "tip": 6.0}, declaration)) == {6}, "没写全"
    assert rules_in(d.check_design({"length": 140.0, "collar": "collared", "tip": 6.0, "shoulder": 18.0, "neck": 3.0},
                                   declaration)) == {6}, "多了声明外的项"
    assert rules_in(d.check_design({"length": 300.0, "collar": "collared", "tip": 6.0, "shoulder": 18.0}, declaration)) == {4}
    assert rules_in(d.check_design({"length": 140.0, "collar": "collared", "tip": 20.0, "shoulder": 18.0}, declaration)) == {5}, \
        "合起来大小关系也要成立"


def test_rule_7_test_settings_and_formal_rounds_do_not_mix():
    declaration = sample()
    assert rules_in(d.check_setting(d.test_setting(declaration, OF), declaration, use="formal")) == {7}
    assert rules_in(d.check_setting(formal(), declaration, use="test")) == {7}


def test_rule_8_names_referred_to_exist_in_the_actual_inputs():
    declaration, setting = sample(), formal()
    assert d.check_setting(setting, declaration, names={"stem.feature": {"taper_center", "tip"}}) == []
    problems = d.check_setting(setting, declaration, names={"stem.feature": {"tip"}})
    assert rules_in(problems) == {8} and "stem.feature.taper_center" in problems[0]


def test_rule_9_a_formal_setting_says_where_every_value_came_from():
    setting = formal()
    del setting["sources"]["mu"]
    problems = d.check_setting(setting, sample())
    assert rules_in(problems) == {9} and "'mu'" in problems[0]
    test = d.test_setting(sample(), OF)
    assert test["sources"]["mu"] == "文献", "测试轮的来路就是声明里测试轮取值的来路"


def test_conditions_chain_down_in_the_test_round():
    """“只在什么时候有”一层层往下推：它看的那一项不在，它也不在（属性测试找到过这个反例）。"""
    declaration = sample()
    declaration["items"].append(item("lock", "bool", test=False))
    declaration["items"].append(item("mode", "choice", choices=[{"value": "a", "label": "甲"}], test="a", when={"lock": [True]}))
    declaration["items"].append(item("depth", "number", unit="mm", range={"min": 0, "max": 1}, test=0.5, when={"mode": ["a"]}))
    assert d.check_declaration(declaration) == []
    values = d.test_setting(declaration, OF)["values"]
    assert "mode" not in values and "depth" not in values and values["lock"] is False


def test_a_setting_that_is_not_shaped_right_is_refused_before_anything_else():
    assert d.check_setting([], sample()) == ["设定必须是一个 JSON 对象"]
    assert "设定缺 use" in d.check_setting({"declaration": {}, "values": {}, "sources": {}}, sample())
    assert "设定多了 extra" in d.check_setting(dict(formal(), extra=1), sample())
    assert d.check_setting(dict(formal(), values=[]), sample())[-1] == "values 和 sources 都要是 JSON 对象"
    assert "设定缺 format" in d.check_setting({k: v for k, v in formal().items() if k != "format"}, sample())
    assert "第 2 版" in d.check_setting(dict(formal(), format=2), sample())[0], "设定的写法有版本，旧的、新的都说出来"
    assert d.is_declared(formal()) and not d.is_declared({"x": 1}) and not d.is_declared({"declaration": {}})
    assert d.find([sample()], "fea") == sample() and d.find([sample(), sample()], "fea") is None and d.find("x", "fea") is None
    assert "用途要是" in d.check_setting(dict(formal(), use="draft"), sample())[0]
    assert d.check_declaration([]) == ["声明必须是一个 JSON 对象"]
    assert d.check_declaration(dict(sample(), extra=1)) == ["声明多了 extra"]
    setting = formal()
    setting["values"]["mu"] = {"per_point": True}
    assert d.check_point([], setting, sample())[0].startswith("一个点给的取值要是一个 JSON 对象")


def test_the_declaration_hash_follows_its_content():
    one, two = sample(), sample()
    assert d.declaration_hash(one) == d.declaration_hash(two)
    two["items"][0]["label"] = "切向"
    assert d.declaration_hash(one) != d.declaration_hash(two)
