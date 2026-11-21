"""CT 这条路的测试共用的形状：tests/real.py 里那根假股骨，做成外表面和内壁两个三角网。"""
from __future__ import annotations

import os

from plugins.recon import solids, sources
from tests import real


def whole_femur(path) -> tuple:
    """假股骨不挖内腔的整根外形：写成 STEP，再读成三角网。

    皮质实体的表面不能直接当外形：那根假股骨的松质芯在颈根的平面上露到了外面，内外两个面连成一块，分不出“最外层”。
    """
    import gmsh

    kept = os.environ.get("PATH", "")
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        real._femur_shapes(gmsh.model.occ, inner=False)
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()
        os.environ["PATH"] = kept               # gmsh 初始化时会把这个进程的 PATH 截短；用完原样放回去
    mesh = sources.read_step(path, 2.0)
    return solids.outward((mesh["vertices"], mesh["triangles"]))


def core(tmp) -> tuple:
    """假股骨的松质芯的表面。"""
    mesh = sources.read_step(real.cad_femur(tmp / "cad") / "cancellous.step", 2.0)
    return solids.outward((mesh["vertices"], mesh["triangles"]))
