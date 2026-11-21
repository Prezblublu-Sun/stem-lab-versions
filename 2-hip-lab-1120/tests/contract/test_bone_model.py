"""骨模型和候选骨模型（第 2 版）：好样本过；每一条规矩一个只违它的坏样本，被点名是哪一段、哪一项。

第 1 版的清单照样读，见 test_bone_model_v1.py；解剖坐标系怎么算，见 test_bone_frame.py；用的一方要什么，见 test_bone_wanted.py。
"""
from __future__ import annotations

import copy

import pytest

from stemlab.contract.formats import bone_model
from stemlab.contract.formats.manifest import check_format, read_manifest
from stemlab.contract.versions import FORMATS, NewerFormat
from tests.contract import bone_samples as samples

GOOD = samples.good()


def problems_of(tmp_path, extra: dict, kind: str = "bone_model", files: dict | None = None) -> list[str]:
    return check_format(kind, samples.write(tmp_path / "b", extra, kind, files))


# ---------------------------------------------------------------- 好样本

@pytest.mark.parametrize("kind", ["bone_model", "bone_draft"])
@pytest.mark.parametrize("side", ["right", "left"])
@pytest.mark.parametrize("whole", [True, False], ids=["whole", "proximal"])
def test_good_bone_models_pass(tmp_path, kind, side, whole):
    """完整的股骨照后髁连线定坐标系；只有近端一段的照颈轴加前倾角定。左右都写得出。"""
    extra = samples.good(side, whole)
    assert problems_of(tmp_path, extra, kind) == []
    assert read_manifest(tmp_path / "b")["format"] == FORMATS["bone_model"] == 2


def test_what_every_bone_model_has():
    assert bone_model.LANDMARKS == ("head_center", "neck_center", "shaft_proximal", "shaft_distal", "lesser_trochanter")
    assert bone_model.CONDYLES == ("condyle_medial", "condyle_lateral")
    assert bone_model.UNITS == {"length": "mm", "force": "N", "stress": "MPa"}
    assert bone_model.SIDES == ("left", "right")
    assert bone_model.BONE_TYPES == ("real", "replica", "synthetic")
    assert bone_model.EXTENTS == ("whole", "proximal") and bone_model.HOWS == ("ct", "cad", "stl")
    assert list(bone_model.ROLES) == ["cortical", "cancellous", "canal", "cartilage", "other"]
    assert bone_model.GEOMETRY_FILES == {"step": (".step", ".stp"), "stl": (".stl",)}
    assert bone_model.MATERIALS == ("elastic", "engineering_constants", "neo_hooke", "mooney_rivlin", "density")
    assert bone_model.METHODS == ("shaft_condyles", "shaft_neck")
    assert bone_model.METHOD_OF == {"whole": "shaft_condyles", "proximal": "shaft_neck"}


def test_other_items_may_ride_along(tmp_path):
    """别的项照旧可以带（比如重建量出来的数），契约不核。"""
    assert problems_of(tmp_path, {**GOOD, "measures": {"head_radius_mm": 25.8}, "note": "第一根"}) == []


def test_one_region_is_enough_and_surfaces_may_be_none(tmp_path):
    extra = copy.deepcopy(GOOD)
    extra["regions"], extra["surfaces"] = extra["regions"][:1], {}
    files = {"regions/cortical.step": b"ISO-10303-21; whole bone"}
    assert problems_of(tmp_path, extra, files=files) == []


MATERIALS = [
    {"model": "engineering_constants", "E1": 12000, "E2": 13400, "E3": 20000, "nu12": 0.38, "nu13": 0.22, "nu23": 0.24,
     "G12": 4500, "G13": 5600, "G23": 6200, "axes": [[1, 0, 0], [0, 1, 0], [0, 0, 1]], "density": 1.9},
    {"model": "neo_hooke", "C10": 6.8, "D1": 0.0015},
    {"model": "mooney_rivlin", "C10": 4.1, "C01": 0.41, "D1": 0.0},
    {"model": "density", "ct": "C0003", "calibration": {"slope": 0.0008, "intercept": 0.0, "phantom": "QRM-BDC"},
     "relation": [{"from": 0.0, "to": 0.27, "a": 33900, "b": 2.2}, {"from": 0.27, "to": 0.6, "a": 5307, "b": 1.0},
                  {"from": 0.6, "to": 3.0, "a": 10200, "b": 2.01}],
     "nu": 0.3, "bounds": {"min": 5.0, "max": 22000.0}, "bins": 50, "mapping": "按单元取平均"},
]


@pytest.mark.parametrize("material", MATERIALS, ids=[row["model"] for row in MATERIALS])
def test_a_region_takes_any_material_a_bone_may_have(tmp_path, material):
    """材料和柄的模型用同一份写法：工程常数、两种超弹性；按骨密度给的只留位置，写法也核。"""
    assert problems_of(tmp_path, samples.changed(GOOD, "regions", 1, "material", value=material)) == []


