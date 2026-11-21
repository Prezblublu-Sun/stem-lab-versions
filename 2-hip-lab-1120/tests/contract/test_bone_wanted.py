"""用骨模型的一方要什么（包的清单 inputs 里的 bone）：要求写得出；写错的被点名；一份骨模型缺哪一样，说得出是哪一样。"""
from __future__ import annotations

import copy

import pytest

from stemlab.contract.formats import bone_model
from stemlab.contract.versions import upcast
from tests.contract import bone_samples as samples
from tests.contract.bone_samples import listed_v1 as listed

WHOLE = samples.manifest(samples.good())                    # 完整的股骨：皮质、松质、髓腔三个区域，照后髁连线定
PROXIMAL = samples.manifest(samples.good(whole=False))      # 只有近端一段的：照颈轴加前倾角定
OLD = upcast("bone_model", listed())                        # 第 1 版读来的：两个区域，覆盖范围和前倾角不知道

# 一份写全了的要求：一块皮质、一块松质，髓腔有没有都行；STEP 或 STL；线弹性；五个标志点；到小转子下至少 150 mm
WANT = {
    "regions": {"cortical": [1, 1], "cancellous": [1, 1], "canal": [0, None]},
    "geometry": ["step", "stl"],
    "materials": ["elastic"],
    "landmarks": ["head_center", "neck_center", "shaft_proximal", "shaft_distal", "lesser_trochanter"],
    "coverage": {"extent": ["whole", "proximal"], "distal_mm": 150.0, "proximal_mm": 60},
    "frame": {"methods": ["shaft_condyles", "shaft_neck"]},
    "what": "两个实体照原样用；干轴、颈轴、远端截断由标志点定",
}


def test_what_a_requirement_may_say():
    assert bone_model.WANTED == ("regions", "geometry", "materials", "landmarks", "coverage", "frame", "what")


def test_a_bone_model_that_has_everything_lacks_nothing():
    assert bone_model.check_wanted(WANT) == []
    assert bone_model.lacking(WANT, WHOLE) == [] and bone_model.lacking(WANT, PROXIMAL) == []


def test_asking_for_nothing_is_fine_and_any_bone_model_will_do():
    """每一项都可以不写，不写就是不挑。"""
    assert bone_model.check_wanted({}) == []
    for model in (WHOLE, PROXIMAL, OLD):
        assert bone_model.lacking({}, model) == []
    for key, value in WANT.items():
        assert bone_model.check_wanted({key: value}) == [], key
        assert bone_model.lacking({key: value}, WHOLE) == [], key


def test_the_requirements_the_test_packages_already_write_are_well_formed():
    assert bone_model.check_wanted({"landmarks": ["head_center"]}) == [] and bone_model.check_wanted({"landmarks": []}) == []
    assert bone_model.lacking({"landmarks": ["head_center"]}, OLD) == []


# ---------------------------------------------------------------- 要求自己写得对不对

def asked(*path, value=...):
    return samples.changed(WANT, *path, value=value)


