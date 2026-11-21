"""Run with the repo venv: PYTHONUTF8=1 .venv-mobo/Scripts/python.exe v2/tests/test_arms_p11_p12.py
Local only: fake queues in the system temp dir (mobo_toy_arms_tests); gated_pool / refresh_pool / stability_of / _calcar / jobs.submit are
replaced by synthetic stand-ins (submit = register + write a synthetic result.json + DONE at once, or FAILED for one pool point);
real BoTorch (mobo.fit_models / propose). No gmsh, no FE, no Abaqus, no Linux, nothing under ~/mobo_toy_v2 is touched; single process.

Parallel arms (2026-10-24, 计算计划_50h §7 修订 1; critic wf_6f8fbde1 issue 1): phase 11 (v3) with --warm none and phase 12 (v4) with the
frozen warm start PHASES[12]["warm_from"] = {phase 11, rounds [0, -1]}, equal own budgets.
A. PHASES[12] / Phase.warm_from (normalised; bad definitions refused); PHASES[11] identical to the synced 4ca6a57 definition.
B. refusals (ValueError before gated_pool, nothing submitted, no state file): no neckopt_p11.json; neckopt_p11.json without round-0 records;
   sb11 jobs phase 11 has not adopted yet (its async has not run); phase-11 adopted jobs still in flight; p12 state with records but no
   warm_from; and arms_gate.py p12 / init agree (exit 8 / 5).
C. phase 11 arm (bo init = segment A, then async --warm none): adopts sb11_* only, never sb12_*; dataset() is never called; its fits use only
   its own records; budget = init records + adopted + new (arms_gate.py BUDGET11).
D. phase 12 first start: frozen ids = round-0 records (ok) + adopted smokes (both of a fric_only / bonded pair), FAILED init skipped;
   --warm family ignored and logged; budget counts only own sb12 jobs (warm rows excluded); det exact on the warm rows; warm pool points
   never submitted; warm_from stored in neckopt_p12.json.
E. after new sb11 jobs appear (phase-11 picks, a hand-submitted late smoke, a pick that finished while phase 11 was down = round -1 with a
   pool index): a fresh selection would take the late smoke but never the picks; the phase-12 restart reuses exactly the stored ids (same X0,
   bitwise), does not read neckopt_p11.json (works with it moved away); a frozen id that is no longer ok is skipped with a warning and
   warm_start_ids stays unchanged.
F. bo(12) sync: the frozen set is saved before the first submission; restart reuses it.
G. arms_gate.py: init gate numbers (not-ok fraction, feasible), flag file written on FAIL / removed on PASS, BUDGET11 / BUDGET12; p12
   readiness; its warm candidates == stage_neckopt.warm_from_select.
H. g1_regress.py on the fake tree: all PASS, writes only under deck/p11_3406/g1; a tampered stored record -> FAIL, exit 1; missing pool
   file -> FAIL; neckopt_p11.json space / fixed different from Phase(11) -> G1d FAIL, exit 1.

Fixes after review wcc2j2fj4 (fixdev, 2026-10-24):
K. guard: phase 11 is the frozen warm-start source of phase 12, so bo / bo_async(11) with --warm family / legacy -> ValueError naming
   '--warm none' (before gated_pool, nothing submitted, state file untouched); --warm none passes; phase 12 / phase 10 not refused; no
   guard once PHASES[12] has no warm_from. (Segment A in C1 therefore runs with legacy_warm None.)
L. zero feasible designs (all init, smokes and picks violate the 150 um constraint): bo_async(11) and bo_async(12) through >= 6
   completions with refresh_k > 0 do not crash (the empty-front refresh is skipped and logged; refresh_pool is never called);
   refresh_pool itself returns empty arrays for an empty centre set without starting a process pool; bo(11) sync rounds the same.
   Reference point: while no feasible row exists every acquisition uses a temporary ref point (= ref_point of all rows of that fit,
   logged) and nothing is stored (ref_point None, HV nan); the first feasible completion freezes it (logged once, = that row's y),
   later acquisitions use the frozen one; in the feasible regime (C2) it is frozen at the first acquisition exactly as before.
M. atomic state writes: both save() functions go through _write_state (.json.tmp + os.replace, no .tmp left behind); a reader thread
   never sees a partial / empty file while _write_state rewrites a ~2 MB state in a loop (a plain write_text control is reported).
"""
import contextlib
import copy
import importlib.util
import io
import json
import math
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

import numpy as np

ROOT = pathlib.Path(r"H:/projects/Femoral implant generation/sandbox/mobo_toy")
SCRIPTS = pathlib.Path(r"H:/projects/application/research-log/neck_implant_2026-10-02/deck_data/scripts")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "v2"))
BASE = pathlib.Path(tempfile.gettempdir()) / "mobo_toy_arms_tests"        # fake queues outside the repo and outside ~/mobo_toy_v2
shutil.rmtree(BASE, ignore_errors=True)
BASE.mkdir(parents=True)

import jobs as J  # noqa: E402
import stage_neckopt as N  # noqa: E402
import mobo  # noqa: E402
import torch  # noqa: E402


def load_script(name):
    spec_ = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(mod)
    return mod


AG = load_script("arms_gate")
G1 = load_script("g1_regress")

P11_ORIG = copy.deepcopy(N.PHASES[11])
P12_ORIG = copy.deepcopy(N.PHASES[12])
IID = N.PHASES[11]["intact_job"]
FID = "sawbone3406"
INTACT = {"kind": "intact", "h_int": 2.0, "stage": "sb", "tag": "intact_h2", "femur_id": FID, "neck_axis": "isthmus"}
checks = []
T_START = time.perf_counter()


def ok(name, cond, extra=""):
    checks.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""), flush=True)


def raises(exc, fn, *a, **k):
    try:
        fn(*a, **k)
    except exc as e:
        return str(e)
    except Exception as e:                                   # noqa: BLE001
        return f"WRONG EXCEPTION {type(e).__name__}: {e}"
    return None


