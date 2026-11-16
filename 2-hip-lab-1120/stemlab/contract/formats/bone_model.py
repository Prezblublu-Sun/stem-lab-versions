"""骨模型和候选骨模型。两种都是一个文件夹：清单、两个实体的文件，别的文件随意。清单另带：

    bone_id     骨标识。从骨源继承
    side        哪一侧：left 或 right
    units       单位，只有一套：{"length": "mm", "force": "N", "stress": "MPa"}
    frame       坐标系的定义，文字：{"origin", "x", "y", "z"}。实体和标志点都在这个坐标系里，右手系
    solids      两个实体：{"cortical": {"file": ...}, "cancellous": {"file": ...}}，file 是文件夹里的文件
    landmarks   标志点：名字 -> {"xyz": [x, y, z], "definition": 这个点是怎么定的}。必有的五个见 LANDMARKS
    materials   两个实体各自的材料：{"model", "E_MPa", "nu"}，另外的项随意
    history     重建记录：一步一条 {"step", "what"}。用过人工修改的，改了哪里记在这里
    checks      检查结果：一项一条 {"name", "value", "limit", "passed"}

必有的五个标志点：
    head_center         股骨头的球心
    neck_center         股骨颈最细截面的质心
    shaft_proximal      骨干轴上靠近端的一点
    shaft_distal        骨干轴上靠远端的一点
    lesser_trochanter   小转子的顶点
颈轴和干轴不另存，由它们算：颈轴从 neck_center 指向 head_center，干轴从 shaft_distal 指向 shaft_proximal。
同一根骨的角度只有在同一种定义下才能比，所以定义跟着每个点一起存。

候选骨模型（bone_draft）是等人工检查的重建结果，检查可以还没做、可以没过。
骨模型（bone_model）里的每一项检查都必须是过了的：没过检查门的不交骨模型。

契约只核清单。实体文件里是什么、标志点找得准不准，由写它的那个冻结文件和检查门负责。
"""
from __future__ import annotations

import math

from stemlab.contract.layout import is_key

SOLIDS = ("cortical", "cancellous")
LANDMARKS = ("head_center", "neck_center", "shaft_proximal", "shaft_distal", "lesser_trochanter")
UNITS = {"length": "mm", "force": "N", "stress": "MPa"}
SIDES = ("left", "right")
FRAME = ("origin", "x", "y", "z")
REQUIRED = ("bone_id", "side", "units", "frame", "solids", "landmarks", "materials", "history", "checks")


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _unit(start, end) -> tuple | None:
    """从 start 指向 end 的单位向量。两个点重合就是 None。"""
    delta = [b - a for a, b in zip(start, end)]
    length = math.sqrt(sum(part * part for part in delta))
    return tuple(part / length for part in delta) if length > 1e-9 else None


def axes(landmarks: dict) -> tuple:
    """（颈轴，干轴）两个单位向量：颈轴从颈中心指向头心，干轴从远端指向近端。定不出来的那一根是 None。"""
    return (_unit(landmarks["neck_center"]["xyz"], landmarks["head_center"]["xyz"]),
            _unit(landmarks["shaft_distal"]["xyz"], landmarks["shaft_proximal"]["xyz"]))


def neck_shaft_angle(landmarks: dict) -> float:
    """颈干角，度：180° 减去颈轴和干轴的夹角。"""
    neck, shaft = axes(landmarks)
    cosine = max(-1.0, min(1.0, sum(a * b for a, b in zip(neck, shaft))))
    return 180.0 - math.degrees(math.acos(cosine))


def names(manifest: dict) -> dict:
    """骨模型里能被名字引用的东西（设定的声明，第 8 条）：{"bone.region": {…}, "bone.landmark": {…}, …}。

    第 1 版只有两个实体和标志点：区域就是这两个实体（cortical、cancellous），没有块、关节和单独给的表面。
    """
    solids, landmarks = manifest.get("solids"), manifest.get("landmarks")
    return {"bone.block": set(), "bone.joint": set(), "bone.surface": set(),
            "bone.region": set(solids) if isinstance(solids, dict) else set(),
            "bone.landmark": set(landmarks) if isinstance(landmarks, dict) else set()}


