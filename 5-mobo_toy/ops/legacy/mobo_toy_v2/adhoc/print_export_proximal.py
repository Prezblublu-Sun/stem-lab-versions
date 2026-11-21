"""近端股骨的可打印模型（Linux，0 次 FE）：只保留小转子下 z_floor（默认 −10 mm，模型坐标原点在小转子）以上的部分。
    femur_proximal_intact.stl / .step        完整近端股骨（皮质 + 松质融合为一个实体）
    femur_proximal_resected_h<h>.stl / .step 截骨后的近端股骨（距头心 h mm、垂直颈轴），没有锉腔
    ~/mobo_toy_v2/run.sh print_export_proximal.py --intact <intact_job> [--z-floor -10] [--h-cut 25] [--size 0.8] [--out print_models/proximal]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "code")); sys.path.insert(0, str(HOME / "code" / "v2")); sys.path.insert(0, str(HOME / "adhoc"))

import jobs as J  # noqa: E402
from print_export import mesh_and_write  # noqa: E402


def proximal_bone(occ, fm, z_floor: float, cut: bool, cortex_only: bool = False):
    import fe3d_geom as E
    from model3d_v2 import _femur_shapes
    C, K = _femur_shapes(occ, fm)
    if cortex_only:                                                        # 只留皮质壳（中空，松质去掉）
        occ.remove(K, recursive=True); W = C
    else:
        W, _ = occ.fuse(C, K, removeObject=True, removeTool=True)
    box = [(3, occ.addBox(-300, -300, z_floor, 600, 600, 600))]
    if cut:
        box, _ = occ.intersect(box, E.kept_halfspace(occ, fm), removeObject=True, removeTool=True)
    Wk, _ = occ.intersect(W, box, removeObject=True, removeTool=True)
    return [x for x in Wk if x[0] == 3]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--intact", required=True)
    ap.add_argument("--z-floor", type=float, default=-10.0)
    ap.add_argument("--h-cut", type=float, default=25.0)
    ap.add_argument("--size", type=float, default=0.8)
    ap.add_argument("--out", default="print_models/proximal")
    ap.add_argument("--cortex-only", action="store_true")
    ap.add_argument("--only-resected", action="store_true")
    a = ap.parse_args()
    import gmsh
    out = HOME / "deck" / a.out
    out.mkdir(parents=True, exist_ok=True)
    spec = json.loads((J.QROOT / a.intact / "spec.json").read_text())
    fm = J.femur_for(spec).with_cut(a.h_cut)
    t0 = time.time()
    rep = {"z_floor_mm": a.z_floor, "h_cut_mm": a.h_cut, "lesser_trochanter_z_mm": 0.0}
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0); gmsh.option.setNumber("General.NumThreads", 1)
        suffix = "_cortex" if a.cortex_only else ""
        for nm, cut in (("femur_proximal_intact" + suffix, False), (f"femur_proximal_resected_h{a.h_cut:g}" + suffix, True)):
            if a.only_resected and not cut:
                continue
            gmsh.model.add(nm); occ = gmsh.model.occ
            proximal_bone(occ, fm, a.z_floor, cut, a.cortex_only)
            rep[nm] = mesh_and_write(gmsh, out / f"{nm}.stl", out / f"{nm}.step", a.size)
            gmsh.model.remove()
            print(nm, json.dumps(rep[nm]), f"{time.time() - t0:.0f} s", flush=True)
    finally:
        gmsh.finalize()
    rp = out / ("export_report_cortex.json" if a.cortex_only else "export_report.json")
    rp.write_text(json.dumps(rep, indent=1))
