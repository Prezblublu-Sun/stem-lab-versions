"""骨模型和候选骨模型（第 2 版，2026-11-19）。两种都是一个文件夹：清单、各个区域的几何文件，别的文件随意。

这一版只做一块骨、三维、封闭的实体。壳、平面模型、现成的体网格、几块骨的关节，等真要用时再升一版。清单另带：

    bone_id     骨标识。从骨源继承
    side        哪一侧：left 或 right
    bone_type   骨的种类：real 真骨；replica 实物的模型骨（比如 Sawbones）；synthetic 合成的（算出来或画出来的形状，没有实物）
    coverage    覆盖范围：{"extent": whole（完整的股骨）或 proximal（只有近端一段）, "proximal_mm": …, "distal_mm": …}，
                后两项是几何从解剖坐标系的原点沿干轴往近端、往远端各到多远
    source      来源：{"how": ct、cad 或 stl, "method": {"id", "hash"}, "setting": {"id", "hash"}}：
                怎么来的，哪个重建方法包，照哪份重建设定（登记的编号和哈希）
    units       单位，只有一套：{"length": "mm", "force": "N", "stress": "MPa"}
    frame       解剖坐标系，见下面
    regions     区域，一个或多个：[{"name", "role", "geometry": {"kind": "solid", "format": step 或 stl, "file"}, "volume_mm3", "material"}]
                role 见 ROLES。几何是封闭的实体，file 是文件夹里的文件，后缀要和 format 对得上；两个区域不共用一个文件。
                material 是一种给法，写法见 material.py，骨收的几种见 MATERIALS；髓腔（canal）是空的，写 null
    surfaces    命名的表面：{名字: {"region": 落在哪个区域上, "file": 表面片文件}}。没有就写 {}
    landmarks   标志点：名字 -> {"xyz": [x, y, z], "definition": {"method": 找法的名字, "version": 版本, "params": {参数}}, "fit": {…}}
                definition 可以另带一句 "text"。fit 是拟合的好坏：{名字: 数或 true、false}，手给的点可以是 {}。
                必有的五个见 LANDMARKS；照后髁连线定坐标系的，另要 CONDYLES 那两个
    history     重建记录：一步一条 {"step", "what"}。用过人工修改的，改了哪里记在这里
    checks      检查结果：一项一条 {"name", "value", "limit", "passed"}
别的项（比如重建量出来的 measures）可以带，契约不核。区域、表面、标志点的名字都用小写字母、数字和下划线。

几何文件、标志点、表面都用文件自己的坐标，不换系。解剖坐标系（frame）记的是它在文件坐标里的原点和三个轴：

    {"file": 文件自己的坐标是怎么来的（一句话）, "method": shaft_condyles 或 shaft_neck, "anteversion_deg": 前倾角（照颈轴定的才写）,
     "origin": [x, y, z], "x": […], "y": […], "z": […]}

    三个轴  x 指向内侧，y 指向后方，z 沿干轴指向近端。两侧都是这个意思：右股骨上它们是右手系，左股骨上是左手系，几何不镜像。
            关节力写成（内侧、后方、近端）三个分量，合力 = 三个分量各乘上对应的轴，两侧同一个算式
    z       从 shaft_distal 指向 shaft_proximal
    原点    干轴上小转子那一层：lesser_trochanter 投到干轴上的那一点
    x       shaft_condyles（完整的股骨）：从 condyle_lateral 指向 condyle_medial 的连线，投到垂直干轴的面上
            shaft_neck（只有近端一段的）：颈轴（从 neck_center 指向 head_center）投到垂直干轴的面上，再绕干轴转过前倾角；
            转完以后，颈轴在这个坐标系里朝前偏的角度正好是前倾角
    前倾角  颈轴朝前偏为正，两侧同号。照后髁连线定的坐标系里量出的前倾角（anteversion），拿去照颈轴定，是同一个坐标系
从标志点算坐标系的算法只有这里的一份（frame）。骨模型里记的原点和三个轴，核的时候照标志点重算，对不上就拒。
哪种骨用哪种定法是定死的（METHOD_OF）：完整的股骨照后髁连线，只有近端一段的照颈轴加前倾角。

颈轴和干轴不另存，由标志点算（axes）。同一根骨的角度只有在同一种定义下才能比，所以定义跟着每个点一起存。

候选骨模型（bone_draft）是等人工检查的重建结果，检查可以还没做、可以没过。
骨模型（bone_model）里的每一项检查都必须是过了的：没过检查门的不交骨模型。

契约只核清单。实体封不封闭、体积对不对、标志点找得准不准，由写它的那个冻结文件和检查门负责。

第 1 版（盘上还有；重建现在写的也还是它）：恰好两个实体 solids {"cortical", "cancellous"}，各一种线弹性材料
materials {"model": "linear_elastic", "E_MPa", "nu"}，标志点是 {"xyz", "definition": 一句话}，frame 是四句话。
读的时候照 from_v1 读成第 2 版（versions.UPCASTS），盘上的不改：先照第 1 版原来的规矩核（check_v1），再读成
一块骨、两个区域、均匀材料。第 1 版没有的几样是“不知道”，写成 null：骨的种类、覆盖范围、来源、体积、标志点的找法和拟合的好坏、
前倾角。第 1 版没有后髁的标志点，也没记前倾角，所以只能照颈轴定坐标系，没法转回去。
null 只有读第 1 版的骨模型时才有：盘上就是第 2 版的，一样都不许不写。

用骨模型的一方要什么，写在它的包清单 inputs 的 bone 里（每一项都可以不写，不写就是不挑）：

    regions    {角色: [最少几个, 最多几个]}，最多写 null 是不限。没列的角色不收
    geometry   收哪种几何文件：["step"]、["step", "stl"]
    materials  会哪些材料模型：MATERIALS 里的名字
    landmarks  要哪些标志点：[名字, …]
    coverage   {"extent": [收哪几种], "distal_mm": 至少往远端到多远, "proximal_mm": 至少往近端到多远}，三项各自可以不写
    frame      {"methods": [收哪几种定法], "unknown_anteversion": true}：后一项可以不写；
               照颈轴定、前倾角不知道的（第 1 版读来的），说了收才收
    what       一句给人看的说明
要求自己写得对不对用 check_wanted 核；一份骨模型缺哪一样用 lacking 核。骨模型里不知道的东西，要求里要它就算缺。
"""
from __future__ import annotations

