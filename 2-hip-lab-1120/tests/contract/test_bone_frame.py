"""解剖坐标系：从标志点怎么算，只有契约里这一份。两种定法各有算例；换一个标志点，结果跟着变；左股骨是右股骨的镜像。"""
from __future__ import annotations

import copy
import math

import pytest

from stemlab.contract.formats import bone_model
from tests.contract import bone_samples as samples


def dot(a, b) -> float:
    return sum(p * q for p, q in zip(a, b))


def cross(a, b) -> list:
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def same(made: dict, truth: dict, tolerance: float = 1e-9) -> bool:
    return all(made[key] == pytest.approx(truth[key], abs=tolerance) for key in ("origin", "x", "y", "z"))


def marked(side="right", anteversion=12.0, condyles=True, pose=samples.TILTED) -> tuple:
    marks, truth = samples.femur(side, anteversion, condyles, pose)
    return samples.landmarks(marks), truth


# ---------------------------------------------------------------- 算例一：造出来的股骨，真值照构造写出来

@pytest.mark.parametrize("side", ["right", "left"])
@pytest.mark.parametrize("pose", [samples.STRAIGHT, samples.TILTED], ids=["straight", "tilted"])
def test_the_condylar_line_gives_the_frame_the_femur_was_built_in(side, pose):
    """照后髁连线定：z 沿干轴指向近端，x 是外髁到内髁的连线投到垂直干轴的面上，y 指向后方，原点在干轴上小转子那一层。"""
    landmarks, truth = marked(side, pose=pose)
    made = bone_model.frame(landmarks, side, "shaft_condyles")
    assert same(made, truth), (made, truth)
    assert set(made) == {"origin", "x", "y", "z"} and all(isinstance(made[key], list) and len(made[key]) == 3 for key in made)
    assert bone_model.anteversion(landmarks, side) == pytest.approx(12.0, abs=1e-9), "颈轴朝前偏了 12°"


@pytest.mark.parametrize("side", ["right", "left"])
@pytest.mark.parametrize("anteversion", [12.0, 0.0, -8.0, 35.0])
def test_the_neck_axis_turned_back_by_the_anteversion_gives_the_same_frame(side, anteversion):
    """照颈轴定：颈轴投到垂直干轴的面上，再照前倾角转回去。前倾角取得对，就是照后髁连线定的那个坐标系；用不着后髁。"""
    landmarks, truth = marked(side, anteversion, condyles=False)
    made = bone_model.frame(landmarks, side, "shaft_neck", anteversion)
    assert same(made, truth), (made, truth)
    neck = [h - n for h, n in zip(landmarks["head_center"]["xyz"], landmarks["neck_center"]["xyz"])]
    forward = math.degrees(math.atan2(-dot(neck, made["y"]), dot(neck, made["x"])))
    assert forward == pytest.approx(anteversion, abs=1e-9), "转完以后，颈轴在这个坐标系里朝前偏的角度正好是前倾角"


@pytest.mark.parametrize("side", ["right", "left"])
def test_without_an_anteversion_the_frame_is_not_turned_back(side):
    """不知道前倾角（第 1 版读来的骨模型）：不转，x 就是颈轴的投影。它和照后髁连线定的绕干轴差一个前倾角。"""
    landmarks, truth = marked(side, 12.0)
    made = bone_model.frame(landmarks, side, "shaft_neck")
    assert made == bone_model.frame(landmarks, side, "shaft_neck", None) == bone_model.frame(landmarks, side, "shaft_neck", 0.0)
    assert made["z"] == pytest.approx(truth["z"], abs=1e-9) and made["origin"] == pytest.approx(truth["origin"], abs=1e-9)
    assert math.degrees(math.acos(dot(made["x"], truth["x"]))) == pytest.approx(12.0, abs=1e-9)
    neck = [h - n for h, n in zip(landmarks["head_center"]["xyz"], landmarks["neck_center"]["xyz"])]
    assert dot(neck, made["y"]) == pytest.approx(0.0, abs=1e-9) and dot(neck, made["x"]) > 0, "颈轴没有前后的分量，指向内侧"
    assert dot(made["x"], truth["y"]) < 0, "颈轴朝前偏：没转回去的 x 也朝前偏"


