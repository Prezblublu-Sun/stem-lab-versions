"""Run with the repo venv: PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 .venv-mobo/Scripts/python.exe v2/tests/test_tpl_record.py
        [--queue DIR] [--sample N] [--expect-jobs N] [--tol 1e-9] [--pool NPZ] [--max-workers 2] [--expect-geom-key KEY] [--tmp DIR]
        [--skip-real]
On Linux (read-only on the pipeline): copy tpl_record.py + tests/test_tpl_record.py to a scratch dir and run with
MOBO_V2_DIR=~/mobo_toy_v2/code/v2 PYTHONDONTWRITEBYTECODE=1 ... --queue ~/mobo_toy_v2/queue --max-workers 1 --tmp <scratch>.
Writes only under --tmp (default: a new dir in the system temp dir); never touches the femur cache, the code dir or the queue.
--max-workers 1 skips every check that starts worker processes (E5, E18-E21); nothing else spawns a process.

v2/tpl_record.py (3406 database plan 2026-10-25, section 2.2 D3): per-offset A0 / usable record around
collar_rule.template_neck_in_shoulder.
A. import-time contract: 9 offsets -8..8 step 2 = the collar_rule default; tol 2 mm2 in both install_neck (prep) and the pool call;
   collar_rule / femur module names untouched by the import; phase_rule(13) = the phase-13 pool settings, CT / collared phases refused;
   format 2, OV_NEAR_MM2 3 mm2, the provenance keys compared on resume.
B. record logic on stubs (no femur): per-offset codes, A0_by_e, overhang only where collar_rule computed it, overhang == tol usable,
   e* / A0* = collar_rule's own choice, tie rule, e_margin cases; overhang-aware columns ov_slack_star / ov_gap_up / A0_up_rel /
   e_margin_eff (larger overhang-blocked offset near / far from tol, a near-blocked offset with a smaller A0, the 3 mm2 boundary,
   infeasible -> NaN); drift detection raises TplRecordError; names restored after errors.
C. femur cache stays read-only (np.save* refused, missing cache -> FileNotFoundError before jobs.femur_for, a writing build refused,
   a plain-file write caught by the listing); femur_geom_key is host-independent (other STEP paths / neck axis -> same key; other
   femur_3406.py bytes, STEP sha256 or cfg value -> other key; a path-like cfg value is refused).
D. real 3406 femur (local cache must exist unless --skip-real): a62 = sb13_a62_1e4338ee gives A0 499.45 mm2, e 0, s_bind 13.2 mm and
   reproduces its prep.json templating and bone_loss.total_mm3 to 1e-9; e_margin and the overhang-aware columns re-derived
   independently from its arrays; record_u of its unit point gives the same; forced entry_offset view = a direct single-offset call.
E. batch: npz fields / dtypes / allow_pickle=False; meta provenance (femur_geom_key, STEP file sha256 = declared, cache sha256);
   serial == spawn workers; a62 row = record_spec; resume recomputes only the not-done rows; resume refused for another point list
   and for every changed compared provenance key (named in the error, file unchanged), accepted when only host info differs;
   readers and bad input; output in the code dir refused; a point error -> error row + CLI exit 3; a TplRecordError aborts after
   saving the done rows; a missing femur cache is caught in the parent before any worker starts (workers=2, no child process);
   workers=2 abort paths, each bounded by --abort-timeout: worker initializer failure -> BrokenProcessPool, a worker killed mid-batch
   -> BrokenProcessPool with the done rows saved (and --resume completes them), a TplRecordError inside a worker -> TplRecordError
   with the done rows saved; no worker process left behind.
F. (needs --queue) every existing 3406 job with prep templating (or --sample N of them): e* / A0* / alpha / s_bind / contact / volume /
   bone loss equal prep.json (scaled diff <= --tol, default 1e-9); e_margin and the overhang-aware columns consistent with each
   job's arrays; --expect-jobs N checks the job count; prep-stage failures after templating (meshing) are feasible.
   prep.json was written on Linux with the Linux femur cache build; the Windows cache is a separate build (other bytes), and on the
   2026-10-25 mirror 2 of 287 jobs (sb14_a8_baddb200 and its d13bond copy) differ there in 'contact' only, by 1.15e-6 absolute.
G. (needs --pool results/pools/neckopt_p11_n16384_s0_<key>.npz) the first --pool-n Sobol points of the phase-11/13 candidate pool:
   feasible flags = the pool file's rows, bone_mm3 = its loss; derived columns consistent with the arrays.
Section F / G inputs can be read-only mirrors (spec / prep / FAILED json of the 3406 jobs; the pool npz + json).
"""
import os

for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_k, "1")                           # before numpy; spawned workers inherit it

import argparse  # noqa: E402
import collections  # noqa: E402
import contextlib  # noqa: E402
import copy  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import multiprocessing as mp  # noqa: E402
import pathlib  # noqa: E402
import random  # noqa: E402
import shutil  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from concurrent.futures.process import BrokenProcessPool  # noqa: E402

import numpy as np  # noqa: E402

TOOLDIR = pathlib.Path(__file__).resolve().parent.parent        # v2/ (or the Linux scratch copy holding tpl_record.py)
sys.path.insert(0, str(TOOLDIR))
import tpl_record as T  # noqa: E402
import collar_rule as CR  # noqa: E402
import femur_3406 as F6  # noqa: E402
import femur_real as FR  # noqa: E402
import geom3d as G  # noqa: E402
import jobs as J  # noqa: E402
import stage_neckopt as N  # noqa: E402
import stage_v2a as S  # noqa: E402

# ---------------------------------------------------------------- fault injection inside spawned workers only (E18-E20)
FAULT_ENV = "TPL_RECORD_TEST_WORKER_FAULT"


def _install_worker_fault(spec: str) -> None:
    """Runs at import in a spawned worker (this file is re-run there as __mp_main__). 'init' -> the worker's femur load fails;
    'kill:<u0>' -> the worker process dies (os._exit) on the point whose first coordinate is u0; 'drift:<u0>' -> TplRecordError there."""
    kind, _, arg = spec.partition(":")
    if kind == "init":
        def _no_cache(*a, **k):
            raise FileNotFoundError("simulated by the test: femur cache missing for this worker")
        T.base_femur = _no_cache
        return
    target, real = float(arg), T.record_u

    def _faulty(u, phase=13):
        u0 = float(np.asarray(u, float).ravel()[0])
        if u0 == target:
            print(f"   [worker {os.getpid()}] simulated fault '{kind}' on the point with u0 {u0:.4f}", file=sys.stderr, flush=True)
            if kind == "kill":
                os._exit(17)
            raise T.TplRecordError("simulated by the test: drift inside a worker")
        r = real(u, phase)
        print(f"   [worker {os.getpid()}] computed the point with u0 {u0:.4f}", file=sys.stderr, flush=True)
        return r
    T.record_u = _faulty


if os.environ.get(FAULT_ENV) and mp.current_process().name != "MainProcess":
    _install_worker_fault(os.environ[FAULT_ENV])

ORIG = {"tb": CR.template_base, "ov": CR.neck_overhang, "tnis": CR.template_neck_in_shoulder, "F6np": F6.np, "FRnp": FR.np,
        "cache": F6.CACHE, "femur_for": J.femur_for, "record_u": T.record_u, "base_femur": T.base_femur}
checks, skipped, HUNG = [], [], []
OFFS = [-8.0, -6.0, -4.0, -2.0, 0.0, 2.0, 4.0, 6.0, 8.0]
DERIVED = ("e_margin", "ov_slack_star", "ov_gap_up", "A0_up_rel", "e_margin_eff")