import math
from pathlib import PurePosixPath

from stemlab.contract.formats import material
from stemlab.contract.formats.manifest import read_manifest
from stemlab.contract.hashing import is_hash
from stemlab.contract.layout import is_item_id, is_key, is_label
from stemlab.contract.versions import FORMATS, CannotUpcast, upcast

LANDMARKS = ("head_center", "neck_center", "shaft_proximal", "shaft_distal", "lesser_trochanter")
CONDYLES = ("condyle_medial", "condyle_lateral")        # 内侧、外侧股骨髁最靠后的点
UNITS = {"length": "mm", "force": "N", "stress": "MPa"}
SIDES = ("left", "right")
FRAME = ("origin", "x", "y", "z")
BONE_TYPES = ("real", "replica", "synthetic")
EXTENTS = ("whole", "proximal")
HOWS = ("ct", "cad", "stl")
ROLES = {"cortical": "皮质", "cancellous": "松质", "canal": "髓腔", "cartilage": "软骨", "other": "其他"}
GEOMETRY_FILES = {"step": (".step", ".stp"), "stl": (".stl",)}      # 几何文件的格式，和它认的后缀
MATERIALS = material.UNIFORM + ("density",)             # 骨收的材料给法。分段的、按预测的场给的是柄用的
METHODS = ("shaft_condyles", "shaft_neck")
METHOD_OF = {"whole": "shaft_condyles", "proximal": "shaft_neck"}   # 哪种覆盖范围的骨照哪种定法
EXTENT_SAID = {"whole": "完整的股骨", "proximal": "只有近端一段的"}
KEYS = ("bone_id", "side", "bone_type", "coverage", "source", "units", "frame", "regions", "surfaces", "landmarks",
        "history", "checks")
WANTED = ("regions", "geometry", "materials", "landmarks", "coverage", "frame", "what")
# 第 1 版
SOLIDS = ("cortical", "cancellous")
KEYS_V1 = ("bone_id", "side", "units", "frame", "solids", "landmarks", "materials", "history", "checks")

_UNKNOWN = "不能不写：null（不知道）只有读第 1 版的骨模型时才有"
_NOT_READ = "骨模型的清单要先读成现在这一版再核（bone_model.read）"


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _point(value) -> bool:
    return isinstance(value, list) and len(value) == 3 and all(map(_is_number, value))


def _one_of(value, choices) -> bool:
    return isinstance(value, str) and value in choices


def _pick(value, choices) -> bool:
    """从 choices 里选的几个：不空、不重复的列表。"""
    return isinstance(value, list) and bool(value) and all(_one_of(one, choices) for one in value) and len(set(value)) == len(value)


# ---------------------------------------------------------------- 轴和解剖坐标系

def _sub(a, b) -> list:
    return [p - q for p, q in zip(a, b)]


def _dot(a, b) -> float:
    return sum(p * q for p, q in zip(a, b))


def _cross(a, b) -> list:
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _unit(start, end) -> tuple | None:
    """从 start 指向 end 的单位向量。两个点重合就是 None。"""
    delta = [b - a for a, b in zip(start, end)]
    length = math.sqrt(sum(part * part for part in delta))
    return tuple(part / length for part in delta) if length > 1e-9 else None


def _across(vector, axis) -> list | None:
    """vector 投到垂直 axis（单位向量）的面上，化成单位向量。投出来是零（和 axis 平行）就是 None。"""
    along = _dot(vector, axis)
    flat = [part - along * unit for part, unit in zip(vector, axis)]
    length = math.sqrt(_dot(flat, flat))
    return [part / length for part in flat] if length > 1e-9 else None


def axes(landmarks: dict) -> tuple:
    """（颈轴，干轴）两个单位向量：颈轴从颈中心指向头心，干轴从远端指向近端。定不出来的那一根是 None。"""
    return (_unit(landmarks["neck_center"]["xyz"], landmarks["head_center"]["xyz"]),
            _unit(landmarks["shaft_distal"]["xyz"], landmarks["shaft_proximal"]["xyz"]))


def neck_shaft_angle(landmarks: dict) -> float:
    """颈干角，度：180° 减去颈轴和干轴的夹角。"""
    neck, shaft = axes(landmarks)
    cosine = max(-1.0, min(1.0, sum(a * b for a, b in zip(neck, shaft))))
    return 180.0 - math.degrees(math.acos(cosine))


