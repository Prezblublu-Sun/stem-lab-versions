"""Run with the repo venv: PYTHONUTF8=1 .venv-mobo/Scripts/python.exe v2/tests/test_v4_phase12.py
Local only: fake queues in the system temp dir (mobo_toy_v4_tests); gated_pool / refresh_pool / stability_of / _calcar / jobs.submit are
replaced by synthetic stand-ins (submit = register + write a synthetic result.json + DONE at once); real BoTorch (mobo.fit_models / propose).
No gmsh, no FE, no Abaqus, no Linux, nothing under ~/mobo_toy_v2 is touched; single process.

metric v4 / PHASES[12] (2026-10-24, 计算计划_50h 段 C, gate G1):
A. PHASES[12] = {**PHASES[11], metric v4, pool_phase 11}; PHASES[11] untouched; Phase.n_obj (2 / 2 / 2 / 3), stage sb12; unknown metric refused.
B. objectives v4: y = [log10 max(rot, floor), -area, bone_loss.total_mm3], c identical to v3 for every record x sed form; failure -> [nan]*3;
   missing bone_loss -> not ok (templating volume is not a substitute); v3 outputs unchanged (2 entries).
C. record_of v4 on a fake job: stability computed (as for v3), y has 3 entries, bone = bone_loss.total_mm3; v3 on the same job unchanged.
D. shapes: _empty / dataset for phase 12 -> Y (n, 3); warm start = DONE sb11 jobs (own sb12 excluded, FAILED excluded), Y[:, 2] = record bone.
E. ref_point 3-D (feasible rows; all rows when none feasible); _stored_ref_point / check_state: 2-D stored ref_point with phase 12 -> clear
   ValueError (before gated_pool); space mismatch -> ignored (existing overwrite behaviour); phase-11 2-D ref passes unchanged.
F. det: det_of v1/v2 {1: pool}, v3 None, v4 {2: pool + extra}; det_extra adds X0 rows, off-pool ok records, off-pool pending with prep.json
   bone; exact values on pool points and on off-pool baseline points (where the pool-only nearest neighbour is off); on-pool records not added.
G. pool reuse: pool_source(12) == 11 when the keys agree (no key computed for phase 11), falls back to 12 when the space changes or
   pool_phase is removed; gated_pool(12) writes / reads neckopt_p11_n<n>_s<seed>_<key>.npz with the phase-11 Sobol seed (51100) and
   gated_pool(11) loads that same file; _coincident marks warm-start pool points.
H. bo_async(12) end-to-end on synthetic data (real BoTorch): 3 objectives + det index 2 + 1 constraint + pending, adoption of an sb12 DONE
   job and an sb12 READY job (prep.json bone), warm start from sb11 (3 jobs exactly on pool points -> never re-submitted), det exact at the
   baseline and pending points, pool refresh rebuilds det, bond_every counter, lengthscales rot / area / constraint, 3-D ref point, restart
   with the stored 3-D ref point, then a 2-D ref point -> ValueError.
I. bo(12) sync: init takes the first UNUSED pool points (skips warm-start pool points), one round q 2 with n_obj 3.
J. phase 11 unchanged: bo_async(11) and bo(11) with this code vs the synced HEAD 4ca6a57 (git show) on identical fake queues ->
   identical state files (minus timestamps), identical job ids / specs / live pool; plus in_family two-way sharing sb11 <-> sb12 (documented).
"""
import copy
import importlib.util
import json
import math
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

import numpy as np

ROOT = pathlib.Path(r"H:/projects/Femoral implant generation/sandbox/mobo_toy")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "v2"))
BASE = pathlib.Path(tempfile.gettempdir()) / "mobo_toy_v4_tests"          # fake queues outside the repo and outside ~/mobo_toy_v2
shutil.rmtree(BASE, ignore_errors=True)
BASE.mkdir(parents=True)

import jobs as J  # noqa: E402
import stage_neckopt as N  # noqa: E402
import mobo  # noqa: E402
import torch  # noqa: E402
from scipy.stats import qmc  # noqa: E402

REF_COMMIT = "4ca6a57"                                                     # the code synced to Linux for phase 11
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


def restore_phases():
    for p, orig in ((11, P11_ORIG), (12, P12_ORIG)):
        N.PHASES[p].clear()
        N.PHASES[p].update(copy.deepcopy(orig))


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


# ---------------------------------------------------------------- synthetic truth (deterministic in the design)
PH11 = N.Phase(11)
NV = len(PH11.vars)


def loss_fn(U):
    U = np.atleast_2d(np.asarray(U, float))
    return 4000.0 + 5000.0 * U[:, 1] + 3000.0 * U[:, 0] + 1000.0 * U[:, 7]


def truth(x):
    rot = 0.01 + 0.08 * x[0] * (1.0 - x[1]) + 0.02 * x[3]
    area = 1200.0 + 900.0 * x[2] + 300.0 * x[4]
    f1 = 40.0 + 160.0 * x[5]                                               # x5 > 0.6875 -> micromotion constraint violated
    return rot, area, f1


def x_of_job(jid):
    spec = json.loads((J.QROOT / jid / "spec.json").read_text())
    return PH11.to_unit(spec["design"], float(spec["h_cut"])), spec


def solve_fake(jid):
    x, spec = x_of_job(jid)
    rot, area, f1 = truth(x)
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
SUBMITTED, AUTO_SOLVE = [], []


def submit_and_solve(spec):
    """J.submit stand-in for the BO loops: register, then 'solve' at once; also completes the adopted in-flight jobs on the first call."""
    jid = _real_submit(spec)
    SUBMITTED.append(jid)
    solve_fake(jid)
    while AUTO_SOLVE:
        solve_fake(AUTO_SOLVE.pop())
    return jid