def test_a_cartilage_region_can_be_written(tmp_path):
    extra = copy.deepcopy(GOOD)
    extra["regions"].append({"name": "head_cartilage", "role": "cartilage",
                             "geometry": {"kind": "solid", "format": "stl", "file": "regions/head_cartilage.STL"},
                             "volume_mm3": 4100.0, "material": {"model": "neo_hooke", "C10": 6.8, "D1": 0.0015}})
    extra["surfaces"]["joint"] = {"region": "head_cartilage", "file": "surfaces/joint.stl"}
    files = {**samples.FILES, "regions/head_cartilage.STL": b"solid cartilage", "surfaces/joint.stl": b"solid joint"}
    assert problems_of(tmp_path, extra, files=files) == [], "后缀不分大小写"


def test_a_hand_picked_landmark_has_nothing_fitted(tmp_path):
    extra = copy.deepcopy(GOOD)
    extra["landmarks"]["greater_trochanter"] = {
        "xyz": [-20.0, 3.0, 40.0], "definition": {"method": "picked-by.hand", "version": "2026-11", "params": {}, "text": "大转子的最高点，人点的"},
        "fit": {}}
    extra["landmarks"]["head_center"]["fit"] = {"rms_mm": 0.3, "converged": True}
    assert problems_of(tmp_path, extra) == []


# ---------------------------------------------------------------- 候选和定稿

def test_a_draft_may_have_checks_still_open_but_a_model_may_not(tmp_path):
    open_checks = [{"name": "landmarks", "value": None, "limit": "要人看过", "passed": None}]
    failed = [dict(GOOD["checks"][0], passed=False)]
    for number, checks in enumerate((open_checks, failed, [])):
        assert check_format("bone_draft", samples.write(tmp_path / f"draft{number}", {**GOOD, "checks": checks}, "bone_draft")) == []
    assert problems_of(tmp_path, {**GOOD, "checks": open_checks}) == ["检查 landmarks 没过或者还没做：骨模型里的每一项检查都必须是过了的"]
    assert check_format("bone_model", samples.write(tmp_path / "failed", {**GOOD, "checks": failed})) == [
        "检查 volume_cortical 没过或者还没做：骨模型里的每一项检查都必须是过了的"]
    assert check_format("bone_model", samples.write(tmp_path / "empty", {**GOOD, "checks": []})) == [
        "骨模型至少要有一项检查结果：没过检查门的不交骨模型"]


def test_the_bone_id_in_the_manifest_is_what_the_register_must_agree_with(tmp_path):
    assert read_manifest(samples.write(tmp_path / "b", GOOD))["bone_id"] == "femur042"


def test_a_newer_bone_model_is_said_out_loud(tmp_path):
    root = samples.write(tmp_path / "b", GOOD, version=3)
    with pytest.raises(NewerFormat, match="第 3 版"):
        check_format("bone_model", root)


# ---------------------------------------------------------------- 每一条规矩一个只违它的坏样本

def to(*path, value=...):
    """把好样本里沿 path 的那一项换成 value（... 是去掉）。"""
    return lambda: samples.changed(GOOD, *path, value=value)


def region(number: int, **change):
    def make():
        extra = copy.deepcopy(GOOD)
        extra["regions"][number].update(change)
        return extra
    return make


def neck_instead_of_condyles():
    """完整的股骨，坐标系却照颈轴定：别的都自洽（前倾角就是这根骨量出来的，原点和三个轴也对）。"""
    extra = copy.deepcopy(GOOD)
    extra["frame"] = {**GOOD["frame"], "method": "shaft_neck", "anteversion_deg": 12.0}
    return extra


def condyles_on_a_proximal_piece():
    """只有近端一段的，坐标系却照后髁连线定：标志点里有两个后髁，原点和三个轴也对。"""
    extra = samples.good(whole=True)
    extra["coverage"] = {"extent": "proximal", "proximal_mm": 74.0, "distal_mm": 180.0}
    return extra


def proximal(*path, value=...):
    return lambda: samples.changed(samples.good(whole=False), *path, value=value)


def landmark_moved_frame_kept():
    extra = copy.deepcopy(GOOD)
    extra["landmarks"]["lesser_trochanter"]["xyz"] = [value + 5.0 for value in extra["landmarks"]["lesser_trochanter"]["xyz"]]
    return extra


def condyle_moved_frame_kept():
    extra = copy.deepcopy(GOOD)
    extra["landmarks"]["condyle_medial"]["xyz"] = [value + 5.0 for value in extra["landmarks"]["condyle_medial"]["xyz"]]
    return extra


def other_side_frame_kept():
    return {**copy.deepcopy(GOOD), "side": "left"}


def anteversion_changed_frame_kept():
    return samples.changed(samples.good(whole=False), "frame", "anteversion_deg", value=13.0)


def condyles_swapped():
    extra = copy.deepcopy(GOOD)
    marks = extra["landmarks"]
    marks["condyle_medial"], marks["condyle_lateral"] = marks["condyle_lateral"], marks["condyle_medial"]
    return extra


