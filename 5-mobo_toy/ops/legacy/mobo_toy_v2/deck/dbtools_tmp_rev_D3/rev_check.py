"""rev_D3 independent checks of tpl_record (read-only on the pipeline; writes only to --out).
Run from the scratch dir holding tpl_record.py, with MOBO_V2_DIR set to the pipeline v2 dir.
R1  every 3406 job with prep templating: compare_job match (not just 20)
R2  independent per-offset recomputation (own loop over CR.template_base / CR.neck_overhang, no tpl_record patching)
    on a62 + random jobs + corner-subbox points: A0_by_e, usable, overhang, e*, A0*, e_margin exact
R3  maximality probe of A0(e): penetration_dense(A0) <= tol and penetration_dense(next bisection grid value) > tol
R4  corner points: tpl_record feasible / e* / A0* / bone vs the production pool call (Phase.template + _feasible formula)
"""
import argparse
import json
import math
import pathlib
import random
import sys
import time

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import tpl_record as T  # noqa: E402
import collar_rule as CR  # noqa: E402
import geom3d as G  # noqa: E402
import jobs as J  # noqa: E402
import stage_neckopt as N  # noqa: E402
import stage_v2a as S  # noqa: E402

OFFS = [-8.0, -6.0, -4.0, -2.0, 0.0, 2.0, 4.0, 6.0, 8.0]
_BASE = {}


def base(neck_axis):
    k = json.dumps(neck_axis)
    if k not in _BASE:
        assert T.femur_cache_file(neck_axis).exists()
        _BASE[k] = J.femur_for({"femur_id": "sawbone3406", "neck_axis": neck_axis})
    return _BASE[k]


def fem_for(spec):
    import copy
    fm = base(spec.get("neck_axis"))
    if spec.get("h_cut") is not None:
        fm = fm.with_cut(spec["h_cut"])
    if spec.get("cfg"):
        fm = copy.copy(fm)
        fm.cfg = copy.deepcopy(fm.cfg)
        J._merge(fm.cfg, spec["cfg"])
    return fm


def indep(st, fm, mc, margin, min_A0, a_max, probe=True):
    """Own per-offset loop (= what template_neck_in_shoulder does, written out), plus maximality probe."""
    out = {"A0": [], "usable": [], "ov": [], "probe": []}
    with J.a_bounds_cap(a_max):
        lo0, hi0 = G.A_BOUNDS
        lo_min = max(min_A0, lo0)
        q = (hi0 / lo0) ** (1.0 / 2 ** 14)
        for e in OFFS:
            r = CR.template_base(st, fm, offsets=np.array([e]), margin=margin, margin_check=mc)
            if not r.get("fit"):
                out["A0"].append(math.nan); out["usable"].append(False); out["ov"].append(math.nan)
                continue
            A0 = r["A0"]
            out["A0"].append(A0)
            if probe:
                pen = CR.penetration_dense if mc == "dense" else G.penetration
                m = st.m if margin is None else margin
                p_at, p_up = pen(st, fm, A0, r["pose"], m), pen(st, fm, A0 * q * (1 + 1e-9), r["pose"], m)
                out["probe"].append((e, p_at <= 0.05, p_up > 0.05, A0))
            if A0 < lo_min:
                out["usable"].append(False); out["ov"].append(math.nan)
                continue
            ov = CR.neck_overhang(st, fm, A0, r["pose"])
            out["ov"].append(ov)
            out["usable"].append(ov <= 2.0)
    best = None
    for k, e in enumerate(OFFS):
        if out["usable"][k]:
            a = out["A0"][k]
            if best is None or a > out["A0"][best] * 1.005 or (abs(a - out["A0"][best]) <= out["A0"][best] * 0.005 and abs(e) < abs(OFFS[best])):
                best = k
    if best is None:
        out.update(e=math.nan, A=math.nan, em=math.nan)
    else:
        oth = [out["A0"][k] for k in range(9) if out["usable"][k] and k != best]
        out.update(e=OFFS[best], A=out["A0"][best], em=(out["A0"][best] - max(oth)) / out["A0"][best] if oth else 1.0)
    return out


