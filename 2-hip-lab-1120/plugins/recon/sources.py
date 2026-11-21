"""【自由】认出是 CT 还是 CAD，读进来。

CAD 骨源：一个文件夹里两个 STEP 实体，皮质和松质各一个，哪个文件是哪个由重建设定说。
CT 骨源：里面有 CT 的体数据（nrrd、nii、mha）；怎么读、怎么重建在 ct.py 里。一组 dcm 认得出是 CT，
但 ct.py 不直接读它：要先转成一个 nrrd。
文件夹里有 STEP 就算 CAD，否则有 CT 的文件就算 CT。

读进来的实体是它的表面三角网：顶点、三角形（绕向朝实体外面）、实体的体积。STEP 由 gmsh 读；
CT 重建出来的实体是 STL（见 solids.py），直接读。
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np

CAD = (".step", ".stp")
CT = (".dcm", ".nii", ".nii.gz", ".nrrd", ".mha", ".mhd")


def kind_of(folder) -> str:
    """这份骨源是什么：cad、ct，或者认不出来的 unknown。"""
    names = [path.name.lower() for path in Path(folder).rglob("*") if path.is_file()]
    if any(name.endswith(CAD) for name in names):
        return "cad"
    if any(name.endswith(CT) or name == "dicomdir" for name in names):
        return "ct"
    return "unknown"


def read_step(path, size: float = 4.0) -> dict:
    """一个 STEP 文件里实体的表面三角网。size 是三角形的最大边长，毫米。"""
    import gmsh

    kept = os.environ.get("PATH", "")
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.occ.importShapes(str(path))
        gmsh.model.occ.synchronize()
        solids = gmsh.model.getEntities(3)
        if not solids:
            raise ValueError(f"{Path(path).name} 里没有实体")
        volume = sum(gmsh.model.occ.getMass(3, tag) for _, tag in solids)
        gmsh.option.setNumber("Mesh.MeshSizeMax", size)
        gmsh.option.setNumber("Mesh.MeshSizeMin", size / 4.0)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 8)
        gmsh.option.setNumber("Mesh.Algorithm", 6)
        gmsh.model.mesh.generate(2)
        tags, coords, _ = gmsh.model.mesh.getNodes()
        row = {int(tag): number for number, tag in enumerate(tags)}
        triangles = []
        for _, surface in gmsh.model.getEntities(2):
            kinds, _, nodes = gmsh.model.mesh.getElements(2, surface)
            for kind, listed in zip(kinds, nodes):
                if kind == 2:
                    triangles.append(np.array([row[int(tag)] for tag in listed], dtype=np.int64).reshape(-1, 3))
        return {"vertices": np.asarray(coords, float).reshape(-1, 3), "triangles": np.vstack(triangles),
                "volume": float(volume), "solids": len(solids)}
    finally:
        gmsh.finalize()
        os.environ["PATH"] = kept           # gmsh 初始化时会把这个进程的 PATH 截短；用完原样放回去，不然之后起不了别的程序


def read_stl(path) -> dict:
    """一个 STL 实体的表面三角网。体积是表面围出来的（带腔的实体，腔的那一块法向朝里，体积自然减掉）；
    solids 是法向朝外的块数，也就是实体的个数。"""
    from plugins.recon import solids

    vertices, triangles = solids.read_stl(path)
    outward = sum(1 for part in solids.split(vertices, triangles) if solids.signed_volume(*part) > 0)
    return {"vertices": vertices, "triangles": triangles, "volume": abs(solids.signed_volume(vertices, triangles)), "solids": outward}


def read_solid(path, size: float = 4.0) -> dict:
    """照文件的种类读一个实体：STL 直接读，别的当 STEP 读。"""
    return read_stl(path) if Path(path).suffix.lower() == ".stl" else read_step(path, size)


def watertight(mesh: dict) -> bool:
    """表面是不是封闭的：每条边正好被两个三角形共用。"""
    triangles = mesh["triangles"]
    edges = np.sort(np.vstack([triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]]), axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    return bool((counts == 2).all())


def quality(mesh: dict) -> np.ndarray:
    """每个三角形的质量：4√3 × 面积 ÷ 三边平方和。正三角形是 1，越扁越接近 0。"""
    a, b, c = (mesh["vertices"][mesh["triangles"][:, k]] for k in range(3))
    area = np.linalg.norm(np.cross(b - a, c - a), axis=1) / 2.0
    edges = ((b - a) ** 2).sum(1) + ((c - b) ** 2).sum(1) + ((a - c) ** 2).sum(1)
    return 4.0 * np.sqrt(3.0) * area / np.maximum(edges, 1e-300)


def quality_histogram(mesh: dict, bins: int = 10) -> dict:
    """三角形质量的分布：0 到 1 分成 bins 段，每段有几个三角形。"""
    counts, edges = np.histogram(np.clip(quality(mesh), 0.0, 1.0), bins=bins, range=(0.0, 1.0))
    return {"edges": [round(float(edge), 6) for edge in edges], "counts": [int(count) for count in counts]}


def enclosed_volume(mesh: dict) -> float:
    """表面三角网围出的体积。和实体自己报的体积对得上，说明三角网没有破、绕向也对。"""
    a, b, c = (mesh["vertices"][mesh["triangles"][:, k]] for k in range(3))
    return float(abs(np.einsum("ij,ij->i", a, np.cross(b, c)).sum()) / 6.0)