def shaft_points_together():
    extra = copy.deepcopy(GOOD)
    extra["landmarks"]["shaft_distal"]["xyz"] = list(extra["landmarks"]["shaft_proximal"]["xyz"])
    return extra


def neck_and_head_together():
    extra = copy.deepcopy(GOOD)
    extra["landmarks"]["neck_center"]["xyz"] = list(extra["landmarks"]["head_center"]["xyz"])
    return extra


UNKNOWN = "不能不写：null（不知道）只有读第 1 版的骨模型时才有"
FRAME = "解剖坐标系（frame）"

BAD = [
    # ---- 身份
    ("没写骨标识", to("bone_id"), "骨模型的清单缺 bone_id"),
    ("骨标识不对", to("bone_id", value="骨 1"), "骨标识要用 ASCII"),
    ("没写哪一侧", to("side"), "骨模型的清单缺 side"),
    ("侧别不认识", to("side", value="R"), "side 只能是 ['left', 'right']：'R'"),
    ("没写骨的种类", to("bone_type"), "骨模型的清单缺 bone_type"),
    ("骨的种类不认识", to("bone_type", value="sawbones"), "骨的种类（bone_type）要是 ['real', 'replica', 'synthetic'] 之一：'sawbones'"),
    ("骨的种类写成不知道", to("bone_type", value=None), f"骨的种类（bone_type）{UNKNOWN}"),
    ("没写覆盖范围", to("coverage"), "骨模型的清单缺 coverage"),
    ("覆盖范围写成不知道", to("coverage", value=None), f"覆盖范围（coverage）{UNKNOWN}"),
    ("覆盖范围的种类不认识", to("coverage", "extent", value="distal"), "覆盖范围（coverage）要写成"),
    ("覆盖范围少一头", to("coverage", "distal_mm"), "覆盖范围（coverage）要写成"),
    ("覆盖范围多一项", to("coverage", "length_mm", value=499.0), "覆盖范围（coverage）要写成"),
    ("覆盖范围往远端是 0", to("coverage", "distal_mm", value=0), "覆盖范围（coverage）要写成"),
    ("覆盖范围往近端是负的", to("coverage", "proximal_mm", value=-74.0), "覆盖范围（coverage）要写成"),
    ("覆盖范围不是数", to("coverage", "proximal_mm", value="74"), "覆盖范围（coverage）要写成"),
    ("覆盖范围不是对象", to("coverage", value="whole"), "覆盖范围（coverage）要写成"),
    # ---- 来源
    ("没写来源", to("source"), "骨模型的清单缺 source"),
    ("来源写成不知道", to("source", value=None), f"来源（source）{UNKNOWN}"),
    ("来源的种类不认识", to("source", "how", value="mri"), "来源（source）要写成"),
    ("来源没写重建方法包", to("source", "method"), "来源（source）要写成"),
    ("重建方法包不是登记的编号", to("source", "method", "id", value="cad-import"), "来源（source）要写成"),
    ("重建方法包的哈希不对", to("source", "method", "hash", value="abc"), "来源（source）要写成"),
    ("重建设定少了哈希", to("source", "setting", "hash"), "来源（source）要写成"),
    ("重建设定多了一项", to("source", "setting", "name", value="x"), "来源（source）要写成"),
    ("重建设定不是登记的编号", to("source", "setting", "id", value="E0001"), "来源（source）要写成"),
    ("来源多了一项", to("source", "experiment", value="E0001"), "来源（source）要写成"),
    # ---- 单位
    ("没写单位", to("units"), "骨模型的清单缺 units"),
    ("单位不是规定的那一套", to("units", "length", value="m"), "单位只有这一套"),
    ("单位少一项", to("units", "stress"), "单位只有这一套"),
    # ---- 区域
    ("没写区域", to("regions"), "骨模型的清单缺 regions"),
    ("一个区域都没有", to("regions", value=[]), "区域（regions）要是区域的列表，至少一个"),
    ("区域不是列表", to("regions", value={"cortical": {}}), "区域（regions）要是区域的列表，至少一个"),
    ("区域里有一个不是对象", to("regions", 2, value="canal"), "区域（regions）要是区域的列表，至少一个"),
    ("区域重名", region(1, name="cortical"), "区域的名字要用小写字母、数字和下划线，不重名：['cortical', 'cortical', 'canal']"),
    ("区域的名字不合规矩", region(1, name="Spongy Bone"), "区域的名字要用小写字母、数字和下划线，不重名"),
    ("区域的名字里有点", region(1, name="cancellous.core"), "区域的名字要用小写字母、数字和下划线，不重名"),
    ("区域多了一项", region(0, colour="ivory"), "区域 'cortical'：要写且只写"),
    ("区域少了体积", to("regions", 0, "volume_mm3"), "区域 'cortical'：要写且只写"),
    ("区域的角色不认识", region(1, role="marrow"), "区域 'cancellous'：角色要是 ['cortical', 'cancellous', 'canal', 'cartilage', 'other'] 之一，这里是 'marrow'"),
    ("区域的角色不是文字", region(1, role=["cancellous"]), "区域 'cancellous'：角色要是"),
    ("几何不是对象", region(0, geometry="regions/cortical.step"), "区域 'cortical'：geometry 要写成"),
    ("几何的种类不是实体", to("regions", 0, "geometry", "kind", value="shell"), "区域 'cortical'：geometry 要写成"),
    ("几何的格式不认识", to("regions", 0, "geometry", "format", value="iges"), "区域 'cortical'：geometry 要写成"),
    ("几何的格式不是文字", to("regions", 0, "geometry", "format", value=["step"]), "区域 'cortical'：geometry 要写成"),
    ("几何少了文件", to("regions", 0, "geometry", "file"), "区域 'cortical'：geometry 要写成"),
    ("几何多了一项", to("regions", 0, "geometry", "closed", value=True), "区域 'cortical'：geometry 要写成"),
    ("几何的文件不是文字", to("regions", 0, "geometry", "file", value=7), "区域 'cortical'：geometry 要写成"),
    ("几何的格式写成不知道", to("regions", 0, "geometry", "format", value=None), f"区域 'cortical' 的几何文件是哪一种（geometry.format）{UNKNOWN}"),
    ("几何的文件清单里没有", to("regions", 0, "geometry", "file", value="regions/none.step"), "区域 'cortical'：几何文件 'regions/none.step' 不在 files 里"),
    ("几何的后缀和格式对不上", to("regions", 0, "geometry", "format", value="stl"), "区域 'cortical'：几何文件 'regions/cortical.step' 的后缀和 format（stl）对不上"),
    ("两个区域是同一个文件", to("regions", 1, "geometry", "file", value="regions/cortical.step"), "区域 'cancellous'：和区域 'cortical' 是同一个几何文件"),
    ("体积是 0", region(0, volume_mm3=0), "区域 'cortical'：volume_mm3 要是正数（mm3）"),
    ("体积不是数", region(0, volume_mm3="271529"), "区域 'cortical'：volume_mm3 要是正数（mm3）"),
    ("体积写成不知道", region(0, volume_mm3=None), f"区域 'cortical' 的体积（volume_mm3）{UNKNOWN}"),
    # ---- 材料
    ("髓腔写了材料", region(2, material=dict(samples.FOAM)), "区域 'canal'：髓腔是空的，材料要写 null"),
    ("皮质没写材料", region(0, material=None), "区域 'cortical'：皮质的区域要写材料"),
    ("材料模型不认识", region(0, material={"model": "linear_elastic", "E_MPa": 16800, "nu": 0.3}), "区域 'cortical' 的材料：骨的材料只收"),
    ("材料不是对象", region(0, material="bone"), "区域 'cortical' 的材料：骨的材料只收"),
    ("分段的材料是柄用的", region(1, material={"model": "piecewise", "along": "shaft", "segments": [{"from": 0, "to": 10, "material": samples.FOAM}]}),
     "区域 'cancellous' 的材料：骨的材料只收"),
    ("按预测的场给的材料是柄用的", region(1, material={"model": "field", "source": {"prediction": "R0042", "field": "density"},
                                               "relation": [{"from": 0, "to": 1, "a": 100, "b": 2.0}], "nu": 0.3}),
     "区域 'cancellous' 的材料：骨的材料只收"),
    ("模量不是正数", to("regions", 0, "material", "E", value=0), "区域 'cortical' 的材料（elastic）：E 要是正数（MPa）"),
    ("泊松比出了范围", to("regions", 0, "material", "nu", value=0.5), "区域 'cortical' 的材料（elastic）：nu 要在 0 到 0.5 之间（不含 0.5）"),
    ("材料少了泊松比", to("regions", 0, "material", "nu"), "区域 'cortical' 的材料（elastic）：缺 nu"),
    ("材料多了一项", to("regions", 0, "material", "E_MPa", value=16800), "区域 'cortical' 的材料（elastic）：多了 E_MPa"),
    # ---- 表面
    ("没写表面", to("surfaces"), "骨模型的清单缺 surfaces"),
    ("表面不是对象", to("surfaces", value=[]), "表面（surfaces）要是 {名字: …}"),
    ("表面的名字不合规矩", to("surfaces", "Outer Surface", value={"region": "cortical", "file": "surfaces/periosteal.stl"}), "表面（surfaces）要是 {名字: …}"),
    ("表面少了文件", to("surfaces", "periosteal", "file"), "表面 'periosteal'：要写成"),
    ("表面多了一项", to("surfaces", "periosteal", "area_mm2", value=9000.0), "表面 'periosteal'：要写成"),
    ("表面不是对象的值", to("surfaces", "periosteal", value="surfaces/periosteal.stl"), "表面 'periosteal'：要写成"),
    ("表面落在没有的区域上", to("surfaces", "periosteal", "region", value="shell"), "表面 'periosteal'：区域 'shell' 不在 regions 里"),
    ("表面的区域不是文字", to("surfaces", "periosteal", "region", value=["cortical"]), "表面 'periosteal'：区域 ['cortical'] 不在 regions 里"),
    ("表面的文件清单里没有", to("surfaces", "periosteal", "file", value="surfaces/none.stl"), "表面 'periosteal'：文件 'surfaces/none.stl' 不在 files 里"),
    # ---- 标志点
    ("没写标志点", to("landmarks"), "骨模型的清单缺 landmarks"),
    ("标志点不是对象", to("landmarks", value=[]), "标志点（landmarks）必须是一个 JSON 对象"),
    ("少一个必有的标志点", to("landmarks", "lesser_trochanter"), "标志点缺 ['lesser_trochanter']"),
    ("标志点的名字不合规矩", to("landmarks", "Head Top", value=GOOD["landmarks"]["head_center"]), "标志点的名字要用小写字母、数字和下划线：'Head Top'"),
    ("标志点少了拟合的好坏", to("landmarks", "head_center", "fit"), '标志点 head_center：要写且只写 "xyz"、"definition"、"fit"'),
    ("标志点多了一项", to("landmarks", "head_center", "radius_mm", value=25.8), '标志点 head_center：要写且只写 "xyz"、"definition"、"fit"'),
    ("标志点不是对象的值", to("landmarks", "head_center", value=[1.0, 2.0, 3.0]), '标志点 head_center：要写且只写 "xyz"、"definition"、"fit"'),
    ("标志点的坐标少一个数", to("landmarks", "neck_center", "xyz", value=[1.0, 2.0]), "标志点 neck_center：xyz 要是三个数"),
    ("标志点的坐标多一个数", to("landmarks", "neck_center", "xyz", value=[1.0, 2.0, 3.0, 4.0]), "标志点 neck_center：xyz 要是三个数"),
    ("标志点的坐标不是数", to("landmarks", "neck_center", "xyz", value=[1.0, "2", 3.0]), "标志点 neck_center：xyz 要是三个数"),
    ("标志点的坐标不是列表", to("landmarks", "neck_center", "xyz", value={"x": 1.0, "y": 2.0, "z": 3.0}), "标志点 neck_center：xyz 要是三个数"),
    ("定义是一句话", to("landmarks", "head_center", "definition", value="股骨头的拟合球心"), "标志点 head_center：definition 要写成"),
    ("定义少了版本", to("landmarks", "head_center", "definition", "version"), "标志点 head_center：definition 要写成"),
    ("定义多了一项", to("landmarks", "head_center", "definition", "author", value="wei"), "标志点 head_center：definition 要写成"),
    ("定义的找法不是名字", to("landmarks", "head_center", "definition", "method", value="sphere fit"), "标志点 head_center：definition 要写成"),
    ("定义的版本是空的", to("landmarks", "head_center", "definition", "version", value=" "), "标志点 head_center：definition 要写成"),
    ("定义的版本不是文字", to("landmarks", "head_center", "definition", "version", value=1), "标志点 head_center：definition 要写成"),
    ("定义的参数不是对象", to("landmarks", "head_center", "definition", "params", value=[1.5]), "标志点 head_center：definition 要写成"),
    ("定义带的那句话是空的", to("landmarks", "head_center", "definition", "text", value=""), "标志点 head_center：definition 要写成"),
    ("定义的找法写成不知道", to("landmarks", "head_center", "definition", "method", value=None), f"标志点 head_center 的找法（definition.method）{UNKNOWN}"),
    ("定义的版本写成不知道", to("landmarks", "head_center", "definition", "version", value=None), f"标志点 head_center 的找法的版本（definition.version）{UNKNOWN}"),
    ("拟合的好坏写成不知道", to("landmarks", "head_center", "fit", value=None), f"标志点 head_center 的拟合的好坏（fit）{UNKNOWN}"),
    ("拟合的好坏不是对象", to("landmarks", "head_center", "fit", value=0.21), "标志点 head_center：fit 要写成"),
    ("拟合的好坏里不是数", to("landmarks", "head_center", "fit", "rms_mm", value="0.21"), "标志点 head_center：fit 要写成"),
    ("拟合的好坏里的名字不合规矩", to("landmarks", "head_center", "fit", "RMS (mm)", value=0.21), "标志点 head_center：fit 要写成"),
    # ---- 解剖坐标系
    ("没写坐标系", to("frame"), "骨模型的清单缺 frame"),
    ("坐标系不是对象", to("frame", value="x 内侧、y 后方、z 近端"), f"{FRAME}：method 要是 ['shaft_condyles', 'shaft_neck'] 之一"),
    ("坐标系没写定法", to("frame", "method"), f"{FRAME}：method 要是 ['shaft_condyles', 'shaft_neck'] 之一"),
    ("坐标系的定法不认识", to("frame", "method", value="isb"), f"{FRAME}：method 要是 ['shaft_condyles', 'shaft_neck'] 之一"),
    ("坐标系少一根轴", to("frame", "y"), f"{FRAME}：照 shaft_condyles 定的要写且只写"),
    ("坐标系多了一项", to("frame", "note", value="x"), f"{FRAME}：照 shaft_condyles 定的要写且只写"),
    ("照后髁连线定的写了前倾角", to("frame", "anteversion_deg", value=12.0), f"{FRAME}：照 shaft_condyles 定的要写且只写"),
    ("照颈轴定的没写前倾角", proximal("frame", "anteversion_deg"), f"{FRAME}：照 shaft_neck 定的要写且只写"),
    ("没写文件坐标是怎么来的", to("frame", "file", value=" "), f"{FRAME}：file 要写几何文件自己的坐标是怎么来的"),
    ("文件坐标的说明不是文字", to("frame", "file", value=["CAD"]), f"{FRAME}：file 要写几何文件自己的坐标是怎么来的"),
    ("原点少一个数", to("frame", "origin", value=[0.0, 0.0]), f"{FRAME}：origin、x、y、z 各要是三个数"),
    ("原点多一个数", to("frame", "origin", value=[12.0, -7.0, 30.0, 0.0]), f"{FRAME}：origin、x、y、z 各要是三个数"),
    ("轴不是数", to("frame", "z", value=["0", "0", "1"]), f"{FRAME}：origin、x、y、z 各要是三个数"),
    ("前倾角写成不知道", proximal("frame", "anteversion_deg", value=None), f"{FRAME}的前倾角（anteversion_deg）{UNKNOWN}"),
    ("前倾角到了 90 度", proximal("frame", "anteversion_deg", value=90.0), f"{FRAME}：anteversion_deg 要是 −90 到 90 之间的数（度）"),
    ("前倾角到了负 90 度", proximal("frame", "anteversion_deg", value=-90.0), f"{FRAME}：anteversion_deg 要是 −90 到 90 之间的数（度）"),
    ("前倾角不是数", proximal("frame", "anteversion_deg", value="12"), f"{FRAME}：anteversion_deg 要是 −90 到 90 之间的数（度）"),
    ("完整的股骨照颈轴定", neck_instead_of_condyles, f"{FRAME}：完整的股骨（whole）要照 shaft_condyles 定，这里写的是 shaft_neck"),
    ("近端一段照后髁连线定", condyles_on_a_proximal_piece, f"{FRAME}：只有近端一段的（proximal）要照 shaft_neck 定，这里写的是 shaft_condyles"),
    ("照后髁连线定却没有后髁", to("landmarks", "condyle_lateral"), f"{FRAME}：照 shaft_condyles 定要有标志点 ['condyle_lateral']"),
    ("内外两个后髁写反了", condyles_swapped, f"{FRAME}：照后髁连线定出的内侧和颈轴指的不同向"),
    ("两个干轴点重合", shaft_points_together, f"{FRAME}：骨干上的两个点重合，定不出干轴"),
    ("颈中心和头心重合", neck_and_head_together, f"{FRAME}：颈中心和头心重合，定不出颈轴"),
    ("原点和算出来的对不上", to("frame", "origin", value=[12.0, -7.0, 30.5]), f"{FRAME}：记的 ['origin'] 和照标志点算出来的对不上"),
    ("一根轴和算出来的对不上", to("frame", "x", value=GOOD["frame"]["y"]), f"{FRAME}：记的 ['x'] 和照标志点算出来的对不上"),
    ("小转子挪了坐标系没重算", landmark_moved_frame_kept, f"{FRAME}：记的 ['origin'] 和照标志点算出来的对不上"),
    ("后髁挪了坐标系没重算", condyle_moved_frame_kept, f"{FRAME}：记的 ['x', 'y'] 和照标志点算出来的对不上"),
    ("换了一侧坐标系没重算", other_side_frame_kept, f"{FRAME}：记的 ['y'] 和照标志点算出来的对不上"),
    ("前倾角改了坐标系没重算", anteversion_changed_frame_kept, f"{FRAME}：记的 ['x', 'y'] 和照标志点算出来的对不上"),
    # ---- 重建记录、检查结果（照旧）
    ("没写重建记录", to("history"), "骨模型的清单缺 history"),
    ("没有重建记录", to("history", value=[]), "重建记录（history）至少要有一步，每一步写 step 和 what"),
    ("重建记录的一步没写做了什么", to("history", value=[{"step": "import"}]), "重建记录（history）至少要有一步，每一步写 step 和 what"),
    ("重建记录不是列表", to("history", value={"step": "import", "what": "x"}), "重建记录（history）至少要有一步，每一步写 step 和 what"),
    ("没写检查结果", to("checks"), "骨模型的清单缺 checks"),
    ("检查结果不是列表", to("checks", value={"volume": True}), "检查结果（checks）必须是一个列表"),
    ("检查少了 passed", to("checks", value=[{"name": "volume", "value": 1, "limit": "x"}]), "每一项检查结果要带且只带"),
    ("检查的名字不合规矩", to("checks", 0, "name", value="Volume OK"), "每一项检查结果要带且只带"),
    ("检查的名字重复", to("checks", value=[GOOD["checks"][0], GOOD["checks"][0]]), "检查结果的名字有重复的"),
    ("有一项检查没过", to("checks", 0, "passed", value=False), "检查 volume_cortical 没过或者还没做"),
]


