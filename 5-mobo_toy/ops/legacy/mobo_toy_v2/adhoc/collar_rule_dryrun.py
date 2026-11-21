"""新领规则的试选号（0 次 FE，Linux）：现行规则 vs wrap_fit 的选号结果（入口偏移、肩部面积）与领外形，代表设计 + 颈伸出最多 / 领被裁最多的设计。
输出 ~/mobo_toy_v2/deck/collar_rule_dryrun.json 与 collar_rule_dryrun.png（截骨面俯视，两种规则并排）。"""
from __future__ import annotations

import csv
import json
import pathlib
import sys
import time

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "code")); sys.path.insert(0, str(HOME / "code" / "v2"))
import numpy as np  # noqa: E402

import collar_rule as CR  # noqa: E402
import fe3d_geom as E  # noqa: E402
import geom3d as G  # noqa: E402
import jobs as J  # noqa: E402

REPS = {"J1": "neck3_a40_967145a2", "FI": "demo_FI_c166a2e2", "R1": "neck5_r3_9f0000eb", "R2": "neck3_a45_639d489d",
        "B2": "neck5_r10_dad61bcd", "LA": "neck5_r7_5df27b13"}


def extra(n=3):
    rows = list(csv.DictReader(open(HOME / "deck" / "collar_trim_census.csv")))
    prot = sorted(rows, key=lambda r: -float(r["neck_protrusion_beyond_collar_mm"] or 0))[:n]
    trim = sorted(rows, key=lambda r: float(r["ring_kept_frac"] or 1))[:n]
    return {f"P{k + 1}": r["job_id"] for k, r in enumerate(prot)} | {f"T{k + 1}": r["job_id"] for k, r in enumerate(trim)}


def main():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from shapely.geometry import Point
    sel = {**REPS, **extra()}
    fig, axes = plt.subplots(3, 4, figsize=(15, 11))
    rep = {}
    for ax, (code, j) in zip(axes.flat, sel.items()):
        spec = json.loads((J.QROOT / j / "spec.json").read_text())
        fm = J.femur_for(spec)
        st = G.Stem3D(**spec["design"])
        t0 = time.time()
        old = CR._ORIG["template"](st, fm, margin=spec.get("margin"))
        new = CR.template_wrap_fit(st, fm, margin=spec.get("margin"), min_A0=float(spec.get("min_A0", 0.0)))
        r = {"job": j, "collar_w": float(st.collar_w), "old": {k: old.get(k) for k in ("e", "A0")},
             "new": {k: new.get(k) for k in ("fit", "e", "A0", "A0_cortex_rule", "reason")}, "seconds": round(time.time() - t0, 1)}
        g = np.arange(-30, 30.1, 0.2)
        U, V = np.meshgrid(g, g)
        C, e1, e2 = E._plane_basis(fm)
        P = C + U.reshape(-1, 1) * e1 + V.reshape(-1, 1) * e2
        outer = E._loops(fm.outer_sdf(P).reshape(U.shape), g, 0.0)
        for p in outer[:1]:
            ax.plot(*p.exterior.xy, color="#8c564b", lw=1.0)
        neck = Point(0, 0).buffer(float(fm.cfg["prosthesis"]["neck_radius_mm"]), quad_segs=32)
        ax.plot(*neck.exterior.xy, color="#d62728", lw=1.0)
        oc = CR._ORIG["collar_outline"](st, fm, old)
        ax.plot(*oc["poly"].exterior.xy, color="grey", lw=1.0, ls="--", label="current rule")
        ax.plot(*oc["footprint"].exterior.xy, color="grey", lw=0.6, ls=":")
        if new.get("fit"):
            nc = CR.collar_outline_wrap(st, fm, new)
            ax.plot(*nc["poly"].exterior.xy, color="#1f77b4", lw=1.4, label="wrap_fit")
            ax.plot(*nc["footprint"].exterior.xy, color="black", lw=0.8)
            r["new"]["collar_area_mm2"] = nc["area_mm2"]; r["new"]["ring_cortex_frac"] = nc["ring_cortex_frac"]
        r["old"]["collar_area_mm2"] = oc["area_mm2"]
        ax.set_aspect("equal"); ax.set_xlim(-22, 22); ax.set_ylim(-20, 18)
        ttl = f"{code}: A0 {old.get('A0', 0):.0f} -> {new.get('A0', 0) if new.get('fit') else 0:.0f} mm², e {old.get('e', 0):+.0f} -> {new.get('e', 0) if new.get('fit') else 0:+.0f}"
        ax.set_title(ttl if new.get("fit") else f"{code}: wrap_fit infeasible", fontsize=8)
        rep[code] = r
        print(code, json.dumps(r, default=float), flush=True)
    axes.flat[0].legend(fontsize=6)
    fig.suptitle("Collar rule: current (grey dashed, built around the stem footprint, trimmed at the bone) vs wrap_fit (blue, wraps the neck base, must fit)", fontsize=9)
    fig.tight_layout(); fig.savefig(HOME / "deck" / "collar_rule_dryrun.png", dpi=150)
    (HOME / "deck" / "collar_rule_dryrun.json").write_text(json.dumps(rep, indent=1, default=float))


if __name__ == "__main__":
    main()