@pytest.mark.parametrize("method,turn", [("shaft_condyles", None), ("shaft_neck", 12.0), ("shaft_neck", None)])
def test_the_axes_are_medial_posterior_proximal_on_both_sides(method, turn):
    """三个轴的意思两侧都一样：右股骨上是右手系，左股骨上是左手系。几何不镜像。"""
    for side, hand in (("right", 1.0), ("left", -1.0)):
        landmarks, _ = marked(side)
        made = bone_model.frame(landmarks, side, method, turn)
        x, y, z = made["x"], made["y"], made["z"]
        assert [dot(x, x), dot(y, y), dot(z, z)] == pytest.approx([1.0, 1.0, 1.0], abs=1e-12)
        assert [dot(x, y), dot(x, z), dot(y, z)] == pytest.approx([0.0, 0.0, 0.0], abs=1e-12)
        assert dot(cross(x, y), z) == pytest.approx(hand, abs=1e-12)
        at = {name: [dot([p - o for p, o in zip(point["xyz"], made["origin"])], axis) for axis in (x, y, z)]
              for name, point in landmarks.items()}
        assert at["head_center"][0] > 30 and at["head_center"][2] > 40, "头在内侧、近端"
        assert at["lesser_trochanter"][1] > 0 and at["lesser_trochanter"][2] == pytest.approx(0.0, abs=1e-9), "小转子在后方，原点在它那一层"
        assert at["shaft_distal"][2] < at["shaft_proximal"][2] < 0


def test_a_left_femur_is_the_mirror_image_of_the_right():
    """左股骨的点换到解剖坐标系里，坐标和它镜像成右股骨以后的一样。"""
    for method, turn in (("shaft_condyles", None), ("shaft_neck", 12.0)):
        seen = {}
        for side in ("right", "left"):
            landmarks, _ = marked(side)
            made = bone_model.frame(landmarks, side, method, turn)
            seen[side] = {name: [dot([p - o for p, o in zip(point["xyz"], made["origin"])], made[axis]) for axis in "xyz"]
                          for name, point in landmarks.items()}
        for name in seen["right"]:
            assert seen["left"][name] == pytest.approx(seen["right"][name], abs=1e-9), name
    right, left = marked("right")[0], marked("left")[0]
    assert bone_model.anteversion(left, "left") == pytest.approx(bone_model.anteversion(right, "right"), abs=1e-9), "前倾角两侧同号"


def test_a_joint_force_is_put_together_the_same_way_on_both_sides():
    """关节力写成（内侧、后方、近端）三个分量：合力 = 三个分量各乘上对应的轴，两侧同一个算式。"""
    load = (-400.0, 250.0, -1900.0)                       # 朝外、朝后、朝下压
    seen = {}
    for side in ("right", "left"):
        landmarks, _ = marked(side, pose=samples.STRAIGHT)
        made = bone_model.frame(landmarks, side, "shaft_condyles")
        seen[side] = [sum(part * made[axis][k] for part, axis in zip(load, "xyz")) for k in range(3)]
    assert seen["right"] == pytest.approx([-400.0, 250.0, -1900.0]) and seen["left"] == pytest.approx([400.0, 250.0, -1900.0]), \
        "文件坐标里，左股骨上的合力是右股骨上的镜像"


# ---------------------------------------------------------------- 算例二：3406，和原项目的模型坐标对

def s3406() -> dict:
    return samples.landmarks(samples.S3406)


def in_frame(made: dict, point) -> list:
    return [dot([p - o for p, o in zip(point, made["origin"])], made[axis]) for axis in "xyz"]