def add_job(ph, u, tag, stage=None, bonded=False, state="DONE", prep_bone=False):
    spec = ph.spec_of(u, tag, bonded=bonded)
    if stage:
        spec = {**spec, "stage": stage}
    jid = _real_submit(spec)
    if state == "DONE":
        solve_fake(jid)
    elif state == "FAILED":
        (J.QROOT / jid / "FAILED.json").write_text(json.dumps({"level": "L1", "stage": "prep", "reason": "fake"}))
    elif state == "READY":
        (J.QROOT / jid / "READY").write_text("x")
        if prep_bone:
            x, _ = x_of_job(jid)
            (J.QROOT / jid / "prep.json").write_text(json.dumps({"bone_loss": {"total_mm3": float(loss_fn(x)[0]), "ref_cut_mm": 16.0}}))
    return jid


rng = np.random.default_rng(11)
POOL = rng.random((300, NV))
LOSS = loss_fn(POOL)
W_OFF = rng.random((4, NV))                                                 # warm-start designs that are not pool points
ON_IDX = [0, 1, 5]                                                          # warm-start designs that ARE pool points (pool reuse)
A_DONE_U, A_PEND_U = rng.random(NV), rng.random(NV)                        # adopted sb12 jobs (off-pool)
REFRESH_CALLS = []


def fake_gated(ph, n=8192, seed=0, workers=6):
    return POOL.copy(), LOSS.copy()


def fake_refresh(ph, centres, k=64, rad=0.08, workers=6, seed=0):
    r = np.random.default_rng(seed)
    U = np.clip(np.vstack([c + r.uniform(-rad, rad, size=(k, len(ph.vars))) for c in np.atleast_2d(centres)]), 0.0, 1.0)
    REFRESH_CALLS.append(len(U))
    return U, loss_fn(U)


N.stability_of = fake_stability
N._calcar = lambda jid: (None, None)

# ================================================================ A. PHASES[12] / Phase fields
p11, p12 = N.PHASES[11], N.PHASES[12]
ok("PHASES[12] == {**PHASES[11], metric 'v4', pool_phase 11} (nothing else differs)",
   {k: v for k, v in p12.items() if k not in ("metric", "pool_phase")} == {k: v for k, v in p11.items() if k != "metric"}
   and p12["metric"] == "v4" and p12["pool_phase"] == 11 and set(p12) == set(p11) | {"pool_phase"})
ok("PHASES[11] untouched: metric v3, no pool_phase, intact_job / femur / L 20-45 / h_cut 16-32 as synced",
   p11["metric"] == "v3" and "pool_phase" not in p11 and p11["intact_job"] == "sb_intact_h2_9c9d7fb5" and p11["femur_id"] == FID
   and p11["vars"]["L"] == (20.0, 45.0) and p11["vars"]["h_cut"] == (16.0, 32.0) and p11["sed"] == "none" and p11["bond_every"] == 5)
ph12 = N.Phase(12)
ok("Phase(12): metric v4, n_obj 3, stage sb12, pool_phase 11, femur / axis / intact / bond_every / ref / amax inherited",
   ph12.metric == "v4" and ph12.n_obj == 3 and ph12.stage == "sb12" and ph12.pool_phase == 11 and ph12.femur_id == FID
   and ph12.neck_axis == "isthmus" and ph12.intact_job == IID and ph12.bond_every == 5 and ph12.ref_cut_mm == 16.0 and ph12.a_bounds_max == 2000.0
   and ph12.vars == PH11.vars and ph12.sed == "none")
ok("Phase.n_obj: phase 1 (v1) 2, 7 (v2) 2, 10 / 11 (v3) 2; pool_phase None for 10 / 11",
   N.Phase(1).n_obj == 2 and N.Phase(7).n_obj == 2 and N.Phase(10).n_obj == 2 and PH11.n_obj == 2
   and N.Phase(10).pool_phase is None and PH11.pool_phase is None)
N.PHASES[12]["metric"] = "v9"
e = raises(ValueError, N.Phase, 12)
restore_phases()
ok("Phase with an unknown metric -> ValueError", e is not None and "v9" in e, (e or "")[:80])
ok("check_launch(12) uses the inherited 3406 intact reference (spec check)", N.Phase(12).intact_job == IID)

# ================================================================ B. objectives v4 vs v3
STAB = {"rot_first_deg": 0.02, "contact_area_load2_mm2": 2000.0}
BL = {"total_mm3": 5000.0, "ref_cut_mm": 16.0}
recs_b = {"fo_ok": {"f1_p95_um": 100.0, "fric_only": True, "_stability": STAB, "bone_loss": BL},
          "fo_f1": {"f1_p95_um": 200.0, "fric_only": True, "_stability": STAB, "bone_loss": BL},
          "bd_vm": {"f1_p95_um": 100.0, "vm_p99": 500.0, "_stability": STAB, "bone_loss": BL},
          "bd_ok": {"f1_p95_um": 100.0, "vm_p99": 100.0, "_stability": STAB, "bone_loss": BL},
          "floor": {"f1_p95_um": 50.0, "fric_only": True, "_stability": {**STAB, "rot_first_deg": 1e-5}, "bone_loss": BL}}
y, c, k = N.objectives(recs_b["fo_ok"], "none", None, "v4", None)
ok("v4 fric_only: y = [log10 rot, -area, bone_loss.total_mm3], c = f1 term, ok",
   k and len(y) == 3 and abs(y[0] - math.log10(0.02)) < 1e-15 and y[1] == -2000.0 and y[2] == 5000.0 and abs(c - (100 - 150) / 150) < 1e-15, f"{y} {c}")
y, c, k = N.objectives(recs_b["floor"], "none", None, "v4", None)
ok("v4: ROT_FLOOR applies to y[0]", k and y[0] == math.log10(N.ROT_FLOOR))
same = True
for name, r in recs_b.items():
    for sed, sc in (("none", None), ("abs", -10.0), ("abs", -40.0), ("one-sided", 45.0), ("one-sided", -45.0)):
        y3, c3, k3 = N.objectives(r, sed, None, "v3", sc)
        y4, c4, k4 = N.objectives(r, sed, None, "v4", sc)
        if k3 != k4 or (k3 and (y4[:2] != y3 or c4 != c3 or y4[2] != r["bone_loss"]["total_mm3"])) or (not k3 and len(y4) != 3):
            same = False
            print("   mismatch", name, sed, sc, y3, c3, k3, y4, c4, k4)