A62 = {"kind": "design", "design": {"L": 43.38704499515694, "rho_tip": 0.16517819132701733, "q": 2.7538719704053864,
       "lam": 1.090195578596122, "g_ml": 0.5223973738876415, "g_ap": 0.49436297860594985, "n_a": 5.112527593167926,
       "n_p": 2.738548572072265, "tau_a": -0.1992985037229839, "tau_p": -0.06939592084101803, "alpha": 44.58580627373884,
       "m": 0.5369298773824921, "cap_h": 1.5}, "h_int": 2.0, "min_A0": 153.93804002589985, "stage": "sb13", "tag": "a62",
       "model": "m1", "h_cut": 16.0, "slip_tol": 0.00025, "delta": 0.1, "collar_rule": "neck_in_shoulder", "femur_id": "sawbone3406",
       "neck_axis": "isthmus", "margin_check": "dense", "ref_cut_mm": 16.0, "a_bounds_max": 2000.0, "fric_only": True}   # spec.json
A62_PREP = {"alpha": 44.58580627373884, "e": 0.0, "A0": 499.44875302714706, "contact": 0.0008697542944118286,
            "s_bind": 13.204752824612981, "volume": 8480.963668790451, "bone_total_mm3": 8480.963668790451}  # sb13_a62_1e4338ee prep.json


def ok(name, cond, extra=""):
    checks.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""), flush=True)


def skip(name, why):
    skipped.append(name)
    print(f"SKIP {name}  [{why}]", flush=True)


def raises(exc, fn, *a, **k):
    try:
        fn(*a, **k)
    except exc as e:
        return str(e) or type(e).__name__
    except Exception as e:                                   # noqa: BLE001
        return f"WRONG EXCEPTION {type(e).__name__}: {e}"
    return None


def good(msg) -> bool:
    return bool(msg) and not str(msg).startswith("WRONG EXCEPTION")


def same(a, b) -> bool:
    a, b = np.asarray(a), np.asarray(b)
    if a.shape != b.shape:
        return False
    if a.dtype.kind == "f" or b.dtype.kind == "f":
        return bool(np.array_equal(a, b, equal_nan=True))
    return bool(np.array_equal(a, b))


def close(a, b, tol=1e-12) -> bool:
    a = math.nan if a is None else float(a)
    b = math.nan if b is None else float(b)
    return (math.isnan(a) and math.isnan(b)) or abs(a - b) <= tol


def names_restored() -> bool:
    return CR.template_base is ORIG["tb"] and CR.neck_overhang is ORIG["ov"] and CR.template_neck_in_shoulder is ORIG["tnis"]


def rederive(A0, code, ovh, e_star, A0_star, tol=2.0, near=3.0) -> dict:
    """Independent re-derivation (plain loops, not tpl_record code) of e_margin and the overhang-aware columns from the 9-offset arrays."""
    nan = math.nan
    f = (lambda v: nan if v is None else float(v))
    A0, ovh, code = [f(v) for v in A0], [f(v) for v in ovh], [int(c) for c in code]
    e_star, A0_star = f(e_star), f(A0_star)
    if math.isnan(e_star):
        return dict.fromkeys(DERIVED, nan)
    k = OFFS.index(e_star)
    others = [A0[j] for j in range(9) if code[j] == 0 and j != k]
    em = (A0_star - max(others)) / A0_star if others else 1.0
    up = [j for j in range(9) if code[j] == 5 and A0[j] > A0_star]
    nr = [j for j in range(9) if code[j] == 5 and ovh[j] - tol <= near]
    return {"e_margin": em, "ov_slack_star": tol - ovh[k],
            "ov_gap_up": min(ovh[j] - tol for j in up) if up else nan,
            "A0_up_rel": (max(A0[j] for j in up) - A0_star) / A0_star if up else nan,
            "e_margin_eff": min(em, (A0_star - max(A0[j] for j in nr)) / A0_star) if nr else em}


def derived_ok(rec) -> bool:
    want = rederive(rec["A0_by_e"], rec["code_by_e"], rec["overhang_by_e"], rec["e_star"], rec["A0_star"])
    return all(close(rec[k], want[k]) for k in DERIVED)


def run_bounded(fn, timeout):
    """fn() in a thread; ('returned', value) / ('raised', exception) / ('hung', None) after timeout s (the run then exits hard)."""
    res = {}

    def run():
        try:
            res["value"] = fn()
        except BaseException as e:                           # noqa: BLE001
            res["exc"] = e
    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive():
        HUNG.append(fn)
        return "hung", None
    return ("raised", res["exc"]) if "exc" in res else ("returned", res.get("value"))


@contextlib.contextmanager
def worker_fault(spec):
    os.environ[FAULT_ENV] = spec
    try:
        yield
    finally:
        os.environ.pop(FAULT_ENV, None)


def sha256(p) -> str:
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


# ---------------------------------------------------------------- stubs for section B
RS = T.Rule("sawbone3406", "isthmus", "dense", 2000.0, 16.0, float(S.MIN_A0))
BLOCKED = "blocked (smallest size hits cortex at every offset)"


class FakeStem:
    has_collar = False
    m = 0.5


class FakeFem:
    def resected_volume(self, ref_cut_mm=25.0):
        return 100.0 if ref_cut_mm == 16.0 else -1.0


def fit(e, A0):
    return {"fit": True, "alpha": 44.0, "e": float(e), "A0": float(A0), "pose": ("pose", float(e)), "volume": 10.0 * A0,
            "contact": 0.01, "s_bind": 5.0 + e, "margin": 0.5, "margin_check": "dense"}


def nofit(reason):
    return {"fit": False, "reason": reason, "margin": 0.5, "margin_check": "dense"}


def install_table(tb_by_e, ov_by_e, calls=None):
    """Stub "originals" for collar_rule.template_base / neck_overhang (tpl_record wraps whatever is there at call time)."""
    def tb(stem, fem, alphas=None, offsets=None, iters=14, margin=None, margin_check=None):
        e = float(np.asarray(offsets).ravel()[0])
        if calls is not None:
            calls.append(("tb", e, margin_check))
        return dict(tb_by_e[e])

    def ov(st, fm, A0, pose):
        if calls is not None:
            calls.append(("ov", pose[1]))
        return ov_by_e[pose[1]]
    CR.template_base, CR.neck_overhang = tb, ov
    return tb, ov


def run_stub(tb_by_e, ov_by_e, calls=None):
    tb, ov = install_table(tb_by_e, ov_by_e, calls)
    return T.record_with(FakeStem(), FakeFem(), RS), (tb, ov)


def table():
    return {e: nofit(BLOCKED) for e in T.OFFSETS.tolist()}


def drift_pick_smallest(stem, fem, offsets=None, margin=None, min_A0=0.0, tol_mm2=2.0, margin_check=None, **k):
    best = None
    for e in offsets:
        r = CR.template_base(stem, fem, offsets=np.array([e]), margin=margin, margin_check=margin_check)
        if r.get("fit") and r["A0"] >= min_A0 and CR.neck_overhang(stem, fem, r["A0"], r["pose"]) <= tol_mm2:
            if best is None or r["A0"] < best["A0"]:
                best = r
    return best or {"fit": False, "reason": "x"}


def drift_all_at_once(stem, fem, offsets=None, margin=None, margin_check=None, **k):
    return CR.template_base(stem, fem, offsets=offsets, margin=margin, margin_check=margin_check)


def drift_skip_one(stem, fem, offsets=None, margin=None, min_A0=0.0, margin_check=None, **k):
    for e in offsets[:-1]:                                   # like collar_rule, but the last offset is never tried
        r = CR.template_base(stem, fem, offsets=np.array([e]), margin=margin, margin_check=margin_check)
        if r.get("fit") and r["A0"] >= max(min_A0, G.A_BOUNDS[0]):
            CR.neck_overhang(stem, fem, r["A0"], r["pose"])
    return {"fit": False, "reason": "x"}


