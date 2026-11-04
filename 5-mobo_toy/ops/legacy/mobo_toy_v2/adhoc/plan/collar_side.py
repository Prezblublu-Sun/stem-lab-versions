"""峰值载荷时领面哪一侧贴着、哪一侧掀起（只读）。e1 = n3：截骨面内、颈平面内、指向内下（股骨距侧）；e2：前后方向。"""
import json
import pathlib
import sys

import numpy as np

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "code")); sys.path.insert(0, str(HOME / "code" / "v2"))
import femur_real as FR  # noqa: E402
import jobs as J  # noqa: E402
import post_m1 as PM  # noqa: E402

fm = FR.build()
n3 = fm.n3 / np.linalg.norm(fm.n3)
e2 = np.cross(fm.u3 / np.linalg.norm(fm.u3), n3)
for job in ("collar_neck_w3_36c2bb73", "collar_neck_asym_L35_w2_d6eb839e", "collar_neck_ell_L25_w4_058b5129", "collar_base_w2_9d3e7e27",
            "collar_short_w3_35350236"):
    d = J.QROOT / job
    p = PM.pairs(d)
    col = p["pair_collar"]
    U = {s: PM._utab(d / "m_fric_csv" / f"{s}_U.csv", p["n"]) for s in ("LOAD2",)}
    gap = -(p["pair_interf"] + ((U["LOAD2"][p["pair_stem"]] - U["LOAD2"][p["pair_bone"]]) * p["pair_normal"]).sum(1)) * 1e3
    pos = np.zeros(int(p["node_labels"].max()) + 1, int); pos[p["node_labels"]] = np.arange(len(p["node_labels"]))
    X = p["nodes"][pos[p["pair_stem"]]][col]
    w = p["pair_area"][col]
    c = X - fm.C03
    a, b = c @ n3, c @ e2
    closed = gap[col] <= PM.OPEN_UM
    def wm(v, m):
        return float((v[m] * w[m]).sum() / w[m].sum()) if m.any() else None
    halves = {"medial(calcar) half": a > np.median(a), "lateral half": a <= np.median(a), "posterior half": b > np.median(b),
              "anterior half": b <= np.median(b)}
    print(job, "closed area frac", round(float(w[closed].sum() / w.sum()), 3),
          {k: round(float(w[m & closed].sum() / w[m].sum()), 2) for k, m in halves.items()},
          "mean a closed/open", round(wm(a, closed), 1), round(wm(a, ~closed), 1), flush=True)
