"""核对（只读，adhoc）：1 三种分区口径下 7 区骨吸收；2 柄与骨的界面是否有几何缝隙（孪生节点坐标差）；
3 摩擦模型里界面张开的比例按柄的近 / 中 / 远三段分；4 剖面图里柄尖白边是不是画图造成的。"""
import json
import pathlib
import sys

import numpy as np

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "adhoc" / "ata_style"))
import ata_style as A  # noqa: E402
from ata_style import J, RS, G, CR, SH  # noqa: E402
import post_m1 as PM  # noqa: E402
from shapely.geometry import Point  # noqa: E402

RS._init()
out = {}
for k, L, col, job, c in A.DESIGNS:
    d = J.QROOT / job
    rows, _ = RS.design_rows(job)
    z7 = {x["scheme"]: {kk: x.get(kk) for kk in ("res_0.6", "sed_chg_pct", "ssi_pct", "vol")} for x in rows
          if x["tissue"] == "cortex" and x["zone"] == "G7"}
    m = dict(np.load(d / "mesh3d.npz"))
    lab, X = m["node_labels"], m["nodes"]
    pos = np.zeros(int(lab.max()) + 1, int); pos[lab] = np.arange(len(lab))
    xs, xb = X[pos[m["pair_stem"]]], X[pos[m["pair_bone"]]]
    mismatch = float(np.linalg.norm(xs - xb, axis=1).max())
    geo = A.design_geom(job)
    P0, dd = geo["pl"]["pose"][:2]
    s = (xs - P0) @ dd
    col_ = m["pair_collar"].astype(bool) if "pair_collar" in m else np.zeros(len(s), bool)
    body = ~col_
    Ls = geo["st"].L
    thirds = {"proximal": body & (s < Ls / 3), "middle": body & (s >= Ls / 3) & (s < 2 * Ls / 3), "distal": body & (s >= 2 * Ls / 3)}
    p = PM.pairs(d)
    U = {st: PM._utab(d / "m_fric_csv" / f"{st}_U.csv", p["n"]) for st in ("RELEASE", "UNLOAD", "LOAD2")}
    nrm, w, di = p["pair_normal"], p["pair_area"], p["pair_interf"]
    gap = {st: -(di + ((U[st][p["pair_stem"]] - U[st][p["pair_bone"]]) * nrm).sum(1)) * 1e3 for st in U}
    reg = {}
    for name, sel in thirds.items():
        ws = w[sel].sum()
        reg[name] = {"area_mm2": float(ws), "s_range": [float(s[sel].min()), float(s[sel].max())] if sel.any() else None,
                     **{f"open_{st}_pct": float(100 * w[sel][gap[st][sel] > PM.OPEN_UM].sum() / ws) if ws else None for st in gap},
                     **{f"gap_p95_{st}_um": float(np.percentile(gap[st][sel], 95)) if sel.any() else None for st in gap}}
    # 画图：柄的真实剖面（inside_stem 掩码）里，有多少像素没被轮廓多边形盖住、落在哪一段
    pg = A.plane_grid()
    keep, stem = A.masks_for(geo)
    poly = CR.stem_silhouette(geo["fm"], geo["st"], geo["pl"])
    C0 = A.fm0().neck_plane()[0]
    a_ = pg["P"][stem] - C0
    e1 = pg["e1"]
    pts = np.c_[a_ @ e1, pg["P"][stem][:, 2] - C0[2]]
    covered = np.array([poly.buffer(0.3).contains(Point(q)) for q in pts])
    s_px = (pg["P"][stem] - P0) @ dd
    unc = ~covered
    out[k] = {"job": job, "G7_res_by_scheme": {sc: v["res_0.6"] for sc, v in z7.items()},
              "G7_vol_mm3_by_scheme": {sc: v["vol"] for sc, v in z7.items()},
              "G7_sedchg_by_scheme": {sc: v["sed_chg_pct"] for sc, v in z7.items()},
              "twin_node_max_mismatch_mm": mismatch, "n_pairs": int(len(s)), "regions": reg,
              "drawing": {"stem_px": int(stem.sum()), "uncovered_px": int(unc.sum()),
                          "uncovered_s_min": float(s_px[unc].min()) if unc.any() else None, "L": float(Ls),
                          "cap_len": float(geo["st"].cap_length(geo["pl"]["A0"]))}}
    print(k, json.dumps(out[k], default=float), flush=True)
(A.OUT / "gap_check.json").write_text(json.dumps(out, indent=1, default=float))