def drift_say_none(stem, fem, offsets=None, margin=None, min_A0=0.0, margin_check=None, **k):
    for e in offsets:
        r = CR.template_base(stem, fem, offsets=np.array([e]), margin=margin, margin_check=margin_check)
        if r.get("fit") and r["A0"] >= min_A0:
            CR.neck_overhang(stem, fem, r["A0"], r["pose"])
    return {"fit": False, "reason": "collar_rule neck_in_shoulder: no offset works"}


def femur_for_writes_np(spec):
    F6.np.savez_compressed(F6.CACHE / "femur_3406_new.npz", a=np.zeros(1))


def femur_for_writes_file(spec):
    (pathlib.Path(F6.CACHE) / "femur_3406_other.npz").write_bytes(b"x")
    return object()


# ================================================================================================ sections
def sec_a():
    ok("A1 OFFSETS = collar_rule default -8..8 step 2 (9 columns)", T.OFFSETS.tolist() == OFFS and T.NE == 9)
    ok("A2 tol_mm2 2.0 = template_neck_in_shoulder default = install_neck default (prep and pool agree)", T.TOL_MM2 == 2.0)
    ok("A3 importing tpl_record leaves collar_rule / femur module names untouched", names_restored() and F6.np is np and FR.np is np)
    r = T.phase_rule(13)
    ok("A4 phase_rule(13) = stage_neckopt phase 13 pool settings", (r.femur_id, r.neck_axis, r.margin_check, r.a_bounds_max,
       r.ref_cut_mm, r.min_A0, r.margin) == ("sawbone3406", "isthmus", "dense", 2000.0, 16.0, float(S.MIN_A0), None), str(r))
    ok("A5 phase_rule refuses a CT phase (10) and a collared phase (8)", good(raises(ValueError, T.phase_rule, 10))
       and good(raises(ValueError, T.phase_rule, 8)))
    ok("A6 format 2, OV_NEAR_MM2 3 mm2, resume compares code_hash / aux_md5 / femur_geom_key / femur_cache (+ sha256) / step sha256",
       T.FORMAT == 2 and T.OV_NEAR_MM2 == 3.0 and T.PROVENANCE_COMPARED == ("code_hash", "aux_md5", "femur_geom_key", "femur_cache",
                                                                            "femur_cache_sha256", "step_sha256", "step_file_sha256"))


def sec_b():
    tab1 = {-8.0: nofit(BLOCKED), -6.0: nofit("canal larger than largest size"), -4.0: nofit("tip too thin (5 mm² < 12)"),
            -2.0: fit(-2, 100.0), 0.0: fit(0, 500.0), 2.0: fit(2, 502.0), 4.0: fit(4, 600.0), 6.0: fit(6, 480.0), 8.0: nofit("something new")}
    ov1 = {0.0: 0.5, 2.0: 0.1, 4.0: 5.0, 6.0: 2.0}
    calls = []
    r1, fakes = run_stub(tab1, ov1, calls)
    ok("B1 per-offset codes [blocked, canal larger, tip thin, below neck min, ok, ok, overhang, ok (ov == tol), other]",
       r1["code_by_e"].tolist() == [1, 2, 3, 4, 0, 0, 5, 0, 9], str(r1["code_by_e"].tolist()))
    ok("B2 A0_by_e = template_base A0 where it fits, NaN elsewhere", same(r1["A0_by_e"], [np.nan] * 3 + [100, 500, 502, 600, 480, np.nan]))
    ok("B3 overhang only where collar_rule computed it", same(r1["overhang_by_e"], [np.nan] * 4 + [0.5, 0.1, 5.0, 2.0, np.nan]))
    ok("B4 every offset evaluated once in order with margin_check dense; neck checked only where A0 >= neck minimum",
       [c[1] for c in calls if c[0] == "tb"] == T.OFFSETS.tolist() and all(c[2] == "dense" for c in calls if c[0] == "tb")
       and [c[1] for c in calls if c[0] == "ov"] == [0.0, 2.0, 4.0, 6.0])
    ok("B5 e* 0 / A0* 500 (502 at e +2 is within 0.5 % -> smaller |e|), n_usable 3, e_margin (500 - 502) / 500 = -0.004",
       r1["e_star"] == 0.0 and r1["A0_star"] == 500.0 and r1["n_usable"] == 3 and abs(r1["e_margin"] + 0.004) < 1e-12, str(r1["e_margin"]))
    ok("B6 feasible, reason ok, bone = resected(ref 16) + reamed volume at e*, s_bind at e*", r1["feasible"] and r1["reason"] == "ok"
       and r1["bone_mm3"] == 100.0 + 5000.0 and r1["volume_star"] == 5000.0 and r1["s_bind_star"] == 5.0)
    ok("B7 collar_rule names restored after the call (the stubs are back)", CR.template_base is fakes[0] and CR.neck_overhang is fakes[1])
    ok("B7b same table, overhang-aware: e +4 (600, overhang 5.0 = tol + 3, on the boundary -> near) gives ov_slack 1.5, ov_gap_up 3.0, "
       "A0_up_rel 0.2, e_margin_eff min(-0.004, -0.2) = -0.2",
       close(r1["ov_slack_star"], 1.5) and close(r1["ov_gap_up"], 3.0) and close(r1["A0_up_rel"], 0.2) and close(r1["e_margin_eff"], -0.2)
       and derived_ok(r1), str({k: r1[k] for k in DERIVED}))
    r2, _ = run_stub({**table(), 4.0: fit(4, 300.0), 2.0: fit(2, 310.0)}, {4.0: 0.0, 2.0: 7.5})
    ok("B8 single usable offset: e* +4, e_margin 1.0, n_usable 1 (e +2 has a larger A0 but overhangs)",
       r2["e_star"] == 4.0 and r2["e_margin"] == 1.0 and r2["n_usable"] == 1 and r2["code_by_e"][5] == 5, str(r2["code_by_e"].tolist()))
    ok("B8b overhang far above tol (7.5 = tol + 5.5): ov_slack 2.0, ov_gap_up 5.5, A0_up_rel 10/300, e_margin_eff stays 1.0 (not near)",
       close(r2["ov_slack_star"], 2.0) and close(r2["ov_gap_up"], 5.5) and close(r2["A0_up_rel"], 10.0 / 300.0)
       and r2["e_margin_eff"] == 1.0 and derived_ok(r2), str({k: r2[k] for k in DERIVED}))
    r3, _ = run_stub({**table(), 0.0: fit(0, 120.0)}, {})
    ok("B9 nothing usable: infeasible, reason no_offset, e* / A0* / e_margin / bone and all overhang-aware columns NaN, code 4 at e 0",
       not r3["feasible"] and r3["reason"] == "no_offset"
       and all(math.isnan(r3[k]) for k in ("e_star", "A0_star", "bone_mm3", *DERIVED)) and r3["code_by_e"][4] == 4 and r3["n_usable"] == 0)
    r4, _ = run_stub({**table(), -2.0: fit(-2, 400.0), 0.0: fit(0, 300.0), 2.0: fit(2, 390.0)}, {-2.0: 0.0, 0.0: 0.0, 2.0: 1.0})
    ok("B10 clear winner e -2: e_margin (400 - 390) / 400 = 0.025, no code 5 -> e_margin_eff = e_margin, ov_gap_up / A0_up_rel NaN",
       r4["e_star"] == -2.0 and abs(r4["e_margin"] - 0.025) < 1e-12 and r4["e_margin_eff"] == r4["e_margin"]
       and math.isnan(r4["ov_gap_up"]) and math.isnan(r4["A0_up_rel"]) and close(r4["ov_slack_star"], 2.0))
    # the review's corner case: e* close to its own overhang limit, larger offsets blocked by only 0.6 / 2.7 mm2, one far (7 mm2)
    tab5 = {**table(), -6.0: fit(-6, 600.0), -4.0: fit(-4, 450.0), -2.0: fit(-2, 520.0), 0.0: fit(0, 400.0), 2.0: fit(2, 380.0),
            4.0: fit(4, 390.0)}
    r5, _ = run_stub(tab5, {-6.0: 9.0, -4.0: 4.7, -2.0: 2.6, 0.0: 1.9, 2.0: 0.5, 4.0: 4.0})
    ok("B13 overhang jump: e* 0 (400, overhang 1.9), e_margin 0.05 vs e +2; ov_slack 0.1; code-5 above A0*: -6 (600, +7.0), -4 (450, +2.7), "
       "-2 (520, +0.6) -> ov_gap_up 0.6, A0_up_rel 0.5; near (<= tol + 3): -4, -2, +4 -> e_margin_eff (400 - 520) / 400 = -0.3",
       r5["e_star"] == 0.0 and close(r5["e_margin"], 0.05) and close(r5["ov_slack_star"], 0.1, 1e-12) and close(r5["ov_gap_up"], 0.6, 1e-12)
       and close(r5["A0_up_rel"], 0.5) and close(r5["e_margin_eff"], -0.3) and r5["code_by_e"].tolist() == [1, 5, 5, 5, 0, 0, 5, 1, 1]
       and derived_ok(r5), str({k: r5[k] for k in DERIVED}))
    r6, _ = run_stub({**table(), 0.0: fit(0, 400.0), 4.0: fit(4, 390.0)}, {0.0: 0.0, 4.0: 4.0})
    ok("B14 near-blocked offset with a smaller A0 (390, +2.0): e_margin 1.0 (single usable) but e_margin_eff (400 - 390) / 400 = 0.025; "
       "nothing larger -> ov_gap_up / A0_up_rel NaN",
       r6["e_margin"] == 1.0 and close(r6["e_margin_eff"], 0.025) and math.isnan(r6["ov_gap_up"]) and math.isnan(r6["A0_up_rel"])
       and derived_ok(r6), str({k: r6[k] for k in DERIVED}))
    r7, _ = run_stub({**table(), 0.0: fit(0, 400.0), 2.0: fit(2, 500.0)}, {0.0: 0.0, 2.0: 5.0 + 1e-9})
    ok("B15 just past the near boundary (overhang tol + 3 + 1e-9): not near -> e_margin_eff 1.0, but ov_gap_up / A0_up_rel still set",
       r7["e_margin_eff"] == 1.0 and close(r7["ov_gap_up"], 3.0 + 1e-9, 1e-12) and close(r7["A0_up_rel"], 0.25) and derived_ok(r7),
       str({k: r7[k] for k in DERIVED}))
    for tag, fake, want in (("other selection rule", drift_pick_smallest, "selection drift"),
                            ("all offsets in one template_base call", drift_all_at_once, "9 offsets at once"),
                            ("an offset not evaluated", drift_skip_one, "offset +8 was not evaluated"),
                            ("'no offset works' while usable offsets exist", drift_say_none, "found no usable offset")):
        tb, ov = install_table(tab1, ov1)
        CR.template_neck_in_shoulder = fake
        try:
            msg = raises(T.TplRecordError, T.record_with, FakeStem(), FakeFem(), RS)
        finally:
            CR.template_neck_in_shoulder = ORIG["tnis"]
        ok(f"B11 drift detection: {tag} -> TplRecordError ('{want}'); names restored after the error",
           good(msg) and want in str(msg) and CR.template_base is tb and CR.neck_overhang is ov, str(msg)[:110])
    CR.template_base, CR.neck_overhang = ORIG["tb"], ORIG["ov"]
    ok("B12 fixture reset: collar_rule names are the originals", names_restored())