ok("v4 vs v3 on 5 records x 5 sed forms: same ok, same c, y[:2] identical, y[2] = bone (c 'exactly as v3')", same)
nan_cases = [N.objectives(None, "none", None, "v4"), N.objectives({"failed": {}}, "none", None, "v4"),
             N.objectives({"f1_p95_um": 10.0}, "none", None, "v4")]
ok("v4 failure / empty / no stability -> y = [nan]*3, c nan, ok False",
   all(len(t[0]) == 3 and all(math.isnan(v) for v in t[0]) and math.isnan(t[1]) and not t[2] for t in nan_cases))
nb = {k_: v for k_, v in recs_b["fo_ok"].items() if k_ != "bone_loss"}
ok("v4 without bone_loss -> not ok, [nan]*3 (templating volume is NOT used as bone); the same record is ok under v3",
   not N.objectives({**nb, "templating": {"volume": 3000.0}}, "none", None, "v4")[2]
   and len(N.objectives(nb, "none", None, "v4")[0]) == 3 and N.objectives(nb, "none", None, "v3")[2])
ok("v4 bonded record without vm_p99 still not ok (as v3)", not N.objectives({"f1_p95_um": 100.0, "_stability": STAB, "bone_loss": BL}, "none", None, "v4")[2])
y, c, k = N.objectives(recs_b["fo_ok"], "none", None, "v3", None)
ok("v3 output unchanged: 2 entries [log10 rot, -area], failure -> 2 nans",
   k and y == [math.log10(0.02), -2000.0] and len(N.objectives(None, "none", None, "v3")[0]) == 2)

# ================================================================ C. record_of v4 on a fake job
make_env("rec")
jid_r = add_job(PH11, np.full(NV, 0.4), "r0")
STAB_CALLS = []
N.stability_of = lambda j: STAB_CALLS.append(j) or fake_stability(j)
rec4 = N.record_of(jid_r, "none", "v4")
rec3 = N.record_of(jid_r, "none", "v3")
N.stability_of = fake_stability
x_r, _ = x_of_job(jid_r)
rot_r, area_r, f1_r = truth(x_r)
ok("record_of(v4): stability computed (called for v4 as for v3), y = [log10 rot, -area, bone], metric v4, bone_mm3 = y[2]",
   STAB_CALLS == [jid_r, jid_r] and rec4["ok"] and len(rec4["y"]) == 3 and abs(rec4["y"][0] - math.log10(rot_r)) < 1e-12
   and abs(rec4["y"][1] + area_r) < 1e-9 and rec4["y"][2] == rec4["bone_mm3"] == float(loss_fn(x_r)[0]) and rec4["metric"] == "v4"
   and rec4["rot_first_deg"] == rot_r, json.dumps(rec4["y"]))
ok("record_of(v3) on the same job: y = rec4.y[:2], same c, same extras", rec3["y"] == rec4["y"][:2] and rec3["c"] == rec4["c"]
   and {k_: v for k_, v in rec3.items() if k_ not in ("y", "metric")} == {k_: v for k_, v in rec4.items() if k_ not in ("y", "metric")})

# ================================================================ D. _empty / dataset shapes
make_env("ds")
X0e, Y0e, C0e, ids_e = N._empty(ph12)
ok("_empty(12): X (0, 13), Y (0, 3), C (0, 1); _empty(11): Y (0, 2)",
   X0e.shape == (0, NV) and Y0e.shape == (0, 3) and C0e.shape == (0, 1) and N._empty(PH11)[1].shape == (0, 2))
X, Y, C, ids = N.dataset(ph12)
ok("dataset(12) on an empty queue: Y (0, 3)", Y.shape == (0, 3) and X.shape == (0, NV))
w_ids = [add_job(PH11, W_OFF[i], f"w{i}", bonded=(i == 3)) for i in range(4)]
w_on = [add_job(PH11, POOL[i], f"p{i}") for i in ON_IDX]
add_job(PH11, rng.random(NV), "wf", state="FAILED")
own12 = add_job(ph12, rng.random(NV), "own")
X, Y, C, ids = N.dataset(ph12)
ok("dataset(12): the 7 DONE sb11 jobs (incl. one bonded) are the warm start; own sb12 and FAILED excluded; Y (7, 3), C (7, 1)",
   sorted(ids) == sorted(w_ids + w_on) and own12 not in ids and X.shape == (7, NV) and Y.shape == (7, 3) and C.shape == (7, 1), str(ids))
ok("dataset(12): Y[:, 2] = each record's bone_loss.total_mm3 (exact)",
   all(Y[i, 2] == json.loads((J.QROOT / j / "result.json").read_text())["bone_loss"]["total_mm3"] for i, j in enumerate(ids)))
ok("stack-style vstack of the (0, 3) empty warm start with 3-entry records works (np.vstack shape (2, 3))",
   np.vstack([Y0e] + [np.array([1.0, -2.0, 3.0])[None], np.array([0.5, -1.0, 2.0])[None]]).shape == (2, 3))
X11, Y11, C11, ids11 = N.dataset(PH11)
ok("dataset(11) (two-way sharing, documented): sb12 DONE job is a phase-11 warm start, Y (n, 2)",
   own12 in ids11 and Y11.shape[1] == 2 and not any(i in ids11 for i in w_ids), str(ids11))

