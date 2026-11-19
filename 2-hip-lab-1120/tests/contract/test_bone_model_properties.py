"""骨模型的属性测试：解剖坐标系跟着骨走；两种定法对得上；左股骨是右股骨的镜像；随便一组合理的标志点上坐标系都是
内侧、后方、近端；第 1 版的清单读成第 2 版都过核对，名字不变。属性测试是什么，见 tests/properties.py。"""
from __future__ import annotations

import math

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from stemlab.contract.formats import bone_model
from stemlab.contract.formats.manifest import make_manifest
from stemlab.contract.versions import upcast
from tests import properties  # noqa: F401  载入 Hypothesis 的设置
from tests.contract import bone_samples as samples

SIDES = st.sampled_from(["right", "left"])
ANTEVERSIONS = st.floats(-70.0, 70.0)
COORDS = st.floats(-300.0, 300.0)
POINTS = st.tuples(COORDS, COORDS, COORDS)
DIRECTIONS = st.tuples(st.floats(-1, 1), st.floats(-1, 1), st.floats(-1, 1)).filter(lambda v: sum(part * part for part in v) > 0.01)
POSES = st.tuples(DIRECTIONS, st.floats(-180.0, 180.0), POINTS).map(lambda drawn: (samples.turn(drawn[0], drawn[1]), drawn[2]))


def dot(a, b) -> float:
    return sum(p * q for p, q in zip(a, b))


def sub(a, b) -> list:
    return [p - q for p, q in zip(a, b)]


def cross(a, b) -> list:
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def across(vector, axis) -> float:
    """vector 垂直于 axis（单位向量）的那部分有多长。"""
    flat = sub(vector, [dot(vector, axis) * part for part in axis])
    return math.sqrt(dot(flat, flat))


def close(made: dict, truth: dict, tolerance: float = 1e-6) -> bool:
    return all(made[key] == pytest.approx(truth[key], abs=tolerance) for key in ("origin", "x", "y", "z"))


# ---------------------------------------------------------------- 造出来的股骨：整根骨一起挪动转动，坐标系跟着走

@given(POSES, SIDES, ANTEVERSIONS)
def test_the_frame_moves_and_turns_with_the_bone(pose, side, anteversion):
    marks, truth = samples.femur(side, anteversion, condyles=True, pose=pose)
    landmarks = samples.landmarks(marks)
    assert close(bone_model.frame(landmarks, side, "shaft_condyles"), truth)
    assert bone_model.anteversion(landmarks, side) == pytest.approx(anteversion, abs=1e-6)
    assert close(bone_model.frame(landmarks, side, "shaft_neck", anteversion), truth), "照颈轴、前倾角取量出来的：同一个坐标系"


@given(POSES, SIDES, ANTEVERSIONS, st.booleans())
def test_a_bone_model_written_with_the_frame_of_its_landmarks_passes(pose, side, anteversion, whole):
    listed = samples.manifest(samples.good(side, whole, anteversion, pose))
    assert bone_model.check_model("bone_model", listed) == []
    other = "left" if side == "right" else "right"
    assert any("对不上" in text for text in bone_model.check_model("bone_model", {**listed, "side": other})), "换一侧：后方反了"


# ---------------------------------------------------------------- 随便一组合理的标志点

@st.composite
def bones(draw) -> dict:
    """随便一组标志点：干轴够长，颈轴、后髁连线都明显不和干轴平行。别的不设限。"""
    marks = {name: list(draw(POINTS)) for name in (*samples.FIVE, "condyle_medial", "condyle_lateral")}
    shaft = sub(marks["shaft_proximal"], marks["shaft_distal"])
    length = math.sqrt(dot(shaft, shaft))
    assume(length > 20.0)
    up = [part / length for part in shaft]
    neck, line = sub(marks["head_center"], marks["neck_center"]), sub(marks["condyle_medial"], marks["condyle_lateral"])
    assume(across(neck, up) > 5.0 and across(line, up) > 5.0)
    return samples.landmarks(marks)


