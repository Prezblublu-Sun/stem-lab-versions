"""材料的给法：柄的模型和骨模型共用的一份写法（《骨模型的写法》第三节，《设定的声明和包的清单》第六节“柄的模型”）。

每种材料模型的参数照 Abaqus 的写法给。单位照契约的单位表：模量、应力、C10、C01 用 MPa，D1 用 1/MPa，密度用 g/cm3，
长度用 mm。用材料的有限元包在清单里声明它支持哪几种（MODELS 里的名字），不支持的，启动前就拒。

一种给法是一个 JSON 对象，model 说是哪一种：
    elastic                各向同性的线弹性（*ELASTIC）：E、nu；density 可以有
    engineering_constants  正交各向异性（*ELASTIC, TYPE=ENGINEERING CONSTANTS）：E1 E2 E3 nu12 nu13 nu23 G12 G13 G23，
                           axes 是材料的三个主方向 [[…], […], […]]，在这个模型的坐标系里，两两垂直、长度为一；density 可以有
    neo_hooke              超弹性（*HYPERELASTIC, NEO HOOKE）：C10、D1。D1 是 0 就是不可压缩。
                           文献里写成剪切模量 G、体积模量 K 的，导入时用 neo_hooke_from 换算：C10 = G/2，D1 = 2/K
    mooney_rivlin          超弹性（*HYPERELASTIC, MOONEY-RIVLIN）：C10、C01、D1
    piecewise              沿一根轴分段，每段一种均匀的给法（上面四种之一）：along 是轴的名字，得是这个模型里有的轴；
                           segments 是 [{"from": mm, "to": mm, "material": …}]，从小到大首尾相接
    field                  按一个场给：source 是 {"prediction": 一份预测的编号, "field": 场的名字}，场的值是密度；
                           relation 是密度到模量的分段表，nu 是泊松比。用了哪一份预测，记进 made_by（改格式的 D 批）
    density                按 CT 的骨密度连续给（骨用，1.0 只留位置）：ct 是那一份 CT 的编号，
                           calibration 是 HU 到密度的直线 {"slope", "intercept", "phantom"}，relation 是密度到模量的分段表，
                           nu 是泊松比，bounds 是模量的上下限 {"min", "max"}，bins 是分成几档，mapping 是怎么映射到单元上
密度到模量的分段表：[{"from": 密度, "to": 密度, "a": 系数, "b": 指数}]，E = a·ρ^b，各段从小到大首尾相接。
文献里常用的 Keyak 式就是分三段的。

契约只核写法和数值合不合理（模量为正、泊松比在 0 到 0.5 之间、超弹性的参数合法、分段的表不重叠）。
数值对不对、有限元包能不能算，由声明支持它的那个包负责。
"""
from __future__ import annotations

import math

from stemlab.contract.layout import is_column, is_item_id, is_label

UNIFORM = ("elastic", "engineering_constants", "neo_hooke", "mooney_rivlin")
MODELS = UNIFORM + ("piecewise", "field", "density")

_KEYS = {
    "elastic": ({"E", "nu"}, {"density"}),
    "engineering_constants": ({"E1", "E2", "E3", "nu12", "nu13", "nu23", "G12", "G13", "G23", "axes"}, {"density"}),
    "neo_hooke": ({"C10", "D1"}, set()),
    "mooney_rivlin": ({"C10", "C01", "D1"}, set()),
    "piecewise": ({"along", "segments"}, set()),
    "field": ({"source", "relation", "nu"}, set()),
    "density": ({"ct", "calibration", "relation", "nu", "bounds", "bins", "mapping"}, set()),
}


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _positive(value) -> bool:
    return _number(value) and value > 0


def _poisson(value) -> bool:
    return _number(value) and 0 <= value < 0.5


def neo_hooke_from(shear_modulus: float, bulk_modulus: float) -> dict:
    """文献里写成剪切模量 G、体积模量 K（都是 MPa）的 neo-Hookean，换成 Abaqus 的 C10、D1。"""
    return {"model": "neo_hooke", "C10": shear_modulus / 2.0, "D1": 2.0 / bulk_modulus}


