"""第 1 版的骨模型照样读：读出来是第 2 版的样子（一块骨、两个区域、均匀材料），过第 2 版的核对。

原来的好样本、坏样本一条不少：样本的内容没变，只是清单明写第 1 版（make_manifest 盖的是现在的版本号）。
第 1 版原来的规矩照旧，不合的照原来的话说出来。
"""
from __future__ import annotations

import copy

import pytest

from stemlab.contract.formats import bone_model
from stemlab.contract.formats.manifest import check_format, read_manifest
from stemlab.contract.versions import CannotUpcast, upcast
from tests.contract import bone_samples as samples
from tests.contract.bone_samples import V1, changed_v1, write_v1
from tests.contract.bone_samples import listed_v1 as listed


# ---------------------------------------------------------------- 原来的好样本、坏样本

@pytest.mark.parametrize("kind", ["bone_model", "bone_draft"])
def test_good_first_version_bone_models_still_pass(tmp_path, kind):
    root = write_v1(tmp_path / "b", kind=kind)
    assert read_manifest(root)["format"] == 1, "盘上的清单不改"
    assert check_format(kind, root) == []


def test_a_first_version_draft_may_have_checks_still_open_but_a_model_may_not(tmp_path):
    open_checks = [{"name": "landmarks", "value": None, "limit": "要人看过", "passed": None}]
    assert check_format("bone_draft", write_v1(tmp_path / "draft", kind="bone_draft", checks=open_checks)) == []
    assert check_format("bone_draft", write_v1(tmp_path / "none", kind="bone_draft", checks=[])) == []
    problems = check_format("bone_model", write_v1(tmp_path / "model", checks=open_checks))
    assert any("landmarks" in text and "没过" in text for text in problems)
    assert any("检查" in text for text in check_format("bone_model", write_v1(tmp_path / "empty", checks=[])))


def test_a_failed_check_is_fine_in_a_first_version_draft(tmp_path):
    failed = [dict(V1["checks"][0], passed=False)]
    assert check_format("bone_draft", write_v1(tmp_path / "b", kind="bone_draft", checks=failed)) == []


BAD = [
    ("没写骨标识", dict(bone_id=...), "bone_id"),
    ("骨标识不对", dict(bone_id="骨 1"), "骨标识"),
    ("没写哪一侧", dict(side=...), "side"),
    ("侧别不认识", dict(side="R"), "side"),
    ("单位不是规定的那一套", changed_v1("units", "length", value="m"), "单位"),
    ("单位少一项", changed_v1("units", "stress"), "单位"),
    ("坐标系少一根轴", changed_v1("frame", "y"), "坐标系"),
    ("坐标系的定义是空的", changed_v1("frame", "origin", value=" "), "坐标系"),
    ("少一个实体", changed_v1("solids", "cancellous"), "cancellous"),
    ("多一个实体", changed_v1("solids", "marrow", value={"file": "solids/cortical.step"}), "marrow"),
    ("实体的文件清单里没有", changed_v1("solids", "cortical", "file", value="solids/none.step"), "solids/none.step"),
    ("两个实体是同一个文件", changed_v1("solids", "cancellous", "file", value="solids/cortical.step"), "同一个文件"),
    ("少一个标志点", changed_v1("landmarks", "lesser_trochanter"), "lesser_trochanter"),
    ("标志点没有定义", changed_v1("landmarks", "head_center", "definition", value=""), "head_center"),
    ("标志点的坐标少一个数", changed_v1("landmarks", "neck_center", "xyz", value=[1.0, 2.0]), "neck_center"),
    ("标志点的坐标不是数", changed_v1("landmarks", "neck_center", "xyz", value=[1.0, "2", 3.0]), "neck_center"),
    ("标志点的名字不合规矩", changed_v1("landmarks", "Head Top", value={"xyz": [0, 0, 0], "definition": "x"}), "Head Top"),
    ("两个干轴点重合", changed_v1("landmarks", "shaft_distal", "xyz", value=[0.0, 0.0, -20.0]), "干轴"),
    ("颈中心和头心重合", changed_v1("landmarks", "neck_center", "xyz", value=[52.4, 1.8, 48.0]), "颈轴"),
    ("少一种材料", changed_v1("materials", "cancellous"), "cancellous"),
    ("模量不是正数", changed_v1("materials", "cortical", "E_MPa", value=0), "E_MPa"),
    ("泊松比出了范围", changed_v1("materials", "cortical", "nu", value=0.5), "nu"),
    ("材料没写模型", changed_v1("materials", "cortical", "model"), "model"),
    ("没有重建记录", dict(history=[]), "重建记录"),
    ("重建记录的一步没写做了什么", dict(history=[{"step": "import"}]), "重建记录"),
    ("检查结果不是列表", dict(checks={"volume": True}), "检查"),
    ("检查少了 passed", dict(checks=[{"name": "volume", "value": 1, "limit": "x"}]), "检查"),
    ("检查的名字重复", dict(checks=[V1["checks"][0], V1["checks"][0]]), "重复"),
    ("有一项检查没过", dict(checks=[dict(V1["checks"][0], passed=False), V1["checks"][1]]), "volume_cortical"),
]
BAD += [(f"清单缺 {key}", {key: ...}, key) for key in ("units", "frame", "solids", "landmarks", "materials", "history", "checks")]


