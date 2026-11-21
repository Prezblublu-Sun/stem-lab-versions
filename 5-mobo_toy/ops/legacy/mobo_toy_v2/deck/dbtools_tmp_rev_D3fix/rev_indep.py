"""rev_D3fix independent checks of the fixed tpl_record (read-only on the pipeline; writes only to --out).
Run from a dir holding tpl_record.py (or with MOBO_V2_DIR + sys.path to it).
V1  own per-offset loop over CR.template_base / CR.neck_overhang (no tpl_record patching): A0_by_e, code_by_e, overhang, e*, A0*,
    e_margin and the 4 overhang-aware columns computed from scratch (plain python) and compared exactly with tpl_record.
V2  counterfactuals with the real collar_rule.template_neck_in_shoulder:
    (a) e_margin_eff == e_margin recomputed with tol relaxed to tol + 3 mm2 while keeping e* fixed (own loop, ov <= tol + 3),
    (b) every point with ov_gap_up finite: template_neck_in_shoulder(tol = tol + ov_gap_up + 1e-9) picks a larger A0 than A0* when the
        jump offset beats A0* by > 0.5 %, and tol = tol + ov_gap_up - 1e-6 keeps (e*, A0*).
V4  femur_geom_key recomputed from the docstring definition.
"""
import argparse
import copy
import hashlib
import json
import math
import pathlib
import random
import sys
import time

import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("--tool", required=True, help="dir holding tpl_record.py")
ap.add_argument("--queue", required=True)
ap.add_argument("--n-jobs", type=int, default=20)
ap.add_argument("--n-corner", type=int, default=100)
ap.add_argument("--n-global", type=int, default=60)
ap.add_argument("--out", required=True)
a = ap.parse_args()
sys.path.insert(0, a.tool)
import tpl_record as T  # noqa: E402
import collar_rule as CR  # noqa: E402
import femur_3406 as F6  # noqa: E402
import geom3d as G  # noqa: E402
import jobs as J  # noqa: E402
import stage_neckopt as N  # noqa: E402
import stage_v2a as S  # noqa: E402

OFFS = [-8.0, -6.0, -4.0, -2.0, 0.0, 2.0, 4.0, 6.0, 8.0]
TOL, NEAR = 2.0, 3.0
nan = math.nan
_BASE = {}


def base(neck_axis):
    k = json.dumps(neck_axis)
    if k not in _BASE:
        _BASE[k] = T.base_femur("sawbone3406", neck_axis)       # read-only load (cache must exist)
    return _BASE[k]


def fem_for(spec):
    fm = base(spec.get("neck_axis"))
    if spec.get("h_cut") is not None:
        fm = fm.with_cut(spec["h_cut"])
    if spec.get("cfg"):
        fm = copy.copy(fm)
        fm.cfg = copy.deepcopy(fm.cfg)
        J._merge(fm.cfg, spec["cfg"])
    return fm


def code_of(reason):
    s = str(reason)
    if s.startswith("blocked"):
        return 1
    if s.startswith("canal larger than largest size"):
        return 2
    if s.startswith("tip too thin"):
        return 3
    return 9


def pick(A0, usable):
    best = None
    for k, e in enumerate(OFFS):
        if usable[k]:
            x = A0[k]
            if best is None or x > A0[best] * 1.005 or (abs(x - A0[best]) <= A0[best] * 0.005 and abs(e) < abs(OFFS[best])):
                best = k
    return best


def indep(st, fm, mc, margin, min_A0, a_max):
    A0, code, ov = [nan] * 9, [-1] * 9, [nan] * 9
    with J.a_bounds_cap(a_max):
        lo_min = max(min_A0, G.A_BOUNDS[0])
        for k, e in enumerate(OFFS):
            r = CR.template_base(st, fm, offsets=np.array([e]), margin=margin, margin_check=mc)
            if not r.get("fit"):
                code[k] = code_of(r.get("reason"))
                continue
            A0[k] = float(r["A0"])
            if r["A0"] < lo_min:
                code[k] = 4
                continue
            ov[k] = float(CR.neck_overhang(st, fm, r["A0"], r["pose"]))
            code[k] = 0 if ov[k] <= TOL else 5
    usable = [c == 0 for c in code]
    b = pick(A0, usable)
    out = {"A0": A0, "code": code, "ov": ov, "e": nan, "A": nan, "em": nan, "ov_slack": nan, "gap_up": nan, "up_rel": nan, "eff": nan,
           "em_relaxed": nan}
    if b is None:
        return out
    As = A0[b]
    oth = [A0[k] for k in range(9) if usable[k] and k != b]
    em = (As - max(oth)) / As if oth else 1.0
    up = [k for k in range(9) if code[k] == 5 and A0[k] > As]
    near = [k for k in range(9) if code[k] == 5 and ov[k] - TOL <= NEAR]
    eff = em
    for k in near:                                           # own loop form of min(e_margin, (A0* - max near A0) / A0*)
        eff = min(eff, (As - A0[k]) / As)
    # counterfactual: tol relaxed by NEAR, e* kept: the usable set grows by the near code-5 offsets
    oth2 = [A0[k] for k in range(9) if k != b and code[k] in (0, 5) and ov[k] <= TOL + NEAR]
    em2 = (As - max(oth2)) / As if oth2 else 1.0
    out.update(e=OFFS[b], A=As, em=em, ov_slack=TOL - ov[b], gap_up=min(ov[k] - TOL for k in up) if up else nan,
               up_rel=(max(A0[k] for k in up) - As) / As if up else nan, eff=eff, em_relaxed=em2,
               up_best=max(up, key=lambda k: A0[k]) if up else None)
    return out


