"""骨模型和候选骨模型：好样本过，坏样本被点名哪里不符。"""
from __future__ import annotations

import copy

import pytest

from stemlab.contract.formats import bone_model
from stemlab.contract.formats.manifest import check_format, make_manifest, read_manifest, write_manifest

FILES = {"solids/cortical.step": b"ISO-10303-21; cortical", "solids/cancellous.step": b"ISO-10303-21; cancellous",
         "notes/readme.txt": b"where this bone came from"}
EXTRA = {
    "bone_id": "femur042",
    "side": "right",
    "units": {"length": "mm", "force": "N", "stress": "MPa"},
    "frame": {"origin": "干轴上小转子的高度", "x": "指向内侧", "y": "指向后方", "z": "沿干轴指向近端"},
    "solids": {"cortical": {"file": "solids/cortical.step"}, "cancellous": {"file": "solids/cancellous.step"}},
    "landmarks": {
        "head_center": {"xyz": [52.4, 1.8, 48.0], "definition": "股骨头的拟合球心"},
        "neck_center": {"xyz": [30.9, 0.4, 39.1], "definition": "股骨颈最细截面的质心"},
        "shaft_proximal": {"xyz": [0.0, 0.0, -20.0], "definition": "近端骨干截面的质心"},
        "shaft_distal": {"xyz": [0.0, 0.0, -140.0], "definition": "远端骨干截面的质心"},
        "lesser_trochanter": {"xyz": [18.0, 14.0, 0.0], "definition": "小转子最凸出的一点"},
        "greater_trochanter": {"xyz": [-22.0, 3.0, 40.0], "definition": "大转子的最高点"},
    },
    "materials": {"cortical": {"model": "linear_elastic", "E_MPa": 16800, "nu": 0.3},
                  "cancellous": {"model": "linear_elastic", "E_MPa": 155.0, "nu": 0.3}},
    "history": [{"step": "import", "what": "从 CAD 读进两个实体"}, {"step": "edit", "what": "填了松质芯里的导针孔"}],
    "checks": [{"name": "volume_cortical", "value": 271.5, "limit": "和骨源相差不到 0.5%", "passed": True},
               {"name": "kernel_smoke", "value": "ok", "limit": "内核能在这根骨上建模", "passed": True}],
}


def make(root, kind="bone_model", files=None, **change):
    """写一个骨模型的文件夹。change 里的项盖掉清单里的同名项；值是 ... 就把那一项去掉。"""
    files = FILES if files is None else files
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(content)
    extra = {**copy.deepcopy(EXTRA), **change}
    write_manifest(root, make_manifest(kind, list(files), **{key: value for key, value in extra.items() if value is not ...}))
    return root


def changed(key, *path, value=...):
    """把 EXTRA[key] 里沿 path 的那一项换成 value；value 是 ... 就把它去掉。"""
    whole = copy.deepcopy(EXTRA[key])
    inner = whole
    for name in path[:-1]:
        inner = inner[name]
    if value is ...:
        del inner[path[-1]]
    else:
        inner[path[-1]] = value
    return {key: whole}


@pytest.mark.parametrize("kind", ["bone_model", "bone_draft"])
def test_good_bone_models_pass(tmp_path, kind):
    assert check_format(kind, make(tmp_path / "b", kind=kind)) == []


def test_names_a_setting_may_refer_to():
    """名字引用（设定的声明，第 8 条）能指向骨模型里的哪些名字。第 1 版：区域就是两个实体，加上标志点。"""
    names = bone_model.names(EXTRA)
    assert names == {"bone.block": set(), "bone.joint": set(), "bone.surface": set(),
                     "bone.region": {"cortical", "cancellous"}, "bone.landmark": set(EXTRA["landmarks"])}
    assert bone_model.names({})["bone.region"] == set(), "清单不全也不报错：名字少了，引用它的设定会被拒"


def test_which_landmarks_every_bone_model_has():
    assert bone_model.LANDMARKS == ("head_center", "neck_center", "shaft_proximal", "shaft_distal", "lesser_trochanter")
    assert bone_model.SOLIDS == ("cortical", "cancellous")
    assert bone_model.UNITS == {"length": "mm", "force": "N", "stress": "MPa"}


def test_a_draft_may_have_checks_still_open_but_a_model_may_not(tmp_path):
    open_checks = [{"name": "landmarks", "value": None, "limit": "要人看过", "passed": None}]
    assert check_format("bone_draft", make(tmp_path / "draft", kind="bone_draft", checks=open_checks)) == []
    assert check_format("bone_draft", make(tmp_path / "none", kind="bone_draft", checks=[])) == []
    problems = check_format("bone_model", make(tmp_path / "model", checks=open_checks))
    assert any("landmarks" in text and "没过" in text for text in problems)
    assert any("检查" in text for text in check_format("bone_model", make(tmp_path / "empty", checks=[])))


