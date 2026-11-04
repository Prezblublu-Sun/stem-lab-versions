"""只建模不求解：领与椭圆截面的建模检查（Linux，adhoc）。
1 回归：基准设计无领，网格与节点对应与改动前已解的作业 mesh3d.npz 逐项相同。
2 带领、椭圆截面的若干组合能否建成；领的外形、接触节点数、接触面积、过盈是否为 0。"""
from __future__ import annotations

import json
import pathlib
import sys
import time

import numpy as np

CODE = pathlib.Path.home() / "mobo_toy_v2" / "code"
sys.path.insert(0, str(CODE)); sys.path.insert(0, str(CODE / "v2"))
import femur_real as FR  # noqa: E402
import geom3d as G  # noqa: E402
import model3d_m1 as M1  # noqa: E402
import fe3d_geom as E  # noqa: E402
import stage_v2a as S  # noqa: E402

Q = pathlib.Path.home() / "mobo_toy_v2" / "queue"
OUT = pathlib.Path.home() / "mobo_toy_v2" / "adhoc" / "build_test"
OUT.mkdir(parents=True, exist_ok=True)
base = dict(S.BASE)
short = json.loads((Q / "probe_L25_12_e265f0bf" / "spec.json").read_text())["design"]
neck = G.ellipse_design(30.0, 0.5, 1.0, 1.3, 40.0)
CASES = [("base_w0", base), ("base_w2", {**base, "collar_w": 2.0}), ("base_w4", {**base, "collar_w": 4.0}),
         ("short_w3", {**short, "collar_w": 3.0}), ("neck_ell_w0", neck), ("neck_ell_w3", {**neck, "collar_w": 3.0})]
fm = FR.build()
res = {}
for name, dsg in CASES:
    st = G.Stem3D(**dsg)
    pl = G.template(st, fm)
    if not pl["fit"]:
        res[name] = {"fit": False, "reason": pl["reason"]}; print(name, res[name], flush=True); continue
    t0 = time.time()
    d = OUT / name
    try:
        info = M1.build(st, fm, pl, d, "m", delta=0.025)
    except Exception as e:                                                # noqa: BLE001
        res[name] = {"fit": True, "error": f"{type(e).__name__}: {e}"[:400]}; print(name, res[name], flush=True); continue
    m = np.load(d / "mesh3d.npz")
    col = m["pair_collar"].astype(bool)
    r = {"A0": pl["A0"], "e": pl["e"], "n_tet": info["n_tet"], "n_pairs": info["n_pairs"], "s": round(time.time() - t0, 1),
         "collar_pairs": int(col.sum()), "collar_interf_max": float(m["pair_interf"][col].max()) if col.any() else None,
         "body_interf_values": sorted({round(float(x), 4) for x in m["pair_interf"][~col]}),
         "collar_normal_dot_plane": float(np.mean(m["pair_normal"][col] @ E.cut_plane(fm)[3])) if col.any() else None,
         "mesh_attempt": info["mesh_attempt"]["algorithm3d"], "quality": info.get("mesh_quality")}
    if info.get("collar"):
        r["collar"] = {k: v for k, v in info["collar"].items() if k != "outline_uv"}
    res[name] = r
    print(name, json.dumps(r, default=float), flush=True)

# 回归：与改动前的作业比较（同一设计、同一网格设置、过盈 0.025 mm）
old = sorted(Q.glob("m1_base_h2_tol0.00025_delta0.025_*"))
if old and (OUT / "base_w0" / "mesh3d.npz").exists():
    a, b = np.load(old[0] / "mesh3d.npz"), np.load(OUT / "base_w0" / "mesh3d.npz")
    cmp = {}
    for k in ("cortex_conn", "cancellous_conn", "stem_conn", "node_labels", "nodes", "pair_bone", "pair_stem", "pair_normal", "pair_area",
              "pair_interf", "pair_cortex"):
        cmp[k] = bool(a[k].shape == b[k].shape and np.array_equal(a[k], b[k]))
    cmp["old_job"] = old[0].name
    res["regression_base_w0"] = cmp
    print("regression", json.dumps(cmp), flush=True)
(OUT / "summary.json").write_text(json.dumps(res, indent=1, default=float))