def frame(landmarks: dict, side: str, method: str, anteversion_deg=None) -> dict:
    """从标志点算解剖坐标系：{"origin", "x", "y", "z"}，在几何文件的坐标里。算法只有这一份，写法见文件开头。

    method 是 shaft_condyles（照后髁连线）或 shaft_neck（照颈轴，再照 anteversion_deg 转回去）。
    shaft_neck 不给前倾角就是不知道：不转，x 就是颈轴的投影（第 1 版读来的骨模型是这样）。
    定不出来报 ValueError，说出为什么。
    """
    if side not in SIDES:
        raise ValueError(f"side 只能是 {list(SIDES)}：{side!r}")
    if method not in METHODS:
        raise ValueError(f"解剖坐标系的定法要是 {list(METHODS)} 之一：{method!r}")
    if not isinstance(landmarks, dict):
        raise ValueError("标志点必须是一个 JSON 对象")
    needed = LANDMARKS + (CONDYLES if method == "shaft_condyles" else ())
    missing = [name for name in needed if name not in landmarks]
    if missing:
        raise ValueError(f"照 {method} 定要有标志点 {missing}")
    odd = [name for name in needed if not (isinstance(landmarks[name], dict) and _point(landmarks[name].get("xyz")))]
    if odd:
        raise ValueError(f"标志点 {odd} 的 xyz 要是三个数")
    at = {name: landmarks[name]["xyz"] for name in needed}
    up = _unit(at["shaft_distal"], at["shaft_proximal"])
    if up is None:
        raise ValueError("骨干上的两个点重合，定不出干轴")
    if _unit(at["neck_center"], at["head_center"]) is None:
        raise ValueError("颈中心和头心重合，定不出颈轴")
    neck = _across(_sub(at["head_center"], at["neck_center"]), up)
    if neck is None:
        raise ValueError("颈轴和干轴平行，定不出内侧朝哪")
    right = side == "right"
    if method == "shaft_condyles":
        if anteversion_deg is not None:
            raise ValueError("照后髁连线定的不给前倾角：前倾角是量出来的（anteversion）")
        medial = _across(_sub(at["condyle_medial"], at["condyle_lateral"]), up)
        if medial is None:
            raise ValueError("两个后髁的连线和干轴平行（或两个点重合），定不出内侧朝哪")
        if _dot(medial, neck) <= 0:
            raise ValueError("照后髁连线定出的内侧和颈轴指的不同向（量出的前倾角到了 ±90° 以外）：内外两个后髁是不是写反了")
    else:
        if anteversion_deg is not None and not (_is_number(anteversion_deg) and -90 < anteversion_deg < 90):
            raise ValueError(f"前倾角要是 −90 到 90 之间的数（度）：{anteversion_deg!r}")
        back = _cross(up, neck) if right else _cross(neck, up)      # x 就取颈轴的投影时，后方朝哪
        turn = math.radians(anteversion_deg or 0.0)
        medial = [math.cos(turn) * along + math.sin(turn) * behind for along, behind in zip(neck, back)]
    level = _dot(_sub(at["lesser_trochanter"], at["shaft_distal"]), up)
    return {"origin": [start + level * part for start, part in zip(at["shaft_distal"], up)], "x": list(medial),
            "y": _cross(up, medial) if right else _cross(medial, up), "z": list(up)}


def anteversion(landmarks: dict, side: str) -> float:
    """照后髁连线量出的前倾角，度：颈轴在照后髁连线定的坐标系里朝前偏多少，朝前为正。要有两个后髁的标志点。"""
    made = frame(landmarks, side, "shaft_condyles")
    neck = _sub(landmarks["head_center"]["xyz"], landmarks["neck_center"]["xyz"])
    return math.degrees(math.atan2(-_dot(neck, made["y"]), _dot(neck, made["x"])))


# ---------------------------------------------------------------- 名字、读

def names(manifest: dict) -> dict:
    """骨模型里能被名字引用的东西（设定的声明，第 8 条）：{"bone.region": {…}, "bone.landmark": {…}, …}。

    两个版本的清单都认：第 2 版是区域、表面、标志点；第 1 版的区域就是那两个实体，没有单独给的表面。
    这两版都没有块和关节。清单不全也不报错：名字少了，引用它的设定会被拒。
    """
    landmarks, regions, surfaces, solids = (manifest.get(key) for key in ("landmarks", "regions", "surfaces", "solids"))
    if manifest.get("format") != 1 and "regions" in manifest:
        region = {one["name"] for one in regions if isinstance(one, dict) and isinstance(one.get("name"), str)} \
            if isinstance(regions, list) else set()
        surface = set(surfaces) if isinstance(surfaces, dict) else set()
    else:
        region, surface = set(solids) if isinstance(solids, dict) else set(), set()
    return {"bone.block": set(), "bone.joint": set(), "bone.surface": surface, "bone.region": region,
            "bone.landmark": set(landmarks) if isinstance(landmarks, dict) else set()}


def read(folder) -> dict:
    """读一份骨模型（或候选骨模型）的清单，读成现在这一版的样子：盘上是旧版本的照 versions.upcast 转，盘上的不动。

    只读不核（核用 check_format）。交给包、拿去核要求（lacking）的都是它读出来的这一份。
    读不出来、转不了、比这份代码新，都报 ValueError。
    """
    return upcast("bone_model", read_manifest(folder))