@pytest.mark.parametrize("why,make,said", BAD, ids=[row[0] for row in BAD])
def test_bad_bone_models_are_named(tmp_path, why, make, said):
    """每个坏样本只违一条：核出来正好一句，说的就是那一处。"""
    problems = problems_of(tmp_path, make())
    assert len(problems) == 1 and said in problems[0], f"{why}：{problems}"


def test_every_missing_item_is_named_at_once(tmp_path):
    extra = {key: value for key, value in GOOD.items() if key not in ("coverage", "frame", "surfaces")}
    assert problems_of(tmp_path, extra) == ["骨模型的清单缺 coverage", "骨模型的清单缺 frame", "骨模型的清单缺 surfaces"]


def test_several_things_wrong_are_all_named(tmp_path):
    extra = copy.deepcopy(GOOD)
    extra["bone_type"], extra["regions"][0]["volume_mm3"], extra["landmarks"]["head_center"]["fit"] = "plastic", -1.0, []
    problems = problems_of(tmp_path, extra)
    assert [text.split("：")[0] for text in problems] == ["骨的种类（bone_type）要是 ['real', 'replica', 'synthetic'] 之一",
                                                         "区域 'cortical'", "标志点 head_center"], problems


def test_the_frame_is_not_checked_until_the_landmarks_and_side_are_right(tmp_path):
    """哪一侧、标志点的位置没写对，坐标系就没法算：只说根上那一处。别的地方写错了不挡着核坐标系。"""
    wrong = [0.0, 0.0, 0.0]
    extra = samples.changed(GOOD, "landmarks", "head_center", "xyz", value=[1.0, 2.0])
    extra["frame"]["origin"] = wrong
    assert problems_of(tmp_path, extra) == ["标志点 head_center：xyz 要是三个数"]
    extra = samples.changed({**GOOD, "side": "R"}, "frame", "origin", value=wrong)
    assert check_format("bone_model", samples.write(tmp_path / "side", extra)) == ["side 只能是 ['left', 'right']：'R'"]
    extra = samples.changed(samples.changed(GOOD, "landmarks", "lesser_trochanter"), "frame", "origin", value=wrong)
    assert check_format("bone_model", samples.write(tmp_path / "fewer", extra)) == ["标志点缺 ['lesser_trochanter']"]
    extra = samples.changed(samples.changed(GOOD, "landmarks", "head_center", "fit", value="good"), "frame", "origin", value=wrong)
    found = check_format("bone_model", samples.write(tmp_path / "fit", extra))
    assert len(found) == 2 and "fit 要写成" in found[0] and "记的 ['origin'] 和照标志点算出来的对不上" in found[1]


