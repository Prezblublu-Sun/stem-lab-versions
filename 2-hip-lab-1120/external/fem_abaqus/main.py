"""有限元包的入口：M1 的界面模型，用 Abaqus/Standard 求解。是从冻结的 FE 模型 M1-3406-v1 里拆出来的建模、求解、后处理那一半。

    python code/main.py <输入文件夹> <输出文件夹>

输入文件夹里的 job.json 说要做什么（约定见 stemlab/contract/formats/package.py 的“有限元”）：
    build      一个点：读骨模型和柄的模型，照这个点的有限元设定划网格、写 Abaqus 的输入（在 job 文件夹里），交出求解的命令
    post       求解结束之后：读结果，算标签，交界面的场，说哪些文件要归档
    selfcheck  自检，不用骨模型，也不用 Abaqus

旧代码在 code/legacy/ 下，从旧系统按原字节搬来，一个字节不改。这个文件只做这几件事：
    把骨模型、柄的模型和有限元设定翻成旧代码建模要的几何和数，照 model3d_m1._build 一步一步建（build_once）：
        界面面片、节点对、孪生节点、接触块、写输入、尺寸场、划网格的选项、合力的方向，都叫旧代码的函数；
    后处理叫旧代码的 jobs.fric_only_result 和 stability.stability。stability 原来从规格重建股骨去拿柄的位姿，
        这里只把它读入的那一步（stability._load）换掉，位姿从柄的模型拿，算法一行不改；
    把结果翻成约定的 result.json。
有限元设定的每一项都从 job 的 settings 里取，这里不留它们的默认值：少了哪一项就说出来。

坐标：在骨模型自己的坐标里建，骨的两个实体不动。柄的实体、面组、特征点在柄自己的坐标系里，照 placement.frame 换过来。
    截骨面          柄的模型的 placement.cut，法向指向头那一侧：骨只留它的另一侧
    远端截断        垂直于干轴（骨模型的 shaft_distal 指向 shaft_proximal），在 distal_from 那个标志点那一层以下 distal_cut_mm
    载荷的坐标系    load_frame 是 shaft_neck：z 沿干轴指向近端，x 是颈轴（neck_center 指向 head_center）投到垂直干轴的面上、
                    指向内侧，y 指向后方。两个倾角照原项目的 load_vector（Bergmann 2016）在这个坐标系里换成合力
求解的命令交给 solve.py（同一个文件夹）。Abaqus 装在哪是机器的事：叫这个包的一方照清单 programs 里写的 abaqus 2025，
在机器清单里找到位置，放进 job 的 programs。这个包不自己去找（不看环境变量，不用旧系统配置里的位置）；建模时就核它在不在。

旧代码每个作业要一个自己的进程（它会改进程里的全局状态），所以这个入口一次只做一件事。
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace

sys.dont_write_bytecode = True      # 包在只读的地方跑：不管外面怎么设，都不往包里写 __pycache__

HERE = Path(__file__).resolve().parent
LEGACY = HERE / "legacy"
LEGACY_FILES = ("abaqus/odb_export.py", "config.yaml", "femur2d.py", "inp_writer.py", "plotstyle.py", "qoi.py", "run_abaqus.py",
                "spot3d/model3d.py", "spot3d/qoi3d.py", "stem2d.py", "v2/fe3d_geom.py", "v2/femur_real.py", "v2/geom3d.py",
                "v2/jobs.py", "v2/model3d_m1.py", "v2/model3d_v2.py", "v2/post.py", "v2/post_m1.py", "v2/stability.py")
UNIT = "m_fric"                     # 求解的那个作业叫什么（原项目的 <名字>_fric）
PROGRAM, RELEASE = "abaqus", "2025"  # 清单的 programs 里写的那个程序和它确切的版本
STEPS = ("RELEASE", "LOAD", "UNLOAD", "LOAD2")
UNSTABLE_UM = 150.0                 # 界面相对位移超过它就长不上骨（Pilliar 1986；Jasty 1997）。不收敛时拿它判是不是已经松动

# 这个包要的设定项。elastic_slip_um 只在罚摩擦时有
ALWAYS = ("E_canc_MPa", "override_region", "element", "h_int_mm", "h_far_mm", "dist_min_mm", "dist_max_mm", "models", "contact_faces",
          "normal", "sliding", "tangential", "mu", "cycles", "nlgeom", "max_increments", "initial_increment", "min_increment",
          "max_increment", "distal", "distal_from", "distal_cut_mm", "load_frame", "load_N", "load_front_deg", "load_sagit_deg",
          "load_point", "load_spread_mm", "delta_mm", "interference_method", "field_outputs", "contact_outputs", "cpus")
# 只有一种做法的几项：这个包只会这一种
ONLY = {"element": "C3D10", "models": "friction", "normal": "hard", "sliding": "small", "distal": "fixed", "load_frame": "shaft_neck"}
# 后处理要的输出：位移，接触应力（CPRESS）、接触位移（CSLIP）、接触状态
NEEDED = {"field_outputs": ("U",), "contact_outputs": ("CSTRESS", "CDISP", "CSTATUS")}
NODE_OUT, ELEMENT_OUT, CONTACT_OUT = ("U", "RF"), ("S", "E", "ELSE", "EVOL"), ("CSTRESS", "CDISP", "CSTATUS", "CFORCE", "CNAREA")
# 划不成网格时依次试的几档：（gmsh 的三维算法，界面尺寸乘多少）。原项目六档里换柄截面点数的那三档归柄空间包
ATTEMPTS = ((1, 1.0), (10, 1.0), (1, 0.97), (10, 0.97))
ON_FACES_MM = 1e-3                  # 网格节点离面组多近算落在面组上：节点就在几何面上，差的只是浮点误差


class Unsupported(Exception):
    """这个包做不了这件事。"""


# ---------------------------------------------------------------- 旧代码

def _legacy_on_path() -> None:
    os.environ.setdefault("MPLBACKEND", "Agg")
    for folder in (LEGACY, LEGACY / "v2"):
        if str(folder) not in sys.path:
            sys.path.insert(0, str(folder))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def launcher(job: dict) -> Path | None:
    """Abaqus 的启动器：叫这个包的一方照机器清单放进 job 的 programs。没有就是 None。"""
    given = (job.get("programs") or {}).get(PROGRAM) if isinstance(job.get("programs"), dict) else None
    return Path(given) if isinstance(given, str) and given else None


# ---------------------------------------------------------------- 设定和两份输入

def reading(settings) -> dict:
    """这个点的有限元设定。要的项都得在，而且是取值：不拿自己的默认值顶上。"""
    if not isinstance(settings, dict):
        raise Unsupported("job 里没有有限元设定（settings）")
    wanted = list(ALWAYS) + (["elastic_slip_um"] if settings.get("tangential") == "penalty" else [])
    missing = [name for name in wanted if settings.get(name) is None]
    if missing:
        raise Unsupported(f"有限元设定里少了 {missing}：这个包不拿自己的默认值顶上")
    left = [name for name in wanted if settings[name] == {"per_point": True}]
    if left:
        raise Unsupported(f"有限元设定里 {left} 写的还是“每个点给”，没有取值")
    other = [f"{name} 是 {settings[name]!r}" for name, value in ONLY.items() if settings[name] != value]
    if other:
        raise Unsupported(f"这个包只会 {ONLY} 这一种做法：{other}")
    if settings["tangential"] not in ("penalty", "lagrange") or settings["interference_method"] not in ("clearance", "offset"):
        raise Unsupported(f"切向行为只会 penalty、lagrange，过盈只会 clearance、offset：{settings['tangential']!r}、"
                          f"{settings['interference_method']!r}")
    lacking = [name for group, names in NEEDED.items() for name in names if name not in settings[group]]
    if lacking:
        raise Unsupported(f"后处理要这几样输出，设定里没要：{lacking}")
    if int(settings["cycles"]) < 2:
        raise Unsupported("加载循环数至少是 2：微动取第二循环")
    return settings


def reference(value, allowed: tuple) -> tuple[str, str, str]:
    """一个名字引用：（哪一份输入，哪一类，叫什么）。"""
    text = value.get("ref") if isinstance(value, dict) and set(value) == {"ref"} else None
    parts = text.split(".", 2) if isinstance(text, str) else []
    if len(parts) != 3 or f"{parts[0]}.{parts[1]}" not in allowed:
        raise Unsupported(f"名字引用要指向 {list(allowed)} 里的一样：{value!r}")
    return parts[0], parts[1], parts[2]


def unit(vector):
    import numpy as np

    vector = np.asarray(vector, float)
    size = float(np.linalg.norm(vector))
    if size < 1e-12:
        raise Unsupported("定不出方向：两个点重合")
    return vector / size


def bone_of(folder) -> SimpleNamespace:
    """骨模型：两个实体的文件、材料、标志点、哪一侧。"""
    import numpy as np

    try:
        listed = json.loads((Path(folder) / "manifest.json").read_text(encoding="utf-8"))
        solids = {name: Path(folder) / listed["solids"][name]["file"] for name in ("cortical", "cancellous")}
        points = {name: np.asarray(point["xyz"], float) for name, point in listed["landmarks"].items()}
        materials, side = listed["materials"], listed["side"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise Unsupported(f"读不出骨模型的清单：{type(error).__name__}: {error}") from None
    odd = [name for name in solids if materials.get(name, {}).get("model") != "linear_elastic"]
    if odd:
        raise Unsupported(f"骨模型里 {odd} 的材料不是 linear_elastic：这个包只会线弹性的骨")
    return SimpleNamespace(solids=solids, points=points, materials=materials, side=side)


def stem_of(folder, settings: dict) -> SimpleNamespace:
    """柄的模型：实体、接触的那组面、材料、特征点、放在骨上的位置。"""
    try:
        model = json.loads((Path(folder) / "stem_model.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise Unsupported(f"读不出柄的模型：{error}") from None
    _, _, name = reference(settings["contact_faces"], ("stem.faces",))
    if name not in model["faces"]:
        raise Unsupported(f"柄的模型里没有面组 {name!r}")
    if model["dimension"] != "3d" or len(model["regions"]) != 1:
        raise Unsupported("这个包只会三维的、一个区域的柄")
    (region,) = model["regions"]
    if region["geometry"]["kind"] != "solid" or region["material"].get("model") != "elastic":
        raise Unsupported(f"柄的区域 {region['name']!r} 要是实体、线弹性的材料，这里是 {region['geometry']['kind']}、"
                          f"{region['material'].get('model')}")
    if model["faces"][name]["region"] != region["name"]:
        raise Unsupported(f"面组 {name!r} 不在柄的区域 {region['name']!r} 上")
    if model["placement"]["cut"] is None:
        raise Unsupported("柄的模型里没有截骨面：这个包只会截骨以后放柄的模型")
    return SimpleNamespace(model=model, folder=Path(folder), solid=Path(folder) / region["geometry"]["file"], faces=name,
                           face_file=Path(folder) / model["faces"][name]["file"], material=region["material"],
                           frame=model["placement"]["frame"], cut=model["placement"]["cut"])


def matrix(origin, x, y, z) -> list[float]:
    """局部坐标换到骨模型的坐标：给 gmsh 的 affineTransform 的十二个数（按行）。"""
    return [x[0], y[0], z[0], origin[0], x[1], y[1], z[1], origin[1], x[2], y[2], z[2], origin[2]]


def placed(bone, stem, settings: dict) -> SimpleNamespace:
    """建模要的几何和数，都在骨模型的坐标里。"""
    import numpy as np

    _legacy_on_path()
    import model3d_v2 as M2

    points = bone.points
    up = unit(points["shaft_proximal"] - points["shaft_distal"])
    neck = points["head_center"] - points["neck_center"]
    medial = unit(neck - (neck @ up) * up)
    posterior = np.cross(up, medial) if bone.side == "right" else np.cross(medial, up)
    _, _, start = reference(settings["distal_from"], ("bone.landmark",))
    if start not in points:
        raise Unsupported(f"骨模型里没有标志点 {start!r}")
    bottom = points["shaft_distal"] + ((points[start] - points["shaft_distal"]) @ up - float(settings["distal_cut_mm"])) * up
    frame = {key: np.asarray(stem.frame[key], float) for key in ("origin", "x", "y", "z")}

    def to_bone(point):
        return frame["origin"] + point[0] * frame["x"] + point[1] * frame["y"] + point[2] * frame["z"]

    source, _, name = reference(settings["load_point"], ("bone.landmark", "stem.feature"))
    features = stem.model["features"]
    if name not in (points if source == "bone" else features):
        raise Unsupported(f"{source} 里没有 {name!r}")
    at = points[name] if source == "bone" else to_bone(np.asarray(features[name], float))
    in_frame = M2.load_vector({"load": {"resultant_N": float(settings["load_N"]), "alpha_front_deg": float(settings["load_front_deg"]),
                                        "alpha_sagit_deg": float(settings["load_sagit_deg"])}})
    force = in_frame[0] * medial + in_frame[1] * posterior + in_frame[2] * up
    normal = unit(stem.cut["normal"])
    across = min((np.eye(3)[k] for k in range(3)), key=lambda axis: abs(axis @ normal))
    _, _, region = reference(settings["override_region"], ("bone.region",))
    if region not in bone.solids:
        raise Unsupported(f"骨模型里没有区域 {region!r}")
    return SimpleNamespace(
        up=up, medial=medial, posterior=posterior, bottom=bottom, load_point=at, force=force, load_frame=in_frame,
        stem_matrix=matrix(frame["origin"], frame["x"], frame["y"], frame["z"]),
        box_matrix=matrix(bottom, medial, np.cross(up, medial), up),
        cut=SimpleNamespace(C03=np.asarray(stem.cut["point"], float), u3=normal, n3=unit(across - (across @ normal) * normal)),
        override=region, frame=frame)


# ---------------------------------------------------------------- 建模

def _keep(occ, place):
    """要留下的骨：远端截断面以上，截骨面以下（原项目 model3d_v2._keep 的写法，盒子换成沿干轴放）。"""
    import fe3d_geom as E

    box = [(3, occ.addBox(-300.0, -300.0, 0.0, 600.0, 600.0, 600.0))]
    occ.affineTransform(box, place.box_matrix)
    kept, _ = occ.intersect(box, E.kept_halfspace(occ, place.cut))
    return kept


def on_faces(file: Path, transform: list, points) -> "object":
    """每个点到这组面（STEP 里的面，照 transform 换到骨上）最近的距离。"""
    import gmsh
    import numpy as np

    points = np.asarray(points, float)
    path = os.environ.get("PATH", "")
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        faces = [one for one in gmsh.model.occ.importShapes(str(file)) if one[0] == 2]
        gmsh.model.occ.affineTransform(faces, transform)
        gmsh.model.occ.synchronize()
        best = np.full(len(points), np.inf)
        flat = points.ravel().tolist()
        for _, tag in faces:
            closest, _ = gmsh.model.getClosestPoint(2, tag, flat)
            best = np.minimum(best, np.linalg.norm(np.asarray(closest, float).reshape(-1, 3) - points, axis=1))
    finally:
        gmsh.finalize()
        os.environ["PATH"] = path               # gmsh 初始化时会把这个进程的 PATH 截短
    return best


def _segment(p, a, b):
    import numpy as np

    ab = b - a
    t = np.clip(((p - a) * ab).sum(1) / np.maximum((ab * ab).sum(1), 1e-30), 0.0, 1.0)
    return np.linalg.norm(p - (a + t[:, None] * ab), axis=1)


def _to_triangles(p, tri):
    """一个点到一组三角形的距离。"""
    import numpy as np

    a, b, c = tri[:, 0], tri[:, 1], tri[:, 2]
    v0, v1 = b - a, c - a
    n = np.cross(v0, v1)
    size = np.linalg.norm(n, axis=1)
    flat = ((p - a) * n).sum(1) / np.maximum(size, 1e-30)
    q = p - flat[:, None] * n / np.maximum(size, 1e-30)[:, None]
    v2 = q - a
    d00, d01, d11 = (v0 * v0).sum(1), (v0 * v1).sum(1), (v1 * v1).sum(1)
    d20, d21 = (v2 * v0).sum(1), (v2 * v1).sum(1)
    denom = np.maximum(d00 * d11 - d01 * d01, 1e-30)
    v = (d11 * d20 - d01 * d21) / denom
    w = (d00 * d21 - d01 * d20) / denom
    inside = (v >= 0) & (w >= 0) & (v + w <= 1) & (size > 1e-12)
    edges = np.minimum(np.minimum(_segment(p, a, b), _segment(p, b, c)), _segment(p, c, a))
    return np.where(inside, np.abs(flat), edges)


def canal_distance(elems: dict, coords: dict, nodes, cut, place) -> "object":
    """界面节点到髓腔壁的有符号距离，在松质里为负。髓腔壁是松质区域的表面，去掉和柄共用的面、截骨面上的、截断面上的。
    原项目是股骨的距离场插出来的（femur_real.canal_sdf）；这个包没有距离场，从网格算：三角形是直边的。"""
    import numpy as np
    from scipy.spatial import cKDTree
    from spot3d.model3d import FACES

    def faces_of(region):
        return [tuple(sorted(int(row[k]) for k in FACES[face])) for row in elems[region] for face in FACES]

    count: dict = {}
    for key in faces_of("cancellous"):
        count[key] = count.get(key, 0) + 1
    stem = set(faces_of("stem"))

    def on_plane(key, point, normal) -> bool:
        return all(abs(float((coords[n] - point) @ normal)) < 1e-6 for n in key)

    wall = [key for key, seen in count.items() if seen == 1 and key not in stem and not on_plane(key, cut.C03, cut.u3)
            and not on_plane(key, place.bottom, place.up)]
    if not wall:
        raise Unsupported("网格里找不到松质区域的表面（髓腔壁）")
    tri = np.array([[coords[n] for n in key] for key in wall])
    centres = tri.mean(1)
    reach = float(np.linalg.norm(tri - centres[:, None], axis=2).max())
    corners = np.unique(np.array(wall).ravel())
    near, _ = cKDTree(np.array([coords[int(n)] for n in corners])).query(np.array([coords[int(n)] for n in nodes]))
    tree = cKDTree(centres)
    inside_canc = {int(n) for n in elems["cancellous"].ravel()}
    touching_cortex = {int(n) for n in elems["cortex"].ravel()}
    found = np.empty(len(nodes))
    for k, n in enumerate(nodes):
        p = coords[int(n)]
        candidates = tree.query_ball_point(p, float(near[k]) + reach + 1e-9)
        size = float(_to_triangles(p, tri[candidates]).min())
        found[k] = -size if int(n) in inside_canc and int(n) not in touching_cortex else size
    return found


def build_once(where: Path, bone, stem, place, settings: dict, algo: int, h: float) -> dict:
    """照原项目 model3d_m1._build 建一个设计的摩擦模型，写 m_fric.inp、mesh3d.npz、model3d.json。失败抛 BuildError。"""
    import gmsh
    import model3d_m1 as M1
    import model3d_v2 as M2
    import numpy as np
    from inp_writer import Inp, _f

    path = os.environ.get("PATH", "")
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.NumThreads", 1)
        gmsh.model.add("m")
        occ = gmsh.model.occ
        C = [one for one in occ.importShapes(str(bone.solids["cortical"])) if one[0] == 3]
        K = [one for one in occ.importShapes(str(bone.solids["cancellous"])) if one[0] == 3]
        Ck, _ = occ.intersect(C, _keep(occ, place))
        Kk, _ = occ.intersect(K, _keep(occ, place))
        body = [one for one in occ.importShapes(str(stem.solid)) if one[0] == 3]
        if len(body) != 1:
            raise M2.BuildError("L1", f"the stem solid has {len(body)} volumes")
        occ.affineTransform(body, place.stem_matrix)
        cortex, _ = occ.cut(Ck, body, removeObject=True, removeTool=False)
        canc, _ = occ.cut(Kk, body, removeObject=True, removeTool=False)
        nb, nc = len(cortex), len(canc)
        _, fmap = occ.fragment(cortex + canc, body)
        occ.synchronize()
        cort_vols = sorted({t for dt in fmap[:nb] for d_, t in dt if d_ == 3})
        canc_vols = sorted({t for dt in fmap[nb:nb + nc] for d_, t in dt if d_ == 3})
        stem_vols = sorted({t for dt in fmap[nb + nc:] for d_, t in dt if d_ == 3})
        if not cort_vols or not canc_vols or not stem_vols:
            raise M2.BuildError("L3", f"fragment produced cortex {len(cort_vols)} / cancellous {len(canc_vols)} / stem {len(stem_vols)}")
        if set(stem_vols) & (set(cort_vols) | set(canc_vols)):
            raise M2.BuildError("L3", "stem and bone volumes overlap after fragment")
        gmsh.model.addPhysicalGroup(3, cort_vols, name="cortex")
        gmsh.model.addPhysicalGroup(3, canc_vols, name="cancellous")
        gmsh.model.addPhysicalGroup(3, stem_vols, name="stem")
        surfs = sorted({t for v in stem_vols for d_, t in gmsh.model.getBoundary([(3, v)], oriented=False) if d_ == 2})
        mesh = {"dist_min_mm": float(settings["dist_min_mm"]), "dist_max_mm": float(settings["dist_max_mm"])}
        M2._size_field(gmsh, surfs, {"mesh": mesh}, h, float(settings["h_far_mm"]))
        for key, value in M2.MESH_OPTS:
            gmsh.option.setNumber(key, value)
        gmsh.option.setNumber("Mesh.Algorithm3D", algo)
        gmsh.model.mesh.generate(3)
        elems, coords, quality = M2._extract(gmsh, {"cortex": cort_vols, "cancellous": canc_vols, "stem": stem_vols})
    finally:
        gmsh.finalize()
        os.environ["PATH"] = path               # gmsh 初始化时会把这个进程的 PATH 截短
    slave, master = M1.interface_faces(elems, ["cortex", "cancellous"])
    if len(slave) < 50:
        raise M2.BuildError("L3", f"interface too small: {len(slave)} faces")
    corners = sorted({int(elems[r][i][k]) for r, i, face in master for k in M1.FACES[face]})
    gaps = dict(zip(corners, on_faces(stem.face_file, place.stem_matrix, [coords[n] for n in corners])))
    off = sum(1 for r, i, face in master if max(gaps[int(elems[r][i][k])] for k in M1.FACES[face]) > ON_FACES_MM)
    if off:
        raise Unsupported(f"柄在面组 {stem.faces!r} 以外也碰到了骨（{off} 个网格面）：contact_faces 那一组面要是柄和骨接触的全部")
    delta, mu = float(settings["delta_mm"]), float(settings["mu"])
    method, lagrange = settings["interference_method"], settings["tangential"] == "lagrange"
    slip_tol = 0.0 if lagrange else float(settings["elastic_slip_um"]) * 1e-3 / float(settings["h_int_mm"])
    nodes, nrm, area, interf, on_cortex, on_collar = M1.node_pairs(elems, coords, slave, delta, plane=None)
    stem_f, coords_f, twin = M1.split_interface(elems, coords, nodes, nrm, interf, method)
    offs = {"cortex": 0, "cancellous": len(elems["cortex"]), "stem": len(elems["cortex"]) + len(elems["cancellous"])}
    elab = {k: np.arange(offs[k] + 1, offs[k] + 1 + len(v)) for k, v in elems.items()}
    used_stem = np.unique(elems["stem"].ravel())
    used_bone = np.unique(np.r_[elems["cortex"].ravel(), elems["cancellous"].ravel()])
    spread = float(settings["load_spread_mm"])
    head_n = [int(n) for n in used_stem if np.linalg.norm(coords[int(n)] - place.load_point) <= spread + 1e-6]
    fixed = [int(n) for n in used_bone if abs(float((coords[int(n)] - place.bottom) @ place.up)) < 1e-4]
    if len(head_n) < 10 or len(fixed) < 10:
        raise M2.BuildError("L3", f"load/BC node sets too small: head {len(head_n)}, fixed {len(fixed)}")
    if set(head_n) & {int(n) for n in nodes}:
        raise M2.BuildError("L3", "head load nodes touch the interface")
    canal = canal_distance(elems, coords, nodes, place.cut, place)
    F = place.force
    material = {name: (float(bone.materials[name]["E_MPa"]), float(bone.materials[name]["nu"])) for name in ("cortical", "cancellous")}
    material[place.override] = (float(settings["E_canc_MPa"]), material[place.override][1])
    element = settings["element"]

    inp = Inp(f"stem-lab fem-abaqus (M1-3406-v1 interface model) {UNIT} delta={delta} mu={mu} E_override={settings['E_canc_MPa']} "
              f"interference={method} slip_tol={slip_tol} lagrange={lagrange}")
    M1._write_nodes(inp, coords_f)
    inp.elements(element, "CORTEX", elab["cortex"], elems["cortex"])
    inp.elements(element, "CANC", elab["cancellous"], elems["cancellous"])
    inp.elements(element, "STEM", elab["stem"], stem_f)
    inp.material("CORTICAL", *material["cortical"])
    inp.material("CANCELLOUS", *material["cancellous"])
    inp.material("STEM", float(stem.material["E"]), float(stem.material["nu"]))
    inp.lines += ["*SOLID SECTION, ELSET=CORTEX, MATERIAL=CORTICAL", ",", "*SOLID SECTION, ELSET=CANC, MATERIAL=CANCELLOUS", ",",
                  "*SOLID SECTION, ELSET=STEM, MATERIAL=STEM", ","]
    inp.nset("HEADN", head_n)
    inp.nset("FIXED", fixed)
    inp.element_surface("S_BONE", [(elab[r][i], fc) for r, i, fc in slave])
    inp.element_surface("S_STEM", [(elab[r][i], fc) for r, i, fc in master])
    n_int, n_no = int((interf > 0).sum()), int((interf <= 0).sum())
    if n_int:
        inp.nset("NS_INTERF", nodes[interf > 0])
    if n_no:
        inp.nset("NS_NOINT", nodes[interf <= 0])
    inp.raw(M1.contact_block(mu, slip_tol, lagrange, method, delta, n_int, n_no))
    cycles = int(settings["cycles"])
    steps = ["PRESSFIT", "RELEASE", "LOAD", "UNLOAD", "LOAD2"] + [x for k in range(2, cycles) for x in (f"UNLOAD{k}", f"LOAD{k + 1}")]
    load = "\n".join(["*CLOAD, OP=NEW"] + [f"HEADN, {axis + 1}, {_f(F[axis] / len(head_n))}" for axis in range(3)])
    unload = "*CLOAD, OP=NEW\nHEADN, 1, 0.\nHEADN, 2, 0.\nHEADN, 3, 0."
    out = outputs(settings["field_outputs"], settings["contact_outputs"])
    opening = f", INC={int(settings['max_increments'])}" + (", NLGEOM=YES" if settings["nlgeom"] else "")
    static = (f"*STATIC\n{_f(settings['initial_increment'])}, {_f(1.0)}, {_f(settings['min_increment'])}, "
              f"{_f(settings['max_increment'])}")
    body = {"PRESSFIT": "*CONTACT INTERFERENCE, SHRINK\nS_BONE, S_STEM\n*BOUNDARY\nFIXED, 1, 3\nHEADN, 1, 3",
            "RELEASE": "*BOUNDARY, OP=NEW\nFIXED, 1, 3"}
    for name in steps:
        inp.raw(f"*STEP, NAME={name}{opening}\n{static}\n{body.get(name) or (unload if name.startswith('UNLOAD') else load)}\n"
                f"{out}\n*END STEP")
    inp.write(where / f"{UNIT}.inp")
    labs = np.array(sorted(coords_f))
    np.savez_compressed(where / "mesh3d.npz", cortex_conn=elems["cortex"], cancellous_conn=elems["cancellous"], stem_conn=stem_f,
                        stem_conn_bond=elems["stem"], **{f"{k}_elab": v for k, v in elab.items()}, node_labels=labs,
                        nodes=np.array([coords_f[int(n)] for n in labs]), pair_bone=nodes, pair_stem=twin, pair_normal=nrm,
                        pair_area=area, pair_interf=interf, pair_cortex=on_cortex, pair_collar=on_collar, pair_canal=canal)
    return {"name": "m", "model": "m1", "n_tet": {k: int(len(v)) for k, v in elems.items()}, "n_nodes": len(coords_f),
            "n_slave_faces": len(slave), "n_master_faces": len(master), "n_pairs": int(len(nodes)),
            "n_pairs_cortex": int(on_cortex.sum()), "interface_area_mm2": float(area.sum()),
            "cortex_area_frac": float(area[on_cortex].sum() / area.sum()), "n_head": len(head_n), "n_fixed": len(fixed), "collar": None,
            "slave": [[int(elab[r][i]), fc] for r, i, fc in slave], "h_int": h, "h_far": float(settings["h_far_mm"]), "delta": delta,
            "mu": mu, "torque": True, "E_override": float(settings["E_canc_MPa"]), "override_region": place.override,
            "slip_tol": slip_tol, "lagrange": lagrange, "interference": method, "cycles": cycles, "steps": steps,
            "load_N": [float(x) for x in F], "load_frame_N": [float(x) for x in place.load_frame],
            "load_point": [float(x) for x in place.load_point], "mesh_quality": quality,
            "mesh": {"h_int_mm": float(settings["h_int_mm"]), "h_far_mm": float(settings["h_far_mm"]), **mesh},
            "contact_faces": stem.faces, "off_group_faces": off,
            "frames": {"load": {"x": place.medial.tolist(), "y": place.posterior.tolist(), "z": place.up.tolist()},
                       "stem": {key: value.tolist() for key, value in place.frame.items()}},
            "cut": {"point": place.cut.C03.tolist(), "normal": place.cut.u3.tolist()},
            "truncation": {"point": place.bottom.tolist(), "normal": place.up.tolist()},
            "materials": {"CORTICAL": material["cortical"], "CANCELLOUS": material["cancellous"],
                          "STEM": [float(stem.material["E"]), float(stem.material["nu"])]}}


def outputs(field, contact) -> str:
    """每一步要哪些输出（原项目 model3d_m1 的 FIELD_M1、CONTACT_M1 的写法），照设定挑。"""
    lines = ["*OUTPUT, FIELD"]
    for keyword, known, chosen in (("*NODE OUTPUT", NODE_OUT, field), ("*ELEMENT OUTPUT", ELEMENT_OUT, field),
                                   ("*CONTACT OUTPUT", CONTACT_OUT, contact)):
        picked = [name for name in known if name in chosen]
        if picked:
            lines += [keyword, ", ".join(picked)]
    return "\n".join(lines)


def build(job: dict, out: Path) -> dict:
    settings = reading(job.get("settings"))
    if job.get("stem_model") is None:
        raise Unsupported("这个点没有柄的模型（无植入物）：这个有限元包只会 M1 的界面做法，不做无植入物的模型")
    stem = stem_of(job["stem_model"], settings)
    bone = bone_of(job["bone_model"])
    run_with = launcher(job)
    if run_with is None:
        return {"status": "env", "pre": {},
                "reason": f"job 里没有 {PROGRAM} {RELEASE} 的位置（programs）：要跑它的那台机器的机器清单里要写上它装在哪"}
    if not run_with.is_file():
        return {"status": "env", "reason": f"机器清单里写的 Abaqus 的启动器不在：{run_with}", "pre": {}}
    place = placed(bone, stem, settings)
    _legacy_on_path()
    import model3d_v2 as M2

    where = Path(job["job"])
    if where.exists():
        shutil.rmtree(where)
    where.mkdir(parents=True)
    errors = []
    for attempt, (algo, scale) in enumerate(ATTEMPTS, start=1):
        h = scale * float(settings["h_int_mm"])
        try:
            info = build_once(where, bone, stem, place, settings, algo, h)
        except Unsupported:
            raise
        except M2.BuildError as error:
            if error.level == "L1":
                return {"status": "error", "reason": str(error)[:600], "pre": {}}
            errors.append(f"algo {algo}, h {h:g}: {error}"[:300])
            continue
        except Exception as error:  # noqa: BLE001  gmsh/OCC 的异常类型不统一
            errors.append(f"algo {algo}, h {h:g}: {type(error).__name__}: {error}"[:300])
            continue
        info["mesh_attempt"] = {"attempt": attempt, "algorithm3d": algo, "h_int": h, "previous_errors": errors}
        (where / "model3d.json").write_text(json.dumps(info), encoding="utf-8")
        pre = {"n_tet": sum(info["n_tet"].values()), "n_pairs": info["n_pairs"], "mesh_attempt": attempt, "h_mesh_mm": h}
        command = ["{python}", str(HERE / "solve.py"), UNIT, str(int(settings["cpus"])), str(run_with)]
        return {"status": "built", "reason": "", "pre": pre, "solve": {"command": command}}
    return {"status": "mesh_failed", "reason": ("meshing failed after retries: " + " | ".join(errors))[:600], "pre": {}}


# ---------------------------------------------------------------- 后处理

def _keep_files(where: Path) -> dict:
    """这个作业该留下什么。odb 不留：场已经导出成 CSV 了。"""
    def there(*names):
        return [name for name in names if (where / name).is_file()]

    csv = sorted(path.relative_to(where).as_posix() for folder in where.glob(f"{UNIT}_csv*") for path in folder.glob("*"))
    return {"mesh": there("mesh3d.npz", "model3d.json"), "fields": csv,
            "process": there(f"{UNIT}.sta", f"{UNIT}.msg", f"{UNIT}.dat", f"{UNIT}.runner.log", "solve.json"),
            "settings": there(f"{UNIT}.inp")}


def _total(where: Path) -> int:
    try:
        return len(json.loads((where / "model3d.json").read_text(encoding="utf-8"))["steps"])
    except (OSError, ValueError, KeyError):
        return len(STEPS) + 1


def _steps_done(where: Path) -> int:
    """.sta 里走完了几个分析步。"""
    try:
        text = (where / f"{UNIT}.sta").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return 0
    steps = [int(parts[0]) for parts in (line.split() for line in text.splitlines()) if len(parts) > 7 and parts[0].isdigit()]
    return max(steps) - 1 if steps else 0


def _not_solved(where: Path, solved: dict) -> dict:
    """求解没有算完：是环境的事、是不收敛，还是别的。不收敛的再看停下之前柄是不是已经松动（照参照包的写法）。"""
    reason, code = str(solved.get("reason") or ""), solved.get("code")
    done = _steps_done(where)
    said = {"reason": f"{code or 'solver'}: {reason}"[:600], "steps": {"done": done, "total": _total(where)}}
    if code == "license_unavailable":
        return dict(said, status="env")
    if "TOO MANY ATTEMPTS" not in reason.upper():
        return dict(said, status="error")
    evidence = _loosened(where, done)
    if evidence is None:
        return dict(said, status="not_converged")
    return dict(said, status="unstable", evidence=evidence,
                reason=said["reason"] + f"；停在 {evidence['step']} 步，那时界面相对位移的 95 分位已经是 {evidence['slip_p95_um']:.0f} 微米")


def _loosened(where: Path, done: int):
    """不收敛的作业停下之前是不是已经松动。有证据就返回它，没有返回 None。

    证据要三样都成立：压配和释放两步已经算完；停在加载步里；停下前最后一个收敛的增量上，
    柄身界面相对释放后的切向相对位移，面积加权 95 分位已经超过长不上骨的阈值。
    """
    partial = where / f"{UNIT}_csv_partial"
    if done < 2 or not (partial / "RELEASE_U.csv").exists():
        return None
    last = next((step for step in reversed(STEPS[1:]) if (partial / f"{step}_U.csv").exists()), None)
    if last is None:
        return None
    try:
        _legacy_on_path()
        import numpy as np
        import post_m1 as PM1

        pairs = PM1.pairs(where)
        body = ~pairs["pair_collar"]
        moved = [PM1._utab(partial / f"{step}_U.csv", pairs["n"]) for step in ("RELEASE", last)]
        rel = [table[pairs["pair_stem"]] - table[pairs["pair_bone"]] for table in moved]
        change = (rel[1] - rel[0])[body]
        normal = pairs["pair_normal"][body]
        slip = np.linalg.norm(change - (change * normal).sum(1)[:, None] * normal, axis=1) * 1e3
        if not np.isfinite(slip).all():
            return None
        p95 = float(PM1._wq(slip, pairs["pair_area"][body], 0.95))
    except Exception:  # noqa: BLE001  证据算不出来就是没有证据
        return None
    return {"step": last, "slip_p95_um": p95, "line_um": UNSTABLE_UM} if p95 > UNSTABLE_UM else None


def _loaded(where: Path, info: dict) -> dict:
    """stability() 和它的台架读数共用的读入（原项目 stability._load 的那一份），柄的位姿从柄的模型拿：
    肩部中心 P0 是柄的坐标系的原点，柄轴是它的 z（指向远端），内侧、前方是它的 x、y；截骨面照柄的模型。"""
    import numpy as np
    import post_m1 as PM

    p = PM.pairs(where)
    frame = {key: np.asarray(value, float) for key, value in info["frames"]["stem"].items()}
    lut = {int(n): i for i, n in enumerate(p["node_labels"])}
    X = np.array([p["nodes"][lut[int(n)]] for n in p["pair_bone"]])
    U = {s: PM._utab(where / f"{UNIT}_csv" / f"{s}_U.csv", p["n"]) for s in STEPS}
    rel = {s: U[s][p["pair_stem"]] - U[s][p["pair_bone"]] for s in STEPS}
    cut = SimpleNamespace(C03=np.asarray(info["cut"]["point"], float), u3=np.asarray(info["cut"]["normal"], float))
    return {"d": where, "p": p, "fm": cut, "P0": frame["origin"], "ax": frame["z"] / np.linalg.norm(frame["z"]),
            "e_ml": frame["x"], "e_ap": frame["y"], "lut": lut, "X": X, "U": U, "rel": rel}


def _force_balance(where: Path, loaded: dict, info: dict) -> dict:
    """界面上骨侧接触力之和对外载：相对差。两者平衡，说明载荷加对了、加满了、读的是对的那一帧。"""
    import numpy as np
    import post_m1 as PM1

    load = np.asarray(info["load_N"], float)
    found = {f"load_{axis}_N": float(value) for axis, value in zip("xyz", info["load_frame_N"])}
    for step in ("LOAD", "LOAD2"):
        table = where / f"{UNIT}_csv" / f"{step}_CFORCE.csv"
        if table.exists():
            total = PM1._ftab(table, loaded["p"]["n"])[loaded["p"]["pair_bone"]].sum(0)
            found[f"iface_force_err_{step.lower()}"] = float(np.linalg.norm(total - load) / np.linalg.norm(load))
    return found


def _interface_field(path: Path, where: Path, loaded: dict, info: dict) -> None:
    """界面的点云：每个界面节点对的位置、法向、面积、过盈、四个分析步的相对位移，和它到髓腔壁的距离。都在骨模型的坐标里。"""
    import numpy as np

    pairs = loaded["p"]
    canal = np.load(where / "mesh3d.npz")["pair_canal"]
    np.savez_compressed(
        path, X=loaded["X"], normal=pairs["pair_normal"], area=pairs["pair_area"], interference=pairs["pair_interf"],
        cortex=pairs["pair_cortex"], collar=pairs["pair_collar"], steps=np.array(STEPS),
        rel=np.stack([loaded["rel"][step] for step in STEPS], axis=1), d_canal=canal,
        P0=np.asarray(loaded["P0"], float), stem_axis=np.asarray(loaded["ax"], float), e_ml=loaded["e_ml"], e_ap=loaded["e_ap"],
        head=np.asarray(info["load_point"], float), neck_axis=np.asarray(info["cut"]["normal"], float),
        cut_centre=np.asarray(info["cut"]["point"], float))


def post(job: dict, out: Path) -> dict:
    where = Path(job["job"])
    keep = _keep_files(where)
    record = where / "solve.json"
    solved = json.loads(record.read_text(encoding="utf-8")).get(UNIT) if record.is_file() else None
    if solved is None:
        return {"status": "env", "reason": "求解的进程没有留下 solve.json：多半是被外面结束了", "keep": keep,
                "steps": {"done": 0, "total": _total(where)}}
    if solved.get("status") != "OK":
        return dict(_not_solved(where, solved), keep=keep)
    total = _total(where)
    solver = {"name": "Abaqus/Standard", "release": solved.get("release"), "launcher": solved.get("launcher"),
              "wall_s": solved.get("wall_s"), "tries": solved.get("tries"), "odb": solved.get("odb_meta")}
    if solved.get("release") and not str(solved["release"]).startswith(RELEASE):
        return {"status": "error", "reason": f"求解用的是 Abaqus {solved['release']}，这个包要的是 {RELEASE}", "keep": keep,
                "steps": {"done": total, "total": total}, "solver": solver}
    _legacy_on_path()
    import jobs as J
    import stability as ST

    info = json.loads((where / "model3d.json").read_text(encoding="utf-8"))
    loaded = _loaded(where, info)
    ST._load = lambda d, job="m_fric": loaded         # 位姿从柄的模型拿，不从规格重建股骨；stability 本身一行不改
    labels = {**J.fric_only_result(where, UNIT), **ST.stability(where, UNIT)}
    labels.update(_force_balance(where, loaded, info))
    labels = {key: (float(value) if math.isfinite(value) else None)
              for key, value in labels.items() if isinstance(value, (int, float)) and not isinstance(value, bool)}
    _interface_field(out / "interface.npz", where, loaded, info)
    return {"status": "ok", "reason": "", "labels": labels, "fields": {"interface": "interface.npz"}, "keep": keep,
            "steps": {"done": total, "total": total}, "solver": solver}


# ---------------------------------------------------------------- 自检

def selfcheck(job: dict, out: Path) -> dict:
    """自检：这个包在这台机器的这个环境里还是不是打包时的那个。不用骨模型，不用 Abaqus，几秒钟。

    旧代码的每个文件还是原来的字节；导得进来；合力的方向、接触块的写法还是老样子；
    一根圆柱放进一块方的骨里，划网格、找界面、分节点对，数还是老数。
    """
    files = {name: _sha256(LEGACY / name)[:16] for name in LEGACY_FILES}
    _legacy_on_path()
    import gmsh
    import model3d_m1 as M1
    import model3d_v2 as M2

    load = [float(x) for x in M2.load_vector({"load": job["load"]})]
    block = M1.contact_block(**job["contact"])
    shape = job["cylinder"]
    path = os.environ.get("PATH", "")
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.NumThreads", 1)
        occ = gmsh.model.occ
        side = float(shape["box"])
        cube = [(3, occ.addBox(-side / 2, -side / 2, -side / 2, side, side, side))]
        rod = [(3, occ.addCylinder(0, 0, -shape["length"] / 2, 0, 0, shape["length"], shape["radius"]))]
        rest, _ = occ.cut(cube, rod, removeObject=True, removeTool=False)
        _, fmap = occ.fragment(rest, rod)
        occ.synchronize()
        canc = sorted({t for dt in fmap[:len(rest)] for d_, t in dt if d_ == 3})
        stem = sorted({t for dt in fmap[len(rest):] for d_, t in dt if d_ == 3})
        for key, value in M2.MESH_OPTS:
            gmsh.option.setNumber(key, value)
        gmsh.option.setNumber("Mesh.MeshSizeMin", shape["h"])
        gmsh.option.setNumber("Mesh.MeshSizeMax", shape["h"])
        gmsh.option.setNumber("Mesh.Algorithm3D", 1)
        gmsh.model.mesh.generate(3)
        elems, coords, _ = M2._extract(gmsh, {"cancellous": canc, "stem": stem})
    finally:
        gmsh.finalize()
        os.environ["PATH"] = path
    slave, master = M1.interface_faces(elems, ["cancellous"])
    nodes, _, area, interf, _, _ = M1.node_pairs(elems, coords, slave, 0.1)
    exact = 2 * math.pi * shape["radius"] * (shape["length"] + shape["radius"])
    return {"legacy": files, "load_N": load, "contact_block": hashlib.sha256(block.encode()).hexdigest()[:16],
            "cylinder": {"tets": {k: int(len(v)) for k, v in elems.items()}, "faces": len(slave), "pairs": int(len(nodes)),
                         "interfered": int((interf > 0).sum()), "area_mm2": float(area.sum()), "area_exact_mm2": exact}}


MODES = {"build": build, "post": post, "selfcheck": selfcheck}


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
    if mode == "build":
        result.setdefault("pre", {})
    (out / "result.json").write_text(json.dumps(result, default=float), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
