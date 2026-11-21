"""领裁剪的普查（只读，Linux）：主表里现行模型的全部带领设计，按现行规则重算领外形，统计领环被骨外轮廓裁掉的比例、最窄处、
以及"截口离骨外缘的最近距离"（= 不裁剪时能放下的最大均匀领宽 + 0.5 mm 余隙）。输出 ~/mobo_toy_v2/deck/collar_trim_census.csv。"""
from __future__ import annotations

import csv
import json
import pathlib
import sys
from multiprocessing import Pool

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "code")); sys.path.insert(0, str(HOME / "code" / "v2"))
import numpy as np  # noqa: E402


def one(j: str):
    import fe3d_geom as E
    import geom3d as G
    import jobs as J
    try:
        spec = json.loads((J.QROOT / j / "spec.json").read_text())
        st = G.Stem3D(**spec["design"])
        if not getattr(st, "has_collar", False):
            return None
        fm = J.femur_for(spec)
        pl = G.template(st, fm, margin=spec.get("margin"))
        info = E.collar_outline(st, fm, pl)
        foot, col = info["footprint"], info["poly"]
        raw = foot.buffer(float(st.collar_w), quad_segs=16)
        C, e1, e2 = E._plane_basis(fm)
        g = np.arange(-45, 45.075, 0.15)
        U, V = np.meshgrid(g, g)
        P = C + U.reshape(-1, 1) * e1 + V.reshape(-1, 1) * e2
        outer = E._loops(fm.outer_sdf(P).reshape(U.shape), g, 0.0)
        host = max(outer, key=lambda p: p.intersection(foot).area)
        gap = float(foot.exterior.distance(host.exterior))              # 截口外缘到骨外缘的最近距离
        from shapely.geometry import Point
        r_neck = float(fm.cfg["prosthesis"]["neck_radius_mm"])
        neck = Point(0.0, 0.0).buffer(r_neck, quad_segs=32)              # 假体颈底面：圆心在截骨中心 C03（平面坐标原点）
        out_col = neck.difference(col)
        out_foot = neck.difference(foot)
        prot = max((neck.exterior.interpolate(t, normalized=True).distance(col) for t in np.linspace(0, 1, 256)), default=0.0)
        return {"neck_outside_collar_mm2": float(out_col.area), "neck_protrusion_beyond_collar_mm": float(prot),
                "neck_outside_footprint_mm2": float(out_foot.area), "entry_offset_e": float(pl.get("e", float("nan"))),
                "job_id": j, "collar_w": float(st.collar_w), "ring_kept_frac": (col.area - foot.area) / max(raw.area - foot.area, 1e-9),
                "footprint_to_periosteum_min_mm": gap, "max_uniform_collar_mm": max(gap - 0.5, 0.0), "A0": float(pl["A0"])}
    except Exception as e:                                              # noqa: BLE001
        return {"job_id": j, "error": f"{type(e).__name__}: {e}"[:160]}


if __name__ == "__main__":
    import os
    os.environ["OMP_NUM_THREADS"] = "1"
    rows = list(csv.DictReader(open(HOME / "deck" / "master_table.csv")))
    sel = [r["job_id"] for r in rows if r["model"] == "m1" and r["cut_plane"] == "unified" and r["collar_w"] not in ("",) and float(r["collar_w"] or 0) > 0
           and r["evidence"].startswith("D")]
    with Pool(4) as pool:
        out = [r for r in pool.map(one, sel, chunksize=8) if r]
    keys = ["job_id", "collar_w", "ring_kept_frac", "footprint_to_periosteum_min_mm", "max_uniform_collar_mm", "A0", "entry_offset_e", "neck_outside_footprint_mm2", "neck_outside_collar_mm2", "neck_protrusion_beyond_collar_mm", "error"]
    with open(HOME / "deck" / "collar_trim_census.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, keys); w.writeheader(); w.writerows(out)
    ok = [r for r in out if "error" not in r]
    k = np.array([r["ring_kept_frac"] for r in ok]); cw = np.array([r["collar_w"] for r in ok]); mx = np.array([r["max_uniform_collar_mm"] for r in ok])
    print(f"{len(ok)} collared optimisation designs ({len(out) - len(ok)} errors)")
    print("ring kept: <95 %:", int((k < 0.95).sum()), " <90 %:", int((k < 0.90).sum()), " <80 %:", int((k < 0.80).sum()), " median", round(float(np.median(k)), 3))
    print("designs whose collar_w exceeds the room for a uniform collar:", int((cw > mx + 1e-6).sum()),
          "; room (footprint to periosteum - 0.5 mm) median", round(float(np.median(mx)), 2), "mm, P10", round(float(np.percentile(mx, 10)), 2))
    pr = np.array([r["neck_protrusion_beyond_collar_mm"] for r in ok]); of = np.array([r["neck_outside_footprint_mm2"] for r in ok])
    print("neck base outside the stem footprint:", int((of > 0.5).sum()), "designs; neck protrudes beyond the collar:", int((pr > 0.05).sum()),
          "(> 0.5 mm:", int((pr > 0.5).sum()), ", > 1 mm:", int((pr > 1.0).sum()), "); max", round(float(pr.max()), 2), "mm")
    for code, j in (("J1", "neck3_a40_967145a2"), ("B2", "neck5_r10_dad61bcd"), ("LA", "neck5_r7_5df27b13"), ("S1B", "neck1_r6_102aba81"),
                    ("R1", "neck5_r3_9f0000eb"), ("R2", "neck3_a45_639d489d")):
        r = next((x for x in ok if x["job_id"] == j), None)
        if r:
            print(" ", code, {k: round(r[k], 2) for k in ("A0", "entry_offset_e", "neck_outside_footprint_mm2", "neck_outside_collar_mm2", "neck_protrusion_beyond_collar_mm", "ring_kept_frac")})
