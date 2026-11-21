"""过渡颈快速核对（Linux）：命令行给预览设计名（preview9/preview.json 里的键），每个设计：建柄（含头）看是否单一实体、体积；
导出 STL 到 preview9b/<name>_loft.stl；在临时目录完整跑一次 M1.build（不求解），看截骨面上朝骨的界面面积。"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import time

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "code")); sys.path.insert(0, str(HOME / "code" / "v2")); sys.path.insert(0, str(HOME / "adhoc"))
import numpy as np  # noqa: E402

import fe3d_geom as E  # noqa: E402
import femur_real as FR  # noqa: E402
import geom3d as G  # noqa: E402
import model3d_m1 as M1  # noqa: E402
import neck_loft as NL  # noqa: E402
import stage_v2a as S  # noqa: E402
from neck_loft_check import bearing_nodes  # noqa: E402


def solid_check(st, fm, pl, stl):
    import gmsh
    pr = fm.cfg["prosthesis"]
    gmsh.initialize(); gmsh.option.setNumber("General.Terminal", 0)
    try:
        gmsh.model.add("p"); occ = gmsh.model.occ
        body = E.stem_solid(occ, st, pl["A0"], pl["pose"], delta=0.0, m=40)
        body_in, _ = occ.intersect(body, E.kept_halfspace(occ, fm))
        a = fm.C03; Lneck = float(np.linalg.norm(fm.H - a))
        neck = occ.addCylinder(*a, *(Lneck * fm.u3), pr["neck_radius_mm"])
        v_neck = occ.getMass(3, neck)
        head = occ.addSphere(*fm.H, pr["head_radius_mm"])
        out, _ = occ.fuse(body_in, [(3, neck), (3, head)])
        occ.synchronize()
        vols = [t for d, t in out if d == 3]
        res = {"n_volumes": len(vols), "v_loft_mm3": v_neck, "v_stem_mm3": sum(occ.getMass(3, t) for t in vols)}
        gmsh.option.setNumber("Mesh.MeshSizeMax", 1.0); gmsh.option.setNumber("Mesh.MeshSizeMin", 0.3)
        gmsh.model.mesh.generate(2)
        gmsh.write(str(stl))
        return res
    finally:
        gmsh.finalize()


if __name__ == "__main__":
    prev = json.loads((HOME / "deck" / "preview9" / "preview.json").read_text())
    fm0 = FR.build()
    NL.install(r_head=float(fm0.cfg["prosthesis"]["head_radius_mm"]))
    out = HOME / "deck" / "preview9b"
    for name in sys.argv[1:]:
        d, h = prev[name]["design"], prev[name]["h_cut"]
        fm = fm0.with_cut(h); st = G.Stem3D(**d); pl = G.template(st, fm)
        try:
            r = solid_check(st, fm, pl, out / f"{name}_loft.stl")
        except Exception as e:                                          # noqa: BLE001
            r = {"solid_error": f"{type(e).__name__}: {e}"[:200]}
        try:
            with tempfile.TemporaryDirectory() as td:
                t0 = time.perf_counter()
                info = M1.build(st, fm, pl, pathlib.Path(td), "m", h_int=S.H_PROD, delta=0.025, slip_tol=2.5e-4)
                n, a_, _ = bearing_nodes(pathlib.Path(td), fm)
                r.update(m1="ok", n_tet=info.get("n_tet"), bearing_area_mm2=a_, build_s=round(time.perf_counter() - t0))
        except Exception as e:                                          # noqa: BLE001
            r["m1"] = f"FAIL {type(e).__name__}: {e}"[:220]
        print(name, json.dumps(r, default=float), flush=True)