# ---------------------------------------------------------------- 第 1 版：照原来的规矩核，再读成第 2 版

def _file_format(file: str) -> str | None:
    """看后缀，这个几何文件是哪一种。认不出就是 None。"""
    suffix = PurePosixPath(file).suffix.lower()
    return next((form for form, suffixes in GEOMETRY_FILES.items() if suffix in suffixes), None)


def check_v1(manifest: dict) -> list[str]:
    """第 1 版自己的规矩，照原来的话说。重建记录和检查结果除外：这两段两个版本一样，读成第 2 版以后一起核。"""
    problems = [f"骨模型的清单缺 {key}" for key in KEYS_V1 if key not in manifest]
    if problems:
        return problems
    if manifest["side"] not in SIDES:
        problems.append(f"side 只能是 {list(SIDES)}：{manifest['side']!r}")
    if manifest["units"] != UNITS:
        problems.append(f"单位只有这一套：{UNITS}")
    said = manifest["frame"]
    if not isinstance(said, dict) or set(said) != set(FRAME) or not all(_text(text) for text in said.values()):
        problems.append(f"坐标系要写 {list(FRAME)} 四项的定义，每项都不能空")
    problems += _check_solids_v1(manifest["solids"], manifest.get("files"))
    problems += _check_landmarks_v1(manifest["landmarks"])
    problems += _check_materials_v1(manifest["materials"])
    return problems


def _check_solids_v1(solids, files) -> list[str]:
    if not isinstance(solids, dict) or set(solids) != set(SOLIDS):
        given = list(solids) if isinstance(solids, dict) else solids
        return [f"实体要有且只有 {list(SOLIDS)} 两个，这里是 {given!r}"]
    problems, used = [], []
    for name in SOLIDS:
        file = solids[name].get("file") if isinstance(solids[name], dict) else None
        # 升版在核清单共用的那几项之前：files 这时可能还不是列表。那就只看它是不是一个文件名，在不在留给后面核
        if not isinstance(file, str) or (isinstance(files, list) and file not in files):
            problems.append(f"实体 {name} 的文件清单里没有：{file!r}")
        used.append(file)
    if not problems and used[0] == used[1]:
        problems.append("两个实体不能是同一个文件")
    return problems


def _check_landmarks_v1(landmarks) -> list[str]:
    if not isinstance(landmarks, dict):
        return ["标志点（landmarks）必须是一个 JSON 对象"]
    missing = [name for name in LANDMARKS if name not in landmarks]
    problems = [f"标志点缺 {missing}"] if missing else []
    for name, point in landmarks.items():
        if not is_key(name):
            problems.append(f"标志点的名字要用小写字母、数字和下划线：{name!r}")
        elif (not isinstance(point, dict) or set(point) != {"xyz", "definition"} or not _text(point["definition"])
              or not _point(point["xyz"])):
            problems.append(f"标志点 {name} 要写 xyz（三个数）和 definition（它是怎么定的）")
    if not problems:
        neck, shaft = axes(landmarks)
        if neck is None:
            problems.append("颈中心和头心重合，定不出颈轴")
        if shaft is None:
            problems.append("骨干上的两个点重合，定不出干轴")
    return problems


def _check_materials_v1(materials) -> list[str]:
    if not isinstance(materials, dict) or set(materials) != set(SOLIDS):
        given = list(materials) if isinstance(materials, dict) else materials
        return [f"材料要有且只有 {list(SOLIDS)} 两种，这里是 {given!r}"]
    problems = []
    for name in SOLIDS:
        spec = materials[name]
        if not isinstance(spec, dict):
            problems.append(f"{name} 的材料必须是一个 JSON 对象")
            continue
        if not _text(spec.get("model")):
            problems.append(f"{name} 的材料没写 model（是哪种材料模型）")
        elif spec["model"] != "linear_elastic":
            problems.append(f"{name} 的材料写的是 {spec['model']!r}：第 1 版的材料只认 linear_elastic，别的不知道是什么，读不成第 2 版")
        if not _is_number(spec.get("E_MPa")) or spec["E_MPa"] <= 0:
            problems.append(f"{name} 的 E_MPa 必须是正数：{spec.get('E_MPa')!r}")
        if not _is_number(spec.get("nu")) or not 0 <= spec["nu"] < 0.5:
            problems.append(f"{name} 的 nu 要在 0 和 0.5 之间：{spec.get('nu')!r}")
    return problems


