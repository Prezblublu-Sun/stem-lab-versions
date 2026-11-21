"""Placement check of candidate designs, size fixed, 8 poses, default tolerances, as in Z2 and pose_fixed. Linux, 0 FE, read only.

    ../run.sh <this> <list.csv> <out.json> [workers]        from ~/mobo_toy_v2/code

list.csv has columns e and u_L ... u_tau_p, optionally src and src_idx. The check repeats the templating, so the design, cut and size written to out.json are what a spec would use.
Pass: no pose enters the cortex, and the neck base overhangs by no more than the production tolerance of 2 mm2 in every pose.
"""
import csv
import json
import sys
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, "v2")
import collar_rule as CR  # noqa: E402
import geom3d as G  # noqa: E402
import jobs as J  # noqa: E402
import pose_fixed as PF  # noqa: E402
import stage_neckopt as SN  # noqa: E402
import tpl_record as TR  # noqa: E402

U_COLS = ["u_L", "u_alpha", "u_h_cut", "u_m", "u_rho_tip", "u_q", "u_lam", "u_g_ml", "u_g_ap", "u_n_a", "u_n_p", "u_tau_a", "u_tau_p"]
POSES = [{"de": -1.0}, {"de": 1.0}, {"ds": -1.0}, {"ds": 1.0}, {"rot_deg": -3.0}, {"rot_deg": 3.0}, {"dalpha_deg": -3.0}, {"dalpha_deg": 3.0}]
TOL_OVER = 2.0
PH = None
RULE = None


def init():
    global PH, RULE
    PH = SN.Phase(13)
    RULE = TR.phase_rule(13)


def one(r):
    base = {"n": r.get("n"), "src": r.get("src"), "src_idx": r.get("src_idx")}
    try:
        u = np.array([float(r[c]) for c in U_COLS])
        d, h = PH.design_of(u)
        fm = J.femur_for({"femur_id": PH.femur_id, "neck_axis": PH.neck_axis, "h_cut": h})
        st = G.Stem3D(**d)
        with J.a_bounds_cap(RULE.a_bounds_max):
            t = CR.template_neck_in_shoulder(st, fm, offsets=np.array([float(r["e"])]), margin=RULE.margin, min_A0=RULE.min_A0, tol_mm2=RULE.tol_mm2, margin_check=RULE.margin_check)
        pl = {"alpha": t["alpha"], "e": t["e"], "A0": t["A0"], "margin": t.get("margin", st.m), "pose": fm.pose(t["alpha"], t["e"])}
        cells, foam_min, into, over = [], 1e9, 0.0, 0.0
        for p in POSES:
            q = PF.apply(st, fm, pl, p)["pose_fixed"]
            foam = q["margin"] - q["penetration_vs_margin_mm"]
            foam_min, into, over = min(foam_min, foam), max(into, q["penetration_vs_endosteum_mm"]), max(over, q["neck_overhang_mm2"])
            cells.append(f"{foam:.2f}/{max(q['penetration_vs_endosteum_mm'], 0):.2f}/{q['neck_overhang_mm2']:.1f}")
        bone = float(fm.resected_volume(ref_cut_mm=RULE.ref_cut_mm)) + float(t["volume"])
        return {**base, "ok": bool(into <= 0.0 and over <= TOL_OVER), "e": float(t["e"]), "A0": float(t["A0"]), "alpha": float(t["alpha"]), "h_cut": float(h), "bone_mm3": bone, "design": {k: float(v) if isinstance(v, (int, float, np.floating)) else v for k, v in d.items()}, "foam_min_mm": float(foam_min), "into_cortex_mm": float(max(into, 0.0)), "overhang_mm2": float(over), "cells": cells}
    except Exception as ex:  # noqa: BLE001
        return {**base, "ok": False, "error": f"{type(ex).__name__}: {str(ex)[:160]}"}


def main():
    rows = list(csv.DictReader(open(sys.argv[1], encoding="utf-8-sig")))
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else 4
    with Pool(workers, init) as p:
        out = p.map(one, rows, chunksize=2)
    json.dump(out, open(sys.argv[2], "w"), indent=1, default=float)
    print("tested", len(out), "passed", sum(x["ok"] for x in out), "errors", sum("error" in x for x in out))
    if len(out) <= 20:
        print("n | e | m | A0 | bone | " + " | ".join(",".join(f"{k}{v:+g}" for k, v in q.items()) for q in POSES))
        for x in out:
            print(f"{x['n']} | {x['e']:+.2f} | {x['design']['m']:.2f} | {x['A0']:.1f} | {x['bone_mm3']:.0f} | {' | '.join(x['cells'])} | ok {x['ok']}")
    else:
        for lab, k in (("into cortex", lambda x: x.get("into_cortex_mm", 9) > 0), ("overhang", lambda x: x.get("overhang_mm2", 99) > TOL_OVER)):
            print(lab, sum(k(x) for x in out))


if __name__ == "__main__":
    main()