def eq(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    return a.shape == b.shape and np.array_equal(a, b, equal_nan=True)


def cmp_rec(tag, rec, ind, fails):
    good = (eq(rec["A0_by_e"], ind["A0"]) and list(map(bool, rec["usable_by_e"])) == ind["usable"]
            and eq(rec["overhang_by_e"], ind["ov"]) and eq([rec["e_star"]], [ind["e"]]) and eq([rec["A0_star"]], [ind["A"]])
            and (eq([rec["e_margin"]], [ind["em"]]) or abs(rec["e_margin"] - ind["em"]) < 1e-14))
    if not good:
        fails.append(tag)
    return good


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", required=True)
    ap.add_argument("--n-jobs-indep", type=int, default=30)
    ap.add_argument("--n-corner", type=int, default=120)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    t0 = time.time()
    listing0 = T._cache_listing()
    rep = {}
    Q = pathlib.Path(a.queue).expanduser()
    jobs_t, specs = [], {}
    for d in sorted(Q.iterdir()):
        sp, pj = d / "spec.json", d / "prep.json"
        if not sp.exists():
            continue
        s = json.loads(sp.read_text(encoding="utf-8"))
        if s.get("femur_id") != "sawbone3406" or s.get("kind") not in ("design", "variant"):
            continue
        specs[d.name] = s
        if pj.exists() and json.loads(pj.read_text(encoding="utf-8")).get("templating"):
            jobs_t.append(d)
    # R1
    res1, bad1, estar, kinds = [], [], {}, {"entry_offset": 0, "cfg": 0, "sparse": 0}
    for d in jobs_t:
        r = T.compare_job(d)
        res1.append(r)
        if not r["match"]:
            bad1.append((d.name, r["sdiff"], r["prep"], r["prep_view"]))
        estar[r["prep"]["e"]] = estar.get(r["prep"]["e"], 0) + 1
        s = specs[d.name]
        kinds["entry_offset"] += s.get("entry_offset") is not None
        kinds["cfg"] += bool(s.get("cfg"))
        kinds["sparse"] += (s.get("margin_check") or "sparse") == "sparse"
    rep["R1"] = {"n_jobs_with_templating": len(jobs_t), "n_match": sum(bool(r["match"]) for r in res1), "mismatches": bad1[:10],
                 "prep_e_counts": estar, "kinds": kinds, "max_sdiff": max(max(r["sdiff"].values()) for r in res1)}
    print("R1", json.dumps({k: v for k, v in rep["R1"].items() if k != "mismatches"}), "mismatches", len(bad1), flush=True)
    # R2 / R3 on jobs
    fails, probes = [], []
    pick = random.Random(7).sample(jobs_t, min(a.n_jobs_indep, len(jobs_t)))
    a62 = Q / "sb13_a62_1e4338ee"
    if a62 in jobs_t and a62 not in pick:
        pick.insert(0, a62)
    for d in pick:
        s = specs[d.name]
        rec = T.record_spec(s)
        if s.get("entry_offset") is not None:
            continue
        st = G.Stem3D(**s["design"])
        ind = indep(st, fem_for(s), s.get("margin_check") or "sparse", s.get("margin"), float(s.get("min_A0", 0.0)), s.get("a_bounds_max"))
        cmp_rec(d.name, rec, ind, fails)
        probes += ind["probe"]
        if d == a62:
            rep["a62"] = {"A0_by_e": [None if math.isnan(x) else round(x, 4) for x in ind["A0"]], "usable": ind["usable"],
                          "ov": [None if math.isnan(x) else round(x, 3) for x in ind["ov"]], "e": ind["e"], "A0": ind["A"], "em": ind["em"],
                          "s_bind_star": rec["s_bind_star"], "bone": rec["bone_mm3"]}
    print("R2 jobs: compared", len(pick), "fails", fails, flush=True)
    # corner points: R2 / R3 / R4
    from scipy.stats import qmc
    ph = N.Phase(13)
    lo = {"L": (38 - 20) / 25, "alpha": (40 - 15) / 30, "h_cut": 0.0, "m": 0.0}
    hi = {"L": 1.0, "alpha": 1.0, "h_cut": 2 / 16, "m": 0.3 / 1.5}
    Z = qmc.Sobol(13, scramble=True, seed=424242).random(a.n_corner)
    U = np.array([[lo.get(v, 0.0) + z * (hi.get(v, 1.0) - lo.get(v, 0.0)) for v, z in zip(ph.vars, row)] for row in Z])
    np.save(pathlib.Path(a.out) / "U_corner.npy", U)
    cf, r4bad, ecount, n_feas, ems, tts = [], [], {}, 0, [], []
    for i, u in enumerate(U):
        rec = T.record_u(u)
        tts.append(rec["t_s"])
        d, h = ph.design_of(u)
        st = G.Stem3D(**d)
        fm = base(ph.neck_axis).with_cut(h)
        ind = indep(st, fm, "dense", None, float(S.MIN_A0), 2000.0, probe=(i < 40))
        cmp_rec(f"corner{i}", rec, ind, cf)
        probes += ind["probe"]
        with J.a_bounds_cap(ph.a_bounds_max):
            r = ph.template(G.Stem3D(**d), fm)
        ok = bool(r["fit"] and r["A0"] >= S.MIN_A0)
        loss = float(fm.resected_volume(ref_cut_mm=ph.ref_cut_mm) + r["volume"]) if ok else math.nan
        if ok != rec["feasible"] or (ok and (r["e"] != rec["e_star"] or r["A0"] != rec["A0_star"] or loss != rec["bone_mm3"])):
            r4bad.append(i)
        if ok:
            n_feas += 1
            ecount[r["e"]] = ecount.get(r["e"], 0) + 1
            ems.append(rec["e_margin"])
    rep["R2_corner"] = {"n": len(U), "fails": cf}
    rep["R4"] = {"n": len(U), "feasible": n_feas, "mismatch": r4bad, "e_counts": ecount,
                 "e_margin_min": min(ems) if ems else None, "e_margin_lt_0.02": int(sum(x < 0.02 for x in ems)),
                 "t_s_mean": float(np.mean(tts))}
    print("R2 corner fails", cf, "R4", json.dumps(rep["R4"]), flush=True)
    pa = sum(p[1] for p in probes)
    pu = sum(p[2] for p in probes)
    rep["R3"] = {"n_probes": len(probes), "ok_at_A0": pa, "fails_at_next_grid": pu,
                 "non_max": [p for p in probes if not p[2]][:10], "not_ok_at_A0": [p for p in probes if not p[1]][:10]}
    print("R3", json.dumps(rep["R3"]), flush=True)
    rep["cache_listing_unchanged"] = T._cache_listing() == listing0
    rep["wall_s"] = time.time() - t0
    (pathlib.Path(a.out) / "rev_check.json").write_text(json.dumps(T._jsonable(rep), indent=1), encoding="utf-8")
    print("cache unchanged", rep["cache_listing_unchanged"], "wall", round(rep["wall_s"], 1), flush=True)


if __name__ == "__main__":
    main()