def test_small_positive_numbers_are_still_positive(tmp_path):
    """覆盖范围、体积只要是正数：不到 1 的也是。"""
    extra = samples.changed(GOOD, "coverage", value={"extent": "whole", "proximal_mm": 0.5, "distal_mm": 0.25})
    extra["regions"][2]["volume_mm3"] = 0.5
    assert problems_of(tmp_path, extra) == []


@pytest.mark.parametrize("degrees", [89.5, -89.5, 0.0, 0.4])
def test_an_anteversion_anywhere_inside_ninety_degrees_can_be_written(degrees):
    listed = samples.manifest(samples.good(whole=False, anteversion=degrees))
    assert listed["frame"]["anteversion_deg"] == degrees and bone_model.check_model("bone_model", listed) == []


def test_exactly_the_tolerance_still_agrees():
    """容差的边上：差正好一百万分之一算对得上，再多就不算。文件坐标就是解剖坐标的那根骨上，x 轴算出来正好是 (1, 0, 0)。"""
    listed = samples.manifest(samples.good(pose=samples.STRAIGHT))
    assert listed["frame"]["x"] == [1.0, 0.0, 0.0] and bone_model.check_model("bone_model", listed) == []
    assert bone_model.check_model("bone_model", samples.changed(listed, "frame", "x", value=[1.0, 1e-6, 0.0])) == []
    found = bone_model.check_model("bone_model", samples.changed(listed, "frame", "x", value=[1.0, 2e-6, 0.0]))
    assert len(found) == 1 and "记的 ['x'] 和照标志点算出来的对不上" in found[0]