def sec_c(tmp, expect_geom_key):
    with T.no_cache_writes():
        m1 = raises(T.CacheWriteRefused, F6.np.savez_compressed, tmp / "x.npz", a=np.zeros(1))
        m2 = raises(T.CacheWriteRefused, FR.np.save, tmp / "y.npy", np.zeros(1))
        z = F6.np.zeros(3)
    ok("C1 inside no_cache_writes: femur_3406.np.savez_compressed and femur_real.np.save refused, reads work, nothing written",
       good(m1) and good(m2) and z.shape == (3,) and not any(tmp.iterdir()))
    ok("C2 after the block both femur modules see numpy again", F6.np is np and FR.np is np)
    key_name = T.femur_cache_file("isthmus").name
    empty = tmp / "cache_empty"
    empty.mkdir()
    calls_ff = []
    saved_fm = dict(T._FM)
    try:
        J.femur_for = lambda spec: calls_ff.append(spec)
        F6.CACHE = empty
        T._FM.clear()
        msg = raises(FileNotFoundError, T.base_femur, "sawbone3406", "isthmus")
        ok("C3 missing cache file -> FileNotFoundError before jobs.femur_for is called; cache dir still empty",
           good(msg) and not calls_ff and not any(empty.iterdir()), str(msg)[:90])
        fake = tmp / "cache_fake"
        fake.mkdir()
        (fake / key_name).write_bytes(b"")
        F6.CACHE = fake
        J.femur_for = femur_for_writes_np
        msg = raises(T.CacheWriteRefused, T.base_femur, "sawbone3406", "isthmus")
        ok("C4 a femur build that calls np.savez_compressed is refused; no file appears", good(msg)
           and sorted(p.name for p in fake.iterdir()) == [key_name] and F6.np is np, str(msg)[:90])
        J.femur_for = femur_for_writes_file
        msg = raises(T.CacheWriteRefused, T.base_femur, "sawbone3406", "isthmus")
        ok("C5 a plain-file write into the cache dir is caught by the before/after listing (and nothing is cached)",
           good(msg) and not T._FM, str(msg)[:90])
    finally:
        J.femur_for, F6.CACHE = ORIG["femur_for"], ORIG["cache"]
        T._FM.clear()
        T._FM.update(saved_fm)
    ok("C6 fixture reset: jobs.femur_for and the cache path are the originals", J.femur_for is ORIG["femur_for"] and F6.CACHE == ORIG["cache"])
    cfg = F6.load_cfg("isthmus")
    k0 = T.femur_geom_key(cfg)
    moved = copy.deepcopy(cfg)
    moved["femur"]["step_cortical"], moved["femur"]["step_cancellous"] = "/elsewhere/a/3406R_cortical.STEP", "D:\\other\\b.STEP"

    def changed(**kv):
        c = copy.deepcopy(cfg)
        c["femur"].update(kv)
        return T.femur_geom_key(c)
    ok("C7 femur_geom_key is host-independent: other STEP paths, another neck axis -> the same key; the cache name hashes the paths",
       len(k0) == 16 and T.femur_geom_key(moved) == k0 and T.femur_geom_key(F6.load_cfg("detector")) == k0
       and F6._cache_key(moved) != F6._cache_key(cfg), f"femur_geom_key {k0}")
    ok("C8 femur_geom_key changes with femur_3406.py bytes, a declared STEP sha256 or a geometry cfg value (voxel_mm)",
       T.femur_geom_key(cfg, src=pathlib.Path(F6.__file__).read_bytes() + b"#") != k0 and changed(sha256_cortical="0" * 64) != k0
       and changed(voxel_mm=0.25) != k0)
    ok("C9 a path-like cfg value left after dropping step_* is refused (the key would depend on the host)",
       good(raises(ValueError, changed, mesh_dir="/home/x/mesh")))
    if expect_geom_key:
        ok("C10 femur_geom_key equals --expect-geom-key (the value from the other host)", k0 == expect_geom_key, f"{k0} vs {expect_geom_key}")
    return k0