def from_v1(old: dict) -> dict:
    """第 1 版的清单读成第 2 版：一块骨、两个区域（皮质、松质）、均匀的线弹性材料。原来那一份不改。

    坐标系照颈轴定、前倾角不知道（没法转回去）；第 1 版没有的几样是 null。不合第 1 版的规矩、或者定不出坐标系，
    报 CannotUpcast，说出是哪里。
    """
    problems = check_v1(old)
    if problems:
        raise CannotUpcast("第 1 版的骨模型不合格式：" + "；".join(problems))
    try:
        made = frame(old["landmarks"], old["side"], "shaft_neck")
    except ValueError as error:
        raise CannotUpcast(f"第 1 版的骨模型定不出解剖坐标系：{error}") from None
    regions = [{"name": name, "role": name,
                "geometry": {"kind": "solid", "format": _file_format(old["solids"][name]["file"]), "file": old["solids"][name]["file"]},
                "volume_mm3": None,
                "material": {"model": "elastic", "E": old["materials"][name]["E_MPa"], "nu": old["materials"][name]["nu"]}}
               for name in SOLIDS]
    landmarks = {name: {"xyz": point["xyz"], "fit": None,
                        "definition": {"method": None, "version": None, "params": {}, "text": point["definition"]}}
                 for name, point in old["landmarks"].items()}
    said = "；".join(f"{key}：{old['frame'][key]}" for key in FRAME)
    kept = {key: value for key, value in old.items() if key not in ("solids", "materials")}
    return {**kept, "format": 2, "bone_type": None, "coverage": None, "source": None,
            "frame": {"file": said, "method": "shaft_neck", "anteversion_deg": None, **made},
            "regions": regions, "surfaces": {}, "landmarks": landmarks}


# ---------------------------------------------------------------- 第 2 版的核对

def check(kind: str, manifest: dict, folder) -> list[str]:
    """check_format 叫的入口。清单共用的那几项、清单列的文件在不在，已经核过了；交来的清单已经读成现在这一版。

    是不是从第 1 版读来的（许不许有“不知道”），看盘上那一份清单写的版本。
    """
    return check_model(kind, manifest, unknown_ok=_stored_version(folder) == 1)


def _stored_version(folder):
    """盘上那一份清单写的是第几版。读不出来就是 None。"""
    try:
        return read_manifest(folder).get("format")
    except (ValueError, OSError, TypeError):
        return None


def check_model(kind: str, manifest: dict, unknown_ok: bool = False) -> list[str]:
    """核一份第 2 版的清单。返回哪里不符，说出是哪一段、哪一项；空列表就是对的。

    unknown_ok：这份清单是从第 1 版读来的，第 1 版没有的那几样可以是 null（不知道）。别的时候一样都不许不写。
    """
    problems = [f"骨模型的清单缺 {key}" for key in KEYS if key not in manifest]
    if problems:
        return problems
    files = manifest.get("files") if isinstance(manifest.get("files"), list) else []
    side_ok = manifest["side"] in SIDES
    if not side_ok:
        problems.append(f"side 只能是 {list(SIDES)}：{manifest['side']!r}")
    problems += _check_identity(manifest["bone_type"], manifest["coverage"], unknown_ok)
    problems += _check_source(manifest["source"], unknown_ok)
    if manifest["units"] != UNITS:
        problems.append(f"单位只有这一套：{UNITS}")
    problems += _check_regions(manifest["regions"], files, unknown_ok)
    problems += _check_surfaces(manifest["surfaces"], manifest["regions"], files)
    problems += _check_landmarks(manifest["landmarks"], unknown_ok)
    if side_ok and _placeable(manifest["landmarks"]):       # 哪一侧、标志点的位置没写对，坐标系没法算：先改那一处
        problems += _check_frame(manifest, unknown_ok)
    history = manifest["history"]
    if (not isinstance(history, list) or not history
            or not all(isinstance(step, dict) and _text(step.get("step")) and _text(step.get("what")) for step in history)):
        problems.append("重建记录（history）至少要有一步，每一步写 step 和 what")
    problems += _check_checks(kind, manifest["checks"])
    return problems


def _unknown(what: str, unknown_ok: bool) -> list[str]:
    """这一项写的是 null（不知道）：读第 1 版时许，别的时候是一条问题。"""
    return [] if unknown_ok else [f"{what}{_UNKNOWN}"]


def _check_identity(bone_type, coverage, unknown_ok: bool) -> list[str]:
    problems = []
    if bone_type is None:
        problems += _unknown("骨的种类（bone_type）", unknown_ok)
    elif bone_type not in BONE_TYPES:
        problems.append(f"骨的种类（bone_type）要是 {list(BONE_TYPES)} 之一：{bone_type!r}")
    if coverage is None:
        problems += _unknown("覆盖范围（coverage）", unknown_ok)
    elif not (isinstance(coverage, dict) and set(coverage) == {"extent", "proximal_mm", "distal_mm"}
              and _one_of(coverage["extent"], EXTENTS)
              and all(_is_number(coverage[key]) and coverage[key] > 0 for key in ("proximal_mm", "distal_mm"))):
        problems.append(f'覆盖范围（coverage）要写成 {{"extent": {list(EXTENTS)} 之一, "proximal_mm": 正数, "distal_mm": 正数}}：'
                        "几何从解剖坐标系的原点沿干轴往近端、往远端各到多远")
    return problems


def _pinned(value) -> bool:
    """登记的一样东西：编号和哈希。"""
    return isinstance(value, dict) and set(value) == {"id", "hash"} and is_item_id(value["id"]) and is_hash(value["hash"])


def _check_source(source, unknown_ok: bool) -> list[str]:
    if source is None:
        return _unknown("来源（source）", unknown_ok)
    if not (isinstance(source, dict) and set(source) == {"how", "method", "setting"} and _one_of(source["how"], HOWS)
            and _pinned(source["method"]) and _pinned(source["setting"])):
        return [f'来源（source）要写成 {{"how": {list(HOWS)} 之一, "method": {{"id", "hash"}}, "setting": {{"id", "hash"}}}}：'
                "怎么来的，重建方法包和重建设定登记的编号和哈希"]
    return []


