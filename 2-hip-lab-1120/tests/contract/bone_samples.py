"""骨模型的测试共用的样本：一根造出来的股骨（解剖坐标系的真值照构造直接写出来），第 2 版和第 1 版的清单，3406 的数。"""
from __future__ import annotations

import copy
import math

from stemlab.contract.formats.manifest import make_manifest, write_manifest

UNITS = {"length": "mm", "force": "N", "stress": "MPa"}
FIVE = ("head_center", "neck_center", "shaft_proximal", "shaft_distal", "lesser_trochanter")


# ---------------------------------------------------------------- 一根造出来的股骨

def turn(axis, degrees: float) -> tuple:
    """绕 axis 转 degrees 度的旋转矩阵（按行）。"""
    length = math.sqrt(sum(part * part for part in axis))
    x, y, z = (part / length for part in axis)
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    t = 1.0 - c
    return ((t * x * x + c, t * x * y - s * z, t * x * z + s * y),
            (t * x * y + s * z, t * y * y + c, t * y * z - s * x),
            (t * x * z - s * y, t * y * z + s * x, t * z * z + c))


STRAIGHT = (((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), (0.0, 0.0, 0.0))    # 文件坐标就是解剖坐标
TILTED = (turn((1.0, 2.0, 3.0), 40.0), (12.0, -7.0, 30.0))                             # 斜着放、挪开了的


def femur(side: str = "right", anteversion: float = 12.0, condyles: bool = True, pose=STRAIGHT) -> tuple:
    """一根造出来的股骨：（标志点的位置，解剖坐标系该是什么）。真值照构造直接写，不经契约的算法。

    先在解剖坐标系里摆右股骨：x 内侧、y 后方、z 近端，原点在干轴上小转子那一层；颈轴在横断面里朝前偏 anteversion 度。
    左股骨是它对着 x = 0 那个面的镜像。再照 pose（旋转矩阵，平移）整个挪动转动，得到文件坐标里的位置。
    """
    a = math.radians(anteversion)
    neck = (0.8 * math.cos(a), -0.8 * math.sin(a), 0.6)
    head = (45.0 * math.cos(a), -45.0 * math.sin(a), 50.0)
    local = {"head_center": head, "neck_center": tuple(h - 23.0 * d for h, d in zip(head, neck)),
             "shaft_proximal": (0.0, 0.0, -20.0), "shaft_distal": (0.0, 0.0, -150.0), "lesser_trochanter": (15.0, 15.0, 0.0)}
    if condyles:        # 两个后髁不一样高：连线要先投到垂直干轴的面上
        local.update(condyle_medial=(32.0, 27.0, -415.0), condyle_lateral=(-30.0, 27.0, -418.0))
    sign = 1.0 if side == "right" else -1.0
    rotation, shift = pose
    marks = {name: [sum(r * c for r, c in zip(row, (sign * x, y, z))) + moved for row, moved in zip(rotation, shift)]
             for name, (x, y, z) in local.items()}
    truth = {"origin": list(shift), "x": [sign * row[0] for row in rotation], "y": [row[1] for row in rotation],
             "z": [row[2] for row in rotation]}
    return marks, truth


def landmarks(marks: dict) -> dict:
    """第 2 版的标志点：每个点带定义（找法的名字、版本、参数）和拟合的好坏。"""
    return {name: {"xyz": list(xyz), "definition": {"method": "section_fit", "version": "1", "params": {"step_mm": 1.0}},
                   "fit": {"rms_mm": 0.21, "points": 480}} for name, xyz in marks.items()}


# ---------------------------------------------------------------- 第 2 版的清单

FILES = {"regions/cortical.step": b"ISO-10303-21; cortical", "regions/cancellous.stp": b"ISO-10303-21; cancellous",
         "regions/canal.stl": b"solid canal", "surfaces/periosteal.stl": b"solid periosteal",
         "notes/readme.txt": b"where this bone came from"}
BONE = {"model": "elastic", "E": 16800, "nu": 0.3}
FOAM = {"model": "elastic", "E": 155.0, "nu": 0.3}


def good(side: str = "right", whole: bool = True, anteversion: float = 12.0, pose=TILTED) -> dict:
    """一份合格的第 2 版骨模型的清单（清单共用的那几项除外）。whole 是完整的股骨，照后髁连线定坐标系；
    不然是只有近端一段的，照颈轴加前倾角定。"""
    marks, truth = femur(side, anteversion, condyles=whole, pose=pose)
    frame = {"file": "CAD 文件自己的坐标", "method": "shaft_condyles" if whole else "shaft_neck", **truth}
    if not whole:
        frame["anteversion_deg"] = anteversion
    return {
        "bone_id": "femur042", "side": side, "bone_type": "replica",
        "coverage": {"extent": "whole" if whole else "proximal", "proximal_mm": 74.0, "distal_mm": 425.0 if whole else 180.0},
        "source": {"how": "cad", "method": {"id": "R0007", "hash": "a" * 64}, "setting": {"id": "R0008", "hash": "b" * 64}},
        "units": dict(UNITS), "frame": frame,
        "regions": [
            {"name": "cortical", "role": "cortical", "geometry": {"kind": "solid", "format": "step", "file": "regions/cortical.step"},
             "volume_mm3": 271529.5, "material": dict(BONE)},
            {"name": "cancellous", "role": "cancellous", "geometry": {"kind": "solid", "format": "step", "file": "regions/cancellous.stp"},
             "volume_mm3": 128616.7, "material": dict(FOAM)},
            {"name": "canal", "role": "canal", "geometry": {"kind": "solid", "format": "stl", "file": "regions/canal.stl"},
             "volume_mm3": 30500.0, "material": None}],
        "surfaces": {"periosteal": {"region": "cortical", "file": "surfaces/periosteal.stl"}},
        "landmarks": landmarks(marks),
        "history": [{"step": "import", "what": "从 CAD 读进两个实体"}, {"step": "edit", "what": "填了松质芯里的导针孔"}],
        "checks": [{"name": "volume_cortical", "value": 271.5, "limit": "和骨源相差不到 0.5%", "passed": True},
                   {"name": "stem_smoke", "value": "ok", "limit": "柄空间包能在这根骨上模板化", "passed": True}],
    }


def write(root, extra: dict, kind: str = "bone_model", files: dict | None = None, version: int | None = None):
    """把清单和文件写成一个文件夹。version 给 1 就明写第 1 版；不给就是现在的版本。"""
    files = FILES if files is None else files
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(content)
    manifest = make_manifest(kind, list(files), **extra)
    write_manifest(root, manifest if version is None else {**manifest, "format": version})
    return root


def manifest(extra: dict, kind: str = "bone_model", files: dict | None = None) -> dict:
    """一份完整的第 2 版清单（带清单共用的那几项），不落盘。"""
    return make_manifest(kind, list(FILES if files is None else files), **extra)


def changed(whole: dict, *path, value=...):
    """把 whole 里沿 path 的那一项换成 value，返回改过的一份；value 是 ... 就把它去掉。"""
    made = copy.deepcopy(whole)
    inner = made
    for name in path[:-1]:
        inner = inner[name]
    if value is ...:
        del inner[path[-1]]
    else:
        inner[path[-1]] = value
    return made


# ---------------------------------------------------------------- 第 1 版的清单（盘上还有的写法）

FILES_V1 = {"solids/cortical.step": b"ISO-10303-21; cortical", "solids/cancellous.step": b"ISO-10303-21; cancellous",
            "notes/readme.txt": b"where this bone came from"}
V1 = {
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


def write_v1(root, kind: str = "bone_model", files: dict | None = None, **change):
    """写一个第 1 版骨模型的文件夹：清单明写第 1 版。change 里的项盖掉清单里的同名项；值是 ... 就把那一项去掉。"""
    extra = {**copy.deepcopy(V1), **change}
    return write(root, {key: value for key, value in extra.items() if value is not ...}, kind,
                 FILES_V1 if files is None else files, version=1)


def listed_v1(**change) -> dict:
    """一份第 1 版的清单（带清单共用的那几项，明写第 1 版），不落盘。change 的用法和 write_v1 一样。"""
    extra = {**copy.deepcopy(V1), **change}
    return {**make_manifest("bone_model", list(FILES_V1), **{key: value for key, value in extra.items() if value is not ...}),
            "format": 1}


def changed_v1(key, *path, value=...) -> dict:
    """把 V1[key] 里沿 path 的那一项换成 value；value 是 ... 就把它去掉。"""
    return {key: changed({key: V1[key]}, key, *path, value=value)[key]}


# ---------------------------------------------------------------- 3406 的数

# Sawbones 3406 右股骨。原项目自己找出的标志点，在那两个 STEP 文件的坐标里（原项目 v2/out/femur_3406_summary.json，
# 2026-11-19 抄的）：头心、颈最细截面的形心、干轴上的两个点（小转子那一层、拟合截面的形心）、内外两个后髁最靠后的点。
# 原项目没记小转子顶点的位置，只记了它那一层（就是 shaft_proximal 那一点的高度）：这里放在那一层上、离干轴 12 mm 的地方，
# 算坐标系只用到它的高度。
S3406 = {
    "head_center": [50.66093682772986, 1.6714987757428237, 109.12888423325442],
    "neck_center": [29.405238991659115, 0.21473629592986584, 99.80048756223515],
    "shaft_proximal": [-0.6691458537212829, -0.7529260937565749, 60.002206759885226],
    "shaft_distal": [3.093165499546842, -4.059642778407382, -107.47904985831791],
    "condyle_medial": [44.90784707086716, 41.74227118333131, -327.97424290264803],
    "condyle_lateral": [-17.56448842120268, 42.25309568429364, -324.9331040360414],
}
# 原项目照干轴加后髁连线定的模型坐标里，同一根骨的几个数（同一份文件）
S3406_ORIGIN = [-0.6691458537212829, -0.7529260937565749, 60.002206759885226]
S3406_Z = [-0.022454034278569453, 0.01973497746861657, 0.9995530736328763]
_OUT = (0.0, S3406_Z[2], -S3406_Z[1])           # 干轴 × (1, 0, 0)：垂直干轴的一个方向
S3406["lesser_trochanter"] = [o + 12.0 * part / math.hypot(*_OUT) for o, part in zip(S3406_ORIGIN, _OUT)]
S3406_HEAD_IN_FRAME = [52.40922027954656, 1.8328374982159503, 47.999999999999986]
S3406_NECK_IN_FRAME = [0.9222817648474724, 0.06136877046293883, 0.3816152777886375]
S3406_ANTEVERSION = -3.806858193056245
S3406_NECK_SHAFT = 112.43377262606323