def check(kind: str, manifest: dict, folder) -> list[str]:
    """check_format 叫的入口。清单共用的那几项、清单列的文件在不在，已经核过了。"""
    problems = [f"骨模型的清单缺 {key}" for key in REQUIRED if key not in manifest]
    if problems:
        return problems
    if manifest["side"] not in SIDES:
        problems.append(f"side 只能是 {list(SIDES)}：{manifest['side']!r}")
    if manifest["units"] != UNITS:
        problems.append(f"单位只有这一套：{UNITS}")
    frame = manifest["frame"]
    if not isinstance(frame, dict) or set(frame) != set(FRAME) or not all(_text(text) for text in frame.values()):
        problems.append(f"坐标系要写 {list(FRAME)} 四项的定义，每项都不能空")
    problems += _check_solids(manifest["solids"], manifest["files"])
    problems += _check_landmarks(manifest["landmarks"])
    problems += _check_materials(manifest["materials"])
    history = manifest["history"]
    if (not isinstance(history, list) or not history
            or not all(isinstance(step, dict) and _text(step.get("step")) and _text(step.get("what")) for step in history)):
        problems.append("重建记录（history）至少要有一步，每一步写 step 和 what")
    problems += _check_checks(kind, manifest["checks"])
    return problems


def _check_solids(solids, files) -> list[str]:
    if not isinstance(solids, dict) or set(solids) != set(SOLIDS):
        given = list(solids) if isinstance(solids, dict) else solids
        return [f"实体要有且只有 {list(SOLIDS)} 两个，这里是 {given!r}"]
    problems, used = [], []
    for name in SOLIDS:
        file = solids[name].get("file") if isinstance(solids[name], dict) else None
        if file not in files:
            problems.append(f"实体 {name} 的文件清单里没有：{file!r}")
        used.append(file)
    if not problems and used[0] == used[1]:
        problems.append("两个实体不能是同一个文件")
    return problems


def _check_landmarks(landmarks) -> list[str]:
    if not isinstance(landmarks, dict):
        return ["标志点（landmarks）必须是一个 JSON 对象"]
    missing = [name for name in LANDMARKS if name not in landmarks]
    problems = [f"标志点缺 {missing}"] if missing else []
    for name, point in landmarks.items():
        if not is_key(name):
            problems.append(f"标志点的名字要用小写字母、数字和下划线：{name!r}")
        elif (not isinstance(point, dict) or set(point) != {"xyz", "definition"} or not _text(point["definition"])
              or not isinstance(point["xyz"], list) or len(point["xyz"]) != 3 or not all(map(_is_number, point["xyz"]))):
            problems.append(f"标志点 {name} 要写 xyz（三个数）和 definition（它是怎么定的）")
    if not problems:
        neck, shaft = axes(landmarks)
        if neck is None:
            problems.append("颈中心和头心重合，定不出颈轴")
        if shaft is None:
            problems.append("骨干上的两个点重合，定不出干轴")
    return problems


def _check_materials(materials) -> list[str]:
    if not isinstance(materials, dict) or set(materials) != set(SOLIDS):
        given = list(materials) if isinstance(materials, dict) else materials
        return [f"材料要有且只有 {list(SOLIDS)} 两种，这里是 {given!r}"]
    problems = []
    for name in SOLIDS:
        material = materials[name]
        if not isinstance(material, dict):
            problems.append(f"{name} 的材料必须是一个 JSON 对象")
            continue
        if not _text(material.get("model")):
            problems.append(f"{name} 的材料没写 model（是哪种材料模型）")
        if not _is_number(material.get("E_MPa")) or material["E_MPa"] <= 0:
            problems.append(f"{name} 的 E_MPa 必须是正数：{material.get('E_MPa')!r}")
        if not _is_number(material.get("nu")) or not 0 <= material["nu"] < 0.5:
            problems.append(f"{name} 的 nu 要在 0 和 0.5 之间：{material.get('nu')!r}")
    return problems


def _check_checks(kind: str, checks) -> list[str]:
    if not isinstance(checks, list):
        return ["检查结果（checks）必须是一个列表"]
    problems, names = [], []
    for one in checks:
        if (not isinstance(one, dict) or set(one) != {"name", "value", "limit", "passed"} or not is_key(one["name"])
                or one["passed"] not in (True, False, None)):
            problems.append('每一项检查结果要带且只带 "name"、"value"、"limit"、"passed"；passed 是 true、false，或者还没做的 null')
            continue
        names.append(one["name"])
        if kind == "bone_model" and one["passed"] is not True:
            problems.append(f"检查 {one['name']} 没过或者还没做：骨模型里的每一项检查都必须是过了的")
    if len(set(names)) != len(names):
        problems.append("检查结果的名字有重复的")
    if kind == "bone_model" and not checks:
        problems.append("骨模型至少要有一项检查结果：没过检查门的不交骨模型")
    return problems