def test_the_recorded_frame_may_differ_from_the_computed_one_only_by_rounding():
    """记的和算出来的差在一百万分之一以内算对得上：只容得下写文件时的舍入，容不下一个挪过的标志点。"""
    listed = samples.manifest(GOOD)
    for key in ("origin", "x", "y", "z"):
        for number in range(3):
            near, far = copy.deepcopy(listed), copy.deepcopy(listed)
            near["frame"][key][number] += 1e-8
            far["frame"][key][number] -= 1e-5
            assert bone_model.check_model("bone_model", near) == [], (key, number)
            found = bone_model.check_model("bone_model", far)
            assert len(found) == 1 and f"记的 ['{key}'] 和照标志点算出来的对不上" in found[0], (key, number, found)


@pytest.mark.parametrize("odd", [float("inf"), float("nan"), True, None, "1.0"])
def test_a_coordinate_must_be_a_finite_number(odd):
    """别的程序写的 JSON 里可以有 Infinity、NaN：读得进来，核的时候拦下。"""
    listed = samples.manifest(samples.changed(GOOD, "landmarks", "neck_center", "xyz", value=[1.0, odd, 3.0]))
    assert bone_model.check_model("bone_model", listed) == ["标志点 neck_center：xyz 要是三个数"]
    listed = samples.manifest(samples.changed(GOOD, "frame", "x", value=[1.0, odd, 3.0]))
    assert bone_model.check_model("bone_model", listed) == ["解剖坐标系（frame）：origin、x、y、z 各要是三个数"]