def _region_names(regions) -> list | None:
    """各个区域的名字。区域不是一个个 JSON 对象的列表，就是 None。"""
    if not isinstance(regions, list) or not regions or not all(isinstance(region, dict) for region in regions):
        return None
    return [region.get("name") for region in regions]


def _named_right(listed: list) -> bool:
    return all(map(is_key, listed)) and len(set(listed)) == len(listed)


def _check_regions(regions, files: list, unknown_ok: bool) -> list[str]:
    listed = _region_names(regions)
    if listed is None:
        return ["区域（regions）要是区域的列表，至少一个，每个一个 JSON 对象"]
    if not _named_right(listed):
        return [f"区域的名字要用小写字母、数字和下划线，不重名：{listed}"]
    problems, used = [], {}
    for region in regions:
        name, said = region["name"], f"区域 {region['name']!r}"
        if set(region) != {"name", "role", "geometry", "volume_mm3", "material"}:
            problems.append(f'{said}：要写且只写 "name"、"role"、"geometry"、"volume_mm3"、"material"')
            continue
        role = region["role"]
        if not _one_of(role, ROLES):
            problems.append(f"{said}：角色要是 {list(ROLES)} 之一，这里是 {role!r}")
        problems += _check_geometry(region["geometry"], files, name, used, unknown_ok)
        if region["volume_mm3"] is None:
            problems += _unknown(f"{said} 的体积（volume_mm3）", unknown_ok)
        elif not (_is_number(region["volume_mm3"]) and region["volume_mm3"] > 0):
            problems.append(f"{said}：volume_mm3 要是正数（mm3）")
        spec = region["material"]
        if role == "canal":
            if spec is not None:
                problems.append(f"{said}：髓腔是空的，材料要写 null")
        elif spec is None:
            problems.append(f"{said}：{ROLES[role] if _one_of(role, ROLES) else ''}的区域要写材料")
        elif not isinstance(spec, dict) or spec.get("model") not in MATERIALS:
            problems.append(f"{said} 的材料：骨的材料只收 {list(MATERIALS)}，这里是 {spec.get('model') if isinstance(spec, dict) else spec!r}")
        else:
            problems += material.check_material(spec, None, f"{said} 的材料")
    return problems


def _check_geometry(geometry, files: list, name: str, used: dict, unknown_ok: bool) -> list[str]:
    said = f"区域 {name!r}"
    if not (isinstance(geometry, dict) and set(geometry) == {"kind", "format", "file"} and geometry["kind"] == "solid"
            and (geometry["format"] is None or _one_of(geometry["format"], GEOMETRY_FILES)) and isinstance(geometry["file"], str)):
        return [f'{said}：geometry 要写成 {{"kind": "solid", "format": {list(GEOMETRY_FILES)} 之一, "file": 文件}}']
    file, form = geometry["file"], geometry["format"]
    problems = []
    if file not in files:
        problems.append(f"{said}：几何文件 {file!r} 不在 files 里")
    if form is None:
        problems += _unknown(f"{said} 的几何文件是哪一种（geometry.format）", unknown_ok)
    elif _file_format(file) != form:
        problems.append(f"{said}：几何文件 {file!r} 的后缀和 format（{form}）对不上")
    if file in used:
        problems.append(f"{said}：和区域 {used[file]!r} 是同一个几何文件")
    used.setdefault(file, name)
    return problems


def _check_surfaces(surfaces, regions, files: list) -> list[str]:
    if not isinstance(surfaces, dict) or not all(map(is_key, surfaces)):
        return ["表面（surfaces）要是 {名字: …}，名字用小写字母、数字和下划线；没有就写 {}"]
    known = _region_names(regions)
    if known is None or not _named_right(known):
        known = None                    # 区域自己没写对：表面落在哪个区域上先不核，先改区域
    problems = []
    for name, surface in surfaces.items():
        if not (isinstance(surface, dict) and set(surface) == {"region", "file"}):
            problems.append(f'表面 {name!r}：要写成 {{"region": 区域名, "file": 表面片文件}}')
        elif known is not None and not _one_of(surface["region"], known):
            problems.append(f"表面 {name!r}：区域 {surface['region']!r} 不在 regions 里")
        elif surface["file"] not in files:
            problems.append(f"表面 {name!r}：文件 {surface['file']!r} 不在 files 里")
    return problems


def _check_landmarks(landmarks, unknown_ok: bool) -> list[str]:
    if not isinstance(landmarks, dict):
        return ["标志点（landmarks）必须是一个 JSON 对象"]
    missing = [name for name in LANDMARKS if name not in landmarks]
    problems = [f"标志点缺 {missing}"] if missing else []
    for name, point in landmarks.items():
        if not is_key(name):
            problems.append(f"标志点的名字要用小写字母、数字和下划线：{name!r}")
            continue
        if not isinstance(point, dict) or set(point) != {"xyz", "definition", "fit"}:
            problems.append(f'标志点 {name}：要写且只写 "xyz"、"definition"、"fit"')
            continue
        if not _point(point["xyz"]):
            problems.append(f"标志点 {name}：xyz 要是三个数")
        problems += _check_definition(point["definition"], name, unknown_ok)
        fit = point["fit"]
        if fit is None:
            problems += _unknown(f"标志点 {name} 的拟合的好坏（fit）", unknown_ok)
        elif not (isinstance(fit, dict) and all(is_key(key) and (isinstance(value, bool) or _is_number(value)) for key, value in fit.items())):
            problems.append(f"标志点 {name}：fit 要写成 {{名字: 数或 true、false}}（拟合的好坏；手给的点可以是 {{}}）")
    return problems


