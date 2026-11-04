"""颈部髓腔在截骨面及其下方若干平面上的内外侧 / 前后宽度（只读；给候选的宽厚比选取依据）。"""
import json
import pathlib
import sys

import numpy as np

CODE = pathlib.Path.home() / "mobo_toy_v2" / "code"
sys.path.insert(0, str(CODE)); sys.path.insert(0, str(CODE / "v2"))
import femur_real as FR  # noqa: E402
import fe3d_geom as E  # noqa: E402

fm = FR.build()
C, e1, e2, nrm = E.cut_plane(fm)
g = np.arange(-30, 30.01, 0.1)
U, V = np.meshgrid(g, g)
out = {"u3_deg_to_shaft": None, "planes": []}
for depth in (0.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0):
    P = (C - depth * nrm) + U.reshape(-1, 1) * e1 + V.reshape(-1, 1) * e2
    canal = (fm.canal_sdf(P) <= 0).reshape(U.shape)
    outer = (fm.outer_sdf(P) <= 0).reshape(U.shape)
    if not canal.any():
        continue
    uu, vv = U[canal], V[canal]
    uo, vo = U[outer], V[outer]
    out["planes"].append({"depth_mm": depth, "canal_ml_mm": float(uu.max() - uu.min()), "canal_ap_mm": float(vv.max() - vv.min()),
                          "canal_area_mm2": float(canal.sum() * 0.01), "outer_ml_mm": float(uo.max() - uo.min()),
                          "outer_ap_mm": float(vo.max() - vo.min()), "outer_area_mm2": float(outer.sum() * 0.01),
                          "cortex_frac": float(1 - canal.sum() / outer.sum())})
# 颈轴与干轴的夹角（项目坐标 z = 干轴）
u3 = fm.u3 if hasattr(fm, "u3") else None
if u3 is not None:
    out["u3_deg_to_shaft"] = float(np.degrees(np.arccos(abs(np.asarray(u3)[2]) / np.linalg.norm(u3))))
(pathlib.Path.home() / "mobo_toy_v2" / "adhoc" / "out" / "canal_aspect.json").write_text(json.dumps(out, indent=1))
print(json.dumps(out, indent=1))