def test_on_the_3406_the_condylar_frame_is_the_legacy_model_frame():
    """3406 是完整的股骨：照干轴加后髁连线定出来，就是原项目的模型坐标。头心在里面的坐标、颈轴的方向、前倾角都和原项目记的一样。"""
    made = bone_model.frame(s3406(), "right", "shaft_condyles")
    assert made["origin"] == pytest.approx(samples.S3406_ORIGIN, abs=1e-9) and made["z"] == pytest.approx(samples.S3406_Z, abs=1e-9)
    assert in_frame(made, samples.S3406["head_center"]) == pytest.approx(samples.S3406_HEAD_IN_FRAME, abs=1e-9)
    neck = [h - n for h, n in zip(samples.S3406["head_center"], samples.S3406["neck_center"])]
    length = math.sqrt(dot(neck, neck))
    assert [dot(neck, made[axis]) / length for axis in "xyz"] == pytest.approx(samples.S3406_NECK_IN_FRAME, abs=1e-9)
    assert bone_model.anteversion(s3406(), "right") == pytest.approx(samples.S3406_ANTEVERSION, abs=1e-9), "−3.81°：颈轴略朝后"
    assert bone_model.neck_shaft_angle(s3406()) == pytest.approx(samples.S3406_NECK_SHAFT, abs=1e-9)


def test_on_the_3406_the_two_ways_differ_by_its_anteversion_about_the_shaft():
    """照颈轴定：前倾角取原项目量的 −3.81°，是同一个坐标系；不知道前倾角就差 3.81°（拆内核 4d 里那 7% 到 11% 的来历）。"""
    by_condyles = bone_model.frame(s3406(), "right", "shaft_condyles")
    turned = bone_model.frame(s3406(), "right", "shaft_neck", samples.S3406_ANTEVERSION)
    assert same(turned, by_condyles, 1e-9)
    as_is = bone_model.frame(s3406(), "right", "shaft_neck")
    assert as_is["z"] == pytest.approx(by_condyles["z"], abs=1e-12) and as_is["origin"] == pytest.approx(by_condyles["origin"], abs=1e-12)
    assert math.degrees(math.acos(dot(as_is["x"], by_condyles["x"]))) == pytest.approx(3.806858193056245, abs=1e-9)
    assert dot(as_is["x"], by_condyles["y"]) > 0, "颈轴略朝后：没转回去的 x 也略朝后"


# ---------------------------------------------------------------- 换一个标志点，结果跟着变

MOVES = [
    # 挪哪个点，照哪种定法，哪几样跟着变
    ("shaft_proximal", "shaft_condyles", {"origin", "x", "y", "z"}),
    ("shaft_distal", "shaft_condyles", {"origin", "x", "y", "z"}),
    ("lesser_trochanter", "shaft_condyles", {"origin"}),
    ("condyle_medial", "shaft_condyles", {"x", "y"}),
    ("condyle_lateral", "shaft_condyles", {"x", "y"}),
    ("head_center", "shaft_condyles", set()),               # 照后髁连线定的，颈轴不进坐标系
    ("neck_center", "shaft_condyles", set()),
    ("head_center", "shaft_neck", {"x", "y"}),
    ("neck_center", "shaft_neck", {"x", "y"}),
    ("lesser_trochanter", "shaft_neck", {"origin"}),
    ("shaft_distal", "shaft_neck", {"origin", "x", "y", "z"}),
    ("condyle_medial", "shaft_neck", set()),                # 照颈轴定的，后髁不进坐标系
]


@pytest.mark.parametrize("name,method,moving", MOVES, ids=[f"{row[0]}-{row[1]}" for row in MOVES])
def test_moving_a_landmark_moves_the_frame_with_it(name, method, moving):
    landmarks, _ = marked("right")
    turn = 12.0 if method == "shaft_neck" else None
    before = bone_model.frame(landmarks, "right", method, turn)
    nudged = copy.deepcopy(landmarks)
    nudged[name]["xyz"] = [value + shift for value, shift in zip(nudged[name]["xyz"], (3.0, -2.0, 4.0))]
    after = bone_model.frame(nudged, "right", method, turn)
    changed = {key for key in before if before[key] != pytest.approx(after[key], abs=1e-6)}
    assert changed == moving, (changed, moving)


def test_the_anteversion_turns_the_frame_about_the_shaft_and_nothing_else():
    landmarks, _ = marked("right", condyles=False)
    base = bone_model.frame(landmarks, "right", "shaft_neck", 0.0)
    for degrees in (5.0, -20.0, 60.0):
        made = bone_model.frame(landmarks, "right", "shaft_neck", degrees)
        assert made["z"] == base["z"] and made["origin"] == base["origin"]
        assert math.degrees(math.atan2(dot(made["x"], base["y"]), dot(made["x"], base["x"]))) == pytest.approx(degrees, abs=1e-9), \
            "前倾角为正：x 朝后转（颈轴相对它就朝前了）"