BAD_WANTS = [
    ("不是对象", ["landmarks"], "对骨模型的要求必须是一个 JSON 对象"),
    ("多了契约不认得的项", asked("landmark", value=["head_center"]), "对骨模型的要求里多了 landmark：只认"),
    ("旧写法的项", {"version": 1, "landmarks": ["head_center"]}, "对骨模型的要求里多了 version：只认"),
    ("区域不是对象", asked("regions", value=["cortical", "cancellous"]), "regions 要写成"),
    ("区域是空的", asked("regions", value={}), "regions 要写成"),
    ("区域的角色不认识", asked("regions", "marrow", value=[0, 1]), "regions 要写成"),
    ("区域的个数不是一对", asked("regions", "cortical", value=1), "regions 要写成"),
    ("区域的个数多写了一个", asked("regions", "cortical", value=[1, 1, 1]), "regions 要写成"),
    ("最少是负的", asked("regions", "cortical", value=[-1, 1]), "regions 要写成"),
    ("最少不是整数", asked("regions", "cortical", value=[1.0, 2]), "regions 要写成"),
    ("最少写成是否", asked("regions", "cortical", value=[True, 2]), "regions 要写成"),
    ("最多比最少小", asked("regions", "cortical", value=[2, 1]), "regions 要写成"),
    ("最多是 0", asked("regions", "canal", value=[0, 0]), "regions 要写成"),
    ("最多不是整数", asked("regions", "cortical", value=[1, "2"]), "regions 要写成"),
    ("最多写成是否", asked("regions", "cortical", value=[1, True]), "regions 要写成"),
    ("几何不是列表", asked("geometry", value="step"), "geometry 要从 ['step', 'stl'] 里选"),
    ("几何是空的", asked("geometry", value=[]), "geometry 要从 ['step', 'stl'] 里选"),
    ("几何的格式不认识", asked("geometry", value=["step", "iges"]), "geometry 要从 ['step', 'stl'] 里选"),
    ("几何重复", asked("geometry", value=["step", "step"]), "geometry 要从 ['step', 'stl'] 里选"),
    ("几何里不是文字", asked("geometry", value=[["step"]]), "geometry 要从 ['step', 'stl'] 里选"),
    ("材料不是列表", asked("materials", value={"elastic": True}), "materials 要从"),
    ("材料是空的", asked("materials", value=[]), "materials 要从"),
    ("材料是第 1 版的叫法", asked("materials", value=["linear_elastic"]), "materials 要从"),
    ("材料是柄才有的给法", asked("materials", value=["elastic", "piecewise"]), "materials 要从"),
    ("材料重复", asked("materials", value=["elastic", "elastic"]), "materials 要从"),
    ("标志点不是列表", asked("landmarks", value="head_center"), "landmarks 要是标志点名字的列表"),
    ("标志点的名字不合规矩", asked("landmarks", value=["Head Center"]), "landmarks 要是标志点名字的列表"),
    ("标志点重复", asked("landmarks", value=["head_center", "head_center"]), "landmarks 要是标志点名字的列表"),
    ("覆盖范围不是对象", asked("coverage", value="whole"), "coverage 要写成"),
    ("覆盖范围是空的", asked("coverage", value={}), "coverage 要写成"),
    ("覆盖范围多了一项", asked("coverage", "length_mm", value=400), "coverage 要写成"),
    ("覆盖范围的种类不是列表", asked("coverage", "extent", value="whole"), "coverage 要写成"),
    ("覆盖范围的种类不认识", asked("coverage", "extent", value=["whole", "distal"]), "coverage 要写成"),
    ("覆盖范围的种类是空的", asked("coverage", "extent", value=[]), "coverage 要写成"),
    ("往远端不是数", asked("coverage", "distal_mm", value="150"), "coverage 要写成"),
    ("往远端是 0", asked("coverage", "distal_mm", value=0), "coverage 要写成"),
    ("往近端是负的", asked("coverage", "proximal_mm", value=-5), "coverage 要写成"),
    ("坐标系写成列表", asked("frame", value=["shaft_condyles"]), "frame 要写成"),
    ("坐标系没写收哪几种", asked("frame", value={"unknown_anteversion": True}), "frame 要写成"),
    ("坐标系多了一项", asked("frame", "origin", value="head"), "frame 要写成"),
    ("坐标系的定法不认识", asked("frame", "methods", value=["isb"]), "frame 要写成"),
    ("坐标系的定法是空的", asked("frame", "methods", value=[]), "frame 要写成"),
    ("坐标系的定法重复", asked("frame", "methods", value=["shaft_neck", "shaft_neck"]), "frame 要写成"),
    ("收不收不知道前倾角的不是是否", asked("frame", "unknown_anteversion", value="yes"), "frame 要写成"),
    ("说明是空的", asked("what", value=" "), "what 要是一句给人看的说明"),
    ("说明不是文字", asked("what", value=["x"]), "what 要是一句给人看的说明"),
]


@pytest.mark.parametrize("why,want,said", BAD_WANTS, ids=[row[0] for row in BAD_WANTS])
def test_a_requirement_written_wrong_is_named(why, want, said):
    problems = bone_model.check_wanted(want)
    assert len(problems) == 1 and said in problems[0], f"{why}：{problems}"
    assert bone_model.lacking(want, WHOLE) == [f"对骨模型的要求写得不对：{problems[0]}"], "写错的要求不拿去核骨模型"


def test_every_mistake_in_a_requirement_is_named():
    problems = bone_model.check_wanted({"geometry": [], "what": "", "solids": {}, "bone_id": []})
    assert [text.split("：")[0].split(" 要")[0] for text in problems] == [
        "对骨模型的要求里多了 solids", "对骨模型的要求里多了 bone_id", "geometry", "what"], problems


def test_the_edges_of_what_a_requirement_may_say():
    assert bone_model.check_wanted({"regions": {"other": [0, 1], "cartilage": [3, 3], "cortical": [0, None], "canal": [2, None]}}) == []
    assert bone_model.check_wanted({"coverage": {"distal_mm": 0.5}}) == [] and bone_model.check_wanted({"coverage": {"extent": ["proximal"]}}) == []
    assert bone_model.check_wanted({"frame": {"methods": ["shaft_neck"], "unknown_anteversion": False}}) == []
    assert bone_model.check_wanted({"materials": list(bone_model.MATERIALS)}) == []