@pytest.mark.parametrize("why,change,word", BAD, ids=[row[0] for row in BAD])
def test_bad_first_version_bone_models_are_still_named(tmp_path, why, change, word):
    problems = check_format("bone_model", write_v1(tmp_path / "b", **change))
    assert problems and any(word in text for text in problems), f"{why}：{problems}"


V1_RULES = [
    # 第 1 版自己的规矩，照原来的话说：读不成第 2 版，说出是哪里
    (dict(side="R"), "side 只能是 ['left', 'right']：'R'"),
    (changed_v1("units", "length", value="m"), "单位只有这一套"),
    (changed_v1("frame", "y"), "坐标系要写 ['origin', 'x', 'y', 'z'] 四项的定义，每项都不能空"),
    (dict(frame="x 内侧"), "坐标系要写 ['origin', 'x', 'y', 'z'] 四项的定义，每项都不能空"),
    (changed_v1("solids", "marrow", value={"file": "solids/cortical.step"}), "实体要有且只有 ['cortical', 'cancellous'] 两个"),
    (dict(solids=["cortical", "cancellous"]), "实体要有且只有 ['cortical', 'cancellous'] 两个"),
    (changed_v1("solids", "cortical", value="solids/cortical.step"), "实体 cortical 的文件清单里没有：None"),
    (changed_v1("solids", "cortical", "file", value="solids/none.step"), "实体 cortical 的文件清单里没有：'solids/none.step'"),
    (changed_v1("solids", "cancellous", "file", value="solids/cortical.step"), "两个实体不能是同一个文件"),
    (dict(landmarks=[]), "标志点（landmarks）必须是一个 JSON 对象"),
    (changed_v1("landmarks", "lesser_trochanter"), "标志点缺 ['lesser_trochanter']"),
    (changed_v1("landmarks", "Head Top", value={"xyz": [0, 0, 0], "definition": "x"}), "标志点的名字要用小写字母、数字和下划线：'Head Top'"),
    (changed_v1("landmarks", "head_center", "definition", value=""), "标志点 head_center 要写 xyz（三个数）和 definition（它是怎么定的）"),
    (changed_v1("landmarks", "head_center", "radius", value=25.0), "标志点 head_center 要写 xyz（三个数）和 definition（它是怎么定的）"),
    (changed_v1("landmarks", "neck_center", "xyz", value=[1.0, 2.0]), "标志点 neck_center 要写 xyz（三个数）和 definition（它是怎么定的）"),
    (changed_v1("landmarks", "neck_center", "xyz", value=[1.0, True, 3.0]), "标志点 neck_center 要写 xyz（三个数）和 definition（它是怎么定的）"),
    (changed_v1("landmarks", "shaft_distal", "xyz", value=[0.0, 0.0, -20.0]), "骨干上的两个点重合，定不出干轴"),
    (changed_v1("landmarks", "neck_center", "xyz", value=[52.4, 1.8, 48.0]), "颈中心和头心重合，定不出颈轴"),
    (changed_v1("materials", "cancellous"), "材料要有且只有 ['cortical', 'cancellous'] 两种"),
    (changed_v1("materials", "cortical", value="bone"), "cortical 的材料必须是一个 JSON 对象"),
    (changed_v1("materials", "cortical", "model"), "cortical 的材料没写 model（是哪种材料模型）"),
    (changed_v1("materials", "cortical", "E_MPa", value=0), "cortical 的 E_MPa 必须是正数：0"),
    (changed_v1("materials", "cortical", "E_MPa", value="16800"), "cortical 的 E_MPa 必须是正数：'16800'"),
    (changed_v1("materials", "cancellous", "nu", value=0.5), "cancellous 的 nu 要在 0 和 0.5 之间：0.5"),
    (changed_v1("materials", "cancellous", "nu", value=-0.1), "cancellous 的 nu 要在 0 和 0.5 之间：-0.1"),
    (changed_v1("materials", "cancellous", "nu"), "cancellous 的 nu 要在 0 和 0.5 之间：None"),
]


