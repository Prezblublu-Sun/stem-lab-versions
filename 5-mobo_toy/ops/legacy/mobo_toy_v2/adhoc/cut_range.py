"""截骨高度的解剖含义（只读）：对每档 h_cut（截骨面到头心的距离，沿颈轴），在截骨面上取骨截面，
报告内下端（股骨距侧）与外上端的高度（相对小转子）、截面尺寸与面积、皮质占比、相对 25 mm 多切的骨量。"""
from __future__ import annotations

import json
import math
import pathlib
import sys

import numpy as np

CODE = pathlib.Path.home() / "mobo_toy_v2" / "code"
sys.path.insert(0, str(CODE)); sys.path.insert(0, str(CODE / "v2"))
import femur_real as FR  # noqa: E402

fm0 = FR.build()
lm = fm0.lm
out = {"head_r": float(fm0.Rh), "neck_shaft_deg": lm.get("neck_shaft_deg"), "offset_mm": lm.get("offset_mm"),
       "config_cut": fm0.cfg["femur"]["cut_from_head_mm"], "rows": []}
# 颈轴与干轴（x = 0, y = 0 的竖线）的最近点：沿颈轴从头心到干轴的距离
H, u = fm0.H, fm0.u3
ez = np.array([0.0, 0.0, 1.0])
w0 = H - np.array([0.0, 0.0, H[2]])
# 求 t 使 H - t u 到 z 轴距离最小
A = np.array([[u @ u, -(u @ ez)], [u @ ez, -1.0]])
b = np.array([u @ (H - 0), ez @ (H - 0)])
t, s = np.linalg.solve(np.array([[u @ u, -(u @ ez)], [u @ ez, -(ez @ ez)]]), np.array([H @ u, H @ ez]))
out["neck_axis_to_shaft_axis_mm"] = float(t)
e_ap = np.cross(fm0.n3, fm0.u3); e_ap /= np.linalg.norm(e_ap)
for h in (20, 25, 30, 35, 40, 45, 50, 55):
    fm = fm0.with_cut(float(h))
    C = fm.C03
    step = 0.2
    g = np.arange(-45, 45 + step, step)
    U, V = np.meshgrid(g, g)
    P = C + U.reshape(-1, 1) * fm.n3 + V.reshape(-1, 1) * e_ap
    outer = fm.outer_sdf(P) <= 0
    canal = fm.canal_sdf(P) <= 0
    if not outer.any():
        out["rows"].append({"h_cut": h, "empty": True}); continue
    # 只取与截骨中心连通的那块（避免平面另一侧碰到大转子等）
    from scipy import ndimage
    lab, n = ndimage.label(outer.reshape(U.shape))
    ci = lab[U.shape[0] // 2, U.shape[1] // 2]
    if ci == 0:
        dist = np.hypot(U, V); dist[lab == 0] = 1e9; ci = lab.flat[int(np.argmin(dist))]
    sec = (lab == ci).ravel()
    Ps, us, vs = P[sec], U.ravel()[sec], V.ravel()[sec]
    i_med, i_lat = int(np.argmax(us)), int(np.argmin(us))       # n3 指向内下：u 最大 = 股骨距端
    area = sec.sum() * step * step
    cort = (sec & ~canal).sum() * step * step
    out["rows"].append({"h_cut": h, "calcar_end_z_mm": float(Ps[i_med, 2]), "lateral_end_z_mm": float(Ps[i_lat, 2]),
                        "calcar_end_x_mm": float(Ps[i_med, 0]), "lateral_end_x_mm": float(Ps[i_lat, 0]),
                        "width_along_cut_mm": float(us.max() - us.min()), "width_ap_mm": float(vs.max() - vs.min()),
                        "section_area_mm2": float(area), "cortex_area_mm2": float(cort), "cortex_frac": float(cort / area),
                        "resected_vs_25_cm3": float(fm.resected_volume() / 1000.0),
                        "centre_z_mm": float(C[2])})
print(json.dumps(out, indent=1, default=float))
pathlib.Path.home().joinpath("mobo_toy_v2/adhoc/out/cut_range.json").write_text(json.dumps(out, indent=1, default=float))
