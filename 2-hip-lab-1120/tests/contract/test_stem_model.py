"""柄的模型（柄空间包交给有限元包、推导量定义包的）：六段都写得出；写错的被拒，说出是哪一段、哪一项；
四篇文献里的柄都写得进去：有领和同形无领的商品柄、八段梯度多孔柄、平面的多孔柄按预测的密度场给材料。"""
from __future__ import annotations

import copy
import json

import pytest

from stemlab.contract.formats import stem_model as s
from tests import helpers

TI = {"model": "elastic", "E": 110000, "nu": 0.3}
FRAME = {"origin": [10.0, 0.0, 50.0], "x": [0, 1, 0], "y": [-1, 0, 0], "z": [0, 0, 1]}


def collared() -> dict:
    """有领的商品柄（Watanabe 2023 那样）：柄体和领两个区域，领的承压面和涂层区两个面组。"""
    return {
        "format": 1, "units": {"length": "mm"}, "dimension": "3d", "design": {"model": "size11-collared"},
        "files": ["geometry/body.step", "geometry/collar.step", "faces/collar_bearing.stl", "faces/coating.stl", "removed.stl"],
        "regions": [{"name": "body", "role": "body", "geometry": {"kind": "solid", "file": "geometry/body.step"}, "material": TI},
                    {"name": "collar", "role": "collar", "geometry": {"kind": "solid", "file": "geometry/collar.step"},
                     "material": TI}],
        "faces": {"collar_bearing": {"region": "collar", "file": "faces/collar_bearing.stl"},
                  "coating": {"region": "body", "file": "faces/coating.stl"}},
        "features": {"taper_center": [0.0, 0.0, 40.0], "tip": [0.0, 0.0, -120.0], "shoulder": [8.0, 0.0, 20.0]},
        "axes": {"stem_axis": {"point": [0.0, 0.0, 0.0], "direction": [0, 0, 1]}},
        "placement": {"frame": FRAME, "cut": {"point": [12.0, 0.0, 45.0], "normal": [0, 0, 1]}, "removed": "removed.stl",
                      "landmarks": ["head_center", "neck_center", "shaft_distal"]},
        "templating": {"entry_offset_mm": 2.5, "fit": 0.82},
    }


def written(tmp_path, model: dict, name: str = "stem"):
    folder = helpers.write_files(tmp_path / name, {rel: b"geometry" for rel in model["files"]})
    (folder / s.MANIFEST).write_bytes(json.dumps(model, ensure_ascii=False).encode("utf-8"))
    return folder


def test_a_collared_stem_model_passes_and_gives_its_names(tmp_path):
    model = collared()
    assert s.check(written(tmp_path, model)) == []
    assert s.names(model) == {"stem.region": {"body", "collar"}, "stem.faces": {"collar_bearing", "coating"},
                              "stem.feature": {"taper_center", "tip", "shoulder"}, "stem.axis": {"stem_axis"}}


def test_the_same_shape_without_a_collar_is_another_model_of_the_same_catalogue(tmp_path):
    """目录式的柄空间：一个型号一份现成的柄的模型。同形无领的，少了领的区域和它的面组。"""
    model = collared()
    model["design"] = {"model": "size11-collarless"}
    model["regions"] = model["regions"][:1]
    del model["faces"]["collar_bearing"]
    model["files"] = [rel for rel in model["files"] if "collar" not in rel]
    assert s.check(written(tmp_path, model)) == []


def test_an_eight_segment_graded_stem_can_be_eight_regions_or_one_region_graded_along_its_axis(tmp_path):
    """Gao 2022：柄分八段，一段实心钛合金，另外七段的模量是设计项。可以写成八个区域，也可以写成一个区域沿柄轴分段。"""
    design = {f"E{n}": 5000.0 + 1000 * n for n in range(1, 8)}
    regions = collared()
    regions["design"] = design
    regions["files"] = [f"geometry/seg{n}.step" for n in range(8)]
    regions["regions"] = [{"name": f"seg{n}", "role": "body" if n == 0 else "porous",
                           "geometry": {"kind": "solid", "file": f"geometry/seg{n}.step"},
                           "material": TI if n == 0 else dict(TI, E=design[f"E{n}"])} for n in range(8)]
    regions["faces"], regions["placement"]["removed"] = {}, None
    assert s.check(written(tmp_path, regions, "eight")) == []

    graded = copy.deepcopy(regions)
    graded["files"] = ["geometry/stem.step"]
    graded["regions"] = [{"name": "stem", "role": "porous", "geometry": {"kind": "solid", "file": "geometry/stem.step"},
                          "material": {"model": "piecewise", "along": "stem_axis",
                                       "segments": [{"from": 20.0 * n, "to": 20.0 * (n + 1),
                                                     "material": TI if n == 0 else dict(TI, E=design[f"E{n}"])}
                                                    for n in range(8)]}}]
    assert s.check(written(tmp_path, graded, "graded")) == []


def test_a_planar_stem_takes_its_material_from_a_predicted_density_field(tmp_path):
    """Pais 2025：二维的柄，中间是多孔区，材料按一份预测的密度场给，两头是实心的。"""
    model = collared()
    model["dimension"] = "2d"
    model["files"] = ["areas/taper.json", "areas/porous.json", "areas/distal.json"]
    field = {"model": "field", "source": {"prediction": "R0042", "field": "density"},
             "relation": [{"from": 0, "to": 1, "a": 110000, "b": 2.0}], "nu": 0.3}
    model["regions"] = [
        {"name": "taper", "role": "taper", "geometry": {"kind": "area", "file": "areas/taper.json"}, "material": TI},
        {"name": "porous", "role": "porous", "geometry": {"kind": "area", "file": "areas/porous.json"}, "material": field},
        {"name": "distal", "role": "body", "geometry": {"kind": "area", "file": "areas/distal.json"}, "material": TI}]
    model["faces"], model["placement"]["removed"] = {}, None
    assert s.check(written(tmp_path, model)) == []