# ---------------------------------------------------------------- “不知道”只有读第 1 版时才有

def test_unknowns_are_only_for_what_was_read_from_the_first_version(tmp_path):
    """盘上就是第 2 版的，一样都不许写不知道；直接叫 check_model 时由调用的一方说是不是读第 1 版来的。"""
    extra = samples.good(whole=False)
    extra.update(bone_type=None, coverage=None, source=None)
    extra["frame"]["anteversion_deg"] = None
    extra["frame"].update(bone_model.frame(extra["landmarks"], "right", "shaft_neck"))
    extra["regions"][0].update(volume_mm3=None)
    extra["regions"][0]["geometry"]["format"] = None
    extra["landmarks"]["head_center"].update(fit=None, definition={"method": None, "version": None, "params": {}, "text": "股骨头的拟合球心"})
    listed = samples.manifest(extra)
    assert bone_model.check_model("bone_model", listed, unknown_ok=True) == []
    found = bone_model.check_model("bone_model", listed)
    assert len(found) == 9 and all(UNKNOWN in text for text in found), found
    assert check_format("bone_model", samples.write(tmp_path / "b", extra)) == found, "盘上是第 2 版：照严的核"


def test_check_reads_which_version_is_on_disk(tmp_path):
    """check_format 交来的清单已经读成第 2 版了；是不是从第 1 版读来的，看盘上那一份写的版本。"""
    extra = {**GOOD, "bone_type": None}
    root = samples.write(tmp_path / "second", extra)
    assert bone_model.check("bone_model", read_manifest(root), root) == [f"骨的种类（bone_type）{UNKNOWN}"]
    first = samples.write_v1(tmp_path / "first")
    assert bone_model.check("bone_model", samples.manifest(extra), first) == [], "盘上是第 1 版：不知道的那几样许"
    assert bone_model.check("bone_model", samples.manifest(extra), tmp_path / "nowhere") == [f"骨的种类（bone_type）{UNKNOWN}"], \
        "读不出盘上的版本：照严的核"


