"""柄的模型：柄空间包交给有限元包和推导量定义包的东西（《设定的声明和包的清单》第六节“柄的模型”）。

有了这一份固定的格式，任何一个柄空间包都能配任何一个有限元包用，不用为某一对包写专门的代码。
它不进账：只在一次作业里，由柄空间包交出，给有限元包和推导量定义包用。
它是怎么来的（哪个柄空间包、哪个设计、哪份放置设定），记在数据的 made_by 里（改格式的 D 批）。
无植入物就不交柄的模型：作业里写 null，有限元设定里就没有柄的那几组。

一个文件夹：清单 stem_model.json，加若干几何文件。清单：
    format       这种格式的版本，见 versions.FORMATS["stem_model"]
    files        文件夹里除清单之外的全部文件：相对路径、正斜杠
    units        {"length": "mm"}：几何、点、轴都用 mm
    dimension    3d，或 2d（平面模型：区域的几何都是 area，厚度由有限元设定给）
    design       这个点的设计项，原样抄下来。目录式的柄空间就是 {"model": 型号}
    regions      区域：[{"name", "role", "geometry": {"kind", "file"}, "material": 材料的给法}]
                   role 见 ROLES。geometry.kind：solid 是封闭的实体（STEP 或 STL），area 是二维的区域，
                   mesh 是现成的体网格（有限元包不再划网格）。file 是文件夹里的文件。材料的写法见 material.py
    faces        命名的面组：{名字: {"region": 区域名, "file": 表面片文件}}。表面片落在那个区域的边界上：
                 有限元设定里的接触、绑定、过盈都用名字引用它们，比如领的承压面、涂层区
    features     特征点：{名字: [x, y, z]}，在柄的模型自己的坐标系里。比如锥头中心（关节力打在哪）、柄尖、肩
    axes         轴：{名字: {"point": [x, y, z], "direction": [x, y, z]}}，direction 长度为一。比如柄轴。
                 推导量定义也用它们，比如照柄轴和柄尖划 Gruen 区
    placement    放在骨上的什么位置。都在骨模型文件自己的坐标里：骨模型的几何文件、标志点用的那一套，
                 不是骨的解剖坐标系（骨模型的 frame）；骨模型的几何不换系，柄换过去就能和骨直接做布尔运算（2026-11-19 定的）：
                   frame      柄的坐标系在骨模型文件的坐标里：{"origin": [x, y, z], "x": […], "y": […], "z": […]}，
                              三个轴两两垂直、长度为一、右手系
                   cut        截骨面：{"point": [x, y, z], "normal": [x, y, z]}，在骨模型文件的坐标里；没有截骨就是 null
                   removed    去掉的骨：文件夹里的一个实体文件，或者 null
                   landmarks  用到了骨模型的哪些标志点：[名字, …]
    templating   模板化算出来的量：{名字: 数}，比如入口偏移、贴合比例、去骨量

名字（区域、面组、特征点、轴）都用 ASCII 的字母、数字和 . _ -，各自不重名。有限元设定、推导量设定里的名字引用
（{"ref": "stem.feature.taper_center"}）照 names() 给出的名字核（设定的声明，第 8 条）。

契约只核清单和清单列的文件在不在。几何里是什么、面组是不是真落在区域的边界上，由交出它的柄空间包负责。
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from stemlab.contract.formats.manifest import check_names
from stemlab.contract.formats.material import check_material
from stemlab.contract.hashing import list_tree
from stemlab.contract.layout import is_column, is_label
from stemlab.contract.versions import FORMATS

MANIFEST = "stem_model.json"
ROLES = ("body", "porous", "coating", "collar", "neck", "taper", "other")
GEOMETRY = ("solid", "area", "mesh")
KEYS = ("format", "files", "units", "dimension", "design", "regions", "faces", "features", "axes", "placement", "templating")


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _point(value) -> bool:
    return isinstance(value, list) and len(value) == 3 and all(map(_number, value))


def _unit(value) -> bool:
    return _point(value) and abs(math.sqrt(sum(part * part for part in value)) - 1.0) < 1e-6


def _frame(frame) -> bool:
    """原点加三个轴：两两垂直、长度为一、右手系。"""
    if not (isinstance(frame, dict) and set(frame) == {"origin", "x", "y", "z"} and _point(frame["origin"])
            and all(_unit(frame[axis]) for axis in "xyz")):
        return False
    x, y, z = frame["x"], frame["y"], frame["z"]
    dot = lambda a, b: sum(p * q for p, q in zip(a, b))  # noqa: E731
    cross = [x[1] * y[2] - x[2] * y[1], x[2] * y[0] - x[0] * y[2], x[0] * y[1] - x[1] * y[0]]
    return abs(dot(x, y)) < 1e-6 and abs(dot(x, z)) < 1e-6 and abs(dot(y, z)) < 1e-6 and dot(cross, z) > 0.999999


def names(model: dict) -> dict:
    """柄的模型里能被名字引用的东西：{"stem.region": {…}, "stem.faces": {…}, "stem.feature": {…}, "stem.axis": {…}}。"""
    return {"stem.region": {region["name"] for region in model["regions"]}, "stem.faces": set(model["faces"]),
            "stem.feature": set(model["features"]), "stem.axis": set(model["axes"])}


def read(folder) -> dict:
    """读柄的模型的清单。没有、或者不是一个 JSON 对象，报 ValueError。"""
    path = Path(folder) / MANIFEST
    try:
        model = json.loads(path.read_bytes().decode("utf-8"))
    except FileNotFoundError:
        raise ValueError(f"文件夹里没有 {MANIFEST}：{folder}") from None
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{MANIFEST} 读不出来：{error}") from None
    if not isinstance(model, dict):
        raise ValueError(f"{MANIFEST} 必须是一个 JSON 对象")
    return model


def check(folder) -> list[str]:
    """核一份柄的模型：清单，和清单列的文件都在、不多不少。返回哪里不符；空列表就是对的。"""
    try:
        model = read(folder)
    except ValueError as error:
        return [str(error)]
    problems = check_model(model)
    if problems:
        return problems
    try:
        present = set(list_tree(folder)) - {MANIFEST}
    except (ValueError, OSError) as error:
        return [str(error)]
    listed = set(model["files"])
    problems += [f"清单列了但文件夹里没有：{rel}" for rel in sorted(listed - present)]
    problems += [f"文件夹里有但清单没列：{rel}" for rel in sorted(present - listed)]
    return problems


def check_model(model: dict) -> list[str]:
    """只核清单。返回哪里不符，说出是哪一段、哪一项。"""
    problems = [f"柄的模型缺 {key}" for key in KEYS if key not in model]
    problems += [f"柄的模型多了 {key}" for key in model if key not in KEYS]
    if problems:
        return problems
    if model["format"] != FORMATS["stem_model"]:
        problems.append(f"柄的模型的格式版本是 {model['format']!r}，现在是第 {FORMATS['stem_model']} 版")
    files = model["files"]
    if not isinstance(files, list) or MANIFEST in files:
        return problems + [f"files 要是文件的列表，不列 {MANIFEST} 自己"]
    problems += check_names(files)
    if model["units"] != {"length": "mm"}:
        problems.append('units 要写成 {"length": "mm"}')
    if model["dimension"] not in ("3d", "2d"):
        problems.append(f"dimension 要是 3d 或 2d，这里是 {model['dimension']!r}")
    design = model["design"]
    if not isinstance(design, dict) or not all(map(is_column, design)):
        problems.append("design 要是这个点的设计项：{名字: 取值}")
    problems += _named_problems(model)
    if problems:
        return problems
    axes = set(model["axes"])
    for region in model["regions"]:
        problems += _region_problems(region, files, model["dimension"], axes)
    regions = {region["name"] for region in model["regions"] if isinstance(region, dict)}
    for name, face in model["faces"].items():
        if not (isinstance(face, dict) and set(face) == {"region", "file"}):
            problems.append(f'面组 {name!r}：要写成 {{"region": 区域名, "file": 表面片文件}}')
        elif face["region"] not in regions:
            problems.append(f"面组 {name!r}：区域 {face['region']!r} 不在 regions 里")
        elif face["file"] not in files:
            problems.append(f"面组 {name!r}：文件 {face['file']!r} 不在 files 里")
    problems += [f"特征点 {name!r}：要是 [x, y, z] 三个数" for name, point in model["features"].items() if not _point(point)]
    for name, axis in model["axes"].items():
        if not (isinstance(axis, dict) and set(axis) == {"point", "direction"} and _point(axis["point"]) and _unit(axis["direction"])):
            problems.append(f'轴 {name!r}：要写成 {{"point": [x, y, z], "direction": 长度为一的 [x, y, z]}}')
    problems += _placement_problems(model["placement"], files)
    templating = model["templating"]
    if not isinstance(templating, dict) or not all(is_column(k) and _number(v) for k, v in templating.items()):
        problems.append("templating 要是 {名字: 数}")
    return problems


def _named_problems(model: dict) -> list[str]:
    """区域、面组、特征点、轴各自的名字：ASCII 的字母、数字和 . _ -，不重名。"""
    problems = []
    regions = model["regions"]
    if not isinstance(regions, list) or not regions or not all(isinstance(region, dict) for region in regions):
        return ["regions 要是区域的列表，至少一个，每个一个 JSON 对象"]
    region_names = [region.get("name") for region in regions]
    if not all(map(is_label, region_names)) or len(set(region_names)) != len(region_names):
        problems.append(f"区域的名字要用 ASCII 的字母、数字和 . _ -，不重名：{region_names}")
    for part in ("faces", "features", "axes"):
        if not isinstance(model[part], dict) or not all(map(is_label, model[part])):
            problems.append(f"{part} 要是 {{名字: …}}，名字用 ASCII 的字母、数字和 . _ -")
    return problems


def _region_problems(region: dict, files: list, dimension: str, axes: set) -> list[str]:
    said = f"区域 {region.get('name')!r}"
    if set(region) != {"name", "role", "geometry", "material"}:
        return [f'{said}：要写且只写 "name"、"role"、"geometry"、"material"']
    problems = []
    if region["role"] not in ROLES:
        problems.append(f"{said}：角色要是 {list(ROLES)} 之一，这里是 {region['role']!r}")
    geometry = region["geometry"]
    if not (isinstance(geometry, dict) and set(geometry) == {"kind", "file"} and geometry["kind"] in GEOMETRY):
        problems.append(f'{said}：geometry 要写成 {{"kind": {list(GEOMETRY)} 之一, "file": 文件}}')
    else:
        if geometry["file"] not in files:
            problems.append(f"{said}：几何文件 {geometry['file']!r} 不在 files 里")
        if (dimension == "2d") != (geometry["kind"] == "area"):
            problems.append(f"{said}：平面模型的区域都是 area，三维模型的不能是 area")
    return problems + check_material(region["material"], axes, f"{said} 的材料")


def _placement_problems(placement, files: list) -> list[str]:
    if not (isinstance(placement, dict) and set(placement) == {"frame", "cut", "removed", "landmarks"}):
        return ['placement 要写且只写 "frame"、"cut"、"removed"、"landmarks"']
    problems = []
    if not _frame(placement["frame"]):
        problems.append("placement.frame 要是原点加三个轴，两两垂直、长度为一、右手系")
    cut = placement["cut"]
    if cut is not None and not (isinstance(cut, dict) and set(cut) == {"point", "normal"} and _point(cut["point"]) and _unit(cut["normal"])):
        problems.append('placement.cut 要写成 {"point": [x, y, z], "normal": 长度为一的 [x, y, z]}，没有截骨就是 null')
    if placement["removed"] is not None and placement["removed"] not in files:
        problems.append(f"placement.removed 要是 files 里的一个文件，或者 null：{placement['removed']!r}")
    landmarks = placement["landmarks"]
    if not isinstance(landmarks, list) or not all(map(is_label, landmarks)):
        problems.append("placement.landmarks 要是骨模型标志点的名字列表")
    return problems