@pytest.mark.parametrize("change,said", V1_RULES, ids=[row[1][:24] for row in V1_RULES])
def test_each_first_version_rule_is_told_in_its_old_words(change, said):
    """每个坏样本只违第 1 版的一条：读成第 2 版时被拒，正好说出那一句。"""
    with pytest.raises(CannotUpcast) as error:
        upcast("bone_model", listed(**change))
    assert str(error.value) == f"第 1 版的骨模型不合格式：{said}" or str(error.value).startswith(f"第 1 版的骨模型不合格式：{said}"), error.value
    assert "；" not in str(error.value), "只有这一句"


def test_everything_a_first_version_manifest_lacks_is_named_at_once():
    with pytest.raises(CannotUpcast, match="骨模型的清单缺 frame；骨模型的清单缺 materials"):
        upcast("bone_model", listed(frame=..., materials=...))
    with pytest.raises(CannotUpcast, match="side 只能是.*；单位只有这一套"):
        upcast("bone_model", listed(side="both", units={}))


def test_boundaries_of_the_first_version_rules_stay_where_they_were():
    assert upcast("bone_model", listed(**changed_v1("materials", "cortical", "nu", value=0)))["regions"][0]["material"]["nu"] == 0
    assert upcast("bone_model", listed(**changed_v1("materials", "cortical", "nu", value=0.499)))
    assert upcast("bone_model", listed(**changed_v1("materials", "cortical", "E_MPa", value=0.001)))
    close = changed_v1("landmarks", "shaft_distal", "xyz", value=[0.0, 0.0, -20.000001])
    assert upcast("bone_model", listed(**close)), "两个点差一纳米以上就定得出干轴"


# ---------------------------------------------------------------- 读出来是什么

def test_a_first_version_manifest_reads_as_one_bone_two_regions_uniform_materials():
    old = listed(measures={"head_radius_mm": 25.8})
    new = upcast("bone_model", old)
    assert old == listed(measures={"head_radius_mm": 25.8}), "原来那一份没被改"
    assert new["format"] == 2 and (new["kind"], new["files"], new["bone_id"], new["side"]) == (
        "bone_model", old["files"], "femur042", "right")
    assert new["regions"] == [
        {"name": "cortical", "role": "cortical", "geometry": {"kind": "solid", "format": "step", "file": "solids/cortical.step"},
         "volume_mm3": None, "material": {"model": "elastic", "E": 16800, "nu": 0.3}},
        {"name": "cancellous", "role": "cancellous", "geometry": {"kind": "solid", "format": "step", "file": "solids/cancellous.step"},
         "volume_mm3": None, "material": {"model": "elastic", "E": 155.0, "nu": 0.3}}]
    assert (new["bone_type"], new["coverage"], new["source"], new["surfaces"]) == (None, None, None, {})
    assert (new["units"], new["history"], new["checks"]) == (V1["units"], V1["history"], V1["checks"])
    assert new["measures"] == {"head_radius_mm": 25.8}, "别的项照旧带着"
    assert "solids" not in new and "materials" not in new
    assert set(new["landmarks"]) == set(V1["landmarks"])
    assert new["landmarks"]["greater_trochanter"] == {
        "xyz": [-22.0, 3.0, 40.0], "definition": {"method": None, "version": None, "params": {}, "text": "大转子的最高点"}, "fit": None}
    assert bone_model.check_model("bone_model", new, unknown_ok=True) == []
    strict = bone_model.check_model("bone_model", new)
    assert len(strict) == 3 + 2 + 3 * 6 + 1 and all("不能不写：null（不知道）" in text for text in strict), \
        "盘上要是第 2 版，这些不知道的一样都不许：骨的种类、覆盖范围、来源，两个体积，六个标志点各三样，前倾角"


