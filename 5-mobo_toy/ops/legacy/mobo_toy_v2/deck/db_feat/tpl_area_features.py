"""db3406: the 3 geometric templating features of the 10-22 CT study (efficiency/README 'E19: + 6 templating quantities') for 3406 jobs,
from each job's OWN recorded templating (prep.json templating alpha / e / A0; no re-templating):
    geo_area_mm2   stem surface area below the cut plane
    near_area_mm2  part of it within m + 1 mm of the canal wall (canal_sdf)
    mean_wall_mm   area-weighted mean distance from the stem surface to the canal wall
surface_quads() is copied verbatim from ml_efficiency_2026-10-22/efficiency/scripts/eff_explore.py (same rings: 8 above S_TOP..0,
70 along L, 64 per ring, 6 cap rings). The other 3 features (A0, e, reamed volume) are already in the export (tpl_A0, tpl_e, tpl_volume).
Read-only on the queue; writes only argv[2]. Linux: cd ~/mobo_toy_v2/code && nice -n 19 taskset -c 8-11 ../run.sh <this> <jobs.txt> <out.json>
"""
import json
import math
import sys
import time

import numpy as np

sys.path.insert(0, "v2")
import geom3d as G  # noqa: E402
import jobs as J  # noqa: E402


def surface_quads(st, A0, ns=70, m=64, ncap=6):
    """rings of local_surface -> quad centroids (local coords) and areas (local == world metric, rigid pose)."""
    sec = G.unit_section(st.d, m)
    s = np.r_[np.linspace(G.S_TOP, 0, 8, endpoint=False), np.linspace(0, st.L, ns)]
    k = np.sqrt(A0 * st.area_ratio(s))
    rings = [np.c_[np.full(m, si), ki * sec] for si, ki in zip(s, k)]
    c = st.cap_length(A0)
    kt = math.sqrt(A0 * st.rho_tip)
    for t in np.linspace(0, 1, ncap + 1)[1:-1]:
        f = math.sqrt(max(1 - t * t, 0.0))
        rings.append(np.c_[np.full(m, st.L + c * t), f * kt * sec])
    tip = np.array([st.L + c, 0.0, 0.0])
    cen, area = [], []
    for a, b in zip(rings[:-1], rings[1:]):
        a2, b2 = np.roll(a, -1, axis=0), np.roll(b, -1, axis=0)
        d1, d2 = b2 - a, b - a2
        area.append(0.5 * np.linalg.norm(np.cross(d1, d2), axis=1))
        cen.append((a + a2 + b + b2) / 4)
    a = rings[-1]; a2 = np.roll(a, -1, axis=0)
    area.append(0.5 * np.linalg.norm(np.cross(a2 - a, tip - a), axis=1)); cen.append((a + a2 + tip) / 3)
    return np.vstack(cen), np.concatenate(area)


def feats(job):
    d = J.QROOT / job
    spec = json.loads((d / "spec.json").read_text())
    prep = json.loads((d / "prep.json").read_text())
    tp = prep.get("templating") or {}
    if spec.get("design") is None or not tp:
        return {"job": job, "ok": False, "reason": "no design or no prep templating"}
    fm = J.femur_for(spec)
    st = G.Stem3D(**spec["design"])
    A0, alpha, e = float(tp["A0"]), float(tp["alpha"]), float(tp["e"])
    pose = fm.pose(alpha, e)
    C, Ar = surface_quads(st, A0)
    P = fm.to_world(C, pose)
    below = fm.below_cut(P)
    dist = -fm.canal_sdf(P[below])
    w = Ar[below]
    return {"job": job, "ok": True, "A0": A0, "alpha": alpha, "e": e, "volume": tp.get("volume"), "m": float(st.m),
            "geo_area_mm2": float(w.sum()), "near_area_mm2": float(w[dist <= st.m + 1.0].sum()),
            "mean_wall_mm": float((w * dist).sum() / w.sum()), "n_quads_below": int(below.sum())}


def main():
    jobs = [l.strip() for l in open(sys.argv[1]) if l.strip()]
    out, t0 = {}, time.time()
    for i, j in enumerate(jobs):
        try:
            out[j] = feats(j)
        except Exception as ex:  # noqa: BLE001 -- recorded per job, never dropped silently
            out[j] = {"job": j, "ok": False, "reason": f"{type(ex).__name__}: {str(ex)[:200]}"}
        if i % 20 == 0:
            print(f"{i + 1}/{len(jobs)} {j} {out[j].get('ok')} {time.time() - t0:.0f}s", flush=True)
    bad = [j for j, v in out.items() if not v["ok"]]
    json.dump({"tool": "tpl_area_features", "n": len(out), "n_bad": len(bad), "bad": bad, "code_hash": J.code_hash(), "rows": out},
              open(sys.argv[2], "w"), indent=1)
    print(f"done {len(out)} jobs, {len(bad)} not ok, {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