# ---------------------------------------------------------------- 一份骨模型缺哪一样

def model(*path, value=...) -> dict:
    return samples.changed(WHOLE, *path, value=value)


def with_region(role: str, name: str, form: str = "step", material=...) -> dict:
    made = copy.deepcopy(WHOLE)
    made["regions"].append({"name": name, "role": role, "geometry": {"kind": "solid", "format": form, "file": f"regions/{name}.{form}"},
                            "volume_mm3": 100.0, "material": dict(samples.BONE) if material is ... else material})
    return made


def without_region(name: str) -> dict:
    made = copy.deepcopy(WHOLE)
    made["regions"] = [region for region in made["regions"] if region["name"] != name]
    return made


LACKING = [
    ("少一个要的角色", WANT, without_region("cancellous"), "区域：要至少 1 个松质（cancellous）的区域，这份骨模型有 0 个"),
    ("一个角色多了一块", WANT, with_region("cortical", "patch"), "区域：最多收 1 个皮质（cortical）的区域，这份骨模型有 2 个：['cortical', 'patch']"),
    ("有没列的角色", WANT, with_region("cartilage", "head_cartilage"), "区域：不收软骨（cartilage）的区域，这份骨模型有 ['head_cartilage']"),
    ("髓腔没列就不收", {"regions": {"cortical": [1, 1], "cancellous": [1, 1]}}, WHOLE, "区域：不收髓腔（canal）的区域，这份骨模型有 ['canal']"),
    ("几何的格式不收", {"geometry": ["step"]}, WHOLE, "几何：只收 ['step'] 的几何文件，区域 'canal' 是 stl"),
    ("材料模型不会", WANT, model("regions", 1, "material", value={"model": "neo_hooke", "C10": 6.8, "D1": 0.0015}),
     "材料：只会 ['elastic'] 这几种材料模型，区域 'cancellous' 的是 neo_hooke"),
    ("少一个标志点", {"landmarks": ["head_center", "greater_trochanter", "fovea"]}, WHOLE, "标志点：缺 ['greater_trochanter', 'fovea']"),
    ("覆盖范围的种类不收", {"coverage": {"extent": ["whole"]}}, PROXIMAL, "覆盖范围：只收 ['whole']，这份是 proximal"),
    ("往远端不够长", {"coverage": {"distal_mm": 200}}, PROXIMAL, "覆盖范围：要往远端至少到 200 mm，这份只到 180.0 mm"),
    ("往近端不够长", {"coverage": {"proximal_mm": 74.5}}, WHOLE, "覆盖范围：要往近端至少到 74.5 mm，这份只到 74.0 mm"),
    ("坐标系的定法不收", {"frame": {"methods": ["shaft_condyles"]}}, PROXIMAL, "解剖坐标系：只收照 ['shaft_condyles'] 定的，这份是照 shaft_neck 定的"),
    ("坐标系的定法不收（反过来）", {"frame": {"methods": ["shaft_neck"], "unknown_anteversion": True}}, WHOLE,
     "解剖坐标系：只收照 ['shaft_neck'] 定的，这份是照 shaft_condyles 定的"),
]


@pytest.mark.parametrize("why,want,given,said", LACKING, ids=[row[0] for row in LACKING])
def test_what_a_bone_model_lacks_is_named(why, want, given, said):
    """每个情形只缺一样：正好一句，说的就是那一样。"""
    assert bone_model.lacking(want, given) == [said], why


def test_just_enough_is_enough():
    assert bone_model.lacking({"coverage": {"distal_mm": 180.0, "proximal_mm": 74}}, PROXIMAL) == []
    assert bone_model.lacking({"regions": {"cortical": [0, 1], "cancellous": [1, None], "canal": [1, 1]}}, WHOLE) == []
    assert bone_model.lacking({"regions": {"cortical": [1, 2], "cancellous": [1, 1], "canal": [0, 1]}}, with_region("cortical", "patch")) == []
    assert bone_model.lacking({"regions": {"cortical": [0, 1], "cancellous": [0, 1], "canal": [0, 1], "other": [0, 3]}}, without_region("canal")) == []
    assert bone_model.lacking({"materials": ["elastic"]}, WHOLE) == [], "髓腔没有材料，不算不会"