@given(bones(), SIDES, ANTEVERSIONS)
def test_any_frame_is_medial_posterior_proximal(landmarks, side, anteversion):
    at = {name: point["xyz"] for name, point in landmarks.items()}
    made = bone_model.frame(landmarks, side, "shaft_neck", anteversion)
    x, y, z = made["x"], made["y"], made["z"]
    assert [dot(x, x), dot(y, y), dot(z, z)] == pytest.approx([1.0, 1.0, 1.0], abs=1e-9)
    assert [dot(x, y), dot(x, z), dot(y, z)] == pytest.approx([0.0, 0.0, 0.0], abs=1e-9)
    assert dot(cross(x, y), z) == pytest.approx(1.0 if side == "right" else -1.0, abs=1e-9), "右股骨右手系，左股骨左手系"
    assert dot(sub(at["shaft_proximal"], at["shaft_distal"]), z) > 0, "z 指向近端"
    assert across(sub(made["origin"], at["shaft_distal"]), z) == pytest.approx(0.0, abs=1e-6), "原点在干轴上"
    assert dot(sub(at["lesser_trochanter"], made["origin"]), z) == pytest.approx(0.0, abs=1e-6), "在小转子那一层"
    neck = sub(at["head_center"], at["neck_center"])
    assert math.degrees(math.atan2(-dot(neck, y), dot(neck, x))) == pytest.approx(anteversion, abs=1e-6), "颈轴朝前偏的就是前倾角"


@given(bones(), SIDES)
def test_the_two_ways_agree_on_any_bone(landmarks, side):
    """照后髁连线定；量出前倾角，再拿它照颈轴定：同一个坐标系。量出的前倾角到了 ±90° 以外的不收（内外后髁写反了）。"""
    at = {name: point["xyz"] for name, point in landmarks.items()}
    shaft = sub(at["shaft_proximal"], at["shaft_distal"])
    up = [part / math.sqrt(dot(shaft, shaft)) for part in shaft]
    neck, line = sub(at["head_center"], at["neck_center"]), sub(at["condyle_medial"], at["condyle_lateral"])
    same_way = dot(neck, line) - dot(neck, up) * dot(line, up)          # 两个都投到垂直干轴的面上以后的点乘
    assume(abs(same_way) > 1e-3)
    if same_way < 0:
        with pytest.raises(ValueError, match="写反了"):
            bone_model.frame(landmarks, side, "shaft_condyles")
        swapped = {**landmarks, "condyle_medial": landmarks["condyle_lateral"], "condyle_lateral": landmarks["condyle_medial"]}
        assert bone_model.frame(swapped, side, "shaft_condyles"), "换过来就定得出"
        return
    by_condyles = bone_model.frame(landmarks, side, "shaft_condyles")
    assert dot(line, by_condyles["y"]) == pytest.approx(0.0, abs=1e-6) and dot(line, by_condyles["x"]) > 0, "后髁连线没有前后的分量"
    measured = bone_model.anteversion(landmarks, side)
    assert -90.0 < measured < 90.0
    assume(abs(measured) < 89.9)
    assert close(bone_model.frame(landmarks, side, "shaft_neck", measured), by_condyles)


@given(bones(), SIDES, st.sampled_from([0, 1, 2]), ANTEVERSIONS)
def test_a_left_bone_is_the_mirror_of_a_right_one(landmarks, side, flipped, anteversion):
    """把整根骨对着一个坐标面镜像、说成另一侧：坐标系就是原来那个的镜像，量出的前倾角不变。"""
    def mirror(vector) -> list:
        return [-part if k == flipped else part for k, part in enumerate(vector)]

    other = "left" if side == "right" else "right"
    image = {name: {**point, "xyz": mirror(point["xyz"])} for name, point in landmarks.items()}
    for method, turn in (("shaft_neck", anteversion), ("shaft_neck", None)):
        made, mirrored = bone_model.frame(landmarks, side, method, turn), bone_model.frame(image, other, method, turn)
        assert close(mirrored, {key: mirror(made[key]) for key in made}, 1e-9)
    try:
        made = bone_model.frame(landmarks, side, "shaft_condyles")
    except ValueError:
        with pytest.raises(ValueError):
            bone_model.frame(image, other, "shaft_condyles")
        return
    assert close(bone_model.frame(image, other, "shaft_condyles"), {key: mirror(made[key]) for key in made}, 1e-9)
    assert bone_model.anteversion(image, other) == pytest.approx(bone_model.anteversion(landmarks, side), abs=1e-9)


