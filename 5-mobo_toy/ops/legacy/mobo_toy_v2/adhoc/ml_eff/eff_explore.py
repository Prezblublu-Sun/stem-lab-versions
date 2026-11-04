"""Step 1: collarless data set, geometric proxies, emulator inputs.

* subset = current code, no overrides, collarless neck_in_shoulder rows of data/metrics_all.csv
* recompute templating (neck_in_shoulder) for each design -> A0 check + timing + geometric proxies:
    geo_area_mm2   stem surface area below the cut plane (quads of Stem3D.local_surface rings)
    near_area_mm2  part of it whose distance to the canal wall is <= m + 1 mm
    mean_wall_mm   area-weighted mean distance from the stem surface to the canal wall
* Spearman of the phase-10 targets against candidate proxies
* GP length scales stored by the optimiser (neckopt_p9 / p10)
Writes OUT/explore.json and OUT/collarless_dataset.npz
"""
from __future__ import annotations

import json
import math
import time
from multiprocessing import Pool

import numpy as np

import eff_common as E

_FM = {}


def femur():
    if "fm" not in _FM:
        import femur_real as FR
        key = FR._cache_key(FR.load_cfg())
        f = FR.CACHE / f"femur_real_{key}.npz"
        if not f.exists():                       # never let build() write into the code tree
            raise RuntimeError(f"femur cache missing: {f}")
        _FM["fm"] = FR.build()
    return _FM["fm"]


def stem_of(d):
    import geom3d as G
    keys = ("L", "rho_tip", "q", "lam", "g_ml", "g_ap", "n_a", "n_p", "tau_a", "tau_p", "alpha", "m")
    return G.Stem3D(**{k: float(d[k]) for k in keys}, cap_h=G.CAP_FLAT)


def surface_quads(st, A0, ns=70, m=64, ncap=6):
    """rings of local_surface -> quad centroids (local coords) and areas (local == world metric, rigid pose)."""
    import geom3d as G
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


def proxies(args):
    d, h_cut = args
    import collar_rule as CR
    import stage_v2a as S
    t0 = time.perf_counter()
    fm = femur().with_cut(h_cut)
    st = stem_of(d)
    r = CR.template_neck_in_shoulder(st, fm, min_A0=S.MIN_A0)
    t_tpl = time.perf_counter() - t0
    if not r.get("fit"):
        return {"fit": False, "t_tpl_s": t_tpl, "reason": str(r.get("reason"))[:80]}
    A0 = r["A0"]
    C, Ar = surface_quads(st, A0)
    P = fm.to_world(C, r["pose"])
    below = fm.below_cut(P)
    dist = -fm.canal_sdf(P[below])                  # >0 inside the canal: distance to the endosteal wall
    w = Ar[below]
    out = {"fit": True, "A0": A0, "e": r["e"], "volume": r["volume"], "contact": r.get("contact"), "s_bind": r.get("s_bind"),
           "geo_area_mm2": float(w.sum()), "near_area_mm2": float(w[dist <= st.m + 1.0].sum()),
           "near05_area_mm2": float(w[dist <= st.m + 0.5].sum()),
           "mean_wall_mm": float((w * dist).sum() / w.sum()), "t_tpl_s": t_tpl, "t_all_s": time.perf_counter() - t0}
    return out


