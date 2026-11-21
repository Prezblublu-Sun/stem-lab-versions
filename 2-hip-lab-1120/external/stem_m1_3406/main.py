"""柄空间包的入口：M1 的直轴短柄放进 Sawbones 3406。是从冻结的 FE 模型 M1-3406-v1 里拆出来的柄的那一半。

    python code/main.py <输入文件夹> <输出文件夹>

输入文件夹里的 job.json 说要做什么（约定见 stemlab/contract/formats/package.py 的“柄空间”）：
    template   一批设计各自放进这根骨里：放不放得下、去多少骨。不出柄的模型
    model      一个点：模板化，交出柄的模型（stemlab/contract/formats/stem_model.py 的格式），写在输出文件夹的 model/ 里
    selfcheck  自检，不用骨模型
骨模型是 job 里的两样：bone_model 是文件夹（两个 STEP 在里面），bone 是它的清单，叫这个包的一方已经读成第 2 版的样子。
这个包读 bone，不自己打开文件夹里的清单；两个实体照区域的角色（皮质、松质）找，不照名字找。
它只认 3406R_v1_hollowcore 的那两个文件（按 sha256）：清单里对骨模型的要求写不出这一条，所以在这里跑的时候核。

旧代码在 code/legacy/ 下，从旧系统按原字节搬来，一个字节不改。这个文件只做四件事：
    把一个点的设计项和放置设定翻成对旧代码的调用：模板化叫的就是旧代码的 collar_rule.template_neck_in_shoulder；
    把旧代码要的文件和缓存安排到可写的地方；
    照旧代码建模的头几步（model3d_m1._build）用 gmsh/OCC 做出柄的实体，写成柄的模型；
    把结果翻成约定的 result.json。
放置设定的每一项都从 job 的 settings 里取，这里不留它们的默认值：少了哪一项就说出来。

交出的柄的模型：
    坐标    柄自己的坐标系：原点在肩部中心（柄轴穿过截骨面的地方），x 指向内侧，y 指向前方，z 沿柄轴指向远端。
            placement.frame 说它在骨模型文件的坐标系里在哪；placement.cut 是截骨面，法向指向头那一侧（被截掉的一侧）
    区域    stem：柄体在截骨面以下的部分、假体颈、假体头并成的一个实体。旧模型里它们就是一个实体、一种材料
    面组    interface：柄体在截骨面以下的表面，和骨接触的就是它（旧模型的 S_STEM）
    特征点  head_center 假体头心（头心复位，就是股骨头心）；neck_base 假体颈底面的中心（就是截骨中心）；
            shoulder 肩部中心；tip 柄尖
    轴      stem_axis 柄轴，从肩部指向柄尖；neck_axis 颈轴，从颈底指向头心
    放置    removed 是 null：去掉的骨就是截骨面以上的，加上柄占的地方（锉腔和柄体一样大，过盈由有限元设定给）。
            landmarks 是空的：头心、颈轴、骨干轴都是旧代码从两个实体里自己找的，没有用骨模型清单里的标志点

旧代码每个作业要一个自己的进程（它会改进程里的全局状态），所以这个入口一次只做一件事。
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import shutil
import sys
import time
import traceback
from pathlib import Path
from types import SimpleNamespace

sys.dont_write_bytecode = True      # 包在只读的地方跑：不管外面怎么设，都不往包里写 __pycache__

HERE = Path(__file__).resolve().parent
LEGACY = HERE / "legacy"
LEGACY_FILES = ("config.yaml", "femur2d.py", "plotstyle.py", "v2/collar_rule.py", "v2/config_v2a.yaml", "v2/fe3d_geom.py",
                "v2/femur_3406.py", "v2/femur_real.py", "v2/geom3d.py")
BONE_ID = "sawbone3406"
BONE_FORMAT = 2                 # 叫这个包的一方交来的骨模型清单（job 的 bone）是第几版的样子
STEP_NAMES = {"cortical": "3406R_cortical.STEP", "cancellous": "3406R_cancellous_v2.STEP"}     # 区域的角色 -> 旧代码要的文件名

SHAPE = ("L", "rho_tip", "q", "lam", "g_ml", "g_ap", "n_a", "n_p", "tau_a", "tau_p", "alpha", "m")     # 12 个设计项
PLACED = ("h_cut", "ref_cut_mm", "neck_axis", "entry", "collar_rule", "neck_radius_mm", "margin_check", "area_min_mm2",
          "area_max_mm2", "bisection_iters", "min_tip_area_mm2")         # 模板化要的放置设定；入口那几项看 entry
CAP_H = 1.5                     # 平端的帽高。必须写进旧代码的设计：缺了就是半椭球帽，几何不同
RULE = "neck_in_shoulder"       # 这个柄空间只会这一种选号规则：无领，假体颈底面落在柄的截口里

MODEL, MANIFEST = "model", "stem_model.json"
SOLID, INTERFACE = "geometry/stem.step", "faces/interface.step"
STEM_MODEL_FORMAT = 1


class Unsupported(Exception):
    """这个包做不了这件事。"""


class Misfit(Exception):
    """这个设计放不进这根骨，或者做不成一根柄。"""


# ---------------------------------------------------------------- 安排旧代码要的文件和缓存

def _cache_root() -> Path:
    """这台机器上放股骨距离场缓存的地方。可写、可删：没有了会重建（约一分钟）。"""
    given = os.environ.get("STEMLAB_STEM_CACHE")
    if given:
        return Path(given)
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "stemlab" / "stem-m1-3406"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _legacy_on_path() -> None:
    os.environ.setdefault("MPLBACKEND", "Agg")
    for folder in (LEGACY, LEGACY / "v2"):
        if str(folder) not in sys.path:
            sys.path.insert(0, str(folder))


def solids_of(job: dict) -> dict:
    """骨模型里皮质、松质两个实体的文件：{角色: 文件}。清单是 job 的 bone（读成第 2 版的），文件在 bone_model 那个文件夹里。"""
    listed, folder = job.get("bone"), job.get("bone_model")
    if not isinstance(listed, dict) or listed.get("format") != BONE_FORMAT or not folder:
        raise Unsupported(f"job 里要带骨模型的文件夹（bone_model）和读成第 {BONE_FORMAT} 版的清单（bone）")
    if listed.get("bone_id") != BONE_ID:
        raise Unsupported(f"这个柄空间只认 {BONE_ID}，骨模型是 {listed.get('bone_id')!r}")
    found = {role: [region for region in listed["regions"] if region["role"] == role] for role in STEP_NAMES}
    odd = {role: len(regions) for role, regions in found.items() if len(regions) != 1}
    if odd:
        raise Unsupported(f"这个柄空间要骨模型里皮质、松质各一个区域，这里是 {odd}")
    return {role: Path(folder) / regions[0]["geometry"]["file"] for role, regions in found.items()}


def setup(job: dict) -> None:
    """让旧代码能在这个进程里跑：两个 STEP 从骨模型里取，缓存放到这台机器可写的地方。"""
    _legacy_on_path()
    sources = solids_of(job)
    import femur_3406 as F3
    import femur_real as FR

    hashes = {name: _sha256(path) for name, path in sources.items()}
    if hashes != F3.SHA256:
        raise Unsupported("骨模型里的两个实体不是这个柄空间认的那两个 STEP 文件（哈希不同）：它只能放进 3406R_v1_hollowcore")
    home = _cache_root() / hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()[:16]
    place = home / "femur_3406"
    place.mkdir(parents=True, exist_ok=True)
    for name, source in sources.items():
        target = place / STEP_NAMES[name]
        if not target.exists():
            spare = target.with_name(f"{target.name}.{os.getpid()}.part")
            shutil.copyfile(source, spare)
            os.replace(spare, target)
    (home / "cache").mkdir(exist_ok=True)
    F3.DATA = place
    FR.CACHE = F3.CACHE = home / "cache"
    _warm(F3, home)


def _warm(F3, home: Path) -> None:
    """缓存不在就先建好。同一时刻只让一个进程建：两个进程同时写同一个缓存文件会写坏。"""
    wanted = F3.CACHE / f"femur_3406_{F3._cache_key(F3.load_cfg(None))}.npz"
    guard = home / "building"
    deadline = time.time() + 1800
    while not wanted.exists():
        try:
            os.close(os.open(guard, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        except FileExistsError:
            if time.time() - guard.stat().st_mtime > 900:       # 建它的那个进程多半已经不在了
                guard.unlink(missing_ok=True)
            elif time.time() > deadline:
                raise Unsupported("股骨的缓存一直没有建好") from None
            else:
                time.sleep(2.0)
            continue
        kept = os.environ.get("PATH", "")
        try:
            if not wanted.exists():
                F3.build()
        finally:
            os.environ["PATH"] = kept                           # 建缓存要用 gmsh，它会把 PATH 截短
            guard.unlink(missing_ok=True)


# ---------------------------------------------------------------- 设定和设计 -> 旧代码的模板化

def placing(settings, with_solid: bool) -> dict:
    """这个点的放置设定。要的项都得在，而且是取值：不拿自己的默认值顶上。"""
    if not isinstance(settings, dict):
        raise Unsupported("job 里没有放置设定（settings）")
    wanted = list(PLACED) + (["e"] if settings.get("entry") == "fixed" else ["offset_min_mm", "offset_max_mm", "offset_step_mm"])
    wanted += ["section_points"] if with_solid else []
    missing = [name for name in wanted if settings.get(name) is None]
    if missing:
        raise Unsupported(f"放置设定里少了 {missing}：这个包不拿自己的默认值顶上")
    left = [name for name in wanted if isinstance(settings[name], dict)]
    if left:
        raise Unsupported(f"放置设定里 {left} 写的还是“每个点给”，没有取值")
    if settings["entry"] not in ("rule", "fixed"):
        raise Unsupported(f"入口怎么定（entry）只能是 rule 或 fixed，这里是 {settings['entry']!r}")
    if settings["collar_rule"] != RULE:
        raise Unsupported(f"这个柄空间只会 {RULE} 这一种选号规则，设定里是 {settings['collar_rule']!r}")
    if settings["entry"] == "rule" and not float(settings["offset_step_mm"]) > 0:
        raise Unsupported("偏移的档距（offset_step_mm）要大于 0")
    return settings


_FEMURS: dict = {}


def femur(placed: dict):
    """这个点用的股骨：颈轴照设定选，截骨面照设定的高度，假体颈的半径照设定。"""
    import femur_3406 as F3

    key = json.dumps(placed["neck_axis"])
    if key not in _FEMURS:
        try:
            _FEMURS[key] = F3.build(neck_axis=placed["neck_axis"])
        except ValueError as error:
            raise Unsupported(f"颈轴怎么定（neck_axis）：{error}") from None
    fm = _FEMURS[key].with_cut(float(placed["h_cut"]))
    fm.cfg = copy.deepcopy(fm.cfg)                      # with_cut 是浅拷贝：改之前先分开，不动别的点用的那一份
    fm.cfg["prosthesis"]["neck_radius_mm"] = float(placed["neck_radius_mm"])
    return fm


def _offsets(placed: dict):
    """入口偏移试哪几档。固定入口就只有那一个。"""
    import numpy as np

    if placed["entry"] == "fixed":
        return np.array([float(placed["e"])])
    low, high, step = (float(placed[name]) for name in ("offset_min_mm", "offset_max_mm", "offset_step_mm"))
    return low + step * np.arange(int(math.floor((high - low) / step + 1e-9)) + 1)


def templating(fm, design, placed: dict):
    """把一个设计放进这根骨。返回（柄，放置结果）：叫的是旧代码的选号，界和规则都照设定。"""
    import collar_rule as CR
    import geom3d as G

    missing = [name for name in SHAPE if not isinstance(design, dict) or design.get(name) is None]
    if missing:
        raise Unsupported(f"这个点少了设计项 {missing}")
    stem = G.Stem3D(**{name: float(design[name]) for name in SHAPE}, cap_h=CAP_H)
    kept = (G.A_BOUNDS, G.MIN_TIP_AREA)
    G.A_BOUNDS = (float(placed["area_min_mm2"]), float(placed["area_max_mm2"]))      # 旧代码在调用时读这两个量
    G.MIN_TIP_AREA = float(placed["min_tip_area_mm2"])
    try:
        found = CR.template_neck_in_shoulder(stem, fm, offsets=_offsets(placed), iters=int(placed["bisection_iters"]),
                                             min_A0=_neck_area(placed), margin_check=placed["margin_check"])
    except ValueError as error:
        raise Unsupported(f"放置设定旧代码不认：{error}") from None
    finally:
        G.A_BOUNDS, G.MIN_TIP_AREA = kept
    return stem, found


def _neck_area(placed: dict) -> float:
    """肩部截面至少要这么大，才放得下假体颈。"""
    return math.pi * float(placed["neck_radius_mm"]) ** 2


def _fits(found: dict, placed: dict) -> bool:
    return bool(found["fit"]) and found["A0"] >= _neck_area(placed)


def _why_not(found: dict) -> str:
    return str(found.get("reason") or "shoulder smaller than the prosthetic neck")


def _pre(fm, placed: dict, found: dict) -> dict:
    """模板化算出的量：选出的号和位置、去骨量。"""
    resected = fm.resected_volume(ref_cut_mm=float(placed["ref_cut_mm"]))
    return {"e_mm": float(found["e"]), "A0_mm2": float(found["A0"]), "alpha_placed_deg": float(found["alpha"]),
            "contact_templated": float(found["contact"]), "bone_resected_mm3": float(resected),
            "bone_reamed_mm3": float(found["volume"]), "bone_total_mm3": float(resected + found["volume"])}


# ---------------------------------------------------------------- 柄的实体和柄的模型

def _stem_frame(found: dict):
    """柄自己的坐标系，在旧代码的模型坐标里：原点（肩部中心），和三个轴（一行一个：内侧、前方、沿柄轴）。"""
    import numpy as np

    origin, along, medial, anterior = (np.asarray(part, float) for part in found["pose"])
    x = medial / np.linalg.norm(medial)
    y = anterior - (anterior @ x) * x
    y /= np.linalg.norm(y)
    axes = np.vstack([x, y, np.cross(x, y)])
    if (axes @ along)[2] < 0.999999:
        raise Unsupported("这根骨上内侧、前方、柄轴不成右手系：这个包只做过右侧的 3406")
    return origin, axes


def _solid(stem, found: dict, fm, placed: dict, folder: Path) -> dict:
    """照旧代码建模的头几步做出柄的实体，写成两个 STEP：整个实体，和它在截骨面以下的那些面。
    都在柄自己的坐标系里。返回特征点、轴和界面的面积。

    不记实体的体积：OCC 的体积积分在这种放样出来的实体上偏小 2% 到 10%（和网格的体积比过，2026-11-18），
    旧代码记在 model3d.json 里的 stem_volume_mm3 就是这个不准的数。面积是准的（和细网格差 0.02%）。"""
    import fe3d_geom as E
    import gmsh
    import numpy as np

    origin, axes = _stem_frame(found)

    def point(position) -> np.ndarray:
        return (np.asarray(position, float) - origin) @ axes.T

    def turn(direction) -> np.ndarray:
        return np.asarray(direction, float) @ axes.T

    cut = SimpleNamespace(C03=point(fm.C03), u3=turn(fm.u3), n3=turn(fm.n3))     # 截骨面，旧代码的写法
    head = point(fm.H)
    along = np.array([0.0, 0.0, 1.0])
    pose = (np.zeros(3), along, np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0]))
    for name in (SOLID, INTERFACE):
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
    kept = os.environ.get("PATH", "")
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.NumThreads", 1)
        gmsh.model.add("stem")
        occ = gmsh.model.occ
        body = E.stem_solid(occ, stem, found["A0"], pose, delta=0.0, m=int(placed["section_points"]))
        body_in, _ = occ.intersect(body, E.kept_halfspace(occ, cut))
        neck = occ.addCylinder(*cut.C03, *(float(np.linalg.norm(fm.H - fm.C03)) * cut.u3), float(placed["neck_radius_mm"]))
        ball = occ.addSphere(*head, float(fm.cfg["prosthesis"]["head_radius_mm"]))
        whole, _ = occ.fuse(body_in, [(3, neck), (3, ball)])
        volumes = [tag for dim, tag in whole if dim == 3]
        if len(volumes) != 1:
            raise Misfit("stem is not a single volume (neck base outside the shoulder?)")
        occ.remove(occ.getEntities(1), recursive=True)          # 放样用过的截面线不在实体上了：清掉，不写进文件
        occ.remove(occ.getEntities(0))
        occ.synchronize()
        faces = [tag for dim, tag in gmsh.model.getBoundary([(3, volumes[0])], oriented=False) if dim == 2]
        under = [tag for tag in faces if (np.asarray(occ.getCenterOfMass(2, tag)) - cut.C03) @ cut.u3 < -1e-6]
        if not under or len(under) == len(faces):
            raise Misfit("the stem has no surface below the resection plane, or nothing above it")
        area = float(sum(occ.getMass(2, tag) for tag in under))
        gmsh.write(str(folder / SOLID))
        occ.remove([(3, volumes[0])])                           # 只留截骨面以下的那些面，写成面组
        occ.remove([(2, tag) for tag in faces if tag not in under], recursive=True)
        occ.synchronize()
        gmsh.write(str(folder / INTERFACE))
    finally:
        gmsh.finalize()
        os.environ["PATH"] = kept                               # gmsh 初始化时会把这个进程的 PATH 截短
    tip = (stem.L + stem.cap_length(found["A0"])) * along
    return {"interface_area": area, "origin": origin, "axes": axes,
            "features": {"head_center": head, "neck_base": cut.C03, "shoulder": np.zeros(3), "tip": tip},
            "stem_axis": {"point": np.zeros(3), "direction": along}, "neck_axis": {"point": cut.C03, "direction": cut.u3}}


def _numbers(values) -> list:
    return [float(value) for value in values]


def _write_model(folder: Path, point: dict, fm, found: dict, pre: dict, made: dict) -> None:
    """写柄的模型的清单。旧代码的模型坐标转回骨模型文件的坐标：X = x @ Rm + 原点。"""
    import numpy as np

    turned, shift = np.asarray(fm.lm["Rm"], float), np.asarray(fm.lm["origin"], float)
    titanium = fm.cfg["materials"]["titanium"]
    listed = {
        "format": STEM_MODEL_FORMAT, "files": sorted([SOLID, INTERFACE]), "units": {"length": "mm"}, "dimension": "3d",
        "design": point["design"],
        "regions": [{"name": "stem", "role": "body", "geometry": {"kind": "solid", "file": SOLID},
                     "material": {"model": "elastic", "E": float(titanium["E"]), "nu": float(titanium["nu"])}}],
        "faces": {"interface": {"region": "stem", "file": INTERFACE}},
        "features": {name: _numbers(where) for name, where in made["features"].items()},
        "axes": {name: {"point": _numbers(made[name]["point"]), "direction": _numbers(made[name]["direction"])}
                 for name in ("stem_axis", "neck_axis")},
        "placement": {
            "frame": {"origin": _numbers(made["origin"] @ turned + shift),
                      **{name: _numbers(axis @ turned) for name, axis in zip("xyz", made["axes"])}},
            "cut": {"point": _numbers(np.asarray(fm.C03, float) @ turned + shift), "normal": _numbers(np.asarray(fm.u3, float) @ turned)},
            "removed": None, "landmarks": []},
        "templating": {**pre, "s_bind_mm": float(found["s_bind"]), "neck_overhang_mm2": float(found["neck_overhang_mm2"]),
                       "interface_area_mm2": made["interface_area"]},
    }
    (folder / MANIFEST).write_text(json.dumps(listed), encoding="utf-8")


# ---------------------------------------------------------------- 三种做法

def template(job: dict, out: Path) -> dict:
    setup(job)
    placed = placing(job.get("settings"), with_solid=False)
    fm = femur(placed)
    rows = []
    for one in job["designs"]:
        try:
            _, found = templating(fm, one["design"], placed)
            fits = _fits(found, placed)
            info = _pre(fm, placed, found) if fits else {"reason": _why_not(found)}
        except Unsupported as error:
            fits, info = False, {"reason": str(error)}
        rows.append({"name": one["name"], "feasible": fits, "info": info})
    return {"designs": rows}


def model(job: dict, out: Path) -> dict:
    setup(job)
    placed = placing(job.get("settings"), with_solid=True)
    fm = femur(placed)
    point = job["point"]
    stem, found = templating(fm, point["design"], placed)
    if not _fits(found, placed):
        return {"status": "misfit", "reason": _why_not(found), "pre": {}}
    pre = _pre(fm, placed, found)
    folder = out / MODEL
    if folder.exists():
        shutil.rmtree(folder)
    try:
        made = _solid(stem, found, fm, placed, folder)
        _write_model(folder, point, fm, found, pre, made)
    except Misfit as error:
        shutil.rmtree(folder, ignore_errors=True)
        return {"status": "misfit", "reason": str(error), "pre": {}}
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)       # 出到一半的柄的模型不留：留着会被当成交出来的
        raise
    return {"status": "ok", "reason": "", "pre": pre}


def selfcheck(job: dict, out: Path) -> dict:
    """自检：这个包在这台机器的这个环境里还是不是打包时的那个。不用骨模型，几秒钟。

    旧代码的每个文件还是原来的字节；导得进来；一根给定的柄，解析的几何量、OCC 放样出的实体的表面积还是老数。
    """
    files = {name: _sha256(LEGACY / name)[:16] for name in LEGACY_FILES}
    _legacy_on_path()
    import fe3d_geom as E
    import geom3d as G
    import gmsh
    import numpy as np

    stem = G.Stem3D(**job["design"])
    area = float(job["A0"])
    pose = (np.zeros(3), np.array([0.0, 0.0, 1.0]), np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0]))
    kept = os.environ.get("PATH", "")
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.NumThreads", 1)
        body = E.stem_solid(gmsh.model.occ, stem, area, pose, delta=0.0, m=int(job["section_points"]))
        gmsh.model.occ.synchronize()
        skin = [tag for dim, tag in gmsh.model.getBoundary([one for one in body if one[0] == 3], oriented=False) if dim == 2]
        lofted = float(sum(gmsh.model.occ.getMass(2, tag) for tag in skin))
    finally:
        gmsh.finalize()
        os.environ["PATH"] = kept
    return {"legacy": files, "volume_mm3": float(stem.volume(area)), "cap_length_mm": float(stem.cap_length(area)),
            "area_ratio_mid": float(stem.area_ratio(0.5 * stem.L)), "area_ratio_tip": float(stem.area_ratio(stem.L)),
            "lofted_faces": len(skin), "lofted_area_mm2": lofted}


MODES = {"template": template, "model": model, "selfcheck": selfcheck}


def main() -> int:
    source, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    job = json.loads((source / "job.json").read_text(encoding="utf-8"))
    mode = job.get("mode")
    try:
        if mode not in MODES:
            raise Unsupported(f"这个包不会 {mode!r}，只会 {sorted(MODES)}")
        result = MODES[mode](job, out)
    except Unsupported as error:
        result = {"status": "error", "reason": str(error)}
    except ImportError as error:        # 库装了却加载不了（比如文件被别的程序占着）：是这台机器的事，不是这个点的事
        result = {"status": "env", "reason": f"这台机器上有库加载不了：{error}"}
    except Exception as error:  # noqa: BLE001  旧代码抛的任何错都说出来，不让这个进程带着一串看不懂的东西死掉
        result = {"status": "error", "reason": f"{type(error).__name__}: {error}\n{traceback.format_exc()[-1500:]}"}
    if mode == "model":
        result.setdefault("pre", {})
    (out / "result.json").write_text(json.dumps(result, default=float), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