def test_the_frame_of_a_first_version_model_is_set_by_its_neck_axis_and_not_turned_back():
    """第 1 版没有后髁的标志点，也没记前倾角：只能照颈轴定，没法转回去。x 就是颈轴投到垂直干轴的面上的方向。"""
    frame = upcast("bone_model", listed())["frame"]
    assert set(frame) == {"file", "method", "anteversion_deg", "origin", "x", "y", "z"}
    assert (frame["method"], frame["anteversion_deg"]) == ("shaft_neck", None)
    assert frame["file"] == "origin：干轴上小转子的高度；x：指向内侧；y：指向后方；z：沿干轴指向近端", "原来那四句话并成一句"
    assert frame["origin"] == [0.0, 0.0, 0.0] and frame["z"] == [0.0, 0.0, 1.0], "原点在干轴上小转子那一层"
    assert frame["x"] == pytest.approx([0.99789, 0.06498, 0.0], abs=1e-5) and frame["y"] == pytest.approx([-0.06498, 0.99789, 0.0], abs=1e-5)
    marks = {name: {"xyz": point["xyz"]} for name, point in V1["landmarks"].items()}
    assert {key: frame[key] for key in ("origin", "x", "y", "z")} == bone_model.frame(marks, "right", "shaft_neck"), "算法就是契约里那一份"
    left = upcast("bone_model", listed(side="left"))["frame"]
    assert left["x"] == frame["x"] and left["y"] == pytest.approx([-part for part in frame["y"]]), "左股骨：后方反过来"


@pytest.mark.parametrize("file,form", [("solids/cortical.step", "step"), ("solids/cortical.STP", "step"), ("solids/cortical.stl", "stl"),
                                       ("solids/cortical.Stl", "stl"), ("solids/cortical.brep", None), ("solids/cortical", None),
                                       ("solids/step", None), ("solids.stl/cortical.txt", None)])
def test_the_kind_of_geometry_file_is_read_off_its_suffix(file, form):
    files = [file, "solids/cancellous.step"]
    old = {**listed(**changed_v1("solids", "cortical", "file", value=file)), "files": files}
    geometry = upcast("bone_model", old)["regions"][0]["geometry"]
    assert geometry == {"kind": "solid", "format": form, "file": file}, "别的后缀是不知道"


def test_first_version_material_that_is_not_linear_elastic_cannot_be_read():
    """第 1 版的 model 是随便写的一段文字。不是 linear_elastic 的不知道是什么材料，不当成线弹性读。"""
    odd = changed_v1("materials", "cancellous", "model", value="crushable_foam")
    with pytest.raises(CannotUpcast, match="cancellous 的材料写的是 'crushable_foam'：第 1 版的材料只认 linear_elastic"):
        upcast("bone_model", listed(**odd))
    more = changed_v1("materials", "cortical", "source", value="Sawbones 的资料")
    assert upcast("bone_model", listed(**more))["regions"][0]["material"] == {"model": "elastic", "E": 16800, "nu": 0.3}, \
        "第 1 版材料里另外的项契约没核过，读的时候不带"


def test_a_first_version_model_whose_frame_cannot_be_determined_cannot_be_read(tmp_path):
    """第 1 版只核了颈轴、干轴各自定得出；两根轴平行，内侧朝哪就定不出来。"""
    straight = {"landmarks": {**V1["landmarks"], "head_center": {"xyz": [0.0, 0.0, 80.0], "definition": "x"},
                              "neck_center": {"xyz": [0.0, 0.0, 60.0], "definition": "x"}}}
    with pytest.raises(CannotUpcast, match="第 1 版的骨模型定不出解剖坐标系：颈轴和干轴平行"):
        upcast("bone_model", listed(**straight))
    assert check_format("bone_model", write_v1(tmp_path / "b", **straight)) == ["第 1 版的骨模型定不出解剖坐标系：颈轴和干轴平行，定不出内侧朝哪"]


def test_items_a_first_version_manifest_happens_to_carry_do_not_leak_into_the_second():
    """第 1 版别的项随意：正好叫 regions、coverage 的，读成第 2 版时让位给真的那几项。"""
    new = upcast("bone_model", listed(regions="two", coverage="whole", surfaces=None, bone_type="sawbones", source="cad"))
    assert [region["name"] for region in new["regions"]] == ["cortical", "cancellous"]
    assert (new["coverage"], new["surfaces"], new["bone_type"], new["source"]) == (None, {}, None, None)