# ================================================================ E. ref_point 3-D and stored-ref checks
Y3 = np.array([[0.0, -10.0, 100.0], [1.0, -20.0, 50.0], [2.0, -5.0, 300.0], [-1.0, -30.0, 10.0]])
C3 = np.array([[-1.0], [-0.5], [-0.1], [0.5]])
rp = N.ref_point(Y3, C3)
ok("ref_point 3-D: hi + 0.1 (hi - lo) over the feasible rows only", rp.shape == (3,) and np.allclose(rp, [2.2, -3.5, 325.0]), str(rp))
rp_all = N.ref_point(Y3, np.ones((4, 1)))
ok("ref_point 3-D with no feasible row: over all rows", np.allclose(rp_all, [2.3, -2.5, 329.0]), str(rp_all))
sp = {k_: list(v) for k_, v in ph12.space.items()}
ok("_stored_ref_point: 3-D for phase 12 passes; 2-D for phase 11 passes and equals np.array(stored)",
   np.array_equal(N._stored_ref_point(ph12, {"ref_point": [1.0, 2.0, 3.0]}), [1.0, 2.0, 3.0])
   and np.array_equal(N._stored_ref_point(PH11, {"ref_point": [-0.0833, -162.03]}), np.array([-0.0833, -162.03]))
   and N._stored_ref_point(ph12, {"ref_point": None}) is None and N._stored_ref_point(ph12, {}) is None)
e = raises(ValueError, N._stored_ref_point, ph12, {"ref_point": [-0.08, -162.0]})
ok("_stored_ref_point: 2-D stored with phase 12 -> ValueError naming ref_point, dims and the 3 objectives",
   e is not None and "ref_point" in e and "3 objectives" in e and "v4" in e, (e or "")[:140])
e = raises(ValueError, N._stored_ref_point, PH11, {"ref_point": [1.0, 2.0, 3.0]})
ok("_stored_ref_point: 3-D stored with phase 11 -> ValueError too (any mismatch)", e is not None and "2 objectives" in e)
N.out_path(12).write_text(json.dumps({"space": sp, "fixed": ph12.fixed, "ref_point": [-0.08, -162.0], "records": []}))
ok("check_state(12) with a 2-D stored ref_point (same space / fixed) -> ValueError", raises(ValueError, N.check_state, ph12) is not None)
N.out_path(12).write_text(json.dumps({"space": {**sp, "L": [20.0, 60.0]}, "fixed": ph12.fixed, "ref_point": [-0.08, -162.0], "records": []}))
ok("check_state(12): state with another space is not reused -> no error (existing overwrite behaviour)", N.check_state(ph12) is None)
N.out_path(12).unlink()
ok("check_state without a state file -> no-op", N.check_state(ph12) is None)

# ================================================================ F. det_of / det_extra
d10, d11, d7 = N.det_of(N.Phase(10), POOL, LOSS), N.det_of(PH11, POOL, LOSS), N.det_of(N.Phase(7), POOL, LOSS)
ok("det_of: v3 (phases 10 / 11) -> None; v2 (phase 7) -> {1: ...}", d10 is None and d11 is None and list(d7) == [1])
Q = np.vstack([POOL[:20], W_OFF, rng.random((10, NV))])
base_fn = N.det_loss_fn(POOL, LOSS)
v7 = d7[1](torch.as_tensor(Q)).numpy()
ok("det_of(v2) == det_loss_fn(pool, loss) on pool and off-pool queries (v1 / v2 unchanged), extras ignored for v2",
   np.array_equal(v7, base_fn(torch.as_tensor(Q)).numpy()) and N.det_extra(N.Phase(7), POOL, W_OFF, np.zeros((4, 2)), [], {}) is None)
ok("det_extra(11) -> None (v3 has no det)", N.det_extra(PH11, POOL, W_OFF, np.zeros((4, 2)), [], {}) is None)
X0f = np.vstack([W_OFF, POOL[ON_IDX] + 1e-13])                          # 1e-13 off a pool point (< _coincident tol)
B0f = loss_fn(X0f) + np.arange(len(X0f)) * 0.125                          # 'record' bone values, deliberately != pool NN values
Y0f = np.c_[np.zeros(len(X0f)), -np.ones(len(X0f)), B0f]
u_adopt, u_bad = rng.random(NV), rng.random(NV)
recs_f = [{"ok": True, "pool_idx": 7, "x": POOL[7].tolist(), "y": [0.0, -1.0, float(LOSS[7])]},              # own pool record
          {"ok": True, "pool_idx": None, "x": u_adopt.tolist(), "y": [0.0, -1.0, 7777.0]},                   # adopted, off-pool
          {"ok": False, "pool_idx": None, "x": u_bad.tolist(), "y": [math.nan] * 3},                         # failed: not baseline
          {"ok": True, "pool_idx": 9999, "x": rng.random(NV).tolist(), "y": [0.0, -1.0, 8888.0]}]           # stale pool_idx -> off-pool
make_env("det")
jp = add_job(ph12, A_PEND_U, "pd", state="READY", prep_bone=True)
jnp = add_job(ph12, rng.random(NV), "pn", state="READY", prep_bone=False)
x_jp, _ = x_of_job(jp)
pend_f = {jp: {"pool_idx": None, "x": x_jp.tolist()}, jnp: {"pool_idx": None, "x": x_of_job(jnp)[0].tolist()},
          "sb12_own_x": {"pool_idx": 11, "x": POOL[11].tolist()}}
ex = N.det_extra(ph12, POOL, X0f, Y0f, recs_f, pend_f)
ok("det_extra(12): 7 X0 rows + adopted off-pool record + stale-index record + pending with prep.json = 10 rows; on-pool record, "
   "failed record, own pool pending and pending without prep.json not added",
   ex[0].shape == (10, NV) and np.array_equal(ex[1][:7], B0f) and list(ex[1][7:9]) == [7777.0, 8888.0]
   and ex[1][9] == float(loss_fn(x_jp)[0]) and not any(np.array_equal(r_, POOL[7]) for r_ in ex[0]), str(ex[1][7:]))
dd = N.det_of(ph12, POOL, LOSS, ex)
ok("det_of(12): {2: ...}", list(dd) == [2])
f2 = dd[2]
vp = f2(torch.as_tensor(POOL)).numpy()
ok("det v4: exact pool_loss on every pool point (candidates)", np.array_equal(vp, LOSS))
vx = f2(torch.as_tensor(X0f)).numpy()
ok("det v4: exact record bone on every warm-start baseline row (incl. rows 1e-13 off a pool point)", np.array_equal(vx, B0f), str(vx - B0f))
vnn = base_fn(torch.as_tensor(W_OFF)).numpy()
ok("det v4: the pool-only nearest neighbour would be off at the off-pool rows (|err| > 50 mm3 each) — the fix matters",
   np.all(np.abs(vnn - B0f[:4]) > 50.0), str(np.round(vnn - B0f[:4], 1)))