def main():
    rows = E.read_table()
    sub = E.collarless_rows(rows)
    fam = {}
    for r in sub:
        fam[r["family"]] = fam.get(r["family"], 0) + 1
    print("collarless rows", len(sub), fam, "m>=0.5:", sum(E.fnum(r["m"]) >= 0.5 - 1e-9 for r in sub))
    designs = [({k: E.fnum(r[k]) for k in ("L", "rho_tip", "q", "lam", "g_ml", "g_ap", "n_a", "n_p", "tau_a", "tau_p", "alpha", "m")},
                E.fnum(r["h_cut"])) for r in sub]
    t0 = time.perf_counter()
    with Pool(4) as p:
        px = p.map(proxies, designs, chunksize=4)
    wall = time.perf_counter() - t0
    print(f"proxies for {len(px)} designs in {wall:.0f} s; per design templating median "
          f"{np.median([q['t_tpl_s'] for q in px]):.2f} s")
    nfit = sum(q["fit"] for q in px)
    dA0 = [abs(q["A0"] - E.fnum(r["tpl_A0"])) / E.fnum(r["tpl_A0"]) for q, r in zip(px, sub) if q["fit"]]
    out = {"n": len(sub), "families": fam, "n_refit": nfit, "A0_rel_diff_max": float(max(dA0)) if dA0 else None,
           "A0_rel_diff_median": float(np.median(dA0)) if dA0 else None, "proxy_wall_s": wall,
           "t_tpl_median_s": float(np.median([q["t_tpl_s"] for q in px])), "t_tpl_p90_s": float(np.percentile([q["t_tpl_s"] for q in px], 90))}
    Y = {k: np.array([E.outputs(r)[k] for r in sub]) for k in ("y_rot", "y_con", "c_mm", "c_vm", "c_sed")}
    cand = {k: np.array([E.fnum(r[k]) for r in sub]) for k in ("body_interface_mm2", "interface_area", "prep_interface_area_mm2", "tpl_A0",
                                                                 "tpl_contact", "tpl_volume", "tpl_s_bind", "tpl_e", "L", "m", "alpha",
                                                                 "contact_frac_load2", "contact_area_load_mm2", "f1_first_p95_um",
                                                                 "rot_tilt_first_deg", "subsid_first_um", "bone_total_mm3", "n_tet")}
    for k in ("geo_area_mm2", "near_area_mm2", "near05_area_mm2", "mean_wall_mm"):
        cand[k] = np.array([q.get(k, np.nan) for q in px])
    corr = {}
    for yk, yv in Y.items():
        corr[yk] = {ck: E.spearman(yv, cv)[0] for ck, cv in cand.items()}
    out["spearman_targets_vs_candidates"] = corr
    # linear R2 of contact area on geometric area
    from numpy.linalg import lstsq
    for ck in ("geo_area_mm2", "body_interface_mm2", "near_area_mm2"):
        x = cand[ck]; y = Y["y_con"]; ok = np.isfinite(x) & np.isfinite(y)
        A = np.c_[np.ones(ok.sum()), x[ok]]
        coef, *_ = lstsq(A, y[ok], rcond=None)
        res = y[ok] - A @ coef
        out[f"R2_contact_on_{ck}"] = float(1 - res.var() / y[ok].var())
        out[f"coef_contact_on_{ck}"] = coef.tolist()
    x, y = cand["geo_area_mm2"], cand["body_interface_mm2"]; ok = np.isfinite(x) & np.isfinite(y)
    out["geo_area_vs_mesh_interface"] = {"spearman": E.spearman(x, y)[0], "ratio_median": float(np.median(y[ok] / x[ok])),
                                          "ratio_p5_p95": np.percentile(y[ok] / x[ok], [5, 95]).tolist()}
    # optimiser length scales
    ls = {}
    for ph in (9, 10):
        st = json.loads((E.HOME / "results" / f"neckopt_p{ph}.json").read_text())
        lsh = st.get("lengthscales", {})
        last = lsh[max(lsh, key=lambda s: int(s))] if lsh else {}
        ls[f"p{ph}"] = {"n_key": max(lsh, key=lambda s: int(s)) if lsh else None, **{k: v for k, v in last.items()}}
        ls[f"p{ph}_vars"] = list(st["space"])
    out["optimiser_lengthscales"] = ls
    E.dump("explore.json", out)
    X9 = np.array([E.to_unit(r, E.SPACE9) for r in sub])
    np.savez(E.OUT / "collarless_dataset.npz", X9=X9, **Y, **{f"px_{k}": v for k, v in cand.items()},
             family=np.array([r["family"] for r in sub]), job=np.array([r["job"] for r in sub]),
             nk_phase=np.array([E.fnum(r["nk_phase"]) for r in sub]), m=np.array([E.fnum(r["m"]) for r in sub]),
             fric_wall_s=np.array([E.fnum(r["fric_wall_s"]) for r in sub]))
    print(json.dumps({k: v for k, v in out.items() if k != "spearman_targets_vs_candidates"}, indent=1, default=float)[:4000])
    for yk in corr:
        top = sorted(corr[yk].items(), key=lambda kv: -abs(kv[1]) if np.isfinite(kv[1]) else 0)[:8]
        print(yk, [(k, round(v, 2)) for k, v in top])


if __name__ == "__main__":
    main()