def test_upcast_does_not_need_the_shared_manifest_items_to_be_right():
    """升版在核清单共用的那几项之前：files 没写、不是列表，也不能在这里出错。实体的文件在不在，后面照第 2 版核。"""
    for files in (..., "solids/cortical.step", None):
        old = {key: value for key, value in {**listed(), "files": files}.items() if value is not ...}
        assert [region["geometry"]["file"] for region in upcast("bone_model", old)["regions"]] == [
            "solids/cortical.step", "solids/cancellous.step"]
    with pytest.raises(CannotUpcast, match="实体 cortical 的文件清单里没有：7"):
        upcast("bone_model", {**listed(**changed_v1("solids", "cortical", "file", value=7)), "files": None})


def test_what_recon_writes_today_still_passes(tmp_path):
    """冻结的 plugins/recon/model.py 这一小步不动：它写的还是第 1 版（"format": 1 是写死的），写完叫 check_format。"""
    extra = {**copy.deepcopy(V1), "measures": {"cortical_volume_mm3": 271529.5}}
    extra["solids"] = {name: {"file": f"solids/{name}.stl"} for name in ("cortical", "cancellous")}
    files = {"solids/cortical.stl": b"solid cortical", "solids/cancellous.stl": b"solid cancellous"}
    for kind in ("bone_model", "bone_draft"):
        root = samples.write(tmp_path / kind, extra, kind, files, version=1)
        assert check_format(kind, root) == []
        assert [region["geometry"]["format"] for region in bone_model.read(root)["regions"]] == ["stl", "stl"]


# ---------------------------------------------------------------- 名字、读

def test_names_are_the_same_whichever_version_the_manifest_is_in(tmp_path):
    """冻结的 plugins/fea/given.py 交来的是盘上原样的清单：第 1 版的也认，给出的名字和读成第 2 版以后一样。"""
    old = listed()
    wanted = {"bone.block": set(), "bone.joint": set(), "bone.surface": set(),
              "bone.region": {"cortical", "cancellous"}, "bone.landmark": set(V1["landmarks"])}
    assert bone_model.names(old) == wanted == bone_model.names(upcast("bone_model", old))
    assert bone_model.names(V1) == wanted, "没带清单共用的那几项也认"
    assert bone_model.names({"solids": dict.fromkeys(bone_model.SOLIDS), "landmarks": dict.fromkeys(bone_model.LANDMARKS)}) == {
        **wanted, "bone.landmark": set(bone_model.LANDMARKS)}
    assert bone_model.names({})["bone.region"] == set(), "清单不全也不报错：名字少了，引用它的设定会被拒"
    assert bone_model.names({**old, "regions": [{"name": "stray"}], "surfaces": {"stray": {}}})["bone.region"] == {"cortical", "cancellous"}, \
        "第 1 版的清单里正好有一项叫 regions：不当成第 2 版的区域"
    assert bone_model.names({**old, "regions": [{"name": "stray"}], "surfaces": {"stray": {}}})["bone.surface"] == set()
    assert bone_model.names({"solids": ["cortical"], "landmarks": ["head_center"]}) == {**wanted, "bone.region": set(), "bone.landmark": set()}


def test_read_gives_a_first_version_folder_in_the_second_version(tmp_path):
    root = write_v1(tmp_path / "b")
    model = bone_model.read(root)
    assert model == upcast("bone_model", read_manifest(root)) and model["format"] == 2
    assert read_manifest(root)["format"] == 1, "盘上的不动"
    with pytest.raises(CannotUpcast, match="标志点缺"):
        bone_model.read(write_v1(tmp_path / "bad", **changed_v1("landmarks", "head_center")))


def test_an_odd_version_number_is_said_out_loud_and_so_is_a_step_that_does_not_reach_the_next_version(monkeypatch):
    """版本号写得不对的，不当成第 1 版去读；转完不是下一版的，说出该是第几版。"""
    from stemlab.contract import versions

    for odd in (0, -1, "1", True, None, 1.0):
        with pytest.raises(CannotUpcast, match="bone_model：没有写格式版本，或者写的不是正整数"):
            upcast("bone_model", {**listed(), "format": odd})
    monkeypatch.setitem(versions.UPCASTS, ("bone_model", 1), lambda old: dict(old))
    with pytest.raises(CannotUpcast, match="bone_model 的第 1 版转完之后不是第 2 版"):
        upcast("bone_model", listed())


def test_what_was_and_is_in_the_first_version():
    assert bone_model.SOLIDS == ("cortical", "cancellous")
    assert bone_model.FRAME == ("origin", "x", "y", "z")
