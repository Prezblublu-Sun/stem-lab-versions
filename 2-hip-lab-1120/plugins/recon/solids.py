"""【自由】转成 FEA 要的两个实体。

CAD 骨源的两个实体本来就是 FEA 要的样子：原样用，一个字节不动。这样内核认实体认的是文件的哈希，
重建前后是同一个文件，对得上。

CT 骨源是从两个表面来的（外表面和内壁，见 ct.py）。照 2026-11 第二版流程的第 16 步把它们变成划得了网格的表面：
    MeshLab 修复（合并重复顶点、修非流形边和顶点、补不超过 30 条边的洞），再等边长重划
    外表面的目标边长默认 2.5 mm，内壁是它的 0.8 倍（内壁更不规则）；迭代 8 次；夹角大于 60 度的棱保留
两个实体写成两个 STL：
    皮质 = 外表面和内壁之间。文件里是外表面，加上法向朝里的内壁
    松质 = 内壁以内（含髓腔）。文件里是内壁
内壁在两个文件里是同一组顶点，所以两个实体在界面上对得上。

tet_check 照第 17 步真的划一次四面体，量出单元质量：这两个表面围得出合格的网格，才算“FEA 要的实体”。
划出来的网格不留，只留量出来的数；真用的网格由内核照它自己的需要去划。

重建设定里和这里有关的项（写在 ct 里，都可以不写）：
    edge_mm 2.5、inner_factor 0.8、remesh_iterations 8、tet_check true
"""
from __future__ import annotations

import math
import os
import struct
from pathlib import Path

import numpy as np

NAMES = ("cortical", "cancellous")
DEFAULTS = {"edge_mm": 2.5, "inner_factor": 0.8, "remesh_iterations": 8, "tet_check": True}

# from_surfaces 量出来的数，说的是重划之后的那两个表面。两个实体都没被人工换过时，定稿用的就是这两个表面，照抄；
# 换过一个，就不再是定稿的实体的数，不沿用（rebuild.finalize）
REMESH_MEASURES = (
    *(f"{side}_{what}" for side in ("outer", "inner")
      for what in ("triangles", "open_edges", "triangle_quality_min", "triangle_quality_p01",
                   "remesh_deviation_mean_mm", "remesh_deviation_p95_mm", "remesh_deviation_max_mm", "volume_mm3")),
    "remesh_deviation_p95_mm", "surfaces_open_edges",
)
_RECORD = np.dtype([("normal", "<3f4"), ("corners", "<9f4"), ("extra", "<u2")])


def from_cad(folder: Path, files: dict) -> dict:
    """CAD 骨源里的两个实体文件：{"cortical": 文件, "cancellous": 文件}。"""
    found = {name: Path(folder) / str(files[name]) for name in NAMES}
    missing = [str(path.name) for path in found.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"骨源里没有这几个文件：{missing}")
    if found["cortical"].resolve() == found["cancellous"].resolve():
        raise ValueError("皮质和松质不能是同一个文件")
    return found


def options(setting: dict) -> dict:
    return {**DEFAULTS, **{name: value for name, value in (setting.get("ct") or {}).items() if name in DEFAULTS}}


def problems(setting: dict) -> list[str]:
    how, found = options(setting), []
    for name, low, high in (("edge_mm", 0.5, 10.0), ("inner_factor", 0.3, 1.5)):
        if isinstance(how[name], bool) or not isinstance(how[name], (int, float)) or not low <= how[name] <= high:
            found.append(f"ct.{name} 要在 {low} 和 {high} 之间")
    if isinstance(how["remesh_iterations"], bool) or not isinstance(how["remesh_iterations"], int) or not 1 <= how["remesh_iterations"] <= 50:
        found.append("ct.remesh_iterations 要是 1 到 50 之间的整数")
    if not isinstance(how["tet_check"], bool):
        found.append("ct.tet_check 写 true 或 false")
    return found


# ---------------------------------------------------------------- STL

def read_stl(path) -> tuple:
    """读一个二进制 STL。返回（顶点，三角形）：位置相同的顶点合成一个。"""
    with open(path, "rb") as stream:
        stream.read(80)
        count = struct.unpack("<I", stream.read(4))[0]
        rows = np.fromfile(stream, dtype=_RECORD, count=count)
    if len(rows) != count:
        raise ValueError(f"{Path(path).name} 不是完整的二进制 STL")
    corners = rows["corners"].reshape(-1, 3)
    vertices, index = np.unique(corners, axis=0, return_inverse=True)
    return vertices.astype(float), index.reshape(-1, 3).astype(np.int64)