# ---------------------------------------------------------------- 能被名字引用的名字

def test_names_a_setting_may_refer_to():
    """名字引用（设定的声明，第 8 条）能指向骨模型里的哪些名字：区域、表面、标志点。这一版没有块和关节。"""
    names = bone_model.names(samples.manifest(GOOD))
    assert names == {"bone.block": set(), "bone.joint": set(), "bone.region": {"cortical", "cancellous", "canal"},
                     "bone.surface": {"periosteal"}, "bone.landmark": set(GOOD["landmarks"])}
    assert {"condyle_medial", "condyle_lateral"} <= names["bone.landmark"]


def test_names_do_not_break_on_a_manifest_that_is_not_whole():
    """清单不全也不报错：名字少了，引用它的设定会被拒。"""
    empty = {"bone.block": set(), "bone.joint": set(), "bone.region": set(), "bone.surface": set(), "bone.landmark": set()}
    assert bone_model.names({}) == empty
    assert bone_model.names({"format": 2, "regions": "cortical", "surfaces": ["periosteal"], "landmarks": None}) == empty
    odd = {"format": 2, "regions": [{"name": "cortical"}, "canal", {"role": "other"}, {"name": 7}], "surfaces": {}, "landmarks": {}}
    assert bone_model.names(odd)["bone.region"] == {"cortical"}


# ---------------------------------------------------------------- 读成现在这一版

def test_read_gives_the_manifest_in_the_current_version(tmp_path):
    root = samples.write(tmp_path / "b", GOOD)
    assert bone_model.read(root) == read_manifest(root)
    with pytest.raises(ValueError, match="没有 manifest.json"):
        bone_model.read(tmp_path / "nowhere")
    with pytest.raises(NewerFormat):
        bone_model.read(samples.write(tmp_path / "newer", GOOD, version=3))