def sec_d():
    before = T._cache_listing()
    ra = T.record_spec(A62)
    pv = ra["prep_view"]
    ok("D1 a62 (sb13_a62_1e4338ee): A0 499.45 mm2, e 0, s_bind 13.2 mm (corner check method)",
       round(pv["A0"], 2) == 499.45 and pv["e"] == 0.0 and round(pv["s_bind"], 1) == 13.2 and ra["feasible"],
       f"A0 {pv['A0']:.5f} e {pv['e']} s_bind {pv['s_bind']:.4f}")
    sd = {k: T._sdiff(pv[k], A62_PREP[k]) for k in ("alpha", "A0", "s_bind", "contact", "volume", "bone_total_mm3")}
    ok("D2 a62 reproduces its prep.json templating and bone_loss.total_mm3 (scaled diff <= 1e-9)", max(sd.values()) <= 1e-9,
       f"max {max(sd.values()):.2e}")
    ok("D3 femur loaded without touching the cache (listing unchanged); collar_rule / femur module names restored",
       T._cache_listing() == before and names_restored() and F6.np is np and FR.np is np)
    k0 = int(np.flatnonzero(T.OFFSETS == 0.0)[0])
    oth = ra["A0_by_e"][ra["usable_by_e"] & (np.arange(9) != k0)]
    ok("D4 a62: e 0 usable, e_margin = (A0* - best other usable A0) / A0* from the arrays",
       ra["usable_by_e"][k0] and abs(ra["e_margin"] - (ra["A0_star"] - oth.max()) / ra["A0_star"]) < 1e-15,
       f"codes {ra['code_by_e'].tolist()} e_margin {ra['e_margin']:.4f}")
    ok("D4b a62: ov_slack_star / ov_gap_up / A0_up_rel / e_margin_eff = the independent re-derivation from its arrays", derived_ok(ra),
       "overhang " + str(np.round(ra["overhang_by_e"], 3).tolist()) + " A0 " + str(np.round(ra["A0_by_e"], 1).tolist()) + " "
       + str({k: round(ra[k], 4) for k in DERIVED}))
    ru = T.record_u(N.Phase(13).to_unit(A62["design"], A62["h_cut"]))
    ok("D5 record_u(unit point of a62) gives the same e* / A0* / s_bind", ru["e_star"] == 0.0 and T._sdiff(ru["A0_star"], pv["A0"]) <= 1e-9
       and T._sdiff(ru["s_bind_star"], pv["s_bind"]) <= 1e-9, f"{ru['A0_star']:.6f}")
    fm16 = T.base_femur("sawbone3406", "isthmus").with_cut(16.0)
    for fe in (-2.0, -4.0):
        rf = T.record_spec({**A62, "entry_offset": fe})["prep_view"]
        with J.a_bounds_cap(2000.0):                         # jobs.prep with entry_offset: the same call restricted to one offset
            dr = ORIG["tnis"](G.Stem3D(**A62["design"]), fm16, offsets=np.array([fe]), min_A0=A62["min_A0"], margin_check="dense")
        agree = (rf["fit"] == bool(dr.get("fit"))) and (not rf["fit"] or (rf["A0"] == dr["A0"] and rf["s_bind"] == dr["s_bind"]
                                                                          and rf["volume"] == dr["volume"] and rf["e"] == dr["e"]))
        ok(f"D6 forced entry_offset {fe:+g}: prep_view = a direct prep-style single-offset call", agree, f"fit {rf['fit']} A0 {rf['A0']}")
    return ra


def _perturbed_copy(src, dst, edits=(), drop=(), not_done_from=3):
    """Copy a batch npz with done[not_done_from:] = False and meta edits (path tuple -> value) / drops (path tuple)."""
    with np.load(src, allow_pickle=False) as zz:
        part = {k: zz[k].copy() for k in zz.files}
    part["done"][not_done_from:] = False
    meta = json.loads(str(part["meta_json"]))
    for path, v in edits:
        d = meta
        for p in path[:-1]:
            d = d[p]
        d[path[-1]] = v
    for path in drop:
        d = meta
        for p in path[:-1]:
            d = d[p]
        d.pop(path[-1])
    part["meta_json"] = np.array(json.dumps(meta))
    with open(dst, "wb") as fh:
        np.savez_compressed(fh, **part)


def _differing(msg) -> list:
    s = str(msg)
    if "differing: " not in s or ". Nothing was computed" not in s:
        return []
    return [x.split(":")[0] for x in s.split("differing: ", 1)[1].split(". Nothing was computed", 1)[0].split("; ")]