@pytest.mark.parametrize("change,said", [
    (lambda x: x.pop("axes"), "柄的模型缺 axes"),
    (lambda x: x.update(colour="grey"), "柄的模型多了 colour"),
    (lambda x: x.update(format=2), "格式版本"),
    (lambda x: x.update(units={"length": "m"}), "units 要写成"),
    (lambda x: x.update(dimension="3D"), "dimension 要是 3d 或 2d"),
    (lambda x: x["regions"][0].update(role="handle"), "角色要是"),
    (lambda x: x["regions"][0].update(geometry={"kind": "area", "file": "geometry/body.step"}), "三维模型的不能是 area"),
    (lambda x: x["regions"][0].update(geometry={"kind": "solid", "file": "geometry/missing.step"}), "不在 files 里"),
    (lambda x: x["regions"][1].update(name="body"), "不重名"),
    (lambda x: x["regions"][0].update(material={"model": "elastic", "E": -1, "nu": 0.3}), "区域 'body' 的材料"),
    (lambda x: x["faces"]["collar_bearing"].update(region="neck"), "不在 regions 里"),
    (lambda x: x["features"].update(tip=[0, 0]), "特征点 'tip'"),
    (lambda x: x["axes"]["stem_axis"].update(direction=[0, 0, 2]), "轴 'stem_axis'"),
    (lambda x: x["placement"].update(frame=dict(FRAME, y=[1, 0, 0])), "两两垂直、长度为一、右手系"),
    (lambda x: x["placement"].update(frame=dict(FRAME, y=[1, 0, 0], x=[0, 1, 0], z=[0, 0, 1])), "右手系"),
    (lambda x: x["placement"].update(cut={"point": [0, 0, 0], "normal": [0, 0, 3]}), "placement.cut"),
    (lambda x: x["placement"].update(removed="bone.stl"), "placement.removed"),
    (lambda x: x["placement"].update(landmarks="head_center"), "placement.landmarks"),
    (lambda x: x.update(templating={"fit": "good"}), "templating"),
    (lambda x: x.update(regions=[]), "至少一个"),
    (lambda x: x.update(files=["../outside.stl"]), "不能是 . 或 .."),
    (lambda x: x.update(files="geometry/body.step"), "files 要是文件的列表"),
    (lambda x: x.update(files=x["files"] + [s.MANIFEST]), "不列 stem_model.json 自己"),
    (lambda x: x.update(design=["size11"]), "design 要是"),
    (lambda x: x.update(design={"1st": 1}), "design 要是"),
    (lambda x: x.update(faces=[]), "faces 要是"),
    (lambda x: x.update(features={"tip point": [0, 0, 0]}), "features 要是"),
    (lambda x: x["faces"].update(rim="faces/coating.stl"), "面组 'rim'：要写成"),
    (lambda x: x["faces"].update(rim={"region": "body"}), "面组 'rim'：要写成"),
    (lambda x: x["faces"].update(rim={"region": "body", "file": "faces/rim.stl"}), "不在 files 里"),
    (lambda x: x["regions"][0].update(geometry="geometry/body.step"), "geometry 要写成"),
    (lambda x: x["regions"][0].update(colour="grey"), "要写且只写"),
    (lambda x: x["placement"].pop("landmarks"), "placement 要写且只写"),
    (lambda x: x["placement"].update(frame={k: v for k, v in FRAME.items() if k != "z"}), "placement.frame"),
    (lambda x: x["placement"].update(frame=dict(FRAME, origin=[0, 0])), "placement.frame"),
    (lambda x: x["placement"].update(landmarks=["head center"]), "placement.landmarks"),
])
def test_a_stem_model_written_wrong_is_refused_and_says_where(tmp_path, change, said):
    model = collared()
    change(model)
    problems = s.check_model(model)
    assert problems and any(said in text for text in problems), problems


@pytest.mark.parametrize("handed,passes", [(1, True), (-1, False)])
def test_a_turned_frame_must_still_be_right_handed(handed, passes):
    """转过的坐标系：三个轴的分量都不是零，叉乘的每一项都要算对，才分得出左手系、右手系。"""
    third = 1 / 3
    frame = {"origin": [1.0, 2.0, 3.0], "x": [2 * third, 2 * third, third], "y": [-2 * third, third, 2 * third],
             "z": [handed * third, -2 * handed * third, 2 * handed * third]}
    model = collared()
    model["placement"]["frame"] = frame
    assert (s.check_model(model) == []) is passes


def test_a_folder_whose_manifest_is_wrong_is_refused_through_check(tmp_path):
    model = collared()
    model["dimension"] = "4d"
    assert any("dimension" in text for text in s.check(written(tmp_path, model)))


def test_the_files_listed_and_the_files_present_must_agree(tmp_path):
    model = collared()
    folder = written(tmp_path, model)
    (folder / "faces" / "coating.stl").unlink()
    (folder / "notes.txt").write_bytes(b"left behind")
    assert s.check(folder) == ["清单列了但文件夹里没有：faces/coating.stl", "文件夹里有但清单没列：notes.txt"]
    assert "没有 stem_model.json" in s.check(tmp_path / "nowhere")[0]
    (folder / s.MANIFEST).write_bytes(b"[1, 2]")
    assert s.check(folder) == [f"{s.MANIFEST} 必须是一个 JSON 对象"]