ok("det v4: adopted record x -> its record bone; pending x -> prep.json bone",
   f2(torch.as_tensor(u_adopt[None])).item() == 7777.0 and f2(torch.as_tensor(x_jp[None])).item() == float(loss_fn(x_jp)[0]))
Zb = torch.as_tensor(np.stack([X0f[:3], POOL[:3]]))                         # batch shape (2, 3, d) as NEHVI sends
ok("det v4 keeps batch shapes (2, 3, d) -> (2, 3)", tuple(f2(Zb).shape) == (2, 3))
ok("det_of(12) with an empty extra table == pool-only", np.array_equal(N.det_of(ph12, POOL, LOSS, (np.zeros((0, NV)), np.zeros(0)))[2](torch.as_tensor(Q)).numpy(),
                                                                       base_fn(torch.as_tensor(Q)).numpy()))
ok("_on_pool: exact index + exact coordinates only", N._on_pool(POOL, 7, POOL[7].tolist()) and not N._on_pool(POOL, None, POOL[7])
   and not N._on_pool(POOL, 9999, POOL[7]) and not N._on_pool(POOL, 7, POOL[8]))
m = N._coincident(POOL, np.vstack([POOL[ON_IDX] + 1e-13, W_OFF]))
ok("_coincident marks exactly the pool points hit by X rows (tol 1e-9)", set(np.nonzero(m)[0]) == set(ON_IDX) and not N._coincident(POOL, np.zeros((0, NV))).any())

# ================================================================ G. pool reuse (pool_source / gated_pool)
make_env("pool")
_real_feasible, _real_pool_cls = N._feasible, N.Pool


class SerialPool:
    def __init__(self, n):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def map(self, f, it, chunksize=1):
        return [f(x) for x in it]


FEAS_PHASES = []


def fake_feasible(args):
    u, phase, ref = args
    FEAS_PHASES.append(phase)
    okf = bool(u[0] < 0.7)
    return okf, (float(loss_fn(u)[0]) if okf else math.nan)


N._feasible, N.Pool = fake_feasible, SerialPool
k11, k12 = N.pool_key(PH11, 16, 0), N.pool_key(ph12, 16, 0)
ok("pool_key(12) == pool_key(11) (metric is not a pool key field)", k11 == k12, f"{k11} {k12}")
_real_pool_key = N.pool_key
N.pool_key = lambda *a, **k: (_ for _ in ()).throw(AssertionError("pool_key computed for a phase without pool_phase"))
src11 = N.pool_source(PH11, 16, 0)
N.pool_key = _real_pool_key
ok("pool_source(11) == 11 without computing any key (phase 11 path untouched)", src11 == 11)
ok("pool_source(12) == 11 (keys agree)", N.pool_source(ph12, 16, 0) == 11)
U12, L12 = N.gated_pool(ph12, n=16, seed=0, workers=1)
f11 = J.RESULTS / "pools" / f"neckopt_p11_n16_s0_{k11}.npz"
Uref = qmc.Sobol(NV, scramble=True, seed=50_000 + 100 * 11 + 0).random(16)
keep = Uref[:, 0] < 0.7
pj = json.loads(f11.with_suffix(".json").read_text())
ok("gated_pool(12) under reuse: writes neckopt_p11_n16_s0_<key>.npz from the phase-11 Sobol stream (seed 51100), json phase 11",
   f11.exists() and np.array_equal(U12, Uref[keep]) and np.allclose(L12, loss_fn(Uref[keep])) and pj["phase"] == 11
   and not list((J.RESULTS / "pools").glob("neckopt_p12_*")), f"{sorted(p.name for p in (J.RESULTS / 'pools').iterdir())}")
FEAS_PHASES.clear()
U11, L11 = N.gated_pool(PH11, n=16, seed=0, workers=1)
ok("gated_pool(11) then loads that same file (no templating, identical arrays)", not FEAS_PHASES and np.array_equal(U11, U12) and np.array_equal(L11, L12))
N.PHASES[12]["vars"] = {**N.PHASES[12]["vars"], "L": (20.0, 44.0)}
ph12b = N.Phase(12)
ok("pool_source(12) with a changed space -> 12 (own pool)", N.pool_source(ph12b, 16, 0) == 12)
Ub, _ = N.gated_pool(ph12b, n=16, seed=0, workers=1)
Uref12 = qmc.Sobol(NV, scramble=True, seed=50_000 + 100 * 12 + 0).random(16)
ok("... gated_pool then builds neckopt_p12_n16_s0_<own key>.npz with the phase-12 seed (51200)",
   (J.RESULTS / "pools" / f"neckopt_p12_n16_s0_{N.pool_key(ph12b, 16, 0)}.npz").exists() and np.array_equal(Ub, Uref12[Uref12[:, 0] < 0.7]))
restore_phases()
del N.PHASES[12]["pool_phase"]
ok("PHASES[12] without pool_phase -> own pool (seed rule 50000 + 100*12 + seed)", N.pool_source(N.Phase(12), 16, 0) == 12)
restore_phases()
N._feasible, N.Pool = _real_feasible, _real_pool_cls

# ================================================================ H. bo_async(12) end-to-end (real BoTorch)
FIT_LOG, PROP_LOG, DET_LOG = [], [], []
_real_fit, _real_prop, _real_det_of = mobo.fit_models, mobo.propose, N.det_of


def fit_spy(X, Y, C, noise_sd=None, det=None):
    FIT_LOG.append({"X": np.array(X), "Y": np.array(Y), "C": np.array(C), "det": None if det is None else sorted(det)})
    return _real_fit(X, Y, C, noise_sd, det)