def sec_e(tmp, ra, max_workers, abort_timeout):
    from scipy.stats import qmc
    U = np.vstack([N.Phase(13).to_unit(A62["design"], A62["h_cut"]), qmc.Sobol(13, scramble=True, seed=7).random(8)[:5]])
    o1 = tmp / "b1.npz"
    T.batch(U, o1, workers=1, checkpoint=2, quiet=True)
    z1 = T.load(o1)
    with np.load(o1, allow_pickle=False) as zz:
        keys = set(zz.files)
    need = {"u13", "x13", "var_names", "offsets", "feasible", "reason", "error", "A0_by_e", "usable_by_e", "code_by_e", "overhang_by_e",
            "n_usable", "e_star", "A0_star", "e_margin", "ov_slack_star", "ov_gap_up", "A0_up_rel", "e_margin_eff", "bone_mm3",
            "s_bind_star", "contact_star", "volume_star", "resected_mm3", "alpha_star", "t_s", "done", "meta_json"}
    ok("E1 npz has the D3 fields (incl. the overhang-aware columns), loads with allow_pickle=False, shapes N x 13 / N x 9, dtypes",
       need <= keys and z1["u13"].shape == (6, 13) and z1["A0_by_e"].shape == (6, 9) and z1["usable_by_e"].dtype == bool
       and z1["feasible"].dtype == bool and z1["code_by_e"].dtype == np.int8 and z1["e_margin_eff"].dtype == np.float64,
       str(sorted(need - keys)))
    m, pr = z1["meta"], z1["meta"]["provenance"]
    ok("E2 meta: format 2, complete, 6 done, 0 errors; rule / offsets / ov_near_mm2 recorded",
       m["format"] == 2 and m["complete"] and m["n_done"] == 6 and m["errors"] == 0 and m["rule"]["margin_check"] == "dense"
       and m["offsets"] == T.OFFSETS.tolist() and m["ov_near_mm2"] == 3.0)
    stepf = pr["step_file_sha256"]
    ok("E2b provenance: code_hash, 6 aux md5s, femur_geom_key = femur_geom_key(cfg), STEP file sha256 = declared (or None if absent), "
       "femur cache name + its sha256, threads_env",
       len(pr["code_hash"]) == 10 and sorted(pr["aux_md5"]) == sorted(["collar_rule.py", "femur_3406.py", "jobs.py", "stage_neckopt.py",
                                                                      "stage_v2a.py", "tpl_record.py"])
       and pr["femur_geom_key"] == T.femur_geom_key(F6.load_cfg("isthmus"))
       and all(stepf[k] in (None, pr["step_sha256"][k]) for k in ("cortical", "cancellous"))
       and pr["femur_cache"] == T.femur_cache_file("isthmus").name and pr["femur_cache_sha256"] == sha256(T.femur_cache_file("isthmus"))
       and set(pr["threads_env"]) == {"OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"},
       f"code_hash {pr['code_hash']} femur_geom_key {pr['femur_geom_key']} cache {pr['femur_cache']} step files "
       f"{ {k: (v or 'absent')[:12] for k, v in stepf.items()} } threads {pr['threads_env']} blas {pr.get('blas_threads')}")
    ok("E3 row 0 (a62) = record_spec: e*, A0*, bone, A0_by_e, codes, overhang-aware columns",
       z1["e_star"][0] == ra["e_star"] and z1["A0_star"][0] == ra["A0_star"] and z1["bone_mm3"][0] == ra["bone_mm3"]
       and same(z1["A0_by_e"][0], ra["A0_by_e"]) and same(z1["code_by_e"][0], ra["code_by_e"])
       and all(same(z1[k][0], ra[k]) for k in DERIVED))
    ok("E4 x13 = Phase(13).design_of of u13; var_names = Phase(13).vars", same(z1["x13"], np.array([T.physical(u) for u in U]))
       and z1["var_names"].tolist() == N.Phase(13).vars)
    print(f"   E: feasible {z1['feasible'].tolist()}  e* {z1['e_star'].tolist()}  t_s {np.round(z1['t_s'], 2).tolist()}", flush=True)
    fields = sorted(k for k in need if k not in ("t_s", "meta_json"))
    if max_workers >= 2:
        o2 = tmp / "b2.npz"
        T.batch(U, o2, workers=2, chunksize=1, quiet=True)
        z2 = T.load(o2)
        diff = [k for k in fields if not same(z1[k], z2[k])]
        ok("E5 spawn workers (2, ProcessPoolExecutor) give the same arrays as the serial run (all fields but timing)",
           not diff and z2["meta"]["workers"] == 2, str(diff))
    else:
        skip("E5 serial == spawn workers", f"--max-workers {max_workers}")
    o3 = tmp / "b3.npz"
    _perturbed_copy(o1, o3)
    s3 = T.batch(U, o3, workers=1, resume=True, quiet=True)
    z3 = T.load(o3)
    diff = [k for k in fields if not same(z1[k], z3[k])]
    ok("E6 resume recomputes only the 3 not-done rows and gives the same arrays", s3["computed_this_run"] == 3 and not diff
       and z3["meta"]["complete"], f"{s3['computed_this_run']} {diff}")
    msg = raises(ValueError, T.batch, U[::-1].copy(), o3, workers=1, resume=True, quiet=True)
    ok("E7 resume with another point list is refused (u13 named)", good(msg) and _differing(msg) == ["u13"], str(_differing(msg)))
    # ---- E15 resume refused for every changed compared provenance key; file unchanged; only that key is named
    P = ("provenance",)
    cases = [((P + ("code_hash",), "0000000000"),), ((P + ("aux_md5", "collar_rule.py"), "deadbeef" * 4),),
             ((P + ("aux_md5", "tpl_record.py"), "0" * 32),), ((P + ("aux_md5", "stage_v2a.py"), "1" * 32),),
             ((P + ("aux_md5", "femur_3406.py"), "2" * 32),), ((P + ("femur_geom_key",), "ffffffffffffffff"),),
             ((P + ("femur_cache",), "femur_3406_0000000000.npz"),), ((P + ("femur_cache_sha256",), "3" * 64),),
             ((P + ("step_sha256", "cortical"), "4" * 64),), ((P + ("step_file_sha256", "cancellous"), "5" * 64),),
             ((("format",), 1),)]
    want = ["provenance.code_hash", "aux_md5.collar_rule.py", "aux_md5.tpl_record.py", "aux_md5.stage_v2a.py", "aux_md5.femur_3406.py",
            "femur_geom_key", "femur_cache", "femur_cache_sha256", "step_sha256.cortical", "step_file_sha256.cancellous", "format"]
    bad = []
    for k, (edits, w) in enumerate(zip(cases, want)):
        ok_path = tmp / f"prov{k}.npz"
        _perturbed_copy(o1, ok_path, edits=edits)
        h0 = sha256(ok_path)
        msg = raises(ValueError, T.batch, U, ok_path, workers=1, resume=True, quiet=True)
        got = _differing(msg)
        w = w.replace("provenance.", "")
        if not (good(msg) and got == [w] and sha256(ok_path) == h0):
            bad.append((w, got, str(msg)[:160]))
    ok(f"E15 resume refused for each of {len(cases)} changed keys (code_hash, aux md5s, femur_geom_key, femur cache + sha256, STEP sha256, "
       "format); exactly that key named; file unchanged", not bad, str(bad)[:400])
    p_old = tmp / "prov_old.npz"
    _perturbed_copy(o1, p_old, edits=(((P + ("code_hash",)), "0000000000"), ((P + ("aux_md5", "collar_rule.py")), "deadbeef" * 4)),
                    drop=((P + ("femur_geom_key",)),))
    msg = raises(ValueError, T.batch, U, p_old, workers=1, resume=True, quiet=True)
    ok("E15b the review's case (other code_hash + collar_rule md5, file without femur_geom_key): refused, all three named",
       good(msg) and _differing(msg) == ["code_hash", "aux_md5.collar_rule.py", "femur_geom_key"], str(_differing(msg)))
    p_host = tmp / "prov_host.npz"
    _perturbed_copy(o1, p_host, edits=(((P + ("host",)), "elsewhere"), ((P + ("platform",)), "x"), ((P + ("code_dir",)), "/x/v2"),
                                       ((P + ("threads_env",)), {}), ((P + ("femur_cache_mtime_utc",)), "2000-01-01T00:00:00Z")))
    s_h = T.batch(U, p_host, workers=1, resume=True, quiet=True)
    z_h = T.load(p_host)
    ok("E16 resume accepted when only host info differs (host, platform, code_dir, threads, cache mtime); same arrays; meta = this host",
       s_h["computed_this_run"] == 3 and not [k for k in fields if not same(z1[k], z_h[k])]
       and z_h["meta"]["provenance"]["host"] == pr["host"], str(s_h["computed_this_run"]))
    names = N.Phase(13).vars
    rows = "\n".join(",".join(repr(float(x)) for x in r) for r in U) + "\n"
    p1, p2, p3, p4 = tmp / "h.csv", tmp / "uh.csv", tmp / "n.csv", tmp / "p.npy"
    p1.write_text(",".join(names) + "\n" + rows, encoding="utf-8")
    p2.write_text(",".join("u_" + v for v in names) + "\n" + rows, encoding="utf-8")
    p3.write_text(rows, encoding="utf-8")
    np.save(p4, U)
    ok("E8 readers: csv with var / u_var header, csv without header, npy -> the same points (+ sha256)",
       all(same(T.read_points(p)[0], U) for p in (p1, p2, p3, p4)) and len(T.read_points(p4)[1]["sha256"]) == 64)
    p5 = tmp / "bad.csv"
    p5.write_text(",".join(reversed(names)) + "\n" + ",".join("0.5" for _ in names) + "\n", encoding="utf-8")
    out_of_box, nanu = U.copy(), U.copy()
    out_of_box[0, 0] = 1.2
    nanu[1, 2] = np.nan
    ok("E9 bad input refused: wrong header, u outside [0, 1] (not clipped), NaN, wrong width", all(good(raises(ValueError, f, a)) for f, a in (
        (T.read_points, p5), (T.check_points, out_of_box), (T.check_points, nanu), (T.check_points, U[:, :12]))))
    target = T.CODE / "tpl_record_refused.npz"
    msg = raises(ValueError, T.batch, U[:1], target, workers=1, quiet=True)
    ok("E10 output inside the pipeline code dir is refused (nothing written there)", good(msg) and not target.exists(), str(msg)[:80])

    def flaky(u, phase=13):
        if np.allclose(u, U[1]):
            raise ValueError("boom")
        return ORIG["record_u"](u, phase)

    def drifting(u, phase=13):
        if np.allclose(u, U[2]):
            raise T.TplRecordError("drift")
        return ORIG["record_u"](u, phase)
    try:
        T.record_u = flaky
        o4 = tmp / "b4.npz"
        s4 = T.batch(U[:3], o4, workers=1, quiet=True)
        z4 = T.load(o4)
        ok("E11 a point error becomes an error row (feasible False, reason 'error: ValueError: boom'), others computed, counted",
           s4["errors"] == 1 and z4["error"].tolist() == [False, True, False] and str(z4["reason"][1]) == "error: ValueError: boom"
           and not z4["feasible"][1] and z4["meta"]["errors"] == 1 and z4["done"].all())
        np.save(tmp / "u3.npy", U[:3])
        rc = T.main(["batch", "--in", str(tmp / "u3.npy"), "--out", str(tmp / "b5.npz"), "--workers", "1"])
        ok("E12 CLI batch exits 3 when a point errored", rc == 3, str(rc))
        T.record_u = drifting
        o6 = tmp / "b6.npz"
        msg = raises(T.TplRecordError, T.batch, U[:4], o6, workers=1, quiet=True)
        z6 = T.load(o6) if o6.exists() else None
        ok("E13 TplRecordError aborts the batch; the done rows are saved with aborted = True",
           msg == "drift" and z6 is not None and z6["meta"].get("aborted") and z6["done"].tolist() == [True, True, False, False]
           and not z6["meta"]["complete"], str(msg))
    finally:
        T.record_u = ORIG["record_u"]
    ok("E14 fixture reset: record_u restored; collar_rule names are the originals", T.record_u is ORIG["record_u"] and names_restored())
    # ---- E17 the parent loads the femur before any worker exists: a missing cache raises at once, no process is started
    empty = tmp / "cache_missing"
    empty.mkdir()
    saved_fm, o7 = dict(T._FM), tmp / "b7.npz"
    try:
        F6.CACHE = empty
        T._FM.clear()
        t0 = time.perf_counter()
        msg = raises(FileNotFoundError, T.batch, U[:2], o7, workers=2, quiet=True)
        dt = time.perf_counter() - t0
        kids = mp.active_children()
    finally:
        F6.CACHE = ORIG["cache"]
        T._FM.clear()
        T._FM.update(saved_fm)
    ok("E17 workers=2 with the femur cache missing: FileNotFoundError from the parent pre-check within seconds; no output file, "
       "no worker process started", good(msg) and "femur cache" in str(msg) and not o7.exists() and not kids and dt < 60,
       f"{dt:.1f} s, children {len(kids)}: {str(msg)[:80]}")
    if max_workers < 2:
        skip("E18-E21 workers=2 abort paths", f"--max-workers {max_workers}")
        return
    # ---- E18 worker initializer failure (simulated only inside the workers) -> BrokenProcessPool, not a hang
    o8 = tmp / "b8.npz"
    with worker_fault("init"):
        how, e = run_bounded(lambda: T.batch(U[:4], o8, workers=2, chunksize=1, quiet=True), abort_timeout)
    z8 = T.load(o8) if o8.exists() else None
    ok(f"E18 workers=2, every worker's femur load fails: BrokenProcessPool within {abort_timeout} s (no hang); file saved with aborted "
       "= True and 0 rows done; the message says what to do",
       how == "raised" and isinstance(e, BrokenProcessPool) and "aborted" in str(e) and "--resume" in str(e) and z8 is not None
       and z8["meta"].get("aborted") and z8["meta"]["abort_reason"].startswith("BrokenProcessPool") and not z8["done"].any(),
       f"{how}: {type(e).__name__ if e else None}: {str(e)[:140]}")
    # ---- E19 a worker process dies while computing U[2] (as if killed for memory) -> BrokenProcessPool, done rows kept
    o9 = tmp / "b9.npz"
    with worker_fault(f"kill:{float(U[2][0])!r}"):
        how, e = run_bounded(lambda: T.batch(U, o9, workers=2, chunksize=1, quiet=True), abort_timeout)
    z9 = T.load(o9) if o9.exists() else None
    dn = z9["done"] if z9 is not None else np.zeros(len(U), bool)
    rows_ok = z9 is not None and all(same(z1[k][dn], z9[k][dn]) for k in fields if k not in ("u13", "x13", "var_names", "offsets", "done"))
    ok("E19 workers=2, a worker dies on one point: BrokenProcessPool (no hang); that row not done; the saved done rows equal the "
       "serial run", how == "raised" and isinstance(e, BrokenProcessPool) and z9 is not None and z9["meta"].get("aborted")
       and not dn[2] and rows_ok, f"{how}: {type(e).__name__ if e else None}; done {dn.tolist()}")
    s9 = T.batch(U, o9, workers=1, resume=True, quiet=True) if z9 is not None else None
    z9b = T.load(o9) if s9 else None
    ok("E19b --resume after that abort computes only the missing rows and gives the serial arrays",
       s9 is not None and s9["computed_this_run"] == int((~dn).sum()) and not [k for k in fields if not same(z1[k], z9b[k])],
       str(s9 and s9["computed_this_run"]))
    # ---- E20 TplRecordError inside a worker -> the same exception type in the parent, done rows kept
    o10 = tmp / "b10.npz"
    with worker_fault(f"drift:{float(U[2][0])!r}"):
        how, e = run_bounded(lambda: T.batch(U, o10, workers=2, chunksize=1, quiet=True), abort_timeout)
    z10 = T.load(o10) if o10.exists() else None
    dn = z10["done"] if z10 is not None else np.zeros(len(U), bool)
    rows_ok = z10 is not None and all(same(z1[k][dn], z10[k][dn]) for k in fields if k not in ("u13", "x13", "var_names", "offsets", "done"))
    ok("E20 workers=2, TplRecordError in a worker: TplRecordError in the parent (no hang); aborted file; that row not done; the other "
       "done rows (incl. chunks that finished during shutdown) equal the serial run",
       how == "raised" and isinstance(e, T.TplRecordError) and "inside a worker" in str(e) and z10 is not None
       and z10["meta"].get("aborted") and z10["meta"]["abort_reason"].startswith("TplRecordError") and not dn[2] and rows_ok,
       f"{how}: {type(e).__name__ if e else None}; done {dn.tolist()}")
    time.sleep(0.5)
    kids = mp.active_children()
    ok("E21 no worker process left after the abort tests; FAULT env cleared", not kids and FAULT_ENV not in os.environ, str(kids))