def write_stl(path, vertices, triangles) -> None:
    corners = np.asarray(vertices)[np.asarray(triangles)].astype("<f4")
    normal = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-12)
    rows = np.zeros(len(corners), dtype=_RECORD)
    rows["normal"], rows["corners"] = normal, corners.reshape(-1, 9)
    with open(path, "wb") as stream:
        stream.write(b"\0" * 80 + struct.pack("<I", len(rows)))
        rows.tofile(stream)


def signed_volume(vertices, triangles) -> float:
    """表面围出的体积，带正负号：法向朝外是正的。"""
    a, b, c = (np.asarray(vertices)[np.asarray(triangles)[:, k]] for k in range(3))
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def open_edges(triangles) -> int:
    """不是正好被两个三角形共用的边有几条。0 就是封闭的。"""
    edges = np.sort(np.vstack([triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]]), axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    return int((counts != 2).sum())


def quality(vertices, triangles) -> np.ndarray:
    a, b, c = (vertices[triangles[:, k]] for k in range(3))
    area = np.linalg.norm(np.cross(b - a, c - a), axis=1) / 2.0
    edges = ((b - a) ** 2).sum(1) + ((c - b) ** 2).sum(1) + ((a - c) ** 2).sum(1)
    return 4.0 * math.sqrt(3.0) * area / np.maximum(edges, 1e-300)


# ---------------------------------------------------------------- 点到表面的距离

def _to_triangles(p, a, b, c) -> np.ndarray:
    """点 p 到三角形 (a, b, c) 的距离，逐行算（Ericson 的分区判断）。"""
    ab, ac, ap = b - a, c - a, p - a
    d1, d2 = (ab * ap).sum(1), (ac * ap).sum(1)
    bp = p - b
    d3, d4 = (ab * bp).sum(1), (ac * bp).sum(1)
    cp = p - c
    d5, d6 = (ab * cp).sum(1), (ac * cp).sum(1)
    vc, vb, va = d1 * d4 - d3 * d2, d5 * d2 - d1 * d6, d3 * d6 - d5 * d4
    total = np.maximum(va + vb + vc, 1e-18)
    v, w = vb / total, vc / total
    q = a + ab * v[:, None] + ac * w[:, None]

    def on_edge(x, y, t):
        return x + (y - x) * np.clip(t, 0, 1)[:, None]

    m = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
    q[m] = on_edge(a[m], b[m], d1[m] / np.maximum(d1[m] - d3[m], 1e-18))
    m = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
    q[m] = on_edge(a[m], c[m], d2[m] / np.maximum(d2[m] - d6[m], 1e-18))
    m = (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)
    q[m] = on_edge(b[m], c[m], (d4[m] - d3[m]) / np.maximum((d4[m] - d3[m]) + (d5[m] - d6[m]), 1e-18))
    m = (d1 <= 0) & (d2 <= 0)
    q[m] = a[m]
    m = (d3 >= 0) & (d4 <= d3)
    q[m] = b[m]
    m = (d6 >= 0) & (d5 <= d6)
    q[m] = c[m]
    return np.linalg.norm(p - q, axis=1)


def distance(points, vertices, triangles, near: int = 16) -> np.ndarray:
    """每个点到一个三角形表面的距离：在形心离它最近的 near 个三角形里找。"""
    from scipy.spatial import cKDTree

    corners = vertices[triangles]
    _, nearest = cKDTree(corners.mean(1)).query(points, k=min(near, len(corners)))
    nearest = nearest.reshape(len(points), -1)
    best = np.full(len(points), np.inf)
    for column in range(nearest.shape[1]):
        chosen = corners[nearest[:, column]]
        best = np.minimum(best, _to_triangles(points, chosen[:, 0], chosen[:, 1], chosen[:, 2]))
    return best


# ---------------------------------------------------------------- CT：两个表面变成两个实体

def remesh(path, edge: float, iterations: int) -> tuple:
    """MeshLab：修复，再等边长重划。返回（顶点，三角形），法向朝外。"""
    import pymeshlab

    meshes = pymeshlab.MeshSet()
    meshes.load_new_mesh(str(path))
    meshes.meshing_remove_duplicate_vertices()
    meshes.meshing_repair_non_manifold_edges()
    meshes.meshing_repair_non_manifold_vertices()
    meshes.meshing_close_holes(maxholesize=30)
    try:
        target = pymeshlab.PureValue(edge)
    except AttributeError:
        target = pymeshlab.AbsoluteValue(edge)
    meshes.meshing_isotropic_explicit_remeshing(iterations=iterations, adaptive=False, targetlen=target, featuredeg=60.0)
    made = meshes.current_mesh()
    vertices, triangles = made.vertex_matrix().astype(float), made.face_matrix().astype(np.int64)
    if signed_volume(vertices, triangles) < 0:
        triangles = triangles[:, ::-1].copy()
    return vertices, triangles


