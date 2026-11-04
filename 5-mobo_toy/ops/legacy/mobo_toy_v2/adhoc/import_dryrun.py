"""外部柄（import_stem）的空跑（Linux，不提交作业）：按 jobs.prep 的顺序装钩子、选号、完整建 M1 模型（不求解），
核对：能否建成、四面体数、领节点数、截骨面上朝骨的界面面积；另在一个空模型里单独建出重建零件（柄体 + 领 + 颈 + 锥颈，不含头），
量体积，与原 STL（15.06 cm³）对比。"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import time

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "code")); sys.path.insert(0, str(HOME / "code" / "v2"))
import numpy as np  # noqa: E402

import geom3d as G  # noqa: E402
import jobs as J  # noqa: E402
import model3d_m1 as M1  # noqa: E402

SPEC = {"kind": "variant", "stage": "user_part", "tag": "Part3-1", "h_int": 2.0, "min_A0": 153.93804002589985, "model": "m1",
        "slip_tol": 0.00025, "delta": 0.025, "h_cut": 25.0, "import_stem": "part3_1", "import_e": 0.0, "bond_collar": "tied"}

if __name__ == "__main__":
    import fe3d_geom as E
    import import_stem as IS
    p = IS.PARTS["part3_1"]
    spec = {**SPEC, "design": {**p["design"], "alpha": round(IS.neck_angle_deg(J.femur_for({**SPEC, "design": p["design"]})), 4)}}
    fm = J.femur_for(spec)
    info0 = IS.install(spec, fm)
    print("install:", json.dumps(info0))
    st = G.Stem3D(**spec["design"])
    pl = G.template(st, fm)
    print("template:", {k: (round(v, 3) if isinstance(v, float) else v) for k, v in pl.items() if k != "pose"})
    # 重建零件的体积（不含头）
    import gmsh
    gmsh.initialize(); gmsh.option.setNumber("General.Terminal", 0)
    try:
        gmsh.model.add("v"); occ = gmsh.model.occ
        body = E.stem_solid(occ, st, pl["A0"], pl["pose"])
        body_in, _ = occ.intersect(body, E.kept_halfspace(occ, fm))
        col = E.collar_solid(occ, fm, E.collar_outline(st, fm, pl)["poly"], p["collar"][2])
        neck = occ.addCylinder(*fm.C03, *(25.0 * fm.u3), 7.0)
        out, _ = occ.fuse(body_in, col + [(3, neck)])
        occ.synchronize()
        vol = sum(occ.getMass(3, t) for d, t in out if d == 3)
        print(f"rebuilt part (no head): {len([1 for d, t in out if d == 3])} volume(s), {vol / 1e3:.2f} cm³ vs STL 15.06 cm³ ({100 * (vol / 15055.5 - 1):+.1f} %)")
    finally:
        gmsh.finalize()
    with tempfile.TemporaryDirectory() as td:
        t0 = time.perf_counter()
        info = M1.build(st, fm, pl, pathlib.Path(td), "m", h_int=2.0, delta=0.025, slip_tol=2.5e-4)
        m = np.load(pathlib.Path(td) / "mesh3d.npz")
        print("M1 build OK in %.0f s:" % (time.perf_counter() - t0), "tets", info.get("n_tet"), "| pairs", int(len(m["pair_bone"])), "| collar nodes", int(m["pair_collar"].sum()),
              "| collar contact area %.0f mm²" % float(m["pair_area"][m["pair_collar"]].sum()), "| cortex pairs", int(m["pair_cortex"].sum()))
    print("spec:", json.dumps(spec))