def eqf(x, y, tol=0.0):
    x = nan if x is None else float(x)
    y = nan if y is None else float(y)
    return (math.isnan(x) and math.isnan(y)) or abs(x - y) <= tol


def compare(tag, rec, ind, fails):
    bad = []
    if not np.array_equal(np.asarray(rec["A0_by_e"], float), np.asarray(ind["A0"], float), equal_nan=True):
        bad.append("A0_by_e")
    if [int(c) for c in rec["code_by_e"]] != ind["code"]:
        bad.append(f"code {list(map(int, rec['code_by_e']))} vs {ind['code']}")
    if not np.array_equal(np.asarray(rec["overhang_by_e"], float), np.asarray(ind["ov"], float), equal_nan=True):
        bad.append("overhang_by_e")
    for kr, ki, t in (("e_star", "e", 0.0), ("A0_star", "A", 0.0), ("e_margin", "em", 1e-15), ("ov_slack_star", "ov_slack", 1e-12),
                      ("ov_gap_up", "gap_up", 1e-12), ("A0_up_rel", "up_rel", 1e-15), ("e_margin_eff", "eff", 1e-15)):
        if not eqf(rec[kr], ind[ki], t):
            bad.append(f"{kr} {rec[kr]} vs {ind[ki]}")
    if not eqf(rec["e_margin_eff"], ind["em_relaxed"], 1e-12):
        bad.append(f"e_margin_eff {rec['e_margin_eff']} vs relaxed-tol e_margin {ind['em_relaxed']}")
    if bad:
        fails.append((tag, bad))
    return not bad


def counterfactual(st, fm, mc, margin, min_A0, a_max, rec, ind, cf):
    """(b): relax tol just past ov_gap_up -> the real selector jumps to a larger A0; just below -> unchanged."""
    if not np.isfinite(rec["ov_gap_up"]):
        return
    g = float(rec["ov_gap_up"])
    with J.a_bounds_cap(a_max):
        hi = CR.template_neck_in_shoulder(st, fm, offsets=T.OFFSETS.copy(), margin=margin, min_A0=min_A0, tol_mm2=TOL + g + 1e-9,
                                          margin_check=mc)
        lo = CR.template_neck_in_shoulder(st, fm, offsets=T.OFFSETS.copy(), margin=margin, min_A0=min_A0, tol_mm2=TOL + g - 1e-6,
                                          margin_check=mc)
    As = rec["A0_star"]
    k_up = [k for k in range(9) if ind["code"][k] == 5 and ind["A0"][k] > As and abs(ind["ov"][k] - TOL - g) <= 1e-12]
    expect_jump = any(ind["A0"][k] > As * 1.005 for k in k_up)
    jumped = bool(hi.get("fit")) and hi["A0"] > As
    kept = bool(lo.get("fit")) and lo["e"] == rec["e_star"] and lo["A0"] == As
    cf.append({"jumped": jumped, "expect_jump": expect_jump, "kept_below": kept, "A0_star": As, "A0_hi": hi.get("A0"),
               "e_hi": hi.get("e"), "gap": g})


def run_point(tag, st, fm, mc, margin, min_A0, a_max, rec, fails, cfs):
    ind = indep(st, fm, mc, margin, min_A0, a_max)
    compare(tag, rec, ind, fails)
    counterfactual(st, fm, mc, margin, min_A0, a_max, rec, ind, cfs)
    return ind