def prop_spy(model, X_obs, ref_min, pool, q, n_obj, n_con, seed, X_pending=None):
    t0 = time.perf_counter()
    out = _real_prop(model, X_obs, ref_min, pool, q, n_obj, n_con, seed, X_pending=X_pending)
    PROP_LOG.append({"n_obj": n_obj, "n_con": n_con, "q": q, "ref": np.array(ref_min), "Xp": None if X_pending is None else np.array(X_pending),
                     "n_cand": len(pool), "s": time.perf_counter() - t0, "models": len(model.models)})
    return out


def det_spy(ph, pool, pool_loss, extra=None):
    d = _real_det_of(ph, pool, pool_loss, extra)
    DET_LOG.append({"pool": np.array(pool), "loss": np.array(pool_loss), "extra": None if extra is None else (np.array(extra[0]), np.array(extra[1])), "det": d})
    return d


def spies(on):
    mobo.fit_models, mobo.propose, N.det_of = (fit_spy, prop_spy, det_spy) if on else (_real_fit, _real_prop, _real_det_of)


make_env("async12")
w_ids = [add_job(PH11, W_OFF[i], f"w{i}", bonded=(i == 3)) for i in range(4)]
w_on = [add_job(PH11, POOL[i], f"p{i}") for i in ON_IDX]
add_job(PH11, rng.random(NV), "wf", state="FAILED")
a_done = add_job(ph12, A_DONE_U, "x0")
a_pend = add_job(ph12, A_PEND_U, "x1", state="READY", prep_bone=True)
x_ad, _ = x_of_job(a_done)
x_ap, _ = x_of_job(a_pend)
SUBMITTED.clear(); AUTO_SOLVE[:] = [a_pend]; REFRESH_CALLS.clear()
N.gated_pool, N.refresh_pool, J.submit = fake_gated, fake_refresh, submit_and_solve
spies(True)
t0 = time.perf_counter()
st = N.bo_async(ph12, budget=9, inflight=2, seed=0, workers=1, legacy_warm=False, n_pool=16384, refresh_k=3, refresh_rad=0.05, poll=0.01)
t_async = time.perf_counter() - t0
spies(False)
print(f"   bo_async(12): {t_async:.1f} s, {len(PROP_LOG)} acquisitions, propose s = {[round(p['s'], 1) for p in PROP_LOG]}", flush=True)
ok("bo_async(12): 7 submissions (budget 9 = 2 adopted + 7), all staged sb12, 9 records, nothing pending",
   len(SUBMITTED) == 7 and all(j.startswith("sb12_a") for j in SUBMITTED) and len(st["records"]) == 9 and st["pending"] == {})
ok("first fit: X = 7 warm rows + adopted DONE record, Y (8, 3), C (8, 1), det index [2]",
   FIT_LOG[0]["X"].shape == (8, NV) and FIT_LOG[0]["Y"].shape == (8, 3) and FIT_LOG[0]["C"].shape == (8, 1) and FIT_LOG[0]["det"] == [2])
ok("every fit: Y has 3 columns and det [2]; ModelList with 4 outputs (rot GP, area GP, det, constraint GP)",
   all(f["Y"].shape[1] == 3 and f["det"] == [2] for f in FIT_LOG) and all(p["models"] == 4 for p in PROP_LOG))
ok("every propose: n_obj 3, n_con 1, q 1; ref point 3-D", all(p["n_obj"] == 3 and p["n_con"] == 1 and p["q"] == 1 and p["ref"].shape == (3,) for p in PROP_LOG))
ok("first propose: X_pending = the adopted READY job's x; later proposes carry 1 own pending point",
   PROP_LOG[0]["Xp"] is not None and len(PROP_LOG[0]["Xp"]) == 1 and np.allclose(PROP_LOG[0]["Xp"][0], x_ap)
   and any(p["Xp"] is not None and len(p["Xp"]) == 1 and not np.allclose(p["Xp"][0], x_ap) for p in PROP_LOG[1:]))
d0 = DET_LOG[0]
f0 = d0["det"][2]
Xb0 = FIT_LOG[0]["X"]
Yb0 = FIT_LOG[0]["Y"]
ok("first det: extra = 7 warm rows + adopted DONE record + adopted READY (prep.json) = 9 rows", d0["extra"][0].shape == (9, NV), str(d0["extra"][0].shape))
ok("first det: exact bone on all 8 baseline rows (= Y[:, 2] of the fit) and exact pool_loss on all pool points",
   np.array_equal(f0(torch.as_tensor(Xb0)).numpy(), Yb0[:, 2]) and np.array_equal(f0(torch.as_tensor(POOL)).numpy(), LOSS))
ok("first det: pending x -> prep.json bone (exact)", f0(torch.as_tensor(x_ap[None])).item() == float(loss_fn(x_ap)[0]))
recs12 = st["records"]
own = [r for r in recs12 if r["job_id"] in SUBMITTED]
ok("warm-start pool points 0 / 1 / 5 never submitted (reuse marks them used); every own record is a pool point with a valid pool_idx",
   all(r["pool_idx"] not in ON_IDX for r in own) and all(r["pool_idx"] is not None for r in own) and len(own) == 7
   and all(np.array_equal(np.array(r["x"]), DET_LOG[-1]["pool"][r["pool_idx"]]) for r in own))
ok("adopted records: sb12 DONE (round -1, pool_idx None) and the READY one completed later (pool_idx None)",
   {r["job_id"]: r["pool_idx"] for r in recs12 if r["job_id"] in (a_done, a_pend)} == {a_done: None, a_pend: None})
ok("records: every ok record has 3 objectives and metric v4; y[2] == bone_mm3", all(len(r["y"]) == 3 and r["metric"] == "v4" for r in recs12)
   and all(r["y"][2] == r["bone_mm3"] for r in recs12 if r["ok"]))