def from_surfaces(outer_file, inner_file, folder: Path, setting: dict) -> dict:
    """外表面和内壁两个 STL 变成皮质、松质两个实体的文件。返回 files、measures、surfaces（重划后的两个表面）。"""
    how, folder = options(setting), Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    edge = {"outer": float(how["edge_mm"]), "inner": float(how["edge_mm"]) * float(how["inner_factor"])}
    surfaces, measures = {}, {}
    for name, path in (("outer", outer_file), ("inner", inner_file)):
        before, _ = read_stl(path)
        vertices, triangles = remesh(path, edge[name], int(how["remesh_iterations"]))
        shape, away = quality(vertices, triangles), distance(before, vertices, triangles)     # 新的顶点是投到原表面上的，所以量的是原表面到新表面
        measures.update({f"{name}_triangles": int(len(triangles)), f"{name}_open_edges": open_edges(triangles),
                         f"{name}_triangle_quality_min": float(shape.min()), f"{name}_triangle_quality_p01": float(np.percentile(shape, 1)),
                         f"{name}_remesh_deviation_mean_mm": float(away.mean()), f"{name}_remesh_deviation_p95_mm": float(np.percentile(away, 95)),
                         f"{name}_remesh_deviation_max_mm": float(away.max()), f"{name}_volume_mm3": abs(signed_volume(vertices, triangles))})
        surfaces[name] = (vertices, triangles)
    measures["remesh_deviation_p95_mm"] = max(measures["outer_remesh_deviation_p95_mm"], measures["inner_remesh_deviation_p95_mm"])
    measures["surfaces_open_edges"] = measures["outer_open_edges"] + measures["inner_open_edges"]
    files = write(surfaces, folder)
    return {"files": files, "measures": measures, "surfaces": surfaces}


def write(surfaces: dict, folder: Path) -> dict:
    """照两个表面写出两个实体的 STL。"""
    (outer, shell), (inner, core) = surfaces["outer"], surfaces["inner"]
    Path(folder).mkdir(parents=True, exist_ok=True)
    files = {name: Path(folder) / f"{name}.stl" for name in NAMES}
    write_stl(files["cortical"], np.vstack([outer, inner]), np.vstack([shell, core[:, ::-1] + len(outer)]))
    write_stl(files["cancellous"], inner, core)
    return files