def _placeable(landmarks) -> bool:
    """标志点够不够拿来算坐标系：必有的五个都在，每个点的位置都是三个数。"""
    return (isinstance(landmarks, dict) and all(name in landmarks for name in LANDMARKS)
            and all(isinstance(point, dict) and _point(point.get("xyz")) for point in landmarks.values()))


def _check_definition(definition, name: str, unknown_ok: bool) -> list[str]:
    shape = (f'标志点 {name}：definition 要写成 {{"method": 找法的名字, "version": 版本, "params": {{参数}}}}，'
             '可以另带一句 "text"；名字用 ASCII 的字母、数字和 . _ -，版本是一段文字')
    if not (isinstance(definition, dict) and {"method", "version", "params"} <= set(definition) <= {"method", "version", "params", "text"}
            and isinstance(definition["params"], dict) and ("text" not in definition or _text(definition["text"]))):
        return [shape]
    problems = []
    for key, good, what in (("method", is_label, "找法"), ("version", _text, "找法的版本")):
        if definition[key] is None:
            problems += _unknown(f"标志点 {name} 的{what}（definition.{key}）", unknown_ok)
        elif not good(definition[key]):
            return [shape]
    return problems


def _check_frame(manifest: dict, unknown_ok: bool) -> list[str]:
    """解剖坐标系：写法；哪种骨照哪种定法；记的原点和三个轴，和照标志点算出来的一样。标志点和哪一侧已经核过。"""
    said, given = "解剖坐标系（frame）", manifest["frame"]
    if not isinstance(given, dict) or not _one_of(given.get("method"), METHODS):
        return [f"{said}：method 要是 {list(METHODS)} 之一"]
    method = given["method"]
    wanted = ["file", "method", *(["anteversion_deg"] if method == "shaft_neck" else []), *FRAME]
    if set(given) != set(wanted):
        return [f"{said}：照 {method} 定的要写且只写 {wanted}"]
    problems = []
    if not _text(given["file"]):
        problems.append(f"{said}：file 要写几何文件自己的坐标是怎么来的")
    if not all(_point(given[key]) for key in FRAME):
        return problems + [f"{said}：origin、x、y、z 各要是三个数"]
    turn = given.get("anteversion_deg")
    if method == "shaft_neck":
        if turn is None:
            if not unknown_ok:
                return problems + _unknown(f"{said}的前倾角（anteversion_deg）", unknown_ok)
        elif not (_is_number(turn) and -90 < turn < 90):
            return problems + [f"{said}：anteversion_deg 要是 −90 到 90 之间的数（度）"]
    coverage = manifest["coverage"]
    extent = coverage.get("extent") if isinstance(coverage, dict) else None
    if _one_of(extent, METHOD_OF) and METHOD_OF[extent] != method:
        problems.append(f"{said}：{EXTENT_SAID[extent]}（{extent}）要照 {METHOD_OF[extent]} 定，这里写的是 {method}")
    try:
        made = frame(manifest["landmarks"], manifest["side"], method, turn)
    except ValueError as error:
        return problems + [f"{said}：{error}"]
    off = [key for key in FRAME if any(abs(a - b) > 1e-6 for a, b in zip(given[key], made[key]))]
    if off:
        problems.append(f"{said}：记的 {off} 和照标志点算出来的对不上。标志点、哪一侧、定法、前倾角动了，坐标系要跟着重算（bone_model.frame）")
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


# ---------------------------------------------------------------- 用的一方要什么