def test_axes_come_from_the_landmarks():
    neck, shaft = bone_model.axes(EXTRA["landmarks"])
    assert neck == pytest.approx((0.922, 0.060, 0.382), abs=1e-3), "颈轴：从颈中心指向头心"
    assert shaft == pytest.approx((0.0, 0.0, 1.0)), "干轴：从远端指向近端"
    assert bone_model.neck_shaft_angle(EXTRA["landmarks"]) == pytest.approx(112.4, abs=0.1)


BAD = [
    ("没写骨标识", dict(bone_id=...), "bone_id"),
    ("骨标识不对", dict(bone_id="骨 1"), "骨标识"),
    ("没写哪一侧", dict(side=...), "side"),
    ("侧别不认识", dict(side="R"), "side"),
    ("单位不是规定的那一套", changed("units", "length", value="m"), "单位"),
    ("单位少一项", changed("units", "stress"), "单位"),
    ("坐标系少一根轴", changed("frame", "y"), "坐标系"),
    ("坐标系的定义是空的", changed("frame", "origin", value=" "), "坐标系"),
    ("少一个实体", changed("solids", "cancellous"), "cancellous"),
    ("多一个实体", changed("solids", "marrow", value={"file": "solids/cortical.step"}), "marrow"),
    ("实体的文件清单里没有", changed("solids", "cortical", "file", value="solids/none.step"), "solids/none.step"),
    ("两个实体是同一个文件", changed("solids", "cancellous", "file", value="solids/cortical.step"), "同一个文件"),
    ("少一个标志点", changed("landmarks", "lesser_trochanter"), "lesser_trochanter"),
    ("标志点没有定义", changed("landmarks", "head_center", "definition", value=""), "head_center"),
    ("标志点的坐标少一个数", changed("landmarks", "neck_center", "xyz", value=[1.0, 2.0]), "neck_center"),
    ("标志点的坐标不是数", changed("landmarks", "neck_center", "xyz", value=[1.0, "2", 3.0]), "neck_center"),
    ("标志点的名字不合规矩", changed("landmarks", "Head Top", value={"xyz": [0, 0, 0], "definition": "x"}), "Head Top"),
    ("两个干轴点重合", changed("landmarks", "shaft_distal", "xyz", value=[0.0, 0.0, -20.0]), "干轴"),
    ("颈中心和头心重合", changed("landmarks", "neck_center", "xyz", value=[52.4, 1.8, 48.0]), "颈轴"),
    ("少一种材料", changed("materials", "cancellous"), "cancellous"),
    ("模量不是正数", changed("materials", "cortical", "E_MPa", value=0), "E_MPa"),
    ("泊松比出了范围", changed("materials", "cortical", "nu", value=0.5), "nu"),
    ("材料没写模型", changed("materials", "cortical", "model"), "model"),
    ("没有重建记录", dict(history=[]), "重建记录"),
    ("重建记录的一步没写做了什么", dict(history=[{"step": "import"}]), "重建记录"),
    ("检查结果不是列表", dict(checks={"volume": True}), "检查"),
    ("检查少了 passed", dict(checks=[{"name": "volume", "value": 1, "limit": "x"}]), "检查"),
    ("检查的名字重复", dict(checks=[EXTRA["checks"][0], EXTRA["checks"][0]]), "重复"),
    ("有一项检查没过", dict(checks=[dict(EXTRA["checks"][0], passed=False), EXTRA["checks"][1]]), "volume_cortical"),
]
BAD += [(f"清单缺 {key}", {key: ...}, key) for key in ("units", "frame", "solids", "landmarks", "materials", "history", "checks")]


@pytest.mark.parametrize("why,change,word", BAD, ids=[row[0] for row in BAD])
def test_bad_bone_models_are_named(tmp_path, why, change, word):
    problems = check_format("bone_model", make(tmp_path / "b", **change))
    assert problems and any(word in text for text in problems), f"{why}：{problems}"


def test_a_failed_check_is_fine_in_a_draft(tmp_path):
    failed = [dict(EXTRA["checks"][0], passed=False)]
    assert check_format("bone_draft", make(tmp_path / "b", kind="bone_draft", checks=failed)) == []


def test_the_bone_id_in_the_manifest_is_what_the_register_must_agree_with(tmp_path):
    root = make(tmp_path / "b")
    assert read_manifest(root)["bone_id"] == "femur042"