def sec_f(queue, sample, seed, expect_jobs, tol):
    Q = pathlib.Path(queue).expanduser()
    cands, prep_failed, unsupported = [], [], []
    for d in sorted(Q.iterdir()):
        sp = d / "spec.json"
        if not sp.exists():
            continue
        s = T.read_json(sp)
        if s.get("femur_id") != "sawbone3406" or s.get("kind") not in ("design", "variant"):
            continue
        try:
            T.spec_rule(s)
        except NotImplementedError:
            unsupported.append(d.name)
            continue
        if (d / "prep.json").exists():
            if T.read_json(d / "prep.json").get("templating"):
                cands.append(d)
        elif (d / "FAILED.json").exists() and T.read_json(d / "FAILED.json").get("stage") == "prep":
            prep_failed.append(d)
    pick = cands if not sample else sorted(random.Random(seed).sample(cands, min(sample, len(cands))))
    by_stage = collections.Counter(d.name.split("_")[0] for d in pick)
    print(f"F: {len(cands)} 3406 jobs with prep templating; comparing {len(pick)}"
          + (f" (sample, seed {seed})" if sample else " (all)") + f" by stage {dict(sorted(by_stage.items()))}; "
          f"{len(prep_failed)} prep failures; {len(unsupported)} unsupported specs", flush=True)
    t0 = time.perf_counter()
    rows = [T.compare_job(d, tol=tol) for d in pick]
    bad = [r for r in rows if not r["match"]]
    for r in bad:
        print(f"   MISMATCH {r['job']}: e* {r['e_star']} prep e {r['prep'] and r['prep']['e']} sdiff "
              f"{ {k: f'{v:.2e}' for k, v in (r['sdiff'] or {}).items()} }", flush=True)
    mx = {k: max(r["sdiff"][k] for r in rows) for k in rows[0]["sdiff"]} if rows else {}
    e_cnt = collections.Counter(r["e_star"] for r in rows)
    ok(f"F1 {len(rows)} existing 3406 jobs: e* / A0* / alpha / s_bind / contact / volume / bone loss = prep.json (scaled diff <= {tol:g})",
       rows and not bad and (sample or len(rows) == len(cands)),
       f"max scaled diff per field { {k: f'{v:.1e}' for k, v in mx.items()} }; e* counts {dict(sorted(e_cnt.items()))}; "
       f"{len(rows) / max(time.perf_counter() - t0, 1e-9):.1f} jobs/s; mismatches {[r['job'] for r in bad]}")
    if expect_jobs is not None:
        ok(f"F1b the queue holds --expect-jobs {expect_jobs} templated 3406 jobs", len(cands) == expect_jobs, str(len(cands)))
    inc = [r["job"] for r in rows if not derived_ok(r)]
    jumps = sorted((r for r in rows if r["A0_up_rel"] is not None), key=lambda r: r["e_margin_eff"])
    lower = [r for r in rows if r["e_margin_eff"] is not None and r["e_margin_eff"] < r["e_margin"]]
    forced = [r["job"] for r in rows if r.get("entry_offset") is not None]
    ok(f"F3 e_margin and the overhang-aware columns of all {len(rows)} jobs = the independent re-derivation from their arrays", not inc,
       f"inconsistent {inc[:5]}; {len(jumps)} jobs with a larger overhang-blocked offset; {len(lower)} with e_margin_eff < e_margin; "
       f"forced entry_offset jobs {len(forced)}")
    for r in jumps[:8]:
        print(f"   jump {r['job']:<44} e* {r['e_star']:+.0f} A0* {r['A0_star']:7.2f} e_margin {r['e_margin']:+.3f} "
              f"e_margin_eff {r['e_margin_eff']:+.3f} ov_slack {r['ov_slack_star']:.3f} ov_gap_up {r['ov_gap_up']:.3f} "
              f"A0_up_rel {r['A0_up_rel']:+.3f}", flush=True)
    if prep_failed:
        pf = [T.compare_job(d) for d in prep_failed]
        ok(f"F2 {len(pf)} prep-stage failures after templating (meshing): the record says feasible, as expected",
           all(r["expect_feasible"] is not None and r["feasible"] == r["expect_feasible"] for r in pf),
           str([(r["job"], r["feasible"], r["expect_feasible"]) for r in pf]))
    ok("F4 collar_rule names restored after the job comparisons", names_restored())