ok("pool refresh happened once (+3 per front point), live pool saved, and the next det used the larger pool",
   len(REFRESH_CALLS) == 1 and st["pool_size"] == 300 + REFRESH_CALLS[0] and len(DET_LOG[-1]["pool"]) == st["pool_size"]
   and (J.RESULTS / "neckopt_p12_pool_live.npz").exists(), f"{REFRESH_CALLS} {st['pool_size']}")
fl = DET_LOG[-1]["det"][2]
ok("last det: exact on the refreshed pool too", np.array_equal(fl(torch.as_tensor(DET_LOG[-1]["pool"])).numpy(), DET_LOG[-1]["loss"]))
specs = {j: json.loads((J.QROOT / j / "spec.json").read_text()) for j in SUBMITTED}
bonded = [j for j in SUBMITTED if not specs[j].get("fric_only")]
ok("bond_every 5: counter starts at 2 (adopted), the 3rd submission (#5) is bonded with intact_job; n_submitted 9",
   bonded == [SUBMITTED[2]] and specs[SUBMITTED[2]].get("intact_job") == IID and st["n_submitted"] == 9, str(bonded))
ls = st["lengthscales"]
ok("lengthscales (v4): rot / area / constraint dicts over the 13 vars, no det entry",
   len(ls) == 7 and all(set(v) == {"rot", "area", "constraint"} and all(isinstance(v[k_], dict) and len(v[k_]) == NV for k_ in v) for v in ls.values()))
ok("ref_point 3-D stored = ref_point(warm + adopted at the first acquisition); hv_hist finite",
   len(st["ref_point"]) == 3 and np.allclose(st["ref_point"], N.ref_point(Yb0, FIT_LOG[0]["C"])) and all(np.isfinite(h["hv"]) for h in st["hv_hist"]))
ok("state file: stage sb12, warm_start_n 7, no new keys for the formulation (records carry metric v4)",
   json.loads(N.out_path(12).read_text())["stage"] == "sb12" and st["warm_start_n"] == 7 and "metric" not in st and "n_obj" not in st)
# restart with the stored 3-D ref point (no submissions left)
n_before = len(list(J.QROOT.iterdir()))
SUBMITTED.clear()
spies(True); FIT_LOG.clear()
st2 = N.bo_async(ph12, budget=9, inflight=2, seed=0, workers=1, legacy_warm=False, n_pool=16384, refresh_k=3, refresh_rad=0.05, poll=0.01)
spies(False)
ok("restart bo_async(12): stored 3-D ref point reused, 9 records re-scored, nothing submitted, no fit",
   st2["ref_point"] == st["ref_point"] and len(st2["records"]) == 9 and not SUBMITTED and not FIT_LOG and len(list(J.QROOT.iterdir())) == n_before)
import contextlib  # noqa: E402
import io  # noqa: E402
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    N.status(12)
lines = [ln_ for ln_ in buf.getvalue().splitlines() if ln_.startswith("  rot ")]
n_feas = sum(1 for r in st2["records"] if r["ok"] and r["c"][0] <= 0)
ok("status(12) prints the v4 rows (rot, contact, bone = y[2], h_cut) for the feasible records",
   len(lines) == min(8, n_feas) and all(" bone " in ln_ and " h_cut " in ln_ for ln_ in lines), (lines[0] if lines else "")[:120])
s_ = json.loads(N.out_path(12).read_text())
s_["ref_point"] = s_["ref_point"][:2]
N.out_path(12).write_text(json.dumps(s_))
N.gated_pool = lambda *a, **k: (_ for _ in ()).throw(AssertionError("gated_pool reached"))
e_a = raises(ValueError, N.bo_async, ph12, 9, 2, 0, 1, False)
e_s = raises(ValueError, N.bo, ph12, 1, 0, 1, 0, 1, False)
ok("2-D stored ref_point with phase 12 -> bo_async and bo raise ValueError before gated_pool (clear message)",
   e_a is not None and "ref_point" in e_a and "3 objectives" in e_a and e_s is not None and "ref_point" in e_s, (e_a or "")[:160])
N.gated_pool = fake_gated

# ================================================================ I. bo(12) sync: init skips warm-start pool points
make_env("sync12")
for i in range(2):
    add_job(PH11, W_OFF[i], f"w{i}")
for i in (0, 1):
    add_job(PH11, POOL[i], f"p{i}")
SUBMITTED.clear(); FIT_LOG.clear(); PROP_LOG.clear(); DET_LOG.clear()
spies(True)
st_s = N.bo(ph12, n_rounds=1, n_init=2, q=2, seed=0, workers=1, legacy_warm=False, n_pool=16384, refresh_k=0)
spies(False)
init = [r for r in st_s["records"] if r["round"] == 0]
r1 = [r for r in st_s["records"] if r["round"] == 1]
ok("bo(12) init under pool reuse: the first 2 UNUSED pool points (2, 3), not the warm-start points 0 / 1",
   [r["pool_idx"] for r in init] == [2, 3], str([r["pool_idx"] for r in init]))
ok("bo(12) round 1: one propose with n_obj 3, q 2, det [2]; 2 new pool points not in {0, 1, 2, 3}; records y 3-D; ref 3-D",
   len(PROP_LOG) == 1 and PROP_LOG[0]["n_obj"] == 3 and PROP_LOG[0]["q"] == 2 and FIT_LOG[0]["det"] == [2] and len(r1) == 2
   and not ({r["pool_idx"] for r in r1} & {0, 1, 2, 3}) and all(len(r["y"]) == 3 for r in st_s["records"]) and len(st_s["ref_point"]) == 3)
ok("bo(12) det: the 4 warm rows are in the extra table with exact bone; init records (pool points) from the pool", DET_LOG[0]["extra"][0].shape == (4, NV)
   and np.array_equal(DET_LOG[0]["det"][2](torch.as_tensor(FIT_LOG[0]["X"][:4])).numpy(), FIT_LOG[0]["Y"][:4, 2])
   # own init records are pool points: the pool value (the fake solver re-derives x via to_unit, so equal to ~1e-12 only)
   and np.allclose(DET_LOG[0]["det"][2](torch.as_tensor(FIT_LOG[0]["X"][4:])).numpy(), FIT_LOG[0]["Y"][4:, 2], rtol=1e-12, atol=0))

