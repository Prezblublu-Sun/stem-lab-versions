"""db3406: the 3 geometric templating features (geo_area_mm2, near_area_mm2, mean_wall_mm; same algorithm as tpl_area_features.py and
the 10-22 eff_explore.proxies) for every FEASIBLE row of the 6.5 万点 templating pool, from the pool's own templating result
(tpl_record: alpha_star, e_star, A0_star) -- no re-templating. Design / h_cut = stage_neckopt.Phase(13).design_of(u13).
Check: rows that coincide with arm jobs must reproduce tpl_area_features.py exactly (run separately on Windows).
Linux:  cd ~/mobo_toy_v2/code && nice -n 19 taskset -c 8-11 ../run.sh <this> <pool.npz> <out.npz> [workers=2]
Writes only <out.npz> (+ <out>.json meta). Rows that fail are recorded (ok False + reason), never dropped.
"""
import json
import math
import sys
import time
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, "v2")
import geom3d as G  # noqa: E402
import jobs as J  # noqa: E402
import stage_neckopt as SN  # noqa: E402

PH = None


def surface_quads(st, A0, ns=70, m=64, ncap=6):
    """copied verbatim from tpl_area_features.py (= ml_efficiency_2026-10-22/efficiency/scripts/eff_explore.py)."""
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


def one(args):
    i, u, alpha, e, A0 = args
    global PH
    if PH is None:
        PH = SN.Phase(13)
    try:
        d, h = PH.design_of(u)
        fm = J.femur_for({"femur_id": PH.femur_id, "neck_axis": PH.neck_axis, "h_cut": h})
        st = G.Stem3D(**d)
        pose = fm.pose(float(alpha), float(e))
        C, Ar = surface_quads(st, float(A0))
        P = fm.to_world(C, pose)
        below = fm.below_cut(P)
        dist = -fm.canal_sdf(P[below])
        w = Ar[below]
        return i, True, float(w.sum()), float(w[dist <= st.m + 1.0].sum()), float((w * dist).sum() / w.sum()), ""
    except Exception as ex:  # noqa: BLE001
        return i, False, math.nan, math.nan, math.nan, f"{type(ex).__name__}: {str(ex)[:160]}"


def main():
    src, out = sys.argv[1], sys.argv[2]
    nw = int(sys.argv[3]) if len(sys.argv) > 3 else 2
    zf = np.load(src)
    z = {k: zf[k] for k in ("u13", "alpha_star", "e_star", "A0_star", "feasible")}   # NpzFile re-reads an array on every z[k]: load once
    idx = np.flatnonzero(z["feasible"])
    n = len(z["feasible"])
    geo, near, wall = (np.full(n, np.nan) for _ in range(3))
    ok = np.zeros(n, bool)
    reasons = {}
    t0 = time.time()
    tasks = [(int(i), z["u13"][i], z["alpha_star"][i], z["e_star"][i], z["A0_star"][i]) for i in idx]
    with Pool(nw) as p:
        for k, (i, good, g_, n_, w_, why) in enumerate(p.imap_unordered(one, tasks, chunksize=16)):
            geo[i], near[i], wall[i], ok[i] = g_, n_, w_, good
            if not good:
                reasons[i] = why
            if k % 500 == 0:
                print(f"{k}/{len(tasks)} {time.time() - t0:.0f}s", flush=True)
    np.savez_compressed(out, geo_area_mm2=geo, near_area_mm2=near, mean_wall_mm=wall, area_ok=ok, feasible=z["feasible"])
    meta = {"tool": "pool_area_features", "source": src, "n": n, "n_feasible": int(len(idx)), "n_ok": int(ok.sum()), "n_failed": len(reasons),
            "failed": {str(k): v for k, v in list(reasons.items())[:200]}, "code_hash": J.code_hash(), "wall_s": round(time.time() - t0, 1),
            "rule": "Phase(13).design_of(u13); pose = femur.pose(alpha_star, e_star); A0 = A0_star; near = within m + 1 mm of canal_sdf"}
    open(out + ".json", "w").write(json.dumps(meta, indent=1))
    print(json.dumps({k: meta[k] for k in ("n_feasible", "n_ok", "n_failed", "wall_s")}))


if __name__ == "__main__":
    main()
