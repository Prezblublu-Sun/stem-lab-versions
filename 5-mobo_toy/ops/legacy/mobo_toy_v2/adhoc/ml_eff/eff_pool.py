"""Step 2: candidate universe for the emulator benchmark + deterministic geometric quantities per candidate.

Universe = phase-10 live pool (base Sobol pool 1750 + 911 refresh points) + phase-9 live pool restricted to m >= 0.5
(same collar rule neck_in_shoulder and same template gate, so every point is template-feasible for phase 10).
Coordinates are expressed in the phase-10 unit cube (m in [0.5, 2]).

For each candidate the templating is recomputed (read-only use of the code) to get
  A0, e, reamed volume, bone loss, geometric stem area below the cut (geo_area_mm2), near-wall area, mean wall distance.

usage:  eff_pool.py test 40      (timing on 40 random candidates)
        eff_pool.py full         (all candidates, Pool(4)) -> OUT/universe.npz
"""
from __future__ import annotations

import json
import sys
import time
from multiprocessing import Pool

import numpy as np

import eff_common as E
import eff_explore as X

POOLS = E.HOME / "results" / "pools"


def p9_to_p10(U9):
    lo9, hi9 = E.SPACE9["m"]
    lo, hi = E.SPACE10["m"]
    j = E.VARS10.index("m")
    m = lo9 + U9[:, j] * (hi9 - lo9)
    keep = m >= lo - 1e-9
    U = U9[keep].copy()
    U[:, j] = (m[keep] - lo) / (hi - lo)
    return U, keep


def design_of(u):
    d = {k: E.SPACE10[k][0] + float(x) * (E.SPACE10[k][1] - E.SPACE10[k][0]) for k, x in zip(E.VARS10, u)}
    h = d.pop("h_cut")
    return d, h


def universe():
    z10 = np.load(E.HOME / "results" / "neckopt_p10_pool_live.npz")
    z9 = np.load(E.HOME / "results" / "neckopt_p9_pool_live.npz")
    base10 = sorted(POOLS.glob("neckopt_p10_n16384_s0_*.npz"))[0]
    base9 = sorted(POOLS.glob("neckopt_p9_n16384_s0_*.npz"))[0]
    nb10 = len(np.load(base10)["U"]); nb9 = len(np.load(base9)["U"])
    U10, L10 = z10["U"], z10["loss"]
    U9, keep = p9_to_p10(z9["U"]); L9 = z9["loss"][keep]
    src = np.r_[np.where(np.arange(len(U10)) < nb10, 10, 11), np.where(np.nonzero(keep)[0] < nb9, 9, 12)]
    # 10 = p10 base Sobol, 11 = p10 refresh, 9 = p9 base Sobol (m>=0.5), 12 = p9 refresh (m>=0.5)
    U = np.vstack([U10, U9]); Lo = np.r_[L10, L9]
    # drop exact duplicates
    _, first = np.unique(np.round(U, 10), axis=0, return_index=True)
    first = np.sort(first)
    return U[first], Lo[first], src[first], {"p10_live": len(U10), "p10_base": nb10, "p9_live": len(z9["U"]), "p9_base": nb9,
                                            "p9_kept_m>=0.5": int(keep.sum()), "universe": int(len(first))}


def job(u):
    d, h = design_of(u)
    try:
        r = X.proxies((d, h))
    except Exception as e:  # noqa: BLE001
        r = {"fit": False, "reason": f"{type(e).__name__}: {str(e)[:80]}"}
    return r


def main():
    mode = sys.argv[1]
    U, Lo, src, info = universe()
    print(json.dumps(info))
    if mode == "test":
        n = int(sys.argv[2])
        rng = np.random.default_rng(0)
        idx = rng.choice(len(U), n, replace=False)
        t0 = time.perf_counter()
        with Pool(4) as p:
            res = p.map(job, [U[i] for i in idx], chunksize=1)
        wall = time.perf_counter() - t0
        tt = [r.get("t_all_s", np.nan) for r in res]
        print(f"{n} candidates in {wall:.1f} s wall (4 procs); per-candidate t_all median {np.nanmedian(tt):.2f} s, p90 {np.nanpercentile(tt, 90):.2f} s, "
              f"max {np.nanmax(tt):.1f}; fit {sum(r['fit'] for r in res)}/{n}")
        dl = [abs(r["volume"] + 0 - 0) for r in res if r["fit"]]
        print("example", {k: res[0].get(k) for k in ("A0", "e", "volume", "geo_area_mm2", "t_tpl_s")})
        return
    t0 = time.perf_counter()
    with Pool(4) as p:
        res = p.map(job, list(U), chunksize=8)
    wall = time.perf_counter() - t0
    keys = ("A0", "e", "volume", "geo_area_mm2", "near_area_mm2", "near05_area_mm2", "mean_wall_mm", "t_tpl_s", "t_all_s")
    arr = {k: np.array([float(r.get(k, np.nan)) if r.get(k) is not None else np.nan for r in res]) for k in keys}
    fit = np.array([bool(r.get("fit")) for r in res])
    np.savez(E.OUT / "universe.npz", U=U, loss=Lo, src=src, fit=fit, **arr)
    E.dump("universe_meta.json", {**info, "wall_s": wall, "n_fit": int(fit.sum()),
                                  "t_all_median_s": float(np.nanmedian(arr["t_all_s"])), "t_all_p90_s": float(np.nanpercentile(arr["t_all_s"], 90)),
                                  "reasons": sorted({str(r.get("reason")) for r in res if not r.get("fit")})[:20]})
    print(f"universe {len(U)} in {wall:.0f} s; fit {fit.sum()}")


if __name__ == "__main__":
    main()