# ---------------------------------------------------------------- 第 1 版的清单读成第 2 版

NAMES = st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=8).filter(lambda name: name[0] != "_")
SENTENCES = st.text(alphabet="abc 内侧后方近端，。", min_size=1, max_size=12).filter(lambda text: text.strip())
SUFFIXES = st.sampled_from([".step", ".STEP", ".stp", ".stl", ".brep", ""])


@st.composite
def first_versions(draw) -> dict:
    """随便一份合格的第 1 版清单：标志点的位置、材料的数、文件的后缀、别的项都是随机的。"""
    marks = draw(bones())
    extra = {name: {"xyz": list(draw(POINTS)), "definition": draw(SENTENCES)}
             for name in draw(st.lists(NAMES.filter(lambda name: name not in marks), max_size=3, unique=True))}
    landmarks = {**{name: {"xyz": point["xyz"], "definition": draw(SENTENCES)} for name, point in marks.items()
                    if name in samples.FIVE or draw(st.booleans())}, **extra}
    files = {name: f"solids/{name}{draw(SUFFIXES)}" for name in ("cortical", "cancellous")}
    materials = {name: {"model": "linear_elastic", "E_MPa": draw(st.floats(0.001, 1e6)), "nu": draw(st.floats(0.0, 0.499)),
                        **draw(st.dictionaries(st.sampled_from(["source", "density"]), SENTENCES, max_size=2))}
                 for name in files}
    others = draw(st.dictionaries(st.sampled_from(["measures", "note", "regions", "coverage", "surfaces", "source", "bone_type"]),
                                  properties.JSON, max_size=3))
    kind = draw(st.sampled_from(["bone_model", "bone_draft"]))
    listed = make_manifest(
        kind, list(files.values()), bone_id="femur042", side=draw(SIDES), units=dict(samples.UNITS),
        frame={key: draw(SENTENCES) for key in ("origin", "x", "y", "z")}, solids={name: {"file": file} for name, file in files.items()},
        landmarks=landmarks, materials=materials, history=[{"step": "import", "what": draw(SENTENCES)}],
        checks=[{"name": "volume", "value": 1.0, "limit": "x", "passed": True}], **others)
    return {**listed, "format": 1}


@given(first_versions())
def test_any_first_version_manifest_reads_as_a_second_version_one_that_passes(old):
    new = upcast("bone_model", old)
    assert new["format"] == 2
    assert bone_model.check_model(old["kind"], new, unknown_ok=True) == []
    assert bone_model.names(new) == bone_model.names(old), "能被名字引用的名字不变"
    for region in new["regions"]:
        before = old["materials"][region["name"]]
        assert region["material"] == {"model": "elastic", "E": before["E_MPa"], "nu": before["nu"]}
        assert region["geometry"]["file"] == old["solids"][region["name"]]["file"]
    assert {name: point["xyz"] for name, point in new["landmarks"].items()} == {name: point["xyz"] for name, point in old["landmarks"].items()}
    assert {key: new["frame"][key] for key in ("origin", "x", "y", "z")} == bone_model.frame(old["landmarks"], old["side"], "shaft_neck")
    asked = {"regions": {"cortical": [1, 1], "cancellous": [1, 1]}, "materials": ["elastic"], "landmarks": list(bone_model.LANDMARKS),
             "frame": {"methods": ["shaft_neck"], "unknown_anteversion": True}}
    assert bone_model.lacking(asked, new) == [], "第 1 版有的那几样，读出来都在"
    assert bone_model.lacking({"coverage": {"extent": ["whole", "proximal"]}}, new) != [], "不知道的，要它就算缺"