def captured(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = fn(*a, **k)
    return r, buf.getvalue()


def make_env(name):
    root = BASE / name
    shutil.rmtree(root, ignore_errors=True)
    (root / "queue").mkdir(parents=True)
    (root / "results").mkdir()
    J.QROOT, J.RESULTS = root / "queue", root / "results"
    assert not str(J.QROOT).startswith(str(pathlib.Path.home() / "mobo_toy_v2"))
    d = J.QROOT / IID
    d.mkdir()
    (d / "spec.json").write_text(json.dumps(INTACT))
    (d / "DONE").write_text("x")
    return root


PH11 = N.Phase(11)
NV = len(PH11.vars)
rng = np.random.default_rng(1211)
POOL = rng.random((300, NV))
FAIL_IDX = 3                                                               # the solver "fails" this pool point (one FAILED init job)


def loss_fn(U):
    U = np.atleast_2d(np.asarray(U, float))
    return 4000.0 + 5000.0 * U[:, 1] + 3000.0 * U[:, 0] + 1000.0 * U[:, 7]


LOSS = loss_fn(POOL)


def truth(x):
    rot = 0.01 + 0.08 * x[0] * (1.0 - x[1]) + 0.02 * x[3]
    area = 1200.0 + 900.0 * x[2] + 300.0 * x[4]
    f1 = 40.0 + 160.0 * x[5]                                               # x5 > 0.6875 -> micromotion constraint violated
    return rot, area, f1


def x_of_job(jid):
    spec = json.loads((J.QROOT / jid / "spec.json").read_text())
    return PH11.to_unit(spec["design"], float(spec["h_cut"])), spec


FEAS_OVERRIDE = [False]                                                    # L: from a point on every new result is feasible (f1 40 um)


def solve_fake(jid):
    x, spec = x_of_job(jid)
    if np.max(np.abs(x - POOL[FAIL_IDX])) < 1e-9:
        (J.QROOT / jid / "FAILED.json").write_text(json.dumps({"level": "L4", "stage": "solve", "reason": "fake: too many attempts"}))
        return
    rot, area, f1 = truth(x)
    if FEAS_OVERRIDE[0]:
        f1 = 40.0
    res = {"f1_p95_um": f1, "bone_loss": {"total_mm3": float(loss_fn(x)[0]), "ref_cut_mm": 16.0},
           "templating": {"A0": 500.0, "e": -1.0, "volume": 3000.0}, "job_id": jid}
    if spec.get("fric_only"):
        res["fric_only"] = True
    else:
        res["vm_p99"] = 90.0
    (J.QROOT / jid / "result.json").write_text(json.dumps(res))
    (J.QROOT / jid / "DONE").write_text("x")


def fake_stability(jid):
    x, _ = x_of_job(jid)
    rot, area, _ = truth(x)
    return {"rot_first_deg": rot, "contact_area_load2_mm2": area}


_real_submit = J.submit
SUBMITTED = []


def submit_and_solve(spec):
    jid = _real_submit(spec)
    SUBMITTED.append(jid)
    solve_fake(jid)
    return jid


def add_job(ph, u, tag, bonded=False, state="DONE"):
    jid = _real_submit(ph.spec_of(u, tag, bonded=bonded))
    if state == "DONE":
        solve_fake(jid)
    elif state == "READY":
        (J.QROOT / jid / "READY").write_text("x")
    return jid


def fake_gated(ph, n=8192, seed=0, workers=6):
    return POOL.copy(), LOSS.copy()


def fake_refresh(ph, centres, k=64, rad=0.08, workers=6, seed=0):
    r = np.random.default_rng(seed)
    U = np.clip(np.vstack([c + r.uniform(-rad, rad, size=(k, len(ph.vars))) for c in np.atleast_2d(centres)]), 0.0, 1.0)
    return U, loss_fn(U)


def no_pool(*a, **k):
    raise AssertionError("gated_pool reached")


FIT_LOG, PROP_LOG, DET_LOG, DS_CALLS = [], [], [], []
_real_fit, _real_prop, _real_det_of, _real_dataset = mobo.fit_models, mobo.propose, N.det_of, N.dataset


def fit_spy(X, Y, C, noise_sd=None, det=None):
    FIT_LOG.append({"X": np.array(X), "Y": np.array(Y), "C": np.array(C)})
    return _real_fit(X, Y, C, noise_sd, det)


def prop_spy(model, X_obs, ref_min, pool, q, n_obj, n_con, seed, X_pending=None):
    PROP_LOG.append({"n_obj": n_obj, "ref": np.array(ref_min, float)})
    return _real_prop(model, X_obs, ref_min, pool, q, n_obj, n_con, seed, X_pending=X_pending)


def det_spy(ph, pool, pool_loss, extra=None):
    d = _real_det_of(ph, pool, pool_loss, extra)
    DET_LOG.append({"det": d})
    return d


def ds_spy(ph, legacy=False):
    DS_CALLS.append(ph.phase)
    return _real_dataset(ph, legacy)


def spies(on):
    if on:                                                                 # logs are cleared when the spies go on and kept after
        for log in (FIT_LOG, PROP_LOG, DET_LOG, DS_CALLS):
            log.clear()
    mobo.fit_models, mobo.propose, N.det_of, N.dataset = (fit_spy, prop_spy, det_spy, ds_spy) if on else \
        (_real_fit, _real_prop, _real_det_of, _real_dataset)


def gate(*argv):
    rc, out = captured(AG.main, list(argv))
    kv = dict(ln.split("=", 1) for ln in out.splitlines() if "=" in ln and ln.split("=", 1)[0].isupper() and " " not in ln.split("=", 1)[0])
    return rc, out, kv


def run11(budget, **kw):
    return N.bo_async(PH11, budget=budget, inflight=1, seed=0, workers=1, legacy_warm=None, n_pool=16384, refresh_k=0, poll=0.01, **kw)


def run12(budget, legacy_warm=False):
    return N.bo_async(N.Phase(12), budget=budget, inflight=1, seed=0, workers=1, legacy_warm=legacy_warm, n_pool=16384, refresh_k=2,
                      refresh_rad=0.05, poll=0.01)


N.stability_of = fake_stability
N._calcar = lambda jid: (None, None)
_real_refresh = N.refresh_pool
REFRESH_CALLS = []


def refresh_spy(ph, centres, k=64, rad=0.08, workers=6, seed=0):
    REFRESH_CALLS.append(len(np.atleast_2d(centres)))
    return fake_refresh(ph, centres, k=k, rad=rad, workers=workers, seed=seed)


N.refresh_pool = refresh_spy

# ================================================================ A. PHASES[12] / Phase.warm_from
ph12 = N.Phase(12)
ok("PHASES[12]['warm_from'] == {'phase': 11, 'rounds': [0, -1]}; Phase(12).warm_from normalised the same; Phase(11).warm_from None",
   N.PHASES[12]["warm_from"] == {"phase": 11, "rounds": [0, -1]} and ph12.warm_from == {"phase": 11, "rounds": [0, -1]}
   and PH11.warm_from is None and N.Phase(10).warm_from is None)
try:
    OLD_SRC = subprocess.run(["git", "-C", str(ROOT), "show", "4ca6a57:v2/stage_neckopt.py"], capture_output=True, check=True).stdout
    (BASE / "stage_neckopt_4ca6a57.py").write_bytes(OLD_SRC)
    _s = importlib.util.spec_from_file_location("stage_neckopt_4ca6a57", BASE / "stage_neckopt_4ca6a57.py")
    OLD = importlib.util.module_from_spec(_s)
    _s.loader.exec_module(OLD)
except Exception as ex_:                                                    # noqa: BLE001
    OLD = None
    print(f"   cannot load 4ca6a57: {type(ex_).__name__}: {ex_}")
ok("PHASES[11] identical to the synced 4ca6a57 definition (vars, fixed, sed, femur, intact_job, ...)", OLD is not None and OLD.PHASES[11] == N.PHASES[11])
for bad in ({"phase": 12, "rounds": [0]}, {"rounds": [0]}, {"phase": 11, "rounds": []}, {"phase": 11, "rounds": ["0"]}, [11, 0]):
    N.PHASES[12]["warm_from"] = bad
    e = raises(ValueError, N.Phase, 12)
    ok(f"Phase(12) with warm_from {bad!r} -> ValueError", e is not None and "warm_from" in e, (e or "")[:70])
N.PHASES[12].clear(); N.PHASES[12].update(copy.deepcopy(P12_ORIG))

# ================================================================ B1. refusal: no neckopt_p11.json
env = make_env("arms")
J.submit = submit_and_solve
N.gated_pool = no_pool
S16, S20 = rng.random(NV), rng.random(NV)
S16[5] = S20[5] = 0.2                                                      # smokes feasible
smk_f16 = add_job(PH11, S16, "smoke_f_h16")
smk_f20 = add_job(PH11, S20, "smoke_f_h20")
smk_b20 = add_job(PH11, S20, "smoke_b_h20", bonded=True, state="READY")   # bonded twin of smoke_f_h20, still in the solver
SUBMITTED.clear()
e = raises(ValueError, run12, 3)
ok("p12 without neckopt_p11.json -> ValueError (before gated_pool), nothing submitted, no neckopt_p12.json",
   e is not None and "neckopt_p11.json does not exist" in e and not SUBMITTED and not N.out_path(12).exists()
   and not list(J.QROOT.glob("sb12_*")), (e or "")[:120])
rc, out, kv = gate("p12", "--root", str(env))
ok("arms_gate p12 without neckopt_p11.json -> exit 8, READY12=0", rc == 8 and kv.get("READY12") == "0", out.strip()[:100])
flag = env / "logs" / "arms_gate.FAIL"
rc, out, kv = gate("init", "--root", str(env), "--flag", str(flag))
ok("arms_gate init without neckopt_p11.json -> exit 5, VERDICT=FAIL, flag file written", rc == 5 and kv.get("VERDICT") == "FAIL" and flag.exists())

# ================================================================ C1. segment A: bo(11) init (6 points, one FAILED)
N.gated_pool = fake_gated
st_a = N.bo(PH11, n_rounds=0, n_init=6, q=1, seed=0, workers=1, legacy_warm=None, n_pool=16384, refresh_k=0)   # --warm none (guard K)
init_ids = [r["job_id"] for r in st_a["records"]]
fail_init = [r["job_id"] for r in st_a["records"] if not r["ok"]]
ok("segment A: 6 round-0 records on pool points 0-5, exactly one FAILED (pool point 3), n_submitted 6",
   len(init_ids) == 6 and [r["pool_idx"] for r in st_a["records"]] == list(range(6)) and all(r["round"] == 0 for r in st_a["records"])
   and len(fail_init) == 1 and J.state(J.QROOT / fail_init[0]) == "FAILED" and st_a["n_submitted"] == 6)

# ================================================================ B2. refusal: smokes not yet adopted by phase 11 / no round-0 / in flight
N.gated_pool = no_pool
SUBMITTED.clear()
e = raises(ValueError, run12, 3)
ok("p12 while phase 11 has not adopted the smokes (its async never ran) -> ValueError naming them; nothing submitted, no p12 state",
   e is not None and "not yet adopted" in e and smk_f16 in e and not SUBMITTED and not N.out_path(12).exists(), (e or "")[:140])
rc, out, kv = gate("p12", "--root", str(env))
ok("arms_gate p12 -> exit 8, lists the 3 unadopted sb11 smokes", rc == 8 and "not yet adopted" in out and kv.get("READY12") == "0"
   and "3 sb11_*" in out, out.strip()[-160:])
st11 = json.loads(N.out_path(11).read_text())
e = raises(ValueError, N.warm_from_select, ph12, {"records": [{**r, "round": -1, "pool_idx": None} for r in st11["records"]]})
ok("warm_from_select on a state without round-0 records -> ValueError 'no round-0'", e is not None and "no round-0" in e, (e or "")[:100])
env_n = make_env("noinit")
(J.RESULTS / "neckopt_p11.json").write_text(json.dumps({"records": [{"job_id": "sb11_x_1", "round": -1, "pool_idx": None, "ok": True}]}))
e = raises(ValueError, run12, 3)
ok("bo_async(12) with a neckopt_p11.json without round-0 records -> ValueError before gated_pool", e is not None and "no round-0" in e, (e or "")[:100])
J.QROOT, J.RESULTS = env / "queue", env / "results"

# ================================================================ G1. arms_gate init numbers / flag
rc, out, kv = gate("init", "--root", str(env), "--flag", str(flag), "--new", "2")
ok("arms_gate init: 6 init, 5 ok, not ok 16.7 % > 15 % -> FAIL exit 3, flag rewritten with the numbers",
   rc == 3 and kv.get("VERDICT") == "FAIL" and kv.get("INIT_RECORDS") == "6" and kv.get("INIT_OK") == "5" and flag.exists()
   and "16.7%" in flag.read_text(), flag.read_text().strip()[:120] if flag.exists() else "no flag")
rc, out, kv = gate("init", "--root", str(env), "--flag", str(flag), "--new", "2", "--max-fail", "0.2")
n_feas_init = sum(1 for r in st_a["records"] if r["ok"] and r["c"][0] <= 0)
ok("arms_gate init --max-fail 0.2 -> PASS exit 0, flag removed; BUDGET11 = 6 init + 3 to adopt + 2 = 11, BUDGET12 = 2",
   rc == 0 and kv.get("VERDICT") == "PASS" and not flag.exists() and kv.get("BUDGET11") == "11" and kv.get("BUDGET12") == "2"
   and kv.get("N_ADOPT") == "3" and kv.get("INIT_FEASIBLE") == str(n_feas_init), f"{kv}")

# ================================================================ C2. phase 11 arm, first start: async --warm none (sb12 job present)
solve_fake(smk_b20)                                                         # the bonded smoke finished before the arms start
(J.QROOT / smk_b20 / "READY").unlink()
stray12 = add_job(ph12, rng.random(NV), "stray")                           # an sb12 job already in the queue (never phase-11 data)
N.gated_pool = fake_gated
SUBMITTED.clear()
spies(True)
st11a, log11a = captured(run11, 11)
spies(False)
recs11 = st11a["records"]
adopted11 = [r["job_id"] for r in recs11 if r["pool_idx"] is None]
ok("p11 async (--warm none): adopts the 3 sb11 smokes (round -1, pool_idx None), submits 2 picks (budget 11 = 6 + 3 + 2)",
   sorted(adopted11) == sorted([smk_f16, smk_f20, smk_b20]) and all(r["round"] == -1 for r in recs11 if r["pool_idx"] is None)
   and len(SUBMITTED) == 2 and all(j.startswith("sb11_a") for j in SUBMITTED) and len(recs11) == 11, f"{adopted11} {SUBMITTED}")
ok("p11 --warm none: never sb12 (records, pending, warm_start_ids empty), dataset() not called",
   not any(r["job_id"].startswith("sb12") for r in recs11) and not any(j.startswith("sb12") for j in st11a["pending"])
   and st11a["warm_start_ids"] == [] and st11a["warm_start_n"] == 0 and DS_CALLS == [])
n_ok11 = sum(1 for r in recs11[:9] if r["ok"])
ok("p11 first fit: X rows = its own ok records only (5 init + 3 smokes = 8), no sb12 row", FIT_LOG and FIT_LOG[0]["X"].shape == (8, NV)
   and n_ok11 == 8, f"{FIT_LOG[0]['X'].shape if FIT_LOG else None}")
ok("p11 (feasible rows at the first acquisition): ref point frozen there exactly as before (= ref_point of the first fit's Y / C, "
   "stored, logged once), no temporary ref point; every acquisition used it",
   FIT_LOG and st11a["ref_point"] == N.ref_point(FIT_LOG[0]["Y"], FIT_LOG[0]["C"]).tolist() and log11a.count("ref point frozen at acquisition #") == 1
   and "temporary ref point" not in log11a and all(np.array_equal(p_["ref"], np.array(st11a["ref_point"])) for p_ in PROP_LOG) and PROP_LOG,
   f"{st11a['ref_point']}")
rc, out, kv = gate("init", "--root", str(env), "--new", "2", "--max-fail", "0.2")
ok("arms_gate init after the p11 start: same BUDGET11 11 (3 adopted records), N_PICKS11 2", kv.get("BUDGET11") == "11" and kv.get("N_ADOPT") == "3"
   and kv.get("N_PICKS11") == "2", f"{kv}")

# ================================================================ G2 / D. phase 12 first start
st11 = json.loads(N.out_path(11).read_text())
cand_n, _ = N.warm_from_select(ph12, st11)
rc, out, kv = gate("p12", "--root", str(env))
ok("arms_gate p12 now READY (exit 0); its candidates == warm_from_select (6 init + 3 adopted = 9, no picks)",
   rc == 0 and kv.get("READY12") == "1" and kv.get("WARM_CANDIDATES") == "9" and AG.warm_candidates(st11) == cand_n
   and cand_n == init_ids + [r["job_id"] for r in st11["records"] if r["pool_idx"] is None], out.strip()[-120:])
SUBMITTED.clear()
spies(True)
st12a, log12a = captured(run12, 3, legacy_warm=False)
spies(False)
frozen = st12a["warm_start_ids"]
exp_frozen = [j for j in init_ids if j not in fail_init] + [r["job_id"] for r in st11["records"] if r["pool_idx"] is None]
ok("p12 first start: frozen warm_start_ids = 5 ok init + 3 adopted smokes (fric_only and bonded twin both kept), FAILED init skipped",
   frozen == exp_frozen and st12a["warm_start_n"] == 8 and st12a["warm_from"]["candidates"] == cand_n
   and st12a["warm_from"]["skipped"] == {fail_init[0]: "FAILED"}, f"{len(frozen)} {st12a['warm_from'].get('skipped')}")
ok("p12: --warm family ignored and logged; first-start log line; dataset() not called",
   "the --warm family option is ignored" in log12a and "first start, froze 8 of 9" in log12a and DS_CALLS == [], log12a.splitlines()[0][:110])
own12 = [r for r in st12a["records"] if r["job_id"] in SUBMITTED]
ok("p12 budget 3 = own records only: adopts the stray sb12 job (1) + 2 own submissions; 8 warm rows not counted; n_submitted 3",
   len(SUBMITTED) == 2 and all(j.startswith("sb12_a") for j in SUBMITTED) and len(st12a["records"]) == 3 and st12a["pending"] == {}
   and stray12 in [r["job_id"] for r in st12a["records"]] and st12a["n_submitted"] == 3, f"{SUBMITTED}")
ok("p12 records: no sb11 job; every record 3 objectives", not any(r["job_id"].startswith("sb11") for r in st12a["records"])
   and all(len(r["y"]) == 3 for r in st12a["records"]))
X0_first = FIT_LOG[0]["X"][:8].copy()
ok("p12 first fit: X = 8 warm rows + 1 adopted sb12 record, Y 3 columns; warm rows = to_unit(spec) of the frozen ids in order",
   FIT_LOG[0]["X"].shape == (9, NV) and FIT_LOG[0]["Y"].shape[1] == 3
   and np.array_equal(X0_first, np.array([x_of_job(j)[0] for j in frozen])))
f0 = DET_LOG[0]["det"][2]
ok("p12 det exact on all 8 warm rows (= Y0[:, 2] = record bone)", np.array_equal(f0(torch.as_tensor(X0_first)).numpy(), FIT_LOG[0]["Y"][:8, 2]))
ok("p12: the 6 init pool points (5 warm rows + the FAILED init point, which is not in X0) never submitted under sb12",
   all(r["pool_idx"] not in (0, 1, 2, 3, 4, 5) for r in own12) and all(r["pool_idx"] is not None for r in own12), str([r["pool_idx"] for r in own12]))
p12file = json.loads(N.out_path(12).read_text())
ok("neckopt_p12.json carries warm_from (phase 11, rounds [0, -1], frozen time, source counts) and the frozen ids",
   p12file["warm_from"]["phase"] == 11 and p12file["warm_from"]["rounds"] == [0, -1] and p12file["warm_from"]["frozen"]
   and p12file["warm_from"]["source_round0"] == 6 and p12file["warm_from"]["source_adopted"] == 3 and p12file["warm_start_ids"] == frozen)

# ================================================================ E. new sb11 jobs appear; phase 11 restarts; phase 12 restarts frozen
late = add_job(PH11, rng.random(NV), "smoke_late")                         # hand-submitted sb11 job (phase 11 adopts it)
k99 = 250
j99 = _real_submit(PH11.spec_of(POOL[k99], "a99", bonded=False))          # a phase-11 pick that finished while its driver was down
solve_fake(j99)
s11 = json.loads(N.out_path(11).read_text())
s11["pending"][j99] = {"pool_idx": k99, "x": POOL[k99].tolist(), "submitted": "2026-10-24 03:00:00", "bonded": False}
N.out_path(11).write_text(json.dumps(s11))
SUBMITTED.clear()
spies(True)
st11b, _ = captured(run11, 15)                                              # 6 init + 4 adopted (3 smokes + late) + 5 picks (2 + a99 + 2 new)
spies(False)
r99 = next(r for r in st11b["records"] if r["job_id"] == j99)
ok("p11 restart: late smoke adopted (pool_idx None), a99 recorded as round -1 WITH pool_idx 250, 2 more picks; still no sb12 anywhere",
   any(r["job_id"] == late and r["pool_idx"] is None for r in st11b["records"]) and r99["round"] == -1 and r99["pool_idx"] == k99
   and len(SUBMITTED) == 2 and len(st11b["records"]) == 15 and not any(r["job_id"].startswith("sb12") for r in st11b["records"])
   and DS_CALLS == [] and FIT_LOG and FIT_LOG[0]["X"].shape[0] == sum(1 for r in st11b["records"][:13] if r["ok"]),
   f"{len(st11b['records'])} {FIT_LOG[0]['X'].shape if FIT_LOG else None}")
st11n = json.loads(N.out_path(11).read_text())
cand_new, _ = N.warm_from_select(ph12, st11n)
ok("a fresh selection now: 6 init + 4 adopted (late smoke included), never the 5 phase-11 picks (incl. a99 = round -1 + pool index)",
   cand_new == init_ids + [r["job_id"] for r in st11n["records"] if r["pool_idx"] is None] and j99 not in cand_new and late in cand_new
   and not any(j.startswith("sb11_a") for j in cand_new) and AG.warm_candidates(st11n) == cand_new, f"{len(cand_new)}")
p11_path = N.out_path(11)
p11_path.rename(p11_path.with_suffix(".moved"))                            # restart must not need phase 11's file
SUBMITTED.clear()
spies(True)
st12b, log12b = captured(run12, 5, legacy_warm=None)
spies(False)
p11_path.with_suffix(".moved").rename(p11_path)
ok("p12 restart (neckopt_p11.json moved away, --warm none given): reuses exactly the stored ids; late smoke / picks not added",
   st12b["warm_start_ids"] == frozen and late not in st12b["warm_start_ids"] and "restart, reusing the 8 frozen ids" in log12b
   and "the --warm none option is ignored" in log12b and DS_CALLS == [], [ln for ln in log12b.splitlines() if "warm" in ln][:2])
ok("p12 restart: X0 bitwise identical to the first start's; 2 more own submissions (budget 5), 5 records",
   FIT_LOG and np.array_equal(FIT_LOG[0]["X"][:8], X0_first) and len(SUBMITTED) == 2 and len(st12b["records"]) == 5
   and all(j.startswith("sb12_") for j in SUBMITTED))
rj = J.QROOT / smk_f16 / "result.json"
rj_text = rj.read_text()
rj.unlink(); (J.QROOT / smk_f16 / "DONE").unlink()
(J.QROOT / smk_f16 / "FAILED.json").write_text(json.dumps({"level": "L5", "stage": "post", "reason": "fake"}))
spies(True)
st12c, log12c = captured(run12, 5)
spies(False)
ok("p12 restart with a frozen id no longer usable: skipped with a warning, warm_start_n 7, warm_start_ids unchanged (8)",
   "no longer usable" in log12c and st12c["warm_start_n"] == 7 and st12c["warm_start_ids"] == frozen, f"{st12c['warm_start_n']}")
(J.QROOT / smk_f16 / "FAILED.json").unlink(); rj.write_text(rj_text); (J.QROOT / smk_f16 / "DONE").write_text("x")
s12 = json.loads(N.out_path(12).read_text())
N.out_path(12).write_text(json.dumps({k: v for k, v in s12.items() if k != "warm_from"}))
N.gated_pool = no_pool
e = raises(ValueError, run12, 5)
ok("p12 state with records but no warm_from (pre-warm_from file) -> ValueError before gated_pool", e is not None and "no frozen warm start" in e, (e or "")[:100])
rc, out, kv = gate("p12", "--root", str(env))
ok("arms_gate p12 on that file -> exit 8 ('move it away')", rc == 8 and "move it away" in out)
N.out_path(12).write_text(json.dumps(s12))
rc, out, kv = gate("p12", "--root", str(env))
ok("arms_gate p12 with the frozen p12 state -> READY (restart), WARM_IDS 8", rc == 0 and kv.get("WARM_IDS") == "8")
N.gated_pool = fake_gated

# ================================================================ B3. in-flight adopted job (crafted copy of the phase-11 state)
s_if = json.loads(N.out_path(11).read_text())
rec_b = next(r for r in s_if["records"] if r["job_id"] == smk_b20)
s_if["records"] = [r for r in s_if["records"] if r["job_id"] != smk_b20]
s_if["pending"] = {smk_b20: {"pool_idx": None, "x": rec_b["x"], "submitted": "adopted"}}
e = raises(ValueError, N.warm_from_select, ph12, s_if)
ok("warm_from_select with a phase-11 adopted job still in flight -> ValueError 'still in flight'", e is not None and "still in flight" in e
   and smk_b20 in e, (e or "")[:100])
env_if = make_env("inflight")
shutil.rmtree(env_if / "queue"); shutil.copytree(env / "queue", env_if / "queue")
(env_if / "results" / "neckopt_p11.json").write_text(json.dumps(s_if))
rc, out, kv = gate("p12", "--root", str(env_if))
ok("arms_gate p12 with the in-flight adopted job -> exit 8 ('still in flight')", rc == 8 and "still in flight" in out)
cand_ns, info_ns = N.warm_from_select(ph12, s_if, strict=False)
ok("warm_from_select(strict=False) returns the candidates and the problem list instead of raising", info_ns["problems"] and len(cand_ns) == 9)
J.QROOT, J.RESULTS = env / "queue", env / "results"

# ================================================================ F. bo(12) sync: frozen set saved before the first submission
env_s = make_env("sync12")
J.submit = submit_and_solve
st_as = N.bo(PH11, n_rounds=0, n_init=4, q=1, seed=0, workers=1, legacy_warm=None, n_pool=16384, refresh_k=0)


def boom(spec):
    raise RuntimeError("submit blocked")


J.submit = boom
e = raises(RuntimeError, N.bo, N.Phase(12), 1, 0, 1, 0, 1, False, 16384)
s_sync = json.loads(N.out_path(12).read_text()) if N.out_path(12).exists() else {}
ok("bo(12) sync: the frozen warm start (3 ok init of 4) is in neckopt_p12.json before the first submission",
   e is not None and s_sync.get("warm_start_ids") == [r["job_id"] for r in st_as["records"] if r["ok"]] and s_sync.get("warm_from", {}).get("phase") == 11
   and s_sync["records"] == [], f"{len(s_sync.get('warm_start_ids') or [])}")
J.submit = submit_and_solve
SUBMITTED.clear()
spies(True)
st_s2, log_s2 = captured(N.bo, N.Phase(12), 1, 0, 1, 0, 1, None, 16384)
spies(False)
ok("bo(12) sync restart: reuses the 3 frozen ids, one round q 1 with n_obj 3, the init pool points 0-3 not re-submitted",
   st_s2["warm_start_ids"] == s_sync["warm_start_ids"] and "restart, reusing the 3 frozen ids" in log_s2 and len(SUBMITTED) == 1
   and PROP_LOG and PROP_LOG[0]["n_obj"] == 3 and st_s2["records"][0]["pool_idx"] not in (0, 1, 2, 3) and st_s2["warm_start_n"] == 3)
J.QROOT, J.RESULTS = env / "queue", env / "results"

# ================================================================ H. g1_regress.py on the fake tree
pf = N.pool_file(ph12, 16384, 0)
ok("pool_file(12, 16384, 0) -> the phase-11 pool file name (pool_phase reuse) under results/pools",
   pf.parent == J.RESULTS / "pools" and pf.name.startswith("neckopt_p11_n16384_s0_") and pf.name.endswith(f"{N.pool_key(PH11, 16384, 0)}.npz"))
pf.parent.mkdir(exist_ok=True)
np.savez(pf, U=POOL, loss=LOSS)
G1.femur_cache_ok = lambda SN, ids: (True, "test: femur caches assumed present")


def snapshot(root, skip):
    out = {}
    for p in root.rglob("*"):
        if p.is_file() and skip not in p.parents:
            s_ = p.stat()
            out[str(p.relative_to(root))] = (s_.st_size, s_.st_mtime_ns)
    return out


g1dir = env / "deck" / "p11_3406" / "g1"
before = snapshot(env, g1dir)
rc, out_g1 = captured(G1.main, ["--root", str(env), "--code", str(ROOT)])
after = snapshot(env, g1dir)
fails = [r for r in G1.ROWS if r["verdict"] == "FAIL"]
ok("g1_regress on the fake tree: exit 0, no FAIL, G1a / G1b / G1c / G1d rows present",
   rc == 0 and not fails and {r["check"] for r in G1.ROWS} >= {"G1a", "G1b", "G1c", "G1d"}, f"rc {rc}; {fails[:2]}")
ok("g1_regress: every DONE sb11 job compared (stored) or computed, det exact row PASS, pool reuse row PASS",
   sum(1 for r in G1.ROWS if r["check"] == "G1b") == len([d for d in J.QROOT.glob("sb11_*") if (d / "DONE").exists()]) + 1
   and any(r["item"].startswith("det(X0)") and r["verdict"] == "PASS" for r in G1.ROWS)
   and any(r["item"].startswith("phase-12 candidate pool") and r["verdict"] == "PASS" for r in G1.ROWS),
   str([r for r in G1.ROWS if r["check"] == "G1c"][:3])[:200])
ok("g1_regress G1d: 'neckopt_p11.json space / fixed == Phase(11)' row present and PASS on the untouched tree",
   [r["verdict"] for r in G1.ROWS if r["item"].startswith("neckopt_p11.json space / fixed")] == ["PASS"])
ok("g1_regress wrote only under deck/p11_3406/g1 (rest of the tree byte-identical, mtimes unchanged)",
   before == after and (g1dir / "g1_latest.txt").exists() and (g1dir / "g1_latest.json").exists()
   and all(p.parent == g1dir for p in g1dir.rglob("*") if p.is_file()))
s11 = json.loads(N.out_path(11).read_text())
s11_orig = copy.deepcopy(s11)
tamper = next(r for r in s11["records"] if r["ok"] and r["round"] == 0)
tamper["y"][1] += 1.0
N.out_path(11).write_text(json.dumps(s11))
rc, _ = captured(G1.main, ["--root", str(env), "--code", str(ROOT)])
bad_rows = [r for r in G1.ROWS if r["verdict"] == "FAIL"]
ok("g1_regress with a tampered stored record -> exit 1, exactly that job FAILs in G1a",
   rc == 1 and [(r["check"], r["item"]) for r in bad_rows] == [("G1a", tamper["job_id"])], str(bad_rows)[:160])
N.out_path(11).write_text(json.dumps(s11_orig))
for what, mut in (("space (L upper bound 45 -> 46)", lambda s_: s_["space"].__setitem__("L", [20.0, 46.0])),
                  ("fixed (collar_w 0 -> 1)", lambda s_: s_["fixed"].__setitem__("collar_w", 1.0)),
                  ("space key missing (h_cut)", lambda s_: s_["space"].pop("h_cut"))):
    s_m = copy.deepcopy(s11_orig)
    mut(s_m)
    N.out_path(11).write_text(json.dumps(s_m))
    rc, _ = captured(G1.main, ["--root", str(env), "--code", str(ROOT)])
    g1d = [r for r in G1.ROWS if r["item"].startswith("neckopt_p11.json space / fixed")]
    ok(f"g1_regress with neckopt_p11.json {what} != Phase(11) -> G1d FAIL ('silently drop'), exit 1",
       rc == 1 and [r["verdict"] for r in g1d] == ["FAIL"] and "silently drop" in g1d[0]["detail"], (g1d[0]["detail"] if g1d else "no row")[:140])
N.out_path(11).write_text(json.dumps(s11_orig))
rc, _ = captured(G1.main, ["--root", str(env), "--code", str(ROOT)])
ok("g1_regress after restoring neckopt_p11.json -> exit 0 again", rc == 0, f"rc {rc}")
pf.rename(pf.with_suffix(".gone"))
rc, _ = captured(G1.main, ["--root", str(env), "--code", str(ROOT)])
ok("g1_regress without the phase-11 pool file -> exit 1 (pool reuse FAIL)", rc == 1 and any(r["item"].startswith("phase-12 candidate pool")
   and r["verdict"] == "FAIL" for r in G1.ROWS))
pf.with_suffix(".gone").rename(pf)
rc, _ = captured(G1.main, ["--root", str(env_n), "--code", str(ROOT)])
ok("g1_regress on a tree whose neckopt_p11.json has no usable records -> non-zero exit", rc != 0)
J.QROOT, J.RESULTS = env / "queue", env / "results"

# ================================================================ CLI: warm --phase 12 (read-only dry run)
import runpy  # noqa: E402
_argv = sys.argv
sys.argv = ["stage_neckopt.py", "warm", "--phase", "12"]
snap_w = snapshot(env, BASE / "none")
try:
    _, out_cli = captured(runpy.run_path, str(ROOT / "v2" / "stage_neckopt.py"), run_name="__main__")
    _lines = out_cli.splitlines()
    cli = json.loads("\n".join(_lines[max(i for i, ln_ in enumerate(_lines) if ln_ == "{"):]))
except Exception as ex_:                                                     # noqa: BLE001
    cli = {"error": f"{type(ex_).__name__}: {ex_}"}
sys.argv = _argv
ok("CLI 'warm --phase 12' (restart case): prints the frozen ids and warm_from as JSON, writes nothing",
   cli.get("ids") == frozen and (cli.get("warm_from") or {}).get("phase") == 11 and snapshot(env, BASE / "none") == snap_w, str(cli)[:120])

# ================================================================ K. guard: phase 11 is phase 12's frozen warm-start source -> --warm none only
J.QROOT, J.RESULTS = env / "queue", env / "results"
N.gated_pool = no_pool
J.submit = submit_and_solve
SUBMITTED.clear()
p11_bytes, p11_mtime = N.out_path(11).read_bytes(), N.out_path(11).stat().st_mtime_ns
ok("warm_dependents: Phase(11) -> [12]; Phase(12) and Phase(10) -> []",
   N.warm_dependents(PH11) == [12] and N.warm_dependents(N.Phase(12)) == [] and N.warm_dependents(N.Phase(10)) == [])
for label, fn in (("bo_async(11, --warm family)", lambda: N.bo_async(PH11, budget=99, inflight=1, seed=0, workers=1, legacy_warm=False, n_pool=16384, poll=0.01)),
                  ("bo_async(11, --warm legacy)", lambda: N.bo_async(PH11, budget=99, inflight=1, seed=0, workers=1, legacy_warm=True, n_pool=16384, poll=0.01)),
                  ("bo(11, --warm family)", lambda: N.bo(PH11, 1, 0, 1, 0, 1, False, 16384)),
                  ("bo(11, --warm legacy)", lambda: N.bo(PH11, 1, 0, 1, 0, 1, True, 16384))):
    e = raises(ValueError, fn)
    ok(f"{label} -> ValueError naming phase 12 and '--warm none' (before gated_pool); nothing submitted; neckopt_p11.json untouched",
       e is not None and "--warm none" in e and "[12]" in e and not SUBMITTED and N.out_path(11).read_bytes() == p11_bytes
       and N.out_path(11).stat().st_mtime_ns == p11_mtime, (e or "")[:120])
e_none = raises(Exception, N.check_warm_source, PH11, None)
e_12 = raises(Exception, N.check_warm_source, N.Phase(12), False)
e_10 = raises(Exception, N.check_warm_source, N.Phase(10), True)
N.PHASES[12].pop("warm_from")
e_nowf = raises(Exception, N.check_warm_source, N.Phase(11), False)
N.PHASES[12].clear(); N.PHASES[12].update(copy.deepcopy(P12_ORIG))
ok("guard passes: phase 11 with --warm none; phase 12 with family (ignored there); phase 10 with legacy; phase 11 family once PHASES[12] has no warm_from",
   e_none is None and e_12 is None and e_10 is None and e_nowf is None, str([e_none, e_12, e_10, e_nowf])[:120])
_argv = sys.argv
sys.argv = ["stage_neckopt.py", "async", "--phase", "11", "--budget", "99"]   # a hand restart with the CLI default --warm family
try:
    captured(runpy.run_path, str(ROOT / "v2" / "stage_neckopt.py"), run_name="__main__")
    e_cli = None
except ValueError as ex_:
    e_cli = str(ex_)
except Exception as ex_:                                                     # noqa: BLE001
    e_cli = f"WRONG EXCEPTION {type(ex_).__name__}: {ex_}"
sys.argv = _argv
ok("CLI 'async --phase 11' with the default --warm family (a hand restart) -> ValueError '--warm none'; nothing submitted, state untouched",
   e_cli is not None and "--warm none" in e_cli and not SUBMITTED and N.out_path(11).read_bytes() == p11_bytes, (e_cli or "")[:100])
N.gated_pool = fake_gated

# ================================================================ L. zero feasible designs (the real 3406 segment A: 0 of 33 ok designs feasible)
WRITES = []
_real_write_state = N._write_state


def write_spy(out, state):
    WRITES.append(out.name)
    return _real_write_state(out, state)


N._write_state = write_spy
env_z = make_env("infeas")
POOL_Z = POOL.copy()
POOL_Z[:, 5] = 0.75 + 0.25 * POOL_Z[:, 5]                                  # f1 = 40 + 160 x5 >= 160 > 150 um: every pool design infeasible
LOSS_Z = loss_fn(POOL_Z)
N.gated_pool = lambda ph, n=8192, seed=0, workers=6: (POOL_Z.copy(), LOSS_Z.copy())
Z16 = rng.random(NV)
Z16[5] = 0.95                                                              # the smokes are infeasible too
zs_f = add_job(PH11, Z16, "smoke_f_h16")
zs_b = add_job(PH11, Z16, "smoke_b_h16", bonded=True)
SUBMITTED.clear(); WRITES.clear()
st_za = N.bo(PH11, n_rounds=0, n_init=6, q=1, seed=0, workers=1, legacy_warm=None, n_pool=16384, refresh_k=0)
ok("zero-feasible segment A: 6 ok round-0 records, all infeasible (c > 0); bo's save() went through _write_state",
   len(st_za["records"]) == 6 and all(r["ok"] and r["c"][0] > 0 for r in st_za["records"]) and WRITES and set(WRITES) == {"neckopt_p11.json"},
   f"{len(WRITES)} writes")


def run_logged(fn, *a, **k):
    try:
        r_, log_ = captured(fn, *a, **k)
        return r_, log_, None
    except Exception as ex_:                                                 # noqa: BLE001
        return None, "", f"{type(ex_).__name__}: {ex_}"


SUBMITTED.clear(); REFRESH_CALLS.clear(); WRITES.clear()
spies(True)
st_z11, log_z11, err_z11 = run_logged(N.bo_async, PH11, budget=16, inflight=1, seed=0, workers=1, legacy_warm=None, n_pool=16384,
                                      refresh_k=2, refresh_rad=0.05, poll=0.01)
spies(False)
fit_z11, prop_z11 = list(FIT_LOG), list(PROP_LOG)
ok("zero feasible, bo_async(11) refresh_k 2: 8 own completions (>= 6) without a crash: 16 records (6 init + 2 smokes + 8), all infeasible",
   err_z11 is None and len(st_z11["records"]) == 16 and len(SUBMITTED) == 8 and not st_z11["pending"]
   and all(r["c"][0] > 0 for r in st_z11["records"] if r["ok"]), err_z11 or "")
ok("zero feasible, bo_async(11): the empty-front refresh is skipped and logged once (at the 6th completion); refresh_pool never called",
   log_z11.count("pool refresh skipped: no feasible design yet") == 1 and REFRESH_CALLS == [], f"{REFRESH_CALLS}")
ok("zero feasible, bo_async(11): no ref point stored (state and file None), HV nan; every acquisition logged and used a temporary ref point "
   "= ref_point of all rows of that fit",
   st_z11 is not None and st_z11["ref_point"] is None and json.loads(N.out_path(11).read_text())["ref_point"] is None
   and "ref point frozen" not in log_z11 and log_z11.count("temporary ref point") == 8 and len(prop_z11) == 8
   and all(math.isnan(h["hv"]) for h in st_z11["hv_hist"])
   and all(np.array_equal(p_["ref"], N.ref_point(f_["Y"], f_["C"])) for p_, f_ in zip(prop_z11, fit_z11)),
   f"{log_z11.count('temporary ref point')} temporary lines")
ok("bo_async's save() went through _write_state; no .tmp file left in results/",
   WRITES and set(WRITES) == {"neckopt_p11.json"} and not list(J.RESULTS.glob("*.tmp")), f"{len(WRITES)} writes")

_real_Pool = N.Pool


def pool_boom(*a, **k):
    raise AssertionError("process pool started")


N.Pool = pool_boom
try:
    Ue, Le = _real_refresh(PH11, np.zeros((0, NV)), k=4, rad=0.05, workers=1, seed=0)
    Ue2, Le2 = _real_refresh(PH11, [], k=4, rad=0.05, workers=1, seed=0)
    e_rp = None
except Exception as ex_:                                                     # noqa: BLE001
    e_rp = f"{type(ex_).__name__}: {ex_}"
N.Pool = _real_Pool
ok("refresh_pool (the real one) with an empty centre set: returns (0, d) / (0,) arrays without starting a process pool",
   e_rp is None and Ue.shape == (0, NV) and Le.shape == (0,) and Ue2.shape == (0, NV) and Le2.shape == (0,), e_rp or "")

st_z11f = json.loads(N.out_path(11).read_text())
cand_z, _ = N.warm_from_select(ph12, st_z11f)
SUBMITTED.clear(); REFRESH_CALLS.clear(); WRITES.clear()
spies(True)
st_z12, log_z12, err_z12 = run_logged(N.bo_async, N.Phase(12), budget=7, inflight=1, seed=0, workers=1, legacy_warm=None, n_pool=16384,
                                      refresh_k=2, refresh_rad=0.05, poll=0.01)
spies(False)
ok("zero feasible, bo_async(12) refresh_k 2: frozen 8 infeasible warm rows, 7 own completions (>= 6) without a crash",
   err_z12 is None and st_z12["warm_start_n"] == 8 and st_z12["warm_start_ids"] == cand_z and len(st_z12["records"]) == 7
   and len(SUBMITTED) == 7 and all(j.startswith("sb12_") for j in SUBMITTED), err_z12 or "")
ok("zero feasible, bo_async(12): refresh skipped and logged once, never called; ref point None; 7 temporary ref points (3-D, all rows)",
   st_z12 is not None and log_z12.count("pool refresh skipped: no feasible design yet") == 1 and REFRESH_CALLS == []
   and st_z12["ref_point"] is None and log_z12.count("temporary ref point") == 7 and all(p_["ref"].shape == (3,) for p_ in PROP_LOG)
   and all(np.array_equal(p_["ref"], N.ref_point(f_["Y"], f_["C"])) for p_, f_ in zip(PROP_LOG, FIT_LOG)),
   f"{log_z12.count('temporary ref point')} temporary")
ok("bo_async(12)'s save() went through _write_state (neckopt_p12.json); no .tmp left", WRITES and set(WRITES) == {"neckopt_p12.json"}
   and not list(J.RESULTS.glob("*.tmp")))

FEAS_OVERRIDE[0] = True                                                     # from now on every new result is feasible
SUBMITTED.clear(); REFRESH_CALLS.clear()
spies(True)
st_z11b, log_z11b, err_z11b = run_logged(N.bo_async, PH11, budget=23, inflight=1, seed=0, workers=1, legacy_warm=None, n_pool=16384,
                                         refresh_k=2, refresh_rad=0.05, poll=0.01)
spies(False)
FEAS_OVERRIDE[0] = False
first_feas = next((r for r in (st_z11b or {}).get("records", []) if r["ok"] and r["c"][0] <= 0), None)
ok("bo_async(11) restart, first acquisition still all-infeasible -> 1 temporary ref point; its pick completes feasible -> ref point "
   "frozen at that completion (logged once), strictly worse than the only feasible row (REF_MIN_FEAS margin from all rows)",
   err_z11b is None and log_z11b.count("temporary ref point") == 1 and log_z11b.count("ref point frozen at completion 17") == 1
   and log_z11b.count("ref point frozen") == 1 and first_feas is not None and first_feas["job_id"] == SUBMITTED[0]
   and all(rp > y for rp, y in zip(st_z11b["ref_point"], first_feas["y"]))
   and json.loads(N.out_path(11).read_text())["ref_point"] == st_z11b["ref_point"], err_z11b or str((st_z11b or {}).get("ref_point")))
ok("after the freeze: the 6 later acquisitions use the frozen ref point; HV defined from the freezing completion on (nan before)",
   st_z11b is not None and len(PROP_LOG) == 7 and not np.array_equal(PROP_LOG[0]["ref"], np.array(st_z11b["ref_point"]))
   and all(np.array_equal(p_["ref"], np.array(st_z11b["ref_point"])) for p_ in PROP_LOG[1:])
   and all(math.isnan(h["hv"]) for h in st_z11b["hv_hist"][:8]) and all(not math.isnan(h["hv"]) for h in st_z11b["hv_hist"][8:])
   and len(st_z11b["hv_hist"]) == 15, f"{len(PROP_LOG)} acquisitions, {len((st_z11b or {}).get('hv_hist', []))} hv entries")
ok("with a feasible front the refresh runs again (refresh_pool called once with >= 1 centre, no skip line)",
   len(REFRESH_CALLS) == 1 and REFRESH_CALLS[0] >= 1 and "pool refresh skipped" not in log_z11b, f"{REFRESH_CALLS}")

env_zs = make_env("infeas_sync")
SUBMITTED.clear(); REFRESH_CALLS.clear(); WRITES.clear()
spies(True)
st_zs, log_zs, err_zs = run_logged(N.bo, PH11, 2, 4, 1, 0, 1, None, 16384, refresh_k=2, refresh_rad=0.05)
spies(False)
ok("zero feasible, bo(11) sync 4 init + 2 rounds with refresh_k 2: no crash; refresh skipped and logged each round, never called",
   err_zs is None and len(st_zs["records"]) == 6 and log_zs.count("pool refresh skipped: no feasible design yet") == 2 and REFRESH_CALLS == [],
   err_zs or "")
ok("zero feasible, bo(11) sync: ref point None (file too), 2 temporary ref points logged and used, HV nan; save() via _write_state",
   st_zs is not None and st_zs["ref_point"] is None and json.loads(N.out_path(11).read_text())["ref_point"] is None
   and log_zs.count("temporary ref point") == 2 and len(PROP_LOG) == 2
   and all(np.array_equal(p_["ref"], N.ref_point(f_["Y"], f_["C"])) for p_, f_ in zip(PROP_LOG, FIT_LOG))
   and all(math.isnan(h["hv"]) for h in st_zs["hv_hist"]) and set(WRITES) == {"neckopt_p11.json"} and not list(J.RESULTS.glob("*.tmp")))
N._write_state = _real_write_state
N.gated_pool = fake_gated
J.QROOT, J.RESULTS = env / "queue", env / "results"

# ================================================================ M. atomic state writes: a concurrent reader never sees a partial file
import threading  # noqa: E402

adir = BASE / "atomic"
adir.mkdir(exist_ok=True)


def concurrent_rw(writer, n_writes=120, blob=600_000):
    path = adir / "neckopt_p99.json"
    if path.exists():
        path.unlink()
    stats = {"ok": 0, "partial": 0, "open_err": 0, "missing": 0}
    st_ = {"k": -1, "blob": "x" * blob, "records": [{"job_id": f"sb99_a{i}", "y": [0.1 * i, -1000.0]} for i in range(200)]}
    writer(path, st_)
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            try:
                t_ = path.read_text()
            except FileNotFoundError:
                stats["missing"] += 1
                continue
            except PermissionError:                                          # Windows: opened while os.replace runs
                stats["open_err"] += 1
                continue
            try:
                d_ = json.loads(t_)
                if len(d_.get("blob", "")) != blob or len(d_.get("records", [])) != 200:
                    stats["partial"] += 1
                else:
                    stats["ok"] += 1
            except ValueError:
                stats["partial"] += 1

    th = threading.Thread(target=reader, daemon=True)
    th.start()
    werr = None
    try:
        for i in range(n_writes):
            st_["k"] = i
            writer(path, st_)
    except Exception as ex_:                                                 # noqa: BLE001
        werr = f"{type(ex_).__name__}: {ex_}"
    stop.set()
    th.join(10)
    final = json.loads(path.read_text())
    return stats, werr, final.get("k"), list(adir.glob("*.tmp"))


stats_a, werr_a, k_a, tmp_a = concurrent_rw(N._write_state)
stats_c, werr_c, _, _ = concurrent_rw(lambda p_, s_: p_.write_text(json.dumps(s_, indent=1, default=float)))
ok("atomic _write_state: 120 rewrites of a ~0.6 MB state with a reader thread in a loop -> 0 partial / empty reads, >= 20 full reads, "
   "last write visible, no .tmp left",
   werr_a is None and stats_a["partial"] == 0 and stats_a["ok"] >= 20 and k_a == 119 and not tmp_a,
   f"atomic {stats_a}; plain write_text control (not asserted) {stats_c}{' ' + werr_c if werr_c else ''}")

# ================================================================ fixture reset
J.submit = _real_submit
ok("fixture reset: PHASES[11] / [12] back to the module definitions", N.PHASES[11] == P11_ORIG and N.PHASES[12] == P12_ORIG)
bad = [k_ for k_, v in checks if not v]
print(f"\n{len(checks) - len(bad)}/{len(checks)} checks passed in {time.perf_counter() - T_START:.0f} s" + (f"; FAILED: {bad}" if bad else ""))
sys.exit(1 if bad else 0)