def sec_g(pool, n):
    """The phase-11 candidate pool file (stage_neckopt.gated_pool: U[feasible], loss) vs the record on its first n Sobol points."""
    from scipy.stats import qmc
    pool = pathlib.Path(pool).expanduser()
    info = json.loads(pool.with_suffix(".json").read_text(encoding="utf-8"))
    with np.load(pool, allow_pickle=False) as z:
        Up, loss = z["U"], z["loss"]
    src, seed, ntot = int(info["phase"]), int(info["seed"]), int(info["n"])
    ok("G0 pool file is the phase-13 pool (phase 13 reuses phase 11's: same space, femur, margin check, ref cut, cap)",
       info["space"] == {k: list(v) for k, v in N.PHASES[13]["vars"].items()} and info["femur_id"] == "sawbone3406"
       and info["margin_check"] == "dense" and info["ref_cut_mm"] == 16.0 and info["a_bounds_max"] == 2000.0 and N.PHASES[13]["pool_phase"] == src)
    U = qmc.Sobol(13, scramble=True, seed=50_000 + 100 * src + seed).random(ntot)[:n]     # = gated_pool's draw
    recs = [T.record_u(u) for u in U]
    feas = np.array([r["feasible"] for r in recs])
    k = int(feas.sum())
    ok(f"G1 first {n} pool Sobol points: the feasible ones are exactly the first {k} rows of the pool file, in order",
       k > 0 and same(U[feas], Up[:k]), f"{k} feasible")
    sd = [T._sdiff(r["bone_mm3"], l) for r, l in zip([r for r in recs if r["feasible"]], loss[:k])]
    ok("G2 bone_mm3 = the pool's loss (resected + reamed) on those rows (scaled diff <= 1e-9)", sd and max(sd) <= 1e-9,
       f"max {max(sd) if sd else math.nan:.1e}")
    ok("G3 derived columns of all those points = the independent re-derivation from their arrays", all(derived_ok(r) for r in recs),
       f"{sum(np.isfinite(r['A0_up_rel']) for r in recs)} with a larger overhang-blocked offset")
    ts = np.array([r["t_s"] for r in recs])
    print(f"   G: per point {ts.mean():.3f} s mean ({ts[feas].mean():.3f} feasible, {ts[~feas].mean():.3f} infeasible); "
          f"reasons {sorted(set(r['reason'] for r in recs))}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", default=None)
    ap.add_argument("--sample", type=int, default=None, help="compare only N random templated 3406 jobs (default: all of them)")
    ap.add_argument("--seed", type=int, default=20261025)
    ap.add_argument("--expect-jobs", type=int, default=None, help="the number of templated 3406 jobs the queue must hold")
    ap.add_argument("--tol", type=float, default=1e-9, help="F1 scaled-diff tolerance (default 1e-9 = rounding only; prep.json was "
                    "written on Linux, so a mirror checked with another host's femur cache build may need more for 'contact')")
    ap.add_argument("--expect-geom-key", default=None, help="femur_geom_key computed on the other host")
    ap.add_argument("--max-workers", type=int, default=2)
    ap.add_argument("--abort-timeout", type=float, default=240.0)
    ap.add_argument("--tmp", default=None)
    ap.add_argument("--skip-real", action="store_true")
    ap.add_argument("--pool", default=None, help="results/pools/neckopt_p11_n16384_s0_<key>.npz (with its .json)")
    ap.add_argument("--pool-n", type=int, default=128)
    a = ap.parse_args()
    t0 = time.perf_counter()
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="tpl_record_test_", dir=a.tmp))
    sec_a()
    sec_b()
    (tmp / "c").mkdir()
    sec_c(tmp / "c", a.expect_geom_key)
    real = not a.skip_real and T.femur_cache_file("isthmus").exists()
    if not real:
        if a.skip_real:
            skip("D / E / F / G real-femur sections", "--skip-real")
        else:
            ok("D0 local 3406 femur cache exists (else run with --skip-real)", False, str(T.femur_cache_file("isthmus")))
    else:
        listing = T._cache_listing()
        ra = sec_d()
        (tmp / "e").mkdir()
        sec_e(tmp / "e", ra, a.max_workers, a.abort_timeout)
        if a.queue:
            sec_f(a.queue, a.sample, a.seed, a.expect_jobs, a.tol)
        else:
            skip("F prep.json agreement on existing 3406 jobs", "no --queue")
        if a.pool:
            sec_g(a.pool, a.pool_n)
        else:
            skip("G candidate pool file agreement", "no --pool")
        ok("Z femur cache listing identical at the end of the run", T._cache_listing() == listing)
    bad = [k for k, v in checks if not v]
    print(f"\n{len(checks) - len(bad)}/{len(checks)} checks passed in {time.perf_counter() - t0:.0f} s"
          + (f"; skipped: {skipped}" if skipped else "") + (f"; FAILED: {bad}" if bad else "") + f"; scratch {tmp}", flush=True)
    if HUNG:                                                 # a batch never returned: do not wait for its threads / workers at exit
        print(f"HUNG: {len(HUNG)} bounded batch call(s) did not return; terminating workers and exiting hard", flush=True)
        for c in mp.active_children():
            c.terminate()
        os._exit(2)
    return 1 if bad else 0


if __name__ == "__main__":          # spawn workers re-import this file as __mp_main__: nothing but the fault hook may run at import
    sys.exit(main())