def unit_axes(axes) -> bool:
    """三个方向两两垂直、长度为一。"""
    if not isinstance(axes, list) or len(axes) != 3 or not all(
            isinstance(axis, list) and len(axis) == 3 and all(map(_number, axis)) for axis in axes):
        return False
    dot = [[sum(a * b for a, b in zip(one, other)) for other in axes] for one in axes]
    return all(abs(dot[i][j] - (1.0 if i == j else 0.0)) < 1e-6 for i in range(3) for j in range(3))


def check_material(spec, axes=None, where: str = "材料") -> list[str]:
    """核一种给法。axes 是这个模型里有的轴的名字（分段的要用）；不给就不核 along 指的轴在不在。返回哪里不符。"""
    if not isinstance(spec, dict) or spec.get("model") not in MODELS:
        return [f"{where}：model 要是 {list(MODELS)} 之一，这里是 {spec.get('model') if isinstance(spec, dict) else spec!r}"]
    model = spec["model"]
    must, may = _KEYS[model]
    problems = [f"{where}（{model}）：缺 {key}" for key in sorted(must - set(spec))]
    problems += [f"{where}（{model}）：多了 {key}" for key in sorted(set(spec) - must - may - {"model"})]
    if problems:
        return problems
    said = f"{where}（{model}）"
    if "density" in spec and not _positive(spec["density"]):
        problems.append(f"{said}：density 要是正数（g/cm3）")
    if model == "elastic":
        if not _positive(spec["E"]):
            problems.append(f"{said}：E 要是正数（MPa）")
        if not _poisson(spec["nu"]):
            problems.append(f"{said}：nu 要在 0 到 0.5 之间（不含 0.5）")
    elif model == "engineering_constants":
        problems += [f"{said}：{key} 要是正数（MPa）" for key in ("E1", "E2", "E3", "G12", "G13", "G23") if not _positive(spec[key])]
        problems += [f"{said}：{key} 要是一个数" for key in ("nu12", "nu13", "nu23") if not _number(spec[key])]
        if not unit_axes(spec["axes"]):
            problems.append(f"{said}：axes 要是三个两两垂直、长度为一的方向")
    elif model == "neo_hooke":
        if not _positive(spec["C10"]):
            problems.append(f"{said}：C10 要是正数（MPa）")
        if not (_number(spec["D1"]) and spec["D1"] >= 0):
            problems.append(f"{said}：D1 不能是负数（1/MPa；0 是不可压缩）")
    elif model == "mooney_rivlin":
        if not (_number(spec["C10"]) and _number(spec["C01"]) and spec["C10"] + spec["C01"] > 0):
            problems.append(f"{said}：C10、C01 要是数，加起来为正（MPa）")
        if not (_number(spec["D1"]) and spec["D1"] >= 0):
            problems.append(f"{said}：D1 不能是负数（1/MPa；0 是不可压缩）")
    elif model == "piecewise":
        problems += _segments(spec, axes, said)
    elif model == "field":
        source = spec["source"]
        if not (isinstance(source, dict) and set(source) == {"prediction", "field"}
                and is_item_id(source["prediction"]) and is_column(source["field"])):
            problems.append(f'{said}：source 要写成 {{"prediction": 一份预测的编号, "field": 场的名字}}')
        problems += _relation(spec["relation"], said)
        if not _poisson(spec["nu"]):
            problems.append(f"{said}：nu 要在 0 到 0.5 之间（不含 0.5）")
    else:
        problems += _density(spec, said)
    return problems