def test_the_side_decides_which_way_is_posterior():
    landmarks, _ = marked("right")
    right, wrong = bone_model.frame(landmarks, "right", "shaft_condyles"), bone_model.frame(landmarks, "left", "shaft_condyles")
    assert wrong["x"] == right["x"] and wrong["z"] == right["z"] and wrong["origin"] == right["origin"]
    assert wrong["y"] == pytest.approx([-part for part in right["y"]]), "同一组标志点说成另一侧：后方反过来"


# ---------------------------------------------------------------- 定不出来的，说出为什么

def moved(landmarks: dict, **to) -> dict:
    """把几个标志点挪到给的位置；给的是另一个标志点的名字，就挪到它原来的位置。"""
    made = copy.deepcopy(landmarks)
    for name, source in to.items():
        made[name]["xyz"] = list(source if isinstance(source, list) else landmarks[source]["xyz"])
    return made


def test_what_cannot_be_determined_is_refused_with_the_reason():
    landmarks, _ = marked("right", pose=samples.STRAIGHT)
    cases = [
        (moved(landmarks, shaft_distal="shaft_proximal"), "shaft_condyles", None, "定不出干轴"),
        (moved(landmarks, neck_center="head_center"), "shaft_condyles", None, "定不出颈轴"),
        (moved(landmarks, head_center=[0.0, 0.0, 80.0], neck_center=[0.0, 0.0, 60.0]), "shaft_neck", 10.0, "颈轴和干轴平行"),
        (moved(landmarks, condyle_medial="condyle_lateral"), "shaft_condyles", None, "后髁的连线"),
        (moved(landmarks, condyle_medial=[0.0, 0.0, -400.0], condyle_lateral=[0.0, 0.0, -420.0]), "shaft_condyles", None, "后髁的连线"),
        (moved(landmarks, condyle_medial="condyle_lateral", condyle_lateral="condyle_medial"), "shaft_condyles", None, "写反了"),
        ({name: point for name, point in landmarks.items() if name != "condyle_lateral"}, "shaft_condyles", None, "condyle_lateral"),
        ({name: point for name, point in landmarks.items() if name != "lesser_trochanter"}, "shaft_neck", 10.0, "lesser_trochanter"),
        (landmarks, "shaft_neck", 90.0, "前倾角"),
        (landmarks, "shaft_neck", -90.0, "前倾角"),
        (landmarks, "shaft_neck", "12", "前倾角"),
        (landmarks, "shaft_neck", True, "前倾角"),
        (landmarks, "shaft_neck", float("nan"), "前倾角"),
        (landmarks, "shaft_condyles", 12.0, "前倾角"),
        (landmarks, "by_eye", None, "定法"),
    ]
    for given, method, turn, word in cases:
        with pytest.raises(ValueError, match=word):
            bone_model.frame(given, "right", method, turn)
    with pytest.raises(ValueError, match="side"):
        bone_model.frame(landmarks, "both", "shaft_neck", 10.0)
    for odd, word in ((None, "标志点必须是一个 JSON 对象"), (["head_center"], "标志点必须是一个 JSON 对象"),
                      ({**landmarks, "head_center": [1.0, 2.0, 3.0]}, r"标志点 \['head_center'\] 的 xyz 要是三个数"),
                      ({**landmarks, "head_center": {"xyz": [1.0, 2.0]}, "shaft_distal": {"at": [0.0, 0.0, 0.0]}},
                       r"标志点 \['head_center', 'shaft_distal'\] 的 xyz 要是三个数"),
                      ({**landmarks, "lesser_trochanter": {"xyz": [1.0, "2", 3.0]}}, r"标志点 \['lesser_trochanter'\] 的 xyz 要是三个数")):
        with pytest.raises(ValueError, match=word):
            bone_model.frame(odd, "right", "shaft_neck", 10.0)
    extra = {**landmarks, "greater_trochanter": {"xyz": "somewhere"}}
    assert bone_model.frame(extra, "right", "shaft_neck", 10.0) == bone_model.frame(landmarks, "right", "shaft_neck", 10.0), \
        "用不到的标志点不看"
    with pytest.raises(ValueError, match="condyle_medial"):
        bone_model.anteversion(marked("right", condyles=False)[0], "right")
    assert bone_model.frame(landmarks, "right", "shaft_neck", 89.9) and bone_model.frame(landmarks, "right", "shaft_neck", -89.9)