def main():
    t0 = time.time()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    listing0 = T._cache_listing()
    rep = {}
    # V4 femur_geom_key from the definition
    cfg = F6.load_cfg("isthmus")
    fc = cfg["femur"]
    rest = {k: v for k, v in fc.items() if not k.startswith("step_") and k != "neck_axis"}
    h = hashlib.sha256(pathlib.Path(F6.__file__).read_bytes())
    h.update(fc["sha256_cortical"].encode())
    h.update(fc["sha256_cancellous"].encode())
    h.update(json.dumps(rest, sort_keys=True, default=float).encode())
    rep["V4"] = {"own": h.hexdigest()[:16], "tool": T.femur_geom_key(), "rest_keys": sorted(rest), "cache_name": T.femur_cache_file("isthmus").name}
    print("V4", json.dumps(rep["V4"]), flush=True)
    # jobs
    Q = pathlib.Path(a.queue).expanduser()
    specs, jobs_t = {}, []
    for d in sorted(Q.iterdir()):
        sp, pj = d / "spec.json", d / "prep.json"
        if not sp.exists():
            continue
        s = T.read_json(sp)
        if s.get("femur_id") != "sawbone3406" or s.get("kind") not in ("design", "variant"):
            continue
        if pj.exists() and (T.read_json(pj).get("templating")):
            specs[d.name] = s
            jobs_t.append(d.name)
    must = [j for j in ("sb13_a62_1e4338ee", "sb14_a60_46532259", "d13bond_p14_a60_46532259_abb4a90f", "sb11_init_da59a243",
                        "sb13_init_4bb091df", "sb14_a39_b1c7c010", "sb14_a67_8f948720", "sb14_a6_81f3fd78") if j in specs]
    rnd = random.Random(4711).sample([j for j in jobs_t if j not in must], min(a.n_jobs, len(jobs_t) - len(must)))
    fails, cfs, nj = [], [], 0
    for j in must + rnd:
        s = specs[j]
        if s.get("entry_offset") is not None:
            continue
        rec = T.record_spec(s)
        run_point(j, G.Stem3D(**s["design"]), fem_for(s), s.get("margin_check") or "sparse", s.get("margin"), float(s.get("min_A0", 0.0)),
                  s.get("a_bounds_max"), rec, fails, cfs)
        nj += 1
        if j == "sb14_a60_46532259":
            rep["sb14_a60"] = {k: rec[k] for k in ("e_star", "A0_star", "e_margin", "ov_slack_star", "ov_gap_up", "A0_up_rel", "e_margin_eff")}
    print(f"V1/V2 jobs: {nj} compared ({len(must)} named), fails {fails}", flush=True)
    # corner sub-box + global points (phase 13 pool settings)
    from scipy.stats import qmc
    ph = N.Phase(13)
    lo = {"L": (38 - 20) / 25, "alpha": (40 - 15) / 30, "h_cut": 0.0, "m": 0.0}
    hi = {"L": 1.0, "alpha": 1.0, "h_cut": 2 / 16, "m": 0.3 / 1.5}
    Z = qmc.Sobol(13, scramble=True, seed=9090).random(a.n_corner)
    Uc = np.array([[lo.get(v, 0.0) + z * (hi.get(v, 1.0) - lo.get(v, 0.0)) for v, z in zip(ph.vars, row)] for row in Z])
    Ug = qmc.Sobol(13, scramble=True, seed=31337).random(a.n_global)
    stats = {"n": 0, "feasible": 0, "jump": 0, "eff_lt_em": 0, "ov_slack_lt_0.1": 0}
    for tag, U in (("corner", Uc), ("global", Ug)):
        for i, u in enumerate(U):
            rec = T.record_u(u)
            d, hh = ph.design_of(u)
            ind = run_point(f"{tag}{i}", G.Stem3D(**d), base(ph.neck_axis).with_cut(hh), "dense", None, float(S.MIN_A0), 2000.0, rec, fails, cfs)
            stats["n"] += 1
            if rec["feasible"]:
                stats["feasible"] += 1
                stats["jump"] += bool(np.isfinite(rec["A0_up_rel"]))
                stats["eff_lt_em"] += bool(rec["e_margin_eff"] < rec["e_margin"])
                stats["ov_slack_lt_0.1"] += bool(rec["ov_slack_star"] < 0.1)
    rep["points"] = stats
    rep["fails"] = fails
    rep["counterfactual"] = {"n": len(cfs), "expect_jump": sum(c["expect_jump"] for c in cfs),
                             "jumped_when_expected": sum(c["jumped"] for c in cfs if c["expect_jump"]),
                             "jumped_when_not_expected": sum(c["jumped"] for c in cfs if not c["expect_jump"]),
                             "kept_below": sum(c["kept_below"] for c in cfs), "rows": cfs[:40]}
    rep["cache_listing_unchanged"] = T._cache_listing() == listing0
    rep["wall_s"] = time.time() - t0
    print("points", json.dumps(stats), flush=True)
    print("counterfactual", json.dumps({k: v for k, v in rep["counterfactual"].items() if k != "rows"}), flush=True)
    print("fails", len(fails), fails[:5], flush=True)
    print("cache listing unchanged", rep["cache_listing_unchanged"], f"wall {rep['wall_s']:.0f} s", flush=True)
    (out / "rev_indep.json").write_text(json.dumps(T._jsonable(rep), indent=1, default=str), encoding="utf-8")


main()