def _segments(spec: dict, axes, said: str) -> list[str]:
    problems = []
    if not is_label(spec["along"]):
        problems.append(f"{said}：along 要是一根轴的名字")
    elif axes is not None and spec["along"] not in axes:
        problems.append(f"{said}：沿的轴 {spec['along']!r} 这个模型里没有")
    segments = spec["segments"]
    if not isinstance(segments, list) or not segments or not all(isinstance(s, dict) for s in segments):
        return problems + [f"{said}：segments 要是段的列表，每段一个 JSON 对象"]
    for number, segment in enumerate(segments, start=1):
        if set(segment) != {"from", "to", "material"}:
            problems.append(f'{said}：第 {number} 段要写且只写 "from"、"to"、"material"')
            continue
        if not (_number(segment["from"]) and _number(segment["to"]) and segment["from"] < segment["to"]):
            problems.append(f"{said}：第 {number} 段的 from、to 要是数，from 小于 to（mm）")
        elif number > 1 and isinstance(segments[number - 2], dict) and segments[number - 2].get("to") != segment["from"]:
            problems.append(f"{said}：第 {number} 段要接着上一段（from 等于上一段的 to）")
        material = segment["material"]
        if not isinstance(material, dict) or material.get("model") not in UNIFORM:
            problems.append(f"{said}：第 {number} 段的材料要是均匀的给法：{list(UNIFORM)}")
        else:
            problems += check_material(material, axes, f"{said} 第 {number} 段")
    return problems


def _relation(table, said: str) -> list[str]:
    """密度到模量的分段表：E = a·ρ^b，各段从小到大首尾相接。"""
    if not isinstance(table, list) or not table or not all(isinstance(row, dict) for row in table):
        return [f"{said}：relation 要是密度到模量的分段表，至少一段"]
    problems = []
    for number, row in enumerate(table, start=1):
        if set(row) != {"from", "to", "a", "b"}:
            problems.append(f'{said}：relation 第 {number} 段要写且只写 "from"、"to"、"a"、"b"')
            continue
        if not (_number(row["from"]) and _number(row["to"]) and 0 <= row["from"] < row["to"]):
            problems.append(f"{said}：relation 第 {number} 段的密度范围要从小到大，不是负的（g/cm3）")
        elif number > 1 and isinstance(table[number - 2], dict) and table[number - 2].get("to") != row["from"]:
            problems.append(f"{said}：relation 第 {number} 段要接着上一段（from 等于上一段的 to）")
        if not (_positive(row["a"]) and _number(row["b"])):
            problems.append(f"{said}：relation 第 {number} 段的 a 要是正数，b 要是一个数")
    return problems


def _density(spec: dict, said: str) -> list[str]:
    problems = []
    if not is_item_id(spec["ct"]):
        problems.append(f"{said}：ct 要是那一份 CT 的登记编号")
    calibration = spec["calibration"]
    if not (isinstance(calibration, dict) and set(calibration) == {"slope", "intercept", "phantom"}
            and _number(calibration["slope"]) and calibration["slope"] != 0 and _number(calibration["intercept"])
            and isinstance(calibration["phantom"], str) and calibration["phantom"].strip()):
        problems.append(f'{said}：calibration 要写成 {{"slope": 不是 0 的数, "intercept": 数, "phantom": 用的标定体模}}')
    problems += _relation(spec["relation"], said)
    if not _poisson(spec["nu"]):
        problems.append(f"{said}：nu 要在 0 到 0.5 之间（不含 0.5）")
    bounds = spec["bounds"]
    if not (isinstance(bounds, dict) and set(bounds) == {"min", "max"} and _positive(bounds["min"])
            and _number(bounds["max"]) and bounds["min"] < bounds["max"]):
        problems.append(f'{said}：bounds 要写成 {{"min", "max"}}，min 是正数、小于 max（MPa）')
    if isinstance(spec["bins"], bool) or not isinstance(spec["bins"], int) or spec["bins"] < 1:
        problems.append(f"{said}：bins 要是正整数")
    if not (isinstance(spec["mapping"], str) and spec["mapping"].strip()):
        problems.append(f"{said}：mapping 要写怎么映射到单元上，比如按单元取平均")
    return problems