# ================================================================ J. phase 11 unchanged vs the synced code (HEAD 4ca6a57)
ref_dir = BASE / f"ref_{REF_COMMIT}"
ref_dir.mkdir()
OLD = None
try:
    src = subprocess.run(["git", "-C", str(ROOT), "show", f"{REF_COMMIT}:v2/stage_neckopt.py"], capture_output=True, check=True).stdout
    (ref_dir / f"stage_neckopt_{REF_COMMIT}.py").write_bytes(src)
    spec_ = importlib.util.spec_from_file_location(f"stage_neckopt_{REF_COMMIT}", ref_dir / f"stage_neckopt_{REF_COMMIT}.py")
    OLD = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(OLD)
except Exception as ex_:                                                    # noqa: BLE001
    print(f"   cannot load {REF_COMMIT}: {type(ex_).__name__}: {ex_}", flush=True)
ok(f"reference module stage_neckopt @ {REF_COMMIT} loaded (git show)", OLD is not None and 12 not in OLD.PHASES and OLD.PHASES[11] == P11_ORIG)


def scrub(st_):
    st_ = json.loads(json.dumps(st_, default=float))
    st_.pop("updated", None)
    for h in st_.get("hv_hist", []):
        h.pop("time", None)
    for p_ in st_.get("pending", {}).values():
        p_.pop("submitted", None)
    return st_


def queue_view():
    out = {}
    for d in sorted(J.QROOT.iterdir()):
        sp_ = json.loads((d / "spec.json").read_text())
        sp_.pop("created", None)
        out[d.name] = (sp_, (d / "result.json").read_text() if (d / "result.json").exists() else None, J.state(d))
    return out


def run_p11(mod, env, mode):
    make_env(env)
    for i in range(4):
        add_job(PH11, W_OFF[i], f"w{i}", stage="sb10", bonded=(i == 3))
    add_job(PH11, A_DONE_U, "x0")                                             # sb11 adopted DONE
    jr = add_job(PH11, A_PEND_U, "x1", state="READY", prep_bone=True)          # sb11 adopted in flight
    SUBMITTED.clear(); AUTO_SOLVE[:] = [jr]; REFRESH_CALLS.clear()
    mod.gated_pool, mod.refresh_pool, mod.stability_of, mod._calcar = fake_gated, fake_refresh, fake_stability, (lambda j: (None, None))
    J.submit = submit_and_solve
    if mode == "async":
        mod.bo_async(mod.Phase(11), budget=8, inflight=2, seed=0, workers=1, legacy_warm=False, n_pool=16384, refresh_k=3, refresh_rad=0.05, poll=0.01)
    else:
        for j in (jr,):                                                       # bo() does not adopt: finish the in-flight job first
            solve_fake(j)
        AUTO_SOLVE.clear()
        mod.bo(mod.Phase(11), n_rounds=2, n_init=3, q=1, seed=0, workers=1, legacy_warm=False, n_pool=16384, refresh_k=2, refresh_rad=0.05)
    live = J.RESULTS / "neckopt_p11_pool_live.npz"
    z = np.load(live) if live.exists() else None
    return scrub(json.loads(N.out_path(11).read_text())), queue_view(), (None if z is None else (z["U"].copy(), z["loss"].copy())), list(SUBMITTED)


if OLD is not None:
    for mode in ("async", "sync"):
        t0 = time.perf_counter()
        s_old, q_old, l_old, sub_old = run_p11(OLD, f"p11_{mode}_old", mode)
        s_new, q_new, l_new, sub_new = run_p11(N, f"p11_{mode}_new", mode)
        diff = sorted(k_ for k_ in set(s_old) | set(s_new) if s_old.get(k_) != s_new.get(k_))
        ok(f"phase 11 {mode}: state file identical to {REF_COMMIT} (minus timestamps): {len(s_new['records'])} records, ref {s_new['ref_point']}",
           not diff and len(sub_new) > 0, f"differing keys {diff}")
        ok(f"phase 11 {mode}: same job ids, specs, results and states in the queue; same submissions; same live pool",
           q_old == q_new and sub_old == sub_new and ((l_old is None and l_new is None) or (l_old is not None and l_new is not None
                                                                                          and all(np.array_equal(a_, b_) for a_, b_ in zip(l_old, l_new)))),
           f"{len(q_new)} dirs, {len(sub_new)} submitted, {time.perf_counter() - t0:.0f} s")
        ok(f"phase 11 {mode}: records have 2 objectives, metric v3, lengthscales labelled micromotion / constraint",
           all(len(r["y"]) == 2 and r["metric"] == "v3" for r in s_new["records"])
           and all(set(v) == {"micromotion", "constraint"} for v in s_new["lengthscales"].values()))
J.submit = _real_submit
N.gated_pool = fake_gated

# ---------------------------------------------------------------- in_family two-way sharing (documented)
s11 = PH11.spec_of(np.full(NV, 0.5), "a0", bonded=False)
s12 = ph12.spec_of(np.full(NV, 0.5), "a0", bonded=False)
ok("in_family: phase 12 accepts sb11 specs and phase 11 accepts sb12 specs (two-way warm start, documented); specs differ only in stage",
   ph12.in_family(s11) and PH11.in_family(s12) and {k_: v for k_, v in s11.items() if k_ != "stage"} == {k_: v for k_, v in s12.items() if k_ != "stage"}
   and s12["stage"] == "sb12" and J.job_id(s11) != J.job_id(s12))
restore_phases()
ok("fixture reset: PHASES[11] / [12] back to the module definitions", N.PHASES[11] == P11_ORIG and N.PHASES[12] == P12_ORIG)

bad = [k_ for k_, v in checks if not v]
print(f"\n{len(checks) - len(bad)}/{len(checks)} checks passed in {time.perf_counter() - T_START:.0f} s" + (f"; FAILED: {bad}" if bad else ""))
sys.exit(1 if bad else 0)