def test_points_within_a_nanometre_count_as_one_point():
    """两个点差一纳米以内（含）算重合；颈轴垂直干轴的那部分不到一纳米（含）算和干轴平行。再多一点就定得出。"""
    marks, _ = marked("right", pose=samples.STRAIGHT)           # 干轴上的两个点是 (0, 0, −150) 和 (0, 0, −20)
    assert bone_model.axes(moved(marks, shaft_proximal=[1e-9, 0.0, -150.0]))[1] is None
    assert bone_model.axes(moved(marks, shaft_proximal=[2e-9, 0.0, -150.0]))[1] == (1.0, 0.0, 0.0)
    assert bone_model.axes(moved(marks, neck_center=[1e-9, 0.0, 0.0], head_center=[0.0, 0.0, 0.0]))[0] is None
    with pytest.raises(ValueError, match="定不出干轴"):
        bone_model.frame(moved(marks, shaft_proximal=[1e-9, 0.0, -150.0]), "right", "shaft_neck")
    with pytest.raises(ValueError, match="颈轴和干轴平行"):
        bone_model.frame(moved(marks, head_center=[0.0, 0.0, 80.0], neck_center=[-1e-9, 0.0, 60.0]), "right", "shaft_neck")
    barely = bone_model.frame(moved(marks, head_center=[0.0, 0.0, 80.0], neck_center=[-2e-9, 0.0, 60.0]), "right", "shaft_neck")
    assert barely["x"] == [1.0, 0.0, 0.0]
    with pytest.raises(ValueError, match="后髁的连线"):
        bone_model.frame(moved(marks, condyle_medial=[1e-9, 27.0, -400.0], condyle_lateral=[0.0, 27.0, -420.0]), "right", "shaft_condyles")
    assert bone_model.frame(moved(marks, condyle_medial=[2e-9, 27.0, -400.0], condyle_lateral=[0.0, 27.0, -420.0]),
                            "right", "shaft_condyles")["x"] == [1.0, 0.0, 0.0]


def test_condyles_the_wrong_way_round_are_told_apart_from_a_large_anteversion():
    """量出的前倾角要在 ±90° 以内：照后髁连线定出的内侧和颈轴指的大致同向。正好垂直也不算。"""
    for degrees in (80.0, -80.0):
        landmarks, truth = marked("right", degrees, pose=samples.STRAIGHT)
        assert same(bone_model.frame(landmarks, "right", "shaft_condyles"), truth)
        assert bone_model.anteversion(landmarks, "right") == pytest.approx(degrees, abs=1e-9)
    square = marked("right", pose=samples.STRAIGHT)[0]
    square = moved(square, head_center=[0.0, -45.0, 50.0], neck_center=[0.0, -26.6, 36.2])      # 颈轴正朝前：和后髁连线垂直
    with pytest.raises(ValueError, match="写反了"):
        bone_model.frame(square, "right", "shaft_condyles")


# ---------------------------------------------------------------- 颈轴、干轴、颈干角（照旧）

def test_axes_come_from_the_landmarks():
    neck, shaft = bone_model.axes(samples.V1["landmarks"])
    assert neck == pytest.approx((0.922, 0.060, 0.382), abs=1e-3), "颈轴：从颈中心指向头心"
    assert shaft == pytest.approx((0.0, 0.0, 1.0)), "干轴：从远端指向近端"
    assert bone_model.neck_shaft_angle(samples.V1["landmarks"]) == pytest.approx(112.4, abs=0.1)
    assert bone_model.axes(samples.landmarks(samples.femur()[0]))[1] == pytest.approx((0.0, 0.0, 1.0)), "第 2 版的标志点一样用"
