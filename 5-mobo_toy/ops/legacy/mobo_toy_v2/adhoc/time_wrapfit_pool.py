"""只读计时（Linux）：5 变量设计空间（L、α、m、领宽、ρ_tip；截骨 25、椭圆 λ 1.3、q 1）里随机 48 个设计，
现行选号 vs wrap_fit 选号的耗时与可行率。用来定批次 G 优化的候选池大小。"""
from __future__ import annotations

import json
import pathlib
import sys
import time

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "code")); sys.path.insert(0, str(HOME / "code" / "v2"))
import numpy as np  # noqa: E402
from scipy.stats import qmc  # noqa: E402

import collar_rule as CR  # noqa: E402
import femur_real as FR  # noqa: E402
import geom3d as G  # noqa: E402
import stage_v2a as S  # noqa: E402

SPACE = {"L": (20.0, 60.0), "alpha": (15.0, 45.0), "m": (-0.25, 2.0), "collar_w": (0.0, 6.0), "rho_tip": (0.10, 0.50)}
fm = FR.build().with_cut(25.0)
U = qmc.Sobol(5, scramble=True, seed=1).random(48)
t_old = t_new = 0.0
n_old = n_new = 0
for u in U:
    v = {k: lo + x * (hi - lo) for (k, (lo, hi)), x in zip(SPACE.items(), u)}
    d = {"L": v["L"], "rho_tip": v["rho_tip"], "q": 1.0, "lam": 1.3, **G.ELLIPSE, "alpha": v["alpha"], "m": v["m"], "cap_h": G.CAP_FLAT}
    if v["collar_w"] > 1e-6:
        d.update(collar_w=v["collar_w"], collar_t=G.COLLAR_T)
    st = G.Stem3D(**d)
    t0 = time.perf_counter(); r = G.template(st, fm); t_old += time.perf_counter() - t0
    n_old += bool(r["fit"] and r["A0"] >= S.MIN_A0)
    t0 = time.perf_counter(); r = CR.template_wrap_fit(st, fm, min_A0=S.MIN_A0); t_new += time.perf_counter() - t0
    n_new += bool(r["fit"] and r["A0"] >= S.MIN_A0)
print(json.dumps({"n": len(U), "old_s_per": t_old / len(U), "wrap_s_per": t_new / len(U), "old_feasible": n_old, "wrap_feasible": n_new}))