def test_everything_lacking_is_named_one_by_one():
    given = with_region("other", "screw_hole", form="stl", material={"model": "mooney_rivlin", "C10": 1.0, "C01": 0.1, "D1": 0.0})
    given = samples.changed(given, "regions", 1, "role", value="cortical")
    want = {**WANT, "geometry": ["step"], "landmarks": ["fovea"], "coverage": {"extent": ["proximal"], "distal_mm": 500, "proximal_mm": 100},
            "frame": {"methods": ["shaft_neck"]}}
    assert bone_model.lacking(want, given) == [
        "区域：最多收 1 个皮质（cortical）的区域，这份骨模型有 2 个：['cortical', 'cancellous']",
        "区域：要至少 1 个松质（cancellous）的区域，这份骨模型有 0 个",
        "区域：不收其他（other）的区域，这份骨模型有 ['screw_hole']",
        "几何：只收 ['step'] 的几何文件，区域 'canal' 是 stl",
        "几何：只收 ['step'] 的几何文件，区域 'screw_hole' 是 stl",
        "材料：只会 ['elastic'] 这几种材料模型，区域 'screw_hole' 的是 mooney_rivlin",
        "标志点：缺 ['fovea']",
        "覆盖范围：只收 ['proximal']，这份是 whole",
        "覆盖范围：要往远端至少到 500 mm，这份只到 425.0 mm",
        "覆盖范围：要往近端至少到 100 mm，这份只到 74.0 mm",
        "解剖坐标系：只收照 ['shaft_neck'] 定的，这份是照 shaft_condyles 定的",
    ]


# ---------------------------------------------------------------- 不知道的东西，要求里要它就算缺

def test_a_bone_model_read_from_the_first_version_lacks_what_it_does_not_know():
    """第 1 版读来的骨模型：覆盖范围不知道；坐标系照颈轴定、前倾角不知道（没有转回去）。用的一方要它而它不知道，就拒。"""
    base = {"regions": {"cortical": [1, 1], "cancellous": [1, 1]}, "geometry": ["step"], "materials": ["elastic"],
            "landmarks": list(bone_model.LANDMARKS)}
    assert bone_model.lacking(base, OLD) == [], "区域、几何、材料、标志点，第 1 版都有"
    assert bone_model.lacking({**base, "coverage": {"extent": ["whole", "proximal"]}}, OLD) == [
        "覆盖范围：这份骨模型不知道覆盖范围（第 1 版读来的），要求里要它"]
    assert bone_model.lacking({**base, "coverage": {"distal_mm": 1}}, OLD) == ["覆盖范围：这份骨模型不知道覆盖范围（第 1 版读来的），要求里要它"]
    both = {"frame": {"methods": ["shaft_condyles", "shaft_neck"]}}
    assert bone_model.lacking({**base, **both}, OLD) == [
        "解剖坐标系：这份是照颈轴定的、前倾角不知道（第 1 版读来的，没有转回去），要求里没说收这种"]
    assert bone_model.lacking({"frame": {**both["frame"], "unknown_anteversion": False}}, OLD) == [
        "解剖坐标系：这份是照颈轴定的、前倾角不知道（第 1 版读来的，没有转回去），要求里没说收这种"]
    assert bone_model.lacking({**base, "frame": {**both["frame"], "unknown_anteversion": True}}, OLD) == [], "说了收才收"
    assert bone_model.lacking({"frame": {"methods": ["shaft_condyles"], "unknown_anteversion": True}}, OLD) == [
        "解剖坐标系：只收照 ['shaft_condyles'] 定的，这份是照 shaft_neck 定的"]
    assert bone_model.lacking({**both}, PROXIMAL) == [], "写了前倾角的照颈轴定的骨模型，不用另说"


def test_a_geometry_file_of_unknown_kind_is_lacking_when_the_kind_is_asked_for():
    odd = upcast("bone_model", {**listed(**samples.changed_v1("solids", "cortical", "file", value="solids/cortical.brep")),
                                "files": ["solids/cortical.brep", "solids/cancellous.step"]})
    assert bone_model.lacking({"geometry": ["step", "stl"]}, odd) == [
        "几何：区域 'cortical' 的几何文件不知道是哪一种（第 1 版读来的），要求只收 ['step', 'stl']"]
    assert bone_model.lacking({"landmarks": ["head_center"]}, odd) == [], "没问几何的格式，就不算缺"


def test_the_bone_model_must_have_been_read_into_the_current_version_first():
    """lacking 认的是读成现在这一版的清单（bone_model.read）。把盘上第 1 版的原样交来，说出来，不当成什么都缺。"""
    assert bone_model.lacking(WANT, listed()) == ["骨模型的清单要先读成现在这一版再核（bone_model.read）"]
    assert bone_model.lacking({}, listed()) == ["骨模型的清单要先读成现在这一版再核（bone_model.read）"]
    assert bone_model.lacking(WANT, None) == ["骨模型的清单要先读成现在这一版再核（bone_model.read）"]