def split(vertices, triangles) -> list:
    """把一个三角网按相连分成几块：[(顶点, 三角形)]，包围盒大的在前。"""
    parent = np.arange(len(vertices))

    def root(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for a, b, c in triangles:
        first = root(int(a))
        for other in (int(b), int(c)):
            found = root(other)
            if found != first:
                parent[found] = first
    roots = np.array([root(node) for node in range(len(vertices))])
    parts = []
    for one in np.unique(roots[triangles[:, 0]]):
        kept = triangles[roots[triangles[:, 0]] == one]
        used, index = np.unique(kept, return_inverse=True)
        parts.append((vertices[used], index.reshape(-1, 3)))
    return sorted(parts, key=lambda part: -float(np.prod(part[0].max(0) - part[0].min(0))))


def outward(surface: tuple) -> tuple:
    """同一个表面，法向朝外。"""
    vertices, triangles = surface
    return (vertices, triangles) if signed_volume(vertices, triangles) > 0 else (vertices, triangles[:, ::-1].copy())


def surfaces_of(files: dict) -> dict | None:
    """从两个实体的文件里取回外表面（outer）和内壁（inner，松质实体的表面）。seam 是皮质实体自己带的那份内壁。
    不是这里写出来的那种（STL，皮质两块、松质一块）就是 None。"""
    if any(Path(files[name]).suffix.lower() != ".stl" for name in NAMES):
        return None
    shell, core = split(*read_stl(files["cortical"])), split(*read_stl(files["cancellous"]))
    if len(shell) != 2 or len(core) != 1:
        return None
    return {"outer": outward(shell[0]), "inner": outward(core[0]), "seam": outward(shell[1])}


def wall(surfaces: dict) -> dict:
    """皮质有多厚：内壁上各点到外表面的距离。另量两个实体在界面上对不对得上：皮质实体带的内壁和松质实体的表面最远差多少。"""
    away = distance(surfaces["inner"][0], *surfaces["outer"])
    found = {"wall_min_mm": float(away.min()), "wall_p05_mm": float(np.percentile(away, 5)), "wall_median_mm": float(np.median(away)),
             "wall_max_mm": float(away.max())}
    if "seam" in surfaces:
        found["interface_gap_max_mm"] = float(max(distance(surfaces["seam"][0], *surfaces["inner"]).max(),
                                                  distance(surfaces["inner"][0], *surfaces["seam"]).max()))
    return found


def reconcile(files: dict, replaced: set, folder: Path) -> tuple:
    """人工换掉了 CT 那种实体里的一个：把另一个照它重写，两个实体在界面上才对得上。返回（两个实体的文件，做了什么）。

    换了松质（也就是内壁）：皮质 = 原来的外表面 + 新的内壁。
    换了皮质：它带着内壁（两块），松质就照这份内壁重写；它只有外表面（一块），就配上原来的内壁写成皮质壳。
    不是这种实体、两个都换了、一个都没换，原样返回，做了什么是 None。
    """
    if len(replaced) != 1 or any(Path(files[name]).suffix.lower() != ".stl" for name in NAMES):
        return files, None
    shell, core = split(*read_stl(files["cortical"])), split(*read_stl(files["cancellous"]))
    if len(core) != 1:
        return files, None
    if "cancellous" in replaced:
        if len(shell) != 2:
            return files, None
        outer, inner, said = shell[0], core[0], "换的是松质实体，也就是内壁：皮质实体照新的内壁重写了，外表面不变"
    elif len(shell) == 2:
        outer, inner, said = shell[0], shell[1], "换的皮质实体带着新的内壁：松质实体照这份内壁重写了"
    elif len(shell) == 1:
        outer, inner, said = shell[0], core[0], "换的皮质实体只有外表面：配上原来的内壁写成了皮质壳"
    else:
        return files, None
    return write({"outer": outward(outer), "inner": outward(inner)}, folder), said


def tet_check(surfaces: dict, edge: float) -> dict:
    """照两个表面划一次四面体（皮质一个区、松质一个区，界面上共用节点），量出单元质量。网格不留。"""
    import gmsh

    kept = os.environ.get("PATH", "")
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.NumThreads", 2)
        gmsh.model.add("femur")
        shift = 0
        for tag, name in ((1, "outer"), (2, "inner")):
            vertices, triangles = surfaces[name]
            gmsh.model.addDiscreteEntity(2, tag)
            gmsh.model.mesh.addNodes(2, tag, (np.arange(len(vertices)) + 1 + shift).tolist(), vertices.ravel().tolist())
            gmsh.model.mesh.addElementsByType(tag, 2, [], (triangles.ravel() + 1 + shift).tolist())
            shift += len(vertices)
        gmsh.model.mesh.createTopology()
        gmsh.model.geo.addSurfaceLoop([1], 1)
        gmsh.model.geo.addSurfaceLoop([2], 2)
        gmsh.model.geo.addVolume([1, 2], 1)
        gmsh.model.geo.addVolume([2], 2)
        gmsh.model.geo.synchronize()
        gmsh.option.setNumber("Mesh.Algorithm3D", 1)
        gmsh.option.setNumber("Mesh.MeshSizeMax", edge * 1.6)
        gmsh.option.setNumber("Mesh.MeshSizeMin", edge * 0.4)
        gmsh.option.setNumber("Mesh.Optimize", 1)
        gmsh.option.setNumber("Mesh.OptimizeNetgen", 1)
        gmsh.model.mesh.generate(3)
        for _ in range(3):
            gmsh.model.mesh.optimize("Relocate3D")
            gmsh.model.mesh.optimize("Netgen")
        counts = {}
        for volume, name in ((1, "cortical"), (2, "cancellous")):
            _, tags, _ = gmsh.model.mesh.getElements(3, volume)
            counts[name] = int(sum(len(part) for part in tags))
        _, tags, _ = gmsh.model.mesh.getElements(3)
        tags = np.concatenate(tags).tolist()
        gamma = np.array(gmsh.model.mesh.getElementQualities(tags, "gamma"))
        sicn = np.array(gmsh.model.mesh.getElementQualities(tags, "minSICN"))
        return {"tet_count": sum(counts.values()), "tet_count_cortical": counts["cortical"], "tet_count_cancellous": counts["cancellous"],
                "tet_gamma_min": float(gamma.min()), "tet_gamma_p01": float(np.percentile(gamma, 1)), "tet_gamma_median": float(np.median(gamma)),
                "tet_inverted": int((sicn <= 0).sum()), "tet_edge_mm": float(edge)}
    finally:
        gmsh.finalize()
        os.environ["PATH"] = kept           # gmsh 初始化时会把这个进程的 PATH 截短；用完原样放回去