def _whole(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _count_ok(pair) -> bool:
    """[最少几个, 最多几个]：最少不小于 0；最多不小于最少、至少是 1，不限写 null。"""
    return (isinstance(pair, list) and len(pair) == 2 and _whole(pair[0]) and pair[0] >= 0
            and (pair[1] is None or (_whole(pair[1]) and pair[1] >= max(pair[0], 1))))


def _coverage_wanted_ok(asked) -> bool:
    return (isinstance(asked, dict) and bool(asked) and set(asked) <= {"extent", "distal_mm", "proximal_mm"}
            and ("extent" not in asked or _pick(asked["extent"], EXTENTS))
            and all(_is_number(asked[key]) and asked[key] > 0 for key in ("distal_mm", "proximal_mm") if key in asked))


def _frame_wanted_ok(asked) -> bool:
    return (isinstance(asked, dict) and "methods" in asked and set(asked) <= {"methods", "unknown_anteversion"}
            and _pick(asked["methods"], METHODS)
            and ("unknown_anteversion" not in asked or isinstance(asked["unknown_anteversion"], bool)))


def check_wanted(want) -> list[str]:
    """用骨模型的一方写的要求（包清单 inputs 里的 bone）自己写得对不对。返回哪里不对；空列表就是对的。

    写了契约不认得的项会被点名：写错一个字，不能悄悄成了不挑。
    """
    if not isinstance(want, dict):
        return ["对骨模型的要求必须是一个 JSON 对象"]
    problems = [f"对骨模型的要求里多了 {key}：只认 {list(WANTED)}" for key in want if key not in WANTED]
    regions = want.get("regions")
    if "regions" in want and not (isinstance(regions, dict) and regions
                                  and all(_one_of(role, ROLES) and _count_ok(pair) for role, pair in regions.items())):
        problems.append(f"regions 要写成 {{角色: [最少几个, 最多几个]}}：角色从 {list(ROLES)} 里选，至少一种；"
                        f"最少不小于 0，最多不小于最少、至少是 1，不限写 null。这里是 {regions!r}")
    if "geometry" in want and not _pick(want["geometry"], GEOMETRY_FILES):
        problems.append(f"geometry 要从 {list(GEOMETRY_FILES)} 里选，不重复，至少一种：{want['geometry']!r}")
    if "materials" in want and not _pick(want["materials"], MATERIALS):
        problems.append(f"materials 要从 {list(MATERIALS)} 里选，不重复，至少一种：{want['materials']!r}")
    marks = want.get("landmarks")
    if "landmarks" in want and not (isinstance(marks, list) and all(map(is_key, marks)) and len(set(marks)) == len(marks)):
        problems.append(f"landmarks 要是标志点名字的列表，不重复：{marks!r}")
    if "coverage" in want and not _coverage_wanted_ok(want["coverage"]):
        problems.append(f'coverage 要写成 {{"extent": [{list(EXTENTS)} 里的几种], "distal_mm": 正数, "proximal_mm": 正数}}，'
                        f"三项各自可以不写，至少写一项：{want['coverage']!r}")
    if "frame" in want and not _frame_wanted_ok(want["frame"]):
        problems.append(f'frame 要写成 {{"methods": [{list(METHODS)} 里的几种], "unknown_anteversion": true 或 false}}，'
                        f"后一项可以不写：{want['frame']!r}")
    if "what" in want and not _text(want["what"]):
        problems.append("what 要是一句给人看的说明")
    return problems


def lacking(want, model) -> list[str]:
    """这份骨模型缺要求里的哪几样。一样一句，说出是哪一样；空列表就是都有。

    want 是包清单 inputs 里的 bone（先照 check_wanted 核，写得不对就只说它不对）。
    model 是读成现在这一版的骨模型清单（read 读出来的），它该是登记过、核过格式的。
    骨模型里不知道的东西（第 1 版读来的覆盖范围、前倾角、认不出的几何文件），要求里要它就算缺。
    """
    wrong = check_wanted(want)
    if wrong:
        return [f"对骨模型的要求写得不对：{text}" for text in wrong]
    if not isinstance(model, dict) or model.get("format") != FORMATS["bone_model"]:
        return [_NOT_READ]
    regions, found = model["regions"], []
    if "regions" in want:
        for role, (least, most) in want["regions"].items():
            have = [region["name"] for region in regions if region["role"] == role]
            if len(have) < least:
                found.append(f"区域：要至少 {least} 个{ROLES[role]}（{role}）的区域，这份骨模型有 {len(have)} 个")
            elif most is not None and len(have) > most:
                found.append(f"区域：最多收 {most} 个{ROLES[role]}（{role}）的区域，这份骨模型有 {len(have)} 个：{have}")
        for role in ROLES:
            others = [region["name"] for region in regions if region["role"] == role]
            if others and role not in want["regions"]:
                found.append(f"区域：不收{ROLES[role]}（{role}）的区域，这份骨模型有 {others}")
    if "geometry" in want:
        for region in regions:
            form = region["geometry"]["format"]
            if form is None:
                found.append(f"几何：区域 {region['name']!r} 的几何文件不知道是哪一种（第 1 版读来的），要求只收 {want['geometry']}")
            elif form not in want["geometry"]:
                found.append(f"几何：只收 {want['geometry']} 的几何文件，区域 {region['name']!r} 是 {form}")
    if "materials" in want:
        found += [f"材料：只会 {want['materials']} 这几种材料模型，区域 {region['name']!r} 的是 {region['material']['model']}"
                  for region in regions if region["material"] is not None and region["material"]["model"] not in want["materials"]]
    if "landmarks" in want:
        missing = [name for name in want["landmarks"] if name not in model["landmarks"]]
        if missing:
            found.append(f"标志点：缺 {missing}")
    if "coverage" in want:
        found += _coverage_lacking(want["coverage"], model["coverage"])
    if "frame" in want:
        asked, have = want["frame"], model["frame"]
        if have["method"] not in asked["methods"]:
            found.append(f"解剖坐标系：只收照 {asked['methods']} 定的，这份是照 {have['method']} 定的")
        elif have["method"] == "shaft_neck" and have["anteversion_deg"] is None and not asked.get("unknown_anteversion", False):
            found.append("解剖坐标系：这份是照颈轴定的、前倾角不知道（第 1 版读来的，没有转回去），要求里没说收这种")
    return found


def _coverage_lacking(asked: dict, have) -> list[str]:
    if have is None:
        return ["覆盖范围：这份骨模型不知道覆盖范围（第 1 版读来的），要求里要它"]
    found = []
    if "extent" in asked and have["extent"] not in asked["extent"]:
        found.append(f"覆盖范围：只收 {asked['extent']}，这份是 {have['extent']}")
    for key, where in (("distal_mm", "远端"), ("proximal_mm", "近端")):
        if key in asked and have[key] < asked[key]:
            found.append(f"覆盖范围：要往{where}至少到 {asked[key]} mm，这份只到 {have[key]} mm")
    return found
