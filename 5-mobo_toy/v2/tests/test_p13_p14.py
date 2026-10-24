"""Run with the repo venv: PYTHONUTF8=1 .venv-mobo/Scripts/python.exe v2/tests/test_p13_p14.py
Local only: fake queues in the system temp dir (mobo_toy_p13_tests); gated_pool / refresh_pool / stability_of / _calcar / jobs.submit are
replaced by synthetic stand-ins (submit = register + write a synthetic result.json + DONE at once); real BoTorch (mobo.fit_models /
propose). No gmsh, no FE, no Abaqus, no Linux, nothing under ~/mobo_toy_v2 is touched; single process.

Phases 13 / 14 (user 2026-10-24 12:20 'continue as you suggest'): Sawbones 3406, provisional cancellous interference delta 0.10 mm, full
stair load, designs ranked (2-obj rotation x fully-closed contact; 3-obj + bone removal); the 150 um micromotion limit is NOT a constraint on
the 3406 foam phases (PHASES[p]['mm_limit'] None: micromotion recorded and reported only).
A. definitions: PHASES[13] = {**PHASES[11], fric delta 0.10, pool_phase 11, mm_limit None}, PHASES[14] = {**PHASES[13], metric v4,
   warm_from {13, [0, -1]}}; Phase fields (stage sb13 / sb14, fric, mm_limit, n_obj, pool_phase); phases 10-12 keep mm_limit 150 / FRIC and
   PHASES[11] / [12] are identical to 4e7a86d; spec_of carries delta 0.1 (different job id from the delta-0.025 twin); in_family isolates
   delta 0.025 <-> 0.10 both ways (11 / 12 vs 13 / 14) and shares 13 <-> 14; bad fric / mm_limit definitions refused; pool reuse of
   phase 11's pool file (same key, same file name); warm_dependents / check_warm_source for 13 -> 14.
B. objectives / record_of: default mm_limit bitwise identical to 4e7a86d (pre-change) for v1-v4 on a grid of records and on fake jobs; mm_limit None:
   a 2000 um fric_only record is ok and feasible with c = -1, bonded rows still carry the vM term; f1 missing still not ok; numeric limit.
C. phase 13 segment A (bo --init, --warm none) and the async arm on a fake queue that also holds delta-0.025 sb11 / sb12 jobs: specs
   delta 0.1, all-loose designs (micromotion 600-2400 um) ok and feasible, state file carries mm_limit null and fric; family / legacy
   refused; async adopts only sb13_*; dataset isolation both ways; budget arithmetic.
D. phase 14 frozen warm start from the phase-13 state file: ids = ok init + adopted sb13 (picks never), rows re-scored with phase 14's
   settings (v4, mm_limit None: C0 = record_of(..., 'v4', None)), budget counts only own sb14 jobs, warm pool points never re-submitted,
   restart reuses the frozen ids; a hand-made phase-13 state file (round 0 + adopted + picks + a round -1 pick) selects the same way;
   refusals (no neckopt_p13.json; unadopted sb13 job).
E. arms_gate.py --src 13 --dst 14: mm_limit null -> no zero-feasible failure (counts reported), key absent -> the rule applies; budgets
   BUDGET13 / BUDGET14; --expect-delta; ready == warm_from_select; default 11 / 12 output keys unchanged.
F. g1_regress.py --src 13 --dst 14 --expect-delta 0.1 on the fake tree: all PASS, G1e rows, writes only deck/p13_3406/g1; a delta-0.025
   spec -> FAIL; a state file without the mm_limit key -> FAIL; wrong --expect-delta -> FAIL.
G. launcher / README command lines parsed by stage_neckopt's own argparse (the parser block executed from the source).
"""
import contextlib
import copy
import importlib.util
import io
import json
import math
import pathlib
import re
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
BASE = pathlib.Path(tempfile.gettempdir()) / "mobo_toy_p13_tests"          # fake queues outside the repo and outside ~/mobo_toy_v2
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
P11_ORIG, P12_ORIG = copy.deepcopy(N.PHASES[11]), copy.deepcopy(N.PHASES[12])
P13_ORIG, P14_ORIG = copy.deepcopy(N.PHASES[13]), copy.deepcopy(N.PHASES[14])
IID = N.PHASES[11]["intact_job"]
INTACT = {"kind": "intact", "h_int": 2.0, "stage": "sb", "tag": "intact_h2", "femur_id": "sawbone3406", "neck_axis": "isthmus"}
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


# ---------------------------------------------------------------- the pre-phase-13 commit (4e7a86d) for the byte-identity checks
BASE_REV = "4e7a86d"                                                          # last commit before mm_limit / fric (pinned: HEAD now contains them)
try:
    _src = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASE_REV}:v2/stage_neckopt.py"], capture_output=True, check=True).stdout
    (BASE / "stage_neckopt_head.py").write_bytes(_src)
    _s = importlib.util.spec_from_file_location("stage_neckopt_head", BASE / "stage_neckopt_head.py")
    OLD = importlib.util.module_from_spec(_s)
    _s.loader.exec_module(OLD)
except Exception as ex_:                                                    # noqa: BLE001
    OLD = None
    print(f"   cannot load stage_neckopt at {BASE_REV}: {type(ex_).__name__}: {ex_}")

PH11, PH12, PH13, PH14 = N.Phase(11), N.Phase(12), N.Phase(13), N.Phase(14)
NV = len(PH13.vars)
rng = np.random.default_rng(1314)
POOL = rng.random((300, NV))


def loss_fn(U):
    U = np.atleast_2d(np.asarray(U, float))
    return 4000.0 + 5000.0 * U[:, 1] + 3000.0 * U[:, 0] + 1000.0 * U[:, 7]


LOSS = loss_fn(POOL)


def truth(x, delta):
    rot = 0.5 + 4.0 * x[0] * (1.0 - x[1]) + 1.0 * x[3]                    # loose designs on the foam femur (degrees)
    area = 600.0 + 700.0 * x[2] + 200.0 * x[4]
    f1 = (600.0 + 1800.0 * x[5]) * (1.0 if delta >= 0.1 else 1.6)          # 600-2400 um at delta 0.1: every design over 150 um
    return rot, area, f1


def x_of_job(jid, ph=None):
    spec = json.loads((J.QROOT / jid / "spec.json").read_text())
    return (ph or PH13).to_unit(spec["design"], float(spec["h_cut"])), spec


def solve_fake(jid):
    x, spec = x_of_job(jid)
    rot, area, f1 = truth(x, float(spec.get("delta", 0.025)))
    res = {"f1_p95_um": f1, "bone_loss": {"total_mm3": float(loss_fn(x)[0]), "ref_cut_mm": 16.0},
           "templating": {"A0": 500.0, "e": -1.0, "volume": 3000.0}, "job_id": jid}
    if spec.get("fric_only"):
        res["fric_only"] = True
    else:
        res["vm_p99"] = 90.0 if x[6] < 0.8 else 520.0                       # a few bonded designs violate the stem stress limit
    (J.QROOT / jid / "result.json").write_text(json.dumps(res))
    (J.QROOT / jid / "DONE").write_text("x")


def fake_stability(jid):
    x, spec = x_of_job(jid)
    rot, area, _ = truth(x, float(spec.get("delta", 0.025)))
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


FIT_LOG, DS_CALLS = [], []
_real_fit, _real_dataset = mobo.fit_models, N.dataset


def fit_spy(X, Y, C, noise_sd=None, det=None):
    FIT_LOG.append({"X": np.array(X), "Y": np.array(Y), "C": np.array(C), "det": det})
    return _real_fit(X, Y, C, noise_sd, det)


def ds_spy(ph, legacy=False):
    DS_CALLS.append(ph.phase)
    return _real_dataset(ph, legacy)


def spies(on):
    if on:
        FIT_LOG.clear(); DS_CALLS.clear()
    mobo.fit_models, N.dataset = (fit_spy, ds_spy) if on else (_real_fit, _real_dataset)


def gate(*argv):
    rc, out = captured(AG.main, list(argv))
    kv = dict(ln.split("=", 1) for ln in out.splitlines() if "=" in ln and ln.split("=", 1)[0].isupper() and " " not in ln.split("=", 1)[0])
    return rc, out, kv


N.stability_of = fake_stability
N._calcar = lambda jid: (None, None)
N.refresh_pool = fake_refresh
if OLD is not None:
    OLD.stability_of = fake_stability
    OLD._calcar = lambda jid: (None, None)

# ================================================================ A. definitions
ok("PHASES[13] == {**PHASES[11], fric {delta 0.10}, pool_phase 11, mm_limit None}; PHASES[14] == {**PHASES[13], metric v4, warm_from {13, [0, -1]}}",
   N.PHASES[13] == {**N.PHASES[11], "fric": {"delta": 0.10}, "pool_phase": 11, "mm_limit": None}
   and N.PHASES[14] == {**N.PHASES[13], "metric": "v4", "warm_from": {"phase": 13, "rounds": [0, -1]}})
ok("Phase(13): stage sb13, metric v3 (2 obj), sed none, fric {slip_tol 2.5e-4, delta 0.1}, mm_limit None, pool_phase 11, no warm_from, "
   "bond_every 5, the phase-11 intact reference",
   PH13.stage == "sb13" and PH13.metric == "v3" and PH13.n_obj == 2 and PH13.sed == "none" and PH13.fric == {"slip_tol": 2.5e-4, "delta": 0.1}
   and PH13.mm_limit is None and PH13.pool_phase == 11 and PH13.warm_from is None and PH13.bond_every == 5 and PH13.intact_job == IID
   and PH13.femur_id == "sawbone3406" and PH13.neck_axis == "isthmus")
ok("Phase(14): stage sb14, metric v4 (3 obj), warm_from {13, [0, -1]}, fric delta 0.1, mm_limit None, pool_phase 11",
   PH14.stage == "sb14" and PH14.metric == "v4" and PH14.n_obj == 3 and PH14.warm_from == {"phase": 13, "rounds": [0, -1]}
   and PH14.fric == PH13.fric and PH14.mm_limit is None and PH14.pool_phase == 11)
ok("phases 1-12: mm_limit 150.0 (= MM_LIMIT) and fric == FRIC; state_extras {} (their state files gain no key)",
   all(N.Phase(p).mm_limit == N.MM_LIMIT == 150.0 and N.Phase(p).fric == N.FRIC and N.state_extras(N.Phase(p)) == {}
       for p in (1, 5, 7, 8, 9, 10, 11, 12)))
ok("Phase.mm_kw: {} for phases 10-12 (record_of called exactly as before, 3 positional args), {'mm_limit': None} for 13 / 14",
   PH11.mm_kw == {} and PH12.mm_kw == {} and N.Phase(10).mm_kw == {} and PH13.mm_kw == {"mm_limit": None} and PH14.mm_kw == {"mm_limit": None})
ok("state_extras(13 / 14) = {mm_limit None, fric {...delta 0.1}}", N.state_extras(PH13) == {"mm_limit": None, "fric": PH13.fric}
   and N.state_extras(PH14) == {"mm_limit": None, "fric": PH14.fric})
ok("PHASES[11] / PHASES[12] identical to the 4e7a86d definitions; 4e7a86d has no PHASES[13]",
   OLD is not None and OLD.PHASES[11] == N.PHASES[11] and OLD.PHASES[12] == N.PHASES[12] and 13 not in OLD.PHASES)
u0 = POOL[10]
s11, s13, s14 = PH11.spec_of(u0, "t", bonded=False), PH13.spec_of(u0, "t", bonded=False), PH14.spec_of(u0, "t", bonded=True)
ok("spec_of: phase 13 delta 0.1 / stage sb13, phase 14 delta 0.1 / stage sb14 (bonded: intact_job), phase 11 delta 0.025; otherwise the same "
   "design spec; different job ids", s13["delta"] == 0.1 and s13["slip_tol"] == 2.5e-4 and s13["stage"] == "sb13" and s14["delta"] == 0.1
   and s14["stage"] == "sb14" and s14["intact_job"] == IID and s11["delta"] == 0.025
   and {k: v for k, v in s13.items() if k not in ("delta", "stage")} == {k: v for k, v in s11.items() if k not in ("delta", "stage")}
   and J.job_id(s13) != J.job_id({**s13, "delta": 0.025}))
s12 = PH12.spec_of(u0, "t", bonded=False)
s14f = PH14.spec_of(u0, "t", bonded=False)
iso = {"13 rejects sb11 (0.025)": not PH13.in_family(s11), "13 rejects sb12 (0.025)": not PH13.in_family(s12),
       "14 rejects sb11": not PH14.in_family(s11), "14 rejects sb12": not PH14.in_family(s12),
       "11 rejects sb13 (0.10)": not PH11.in_family(s13), "11 rejects sb14": not PH11.in_family(s14f),
       "12 rejects sb13": not PH12.in_family(s13), "12 rejects sb14": not PH12.in_family(s14f), "10 rejects sb13": not N.Phase(10).in_family(s13),
       "13 accepts sb13": PH13.in_family(s13), "13 accepts sb14": PH13.in_family(s14f), "14 accepts sb13": PH14.in_family(s13),
       "14 accepts its bonded sb14": PH14.in_family(s14), "11 still accepts sb11 / sb12": PH11.in_family(s11) and PH11.in_family(s12),
       "13 rejects an sb13 spec rewritten to delta 0.025": not PH13.in_family({**s13, "delta": 0.025}),
       "13 rejects slip_tol 5e-4": not PH13.in_family({**s13, "slip_tol": 5e-4})}
ok("in_family: delta 0.025 (phases 10-12) <-> 0.10 (phases 13 / 14) isolated both ways; 13 <-> 14 shared (sb* prefix, same delta)",
   all(iso.values()), str([k for k, v in iso.items() if not v]))
for label, defn, frag in (("fric with an unknown key", {**P13_ORIG, "fric": {"delta": 0.1, "mu": 0.5}}, "fric"),
                          ("mm_limit -5", {**P13_ORIG, "mm_limit": -5.0}, "mm_limit"),
                          ("mm_limit '150' (string)", {**P13_ORIG, "mm_limit": "150"}, "mm_limit"),
                          ("mm_limit True", {**P13_ORIG, "mm_limit": True}, "mm_limit"),
                          ("mm_limit nan", {**P13_ORIG, "mm_limit": float("nan")}, "mm_limit"),
                          ("mm_limit on a metric-v2 phase", {**N.PHASES[8], "mm_limit": None}, "metric")):
    N.PHASES[99] = defn
    e = raises(ValueError, N.Phase, 99)
    ok(f"Phase with {label} -> ValueError", e is not None and frag in e, (e or "")[:90])
N.PHASES[99] = {**P13_ORIG, "mm_limit": 200}
ok("mm_limit 200 (int) accepted -> 200.0", N.Phase(99).mm_limit == 200.0)
N.PHASES.pop(99)
pk = {p: N.pool_key(N.Phase(p), 16384, 0) for p in (11, 13, 14)}
ok("pool: pool_key(11) == pool_key(13) == pool_key(14) (delta / mm_limit / metric not in the key); pool_source(13) == pool_source(14) == 11; "
   "pool_file(13) / (14) == phase 11's file",
   len(set(pk.values())) == 1 and N.pool_source(PH13, 16384, 0) == 11 and N.pool_source(PH14, 16384, 0) == 11
   and N.pool_file(PH13, 16384, 0) == N.pool_file(PH11, 16384, 0) == N.pool_file(PH14, 16384, 0), str(pk))
ok("warm_dependents: 11 -> [12], 13 -> [14], 12 / 14 / 10 -> []",
   N.warm_dependents(PH11) == [12] and N.warm_dependents(PH13) == [14] and N.warm_dependents(PH12) == [] and N.warm_dependents(PH14) == []
   and N.warm_dependents(N.Phase(10)) == [])
e_f, e_l = raises(ValueError, N.check_warm_source, PH13, False), raises(ValueError, N.check_warm_source, PH13, True)
ok("check_warm_source(13, family / legacy) -> ValueError naming [14] and '--warm none'; 13 with none, 14 with family pass",
   e_f and e_l and "[14]" in e_f and "--warm none" in e_f and "sb*" in e_f and raises(Exception, N.check_warm_source, PH13, None) is None
   and raises(Exception, N.check_warm_source, PH14, False) is None, (e_f or "")[:100])

# ================================================================ B. objectives / record_of
grid = []
for f1 in (1.0, 40.0, 150.0, 151.0, 2000.0):
    for vm in (None, 90.0, 440.0, 520.0):
        for fo in (False, True):
            for sedc in (None, -10.0, 45.0):
                r = {"f1_p95_um": f1, "f1_all_p95_um": f1 * 1.1, "bone_loss": {"total_mm3": 5000.0}, "templating": {"volume": 3000.0},
                     "_stability": {"rot_first_deg": 0.3, "contact_area_load2_mm2": 900.0}}
                if vm is not None:
                    r["vm_p99"] = vm
                if fo:
                    r["fric_only"] = True
                grid.append((r, sedc))
grid += [(None, None), ({"failed": "x"}, None), ({"f1_p95_um": 10.0}, None)]
mismatch = []
for metric in ("v1", "v2", "v3", "v4"):
    for sed in ("none", "abs", "one-sided"):
        for r, sedc in grid:
            a_ = N.objectives(r, sed, 5.0, metric, sedc)
            b_ = N.objectives(r, sed, 5.0, metric, sedc, N.MM_LIMIT)
            c_ = OLD.objectives(r, sed, 5.0, metric, sedc) if OLD is not None else None
            if not (repr(a_) == repr(b_) == repr(c_)):
                mismatch.append((metric, sed, a_, c_))
ok(f"objectives: default == explicit MM_LIMIT == 4e7a86d (repr, bitwise) on {len(grid) * 12} record x metric x sed cases", not mismatch and OLD is not None,
   str(mismatch[:2]))
r2000 = {"f1_p95_um": 2000.0, "fric_only": True, "bone_loss": {"total_mm3": 5000.0}, "_stability": {"rot_first_deg": 0.3, "contact_area_load2_mm2": 900.0}}
y3, c3, ok3 = N.objectives(r2000, "none", None, "v3", None, None)
y4, c4, ok4 = N.objectives(r2000, "none", None, "v4", None, None)
y3d, c3d, _ = N.objectives(r2000, "none", None, "v3", None)
ok("mm_limit None: a 2000 um fric_only record is ok and feasible, c == -1 (v3 and v4); with the default 150 c = (2000 - 150) / 150",
   ok3 and ok4 and c3 == -1.0 and c4 == -1.0 and len(y3) == 2 and len(y4) == 3 and y4[2] == 5000.0 and c3d == (2000.0 - 150.0) / 150.0
   and y3 == y3d, f"{c3} {c4} {c3d}")
rb = {**r2000, "vm_p99": 520.0}
rb.pop("fric_only")
_, cb, okb = N.objectives(rb, "none", None, "v3", None, None)
_, cb2, _ = N.objectives({**rb, "vm_p99": 90.0}, "none", None, "v4", None, None)
_, cb3, okb3 = N.objectives({k: v for k, v in rb.items() if k != "vm_p99"}, "none", None, "v3", None, None)
ok("mm_limit None, bonded rows still carry vM: vm 520 -> c = (520 - 440) / 440 > 0 (infeasible), vm 90 -> c = (90 - 440) / 440; a bonded "
   "record without vm_p99 is still not ok", okb and cb == (520.0 - 440.0) / 440.0 and cb2 == (90.0 - 440.0) / 440.0 and not okb3, f"{cb} {cb2}")
_, cn, okn = N.objectives({k: v for k, v in r2000.items() if k != "f1_p95_um"}, "none", None, "v3", None, None)
_, c200, _ = N.objectives(r2000, "none", None, "v3", None, 200.0)
ok("mm_limit None: a record without f1_p95_um is still not ok; mm_limit 200 -> c = (2000 - 200) / 200", not okn and c200 == 9.0, f"{c200}")

env = make_env("defs")
jf = add_job(PH13, POOL[20], "rec_f", bonded=False)
jb = add_job(PH13, POOL[21], "rec_b", bonded=True)
j11 = add_job(PH11, POOL[22], "rec11", bonded=False)
same_head = OLD is not None and all(N.record_of(j, s, m) == OLD.record_of(j, s, m) for j in (jf, jb, j11) for s in ("none", "abs")
                                    for m in ("v1", "v2", "v3", "v4"))
ok("record_of default == 4e7a86d record_of (dict equality) for fric_only / bonded / phase-11 fake jobs, all metrics", same_head)
rf, rf150 = N.record_of(jf, "none", "v3", None), N.record_of(jf, "none", "v3")
ok("record_of(..., mm_limit None) on a loose fric_only job (micromotion > 600 um): ok, c == -1, f1_body_p95_um still recorded; "
   "the default 150 makes it infeasible", rf["ok"] and rf["c"] == [-1.0] and rf["f1_body_p95_um"] > 600 and rf150["c"][0] > 0
   and rf["y"] == rf150["y"], f"{rf['c']} {rf150['c']}")

# ================================================================ C. phase 13 segment A + async arm (fake queue with sb11 / sb12 neighbours)
env = make_env("arms13")
J.submit = submit_and_solve
N.gated_pool = fake_gated
old11 = [add_job(PH11, POOL[k], f"init{k}", bonded=(k % 2 == 0)) for k in range(4)]       # delta-0.025 neighbours in the same queue
old12 = [add_job(PH12, POOL[k], f"a{k}", bonded=False) for k in (40, 41)]
smk13 = add_job(PH13, POOL[200], "smoke_f_h16")                                          # a phase-13 smoke (fric_only) to be adopted
SUBMITTED.clear()
p13_path = N.out_path(13)
for label, lw in (("family", False), ("legacy", True)):
    e = raises(ValueError, N.bo, PH13, 0, 6, 1, 0, 1, lw, 16384)
    ok(f"bo(13, --warm {label}) -> ValueError '--warm none' (phase 13 is phase 14's warm source); nothing submitted, no state file",
       e is not None and "--warm none" in e and not SUBMITTED and not p13_path.exists(), (e or "")[:80])
st_a, log_a = captured(N.bo, PH13, n_rounds=0, n_init=6, q=1, seed=0, workers=1, legacy_warm=None, n_pool=16384, refresh_k=0)
init13 = [r["job_id"] for r in st_a["records"]]
specs13 = [json.loads((J.QROOT / j / "spec.json").read_text()) for j in init13]
ok("phase 13 segment A (bo --init 6 --warm none): 6 round-0 records on pool points 0-5 (phase 11's pool, first unused), stage sb13, "
   "every spec delta 0.1 / slip_tol 2.5e-4, bonded every 5th (n_submitted 6)",
   len(init13) == 6 and [r["pool_idx"] for r in st_a["records"]] == list(range(6)) and all(j.startswith("sb13_init") for j in init13)
   and all(s_["delta"] == 0.1 and s_["slip_tol"] == 2.5e-4 for s_ in specs13) and st_a["n_submitted"] == 6
   and [bool(r["bonded"]) for r in st_a["records"]] == [False, False, False, False, True, False])
f1s = [r["f1_body_p95_um"] for r in st_a["records"]]
ok("phase 13 init: every design loose (micromotion P95 > 600 um) yet ok; fric_only rows c == -1 (feasible), the bonded row c = its vM term",
   all(r["ok"] for r in st_a["records"]) and min(f1s) > 600 and all(r["c"] == [-1.0] for r in st_a["records"] if not r["bonded"])
   and all(r["c"] == [(r["vm_p99"] - 440.0) / 440.0] for r in st_a["records"] if r["bonded"]), f"f1 {min(f1s):.0f}-{max(f1s):.0f}")
f13 = json.loads(p13_path.read_text())
ok("neckopt_p13.json: mm_limit null, fric {slip_tol, delta 0.1}, stage sb13 (key order of the phase-11 fields unchanged before them)",
   "mm_limit" in f13 and f13["mm_limit"] is None and f13["fric"] == {"slip_tol": 2.5e-4, "delta": 0.1} and f13["stage"] == "sb13"
   and list(f13)[:list(f13).index("mm_limit")] == [k for k in st_a if k not in ("mm_limit", "fric", "updated")][:list(f13).index("mm_limit")])
spies(True)
SUBMITTED.clear()
st13, log13 = captured(N.bo_async, PH13, budget=6 + 1 + 3, inflight=1, seed=0, workers=1, legacy_warm=None, n_pool=16384, refresh_k=0, poll=0.01)
spies(False)
recs13 = st13["records"]
ok("phase 13 async (--warm none, budget 6 init + 1 adopted + 3): adopts the sb13 smoke only (no sb11 / sb12), 3 own picks, dataset() not called",
   [r["job_id"] for r in recs13 if r["pool_idx"] is None] == [smk13] and len(SUBMITTED) == 3 and all(j.startswith("sb13_a") for j in SUBMITTED)
   and not any(r["job_id"].startswith(("sb11", "sb12", "sb14")) for r in recs13) and DS_CALLS == [] and len(recs13) == 10)
ok("phase 13 async: every fit's C = stored c (fric_only -1); feasible rows exist -> ref point frozen at the first acquisition, no temporary one",
   FIT_LOG and all(np.array_equal(np.array([r["c"] for r in recs13[:len(f_["C"])] if r["ok"]]).reshape(-1, 1), f_["C"]) for f_ in FIT_LOG)
   and st13["ref_point"] is not None and "temporary ref point" not in log13 and log13.count("ref point frozen at acquisition #") == 1)
ok("phase 13 async picks: specs delta 0.1, all records ok; the state file keeps mm_limit null",
   all(json.loads((J.QROOT / j / "spec.json").read_text())["delta"] == 0.1 for j in SUBMITTED) and all(r["ok"] for r in recs13)
   and json.loads(p13_path.read_text())["mm_limit"] is None)
X13, _, _, ids13 = N.dataset(PH13)
X11, _, _, ids11 = N.dataset(PH11)
X14d, _, _, ids14d = N.dataset(PH14)
ok("dataset isolation (dataset skips the phase's own stage): dataset(11) = the two delta-0.025 sb12 jobs only (no sb13); dataset(13) has no "
   "sb11 / sb12 (empty: no sb14 yet); dataset(14) = sb13 jobs only, all 6 init included, never sb11 / sb12",
   sorted(ids11) == sorted(old12) and ids13 == [] and ids14d and all(j.startswith("sb13") for j in ids14d) and set(init13) <= set(ids14d),
   f"{ids11} / {ids13} / {len(ids14d)}")
rc, out, kv = gate("init", "--root", str(env), "--src", "13", "--dst", "14", "--new", "3", "--expect-delta", "0.1")
ok("arms_gate init --src 13 --dst 14: PASS, MM_LIMIT none, BUDGET13 = 6 + 1 + 3 = 10, BUDGET14 3, N_PICKS13 3, delta check passes",
   rc == 0 and kv.get("VERDICT") == "PASS" and kv.get("MM_LIMIT") == "none" and kv.get("BUDGET13") == "10" and kv.get("BUDGET14") == "3"
   and kv.get("BUDGET_SRC") == "10" and kv.get("N_PICKS13") == "3" and "6 of 6 init specs match" in out, f"{kv}")

# ================================================================ D. phase 14 frozen warm start
st13f = json.loads(p13_path.read_text())
cand14, info14 = N.warm_from_select(PH14, st13f)
rc, out, kv = gate("ready", "--root", str(env), "--src", "13", "--dst", "14")
ok("arms_gate ready --src 13 --dst 14: READY14=1; candidates == warm_from_select(14) == 6 init + 1 adopted (no picks)",
   rc == 0 and kv.get("READY14") == "1" and kv.get("READY_DST") == "1" and kv.get("WARM_CANDIDATES") == "7"
   and AG.warm_candidates(st13f) == cand14 == init13 + [smk13], out.strip()[-120:])
spies(True)
SUBMITTED.clear()
st14, log14 = captured(N.bo_async, PH14, budget=3, inflight=1, seed=0, workers=1, legacy_warm=False, n_pool=16384, refresh_k=0, poll=0.01)
spies(False)
frozen = st14["warm_start_ids"]
X0 = FIT_LOG[0]["X"][:len(frozen)]
C0, Y0 = FIT_LOG[0]["C"][:len(frozen)], FIT_LOG[0]["Y"][:len(frozen)]
want_c = np.array([N.record_of(j, "none", "v4", None)["c"] for j in frozen])
c150 = np.array([N.record_of(j, "none", "v4")["c"] for j in frozen])
ok("phase 14 first start: frozen = 6 ok init + the adopted sb13 smoke (phase-13 picks never); --warm family ignored and logged",
   frozen == init13 + [smk13] and st14["warm_from"]["phase"] == 13 and "the --warm family option is ignored" in log14
   and not any(j in frozen for j in SUBMITTED) and DS_CALLS == [], f"{len(frozen)}")
ok("phase 14 warm rows re-scored with phase 14's settings (v4, mm_limit None): Y0 3 columns (y[2] = bone), C0 == record_of(j, 'none', 'v4', None) "
   "(-1 on fric_only rows although every micromotion > 600 um), != the 150-um scoring",
   Y0.shape == (7, 3) and np.array_equal(C0, want_c) and (C0[:, 0] == -1.0).sum() == 6 and (c150[:, 0] > 0).sum() >= 6
   and np.array_equal(Y0[:, 2], np.array([(J.result(j) or {})["bone_loss"]["total_mm3"] for j in frozen])), f"{C0.ravel().round(3).tolist()}")
own14 = [r for r in st14["records"] if r["job_id"] in SUBMITTED]
ok("phase 14 budget 3 = own sb14 submissions only (7 warm rows not counted); specs delta 0.1; records 3 objectives, fric_only c == -1",
   len(SUBMITTED) == 3 and all(j.startswith("sb14_a") for j in SUBMITTED) and len(st14["records"]) == 3
   and all(json.loads((J.QROOT / j / "spec.json").read_text())["delta"] == 0.1 for j in SUBMITTED)
   and all(len(r["y"]) == 3 for r in st14["records"]) and all(r["c"] == [-1.0] for r in st14["records"] if not r["bonded"]))
ok("phase 14: the 6 init pool points never submitted under sb14 (warm points on phase 11's pool marked used)",
   all(r["pool_idx"] not in range(6) for r in own14) and all(r["pool_idx"] is not None for r in own14), str([r["pool_idx"] for r in own14]))
f14 = json.loads(N.out_path(14).read_text())
ok("neckopt_p14.json: warm_from {phase 13, rounds [0, -1], source neckopt_p13.json}, warm_start_ids, mm_limit null, fric delta 0.1",
   f14["warm_from"]["phase"] == 13 and f14["warm_from"]["source"] == "neckopt_p13.json" and f14["warm_start_ids"] == frozen
   and f14["mm_limit"] is None and f14["fric"]["delta"] == 0.1)
SUBMITTED.clear()
st13b, _ = captured(N.bo_async, PH13, budget=12, inflight=1, seed=0, workers=1, legacy_warm=None, n_pool=16384, refresh_k=0, poll=0.01)
p13_path.rename(p13_path.with_suffix(".moved"))
spies(True)
SUBMITTED.clear()
st14b, log14b = captured(N.bo_async, PH14, budget=4, inflight=1, seed=0, workers=1, legacy_warm=None, n_pool=16384, refresh_k=0, poll=0.01)
spies(False)
p13_path.with_suffix(".moved").rename(p13_path)
ok("phase 14 restart (2 more phase-13 picks meanwhile, neckopt_p13.json moved away): reuses exactly the frozen ids, X0 bitwise; 1 more own job",
   st14b["warm_start_ids"] == frozen and "restart, reusing the 7 frozen ids" in log14b and np.array_equal(FIT_LOG[0]["X"][:7], X0)
   and len(SUBMITTED) == 1 and len(st14b["records"]) == 4)
hand = {"records": [{"job_id": init13[0], "round": 0, "pool_idx": 0}, {"job_id": init13[1], "round": 0, "pool_idx": 1},
                    {"job_id": smk13, "round": -1, "pool_idx": None}, {"job_id": "sb13_a7_x", "round": 8, "pool_idx": 77},
                    {"job_id": "sb13_a9_y", "round": -1, "pool_idx": 99}, {"job_id": "sb13_late", "round": 9, "pool_idx": None}],
        "pending": {}}
c_h, i_h = N.warm_from_select(PH14, hand, strict=False)
ok("hand-made phase-13 state file: selection = round 0 + adopted (pool_idx None, any round); picks (incl. a round -1 pick) never",
   c_h == [init13[0], init13[1], smk13, "sb13_late"] and AG.warm_candidates(hand) == c_h, str(c_h))
env_n = make_env("p14_refuse")
N.gated_pool = no_pool
SUBMITTED.clear()
e = raises(ValueError, N.bo_async, PH14, budget=3, inflight=1, seed=0, workers=1, legacy_warm=None, n_pool=16384, poll=0.01)
ok("phase 14 without neckopt_p13.json -> ValueError (before gated_pool), nothing submitted", e is not None and "neckopt_p13.json does not exist" in e
   and not SUBMITTED and not N.out_path(14).exists(), (e or "")[:100])
(J.RESULTS / "neckopt_p13.json").write_text(json.dumps({"records": [{"job_id": "sb13_init_1", "round": 0, "pool_idx": 0, "ok": True}]}))
stray = add_job(PH13, POOL[150], "late_smoke")
e = raises(ValueError, N.bo_async, PH14, budget=3, inflight=1, seed=0, workers=1, legacy_warm=None, n_pool=16384, poll=0.01)
ok("phase 14 with an sb13 job phase 13 has not adopted -> ValueError naming it", e is not None and "not yet adopted" in e and stray in e, (e or "")[:120])
rc, out, kv = gate("ready", "--root", str(env_n), "--src", "13", "--dst", "14")
ok("arms_gate ready --src 13 --dst 14 on that tree -> exit 8, READY14=0, names g13b_run.sh", rc == 8 and kv.get("READY14") == "0"
   and "start g13b_run.sh first" in out)
J.QROOT, J.RESULTS = env / "queue", env / "results"
N.gated_pool = fake_gated

# ================================================================ E. arms_gate: mm_limit null vs absent, defaults
envg = BASE / "gate13"
shutil.rmtree(envg, ignore_errors=True)
(envg / "results").mkdir(parents=True)
(envg / "queue").mkdir()
recs_g = [{"job_id": f"sb13_init_{i}", "round": 0, "pool_idx": i, "ok": True, "c": [0.2], "y": [0.5, -900.0], "f1_body_p95_um": 1500.0}
          for i in range(10)]
for r in recs_g:
    (envg / "queue" / r["job_id"]).mkdir()
    (envg / "queue" / r["job_id"] / "spec.json").write_text(json.dumps({"delta": 0.1}))
(envg / "results" / "neckopt_p13.json").write_text(json.dumps({"records": recs_g, "mm_limit": None}))
rc, out, kv = gate("init", "--root", str(envg), "--src", "13", "--dst", "14", "--new", "75")
ok("arms_gate init, mm_limit null and 0 feasible -> PASS (no zero-feasible rule), counts reported (INIT_FEASIBLE 0, 10 over 150), BUDGET13 85",
   rc == 0 and kv.get("VERDICT") == "PASS" and kv.get("INIT_FEASIBLE") == "0" and kv.get("INIT_OVER_150") == "10" and kv.get("BUDGET13") == "85"
   and "zero-feasible rule does not apply" in out and "reported only" in out, f"{kv}")
(envg / "results" / "neckopt_p13.json").write_text(json.dumps({"records": recs_g}))
rc, out, kv = gate("init", "--root", str(envg), "--src", "13", "--dst", "14", "--new", "75")
ok("arms_gate init, no mm_limit key (default 150) and 0 feasible -> FAIL 'zero feasible', MM_LIMIT 150", rc == 3 and "zero feasible" in out
   and kv.get("MM_LIMIT") == "150")
(envg / "results" / "neckopt_p13.json").write_text(json.dumps({"records": recs_g, "mm_limit": None}))
rc, out, kv = gate("init", "--root", str(envg), "--src", "13", "--dst", "14", "--expect-delta", "0.025")
ok("arms_gate init --expect-delta 0.025 on delta-0.1 specs -> FAIL ('without delta')", rc == 3 and "without delta 0.025" in out)
rc, _, _ = gate("init", "--root", str(envg), "--src", "13", "--dst", "13")
ok("arms_gate --src 13 --dst 13 -> exit 2", rc == 2)
env11 = BASE / "gate11"
shutil.rmtree(env11, ignore_errors=True)
(env11 / "results").mkdir(parents=True)
(env11 / "queue").mkdir()
(env11 / "results" / "neckopt_p11.json").write_text(json.dumps({"records": [{**r, "job_id": r["job_id"].replace("sb13", "sb11"), "c": [-0.5]}
                                                                         for r in recs_g]}))
rc, out, kv = gate("init", "--root", str(env11), "--new", "95")
ok("arms_gate init with the defaults (11 / 12): keys BUDGET11 / BUDGET12 / N_PICKS11 as before, old one-line verdict format",
   rc == 0 and kv.get("BUDGET11") == "105" and kv.get("BUDGET12") == "95" and kv.get("N_PICKS11") == "0" and kv.get("MM_LIMIT") == "150"
   and re.search(r"^PASS \S+ \S+: init 10, ok 10, feasible 10, not ok 0\.0% \(limit 15%\)$", out, re.M) is not None, f"{kv}")

# ================================================================ F. g1_regress --src 13 --dst 14
pf = N.pool_file(PH14, 16384, 0)
pf.parent.mkdir(exist_ok=True)
np.savez(pf, U=POOL, loss=LOSS)
G1.femur_cache_ok = lambda SN, ids: (True, "test: femur caches assumed present")


def snapshot(root, skip):
    out_ = {}
    for p in root.rglob("*"):
        if p.is_file() and skip not in p.parents:
            s_ = p.stat()
            out_[str(p.relative_to(root))] = (s_.st_size, s_.st_mtime_ns)
    return out_


g1dir = env / "deck" / "p13_3406" / "g1"
before = snapshot(env, g1dir)
argv13 = ["--root", str(env), "--code", str(ROOT), "--src", "13", "--dst", "14", "--expect-delta", "0.1"]
rc, out_g1 = captured(G1.main, argv13)
after = snapshot(env, g1dir)
fails = [r for r in G1.ROWS if r["verdict"] == "FAIL"]
items = [r["item"] for r in G1.ROWS]
ok("g1_regress --src 13 --dst 14: exit 0, no FAIL; G1a-G1e rows; pool row = phase 11's file; det exact; writes only deck/p13_3406/g1",
   rc == 0 and not fails and {r["check"] for r in G1.ROWS} >= {"G1a", "G1b", "G1c", "G1d", "G1e"}
   and any(i.startswith("phase-14 candidate pool") for i in items) and any(i.startswith("det(X0)") for i in items)
   and before == after and (g1dir / "g1_latest.json").exists(), f"rc {rc}; {fails[:2]}")
want_e = ["fric Phase(13) == Phase(14)", "mm_limit Phase(13) == Phase(14)", "Phase(13) delta == expected 0.1",
          "neckopt_p13.json micromotion limit == Phase(13).mm_limit", "phase-13 job specs carry delta 0.1 / slip_tol 0.00025",
          "no delta-0.025 job in phase 13's records / pending / queue", "warm-start candidates carry Phase(14).fric (delta 0.1)"]
ok("g1 G1e: fric / mm_limit definitions, expected delta, stored micromotion limit, every job delta 0.1 (none 0.025), warm candidates -> PASS",
   all(any(r["item"] == w and r["verdict"] == "PASS" for r in G1.ROWS) for w in want_e)
   and any(r["item"].startswith("micromotion > 150 um, feasible") and r["verdict"] == "INFO" for r in G1.ROWS),
   str([w for w in want_e if not any(r["item"] == w and r["verdict"] == "PASS" for r in G1.ROWS)]))
n_g1b = sum(1 for r in G1.ROWS if r["check"] == "G1b")
ok("g1 G1b: one row per sb13 job (records + DONE queue), all PASS (v4 with mm_limit None: y[:2], c == v3)",
   n_g1b == len({d.name for d in J.QROOT.glob("sb13_*") if (d / "DONE").exists()} | {r["job_id"] for r in json.loads(p13_path.read_text())["records"]}),
   f"{n_g1b}")
spj = J.QROOT / init13[2] / "spec.json"
sp_text = spj.read_text()
spj.write_text(json.dumps({**json.loads(sp_text), "delta": 0.025}))
rc, _ = captured(G1.main, argv13)
bad_rows = [(r["check"], r["item"]) for r in G1.ROWS if r["verdict"] == "FAIL"]
ok("g1 with one phase-13 spec rewritten to delta 0.025 -> exit 1; the delta rows FAIL ('carry delta', 'no delta-0.025 job', warm candidates)",
   rc == 1 and ("G1e", "phase-13 job specs carry delta 0.1 / slip_tol 0.00025") in bad_rows
   and ("G1e", "no delta-0.025 job in phase 13's records / pending / queue") in bad_rows
   and ("G1e", "warm-start candidates carry Phase(14).fric (delta 0.1)") in bad_rows, str(bad_rows)[:200])
spj.write_text(sp_text)
s13_orig = p13_path.read_text()
p13_path.write_text(json.dumps({k: v for k, v in json.loads(s13_orig).items() if k != "mm_limit"}))
rc, _ = captured(G1.main, argv13)
bad_rows = [(r["check"], r["item"]) for r in G1.ROWS if r["verdict"] == "FAIL"]
ok("g1 with a neckopt_p13.json without the mm_limit key (stored c computed under another rule) -> exactly the G1e limit row FAILs, exit 1",
   rc == 1 and bad_rows == [("G1e", "neckopt_p13.json micromotion limit == Phase(13).mm_limit")], str(bad_rows))
p13_path.write_text(s13_orig)
rc, _ = captured(G1.main, argv13[:-1] + ["0.025"])
ok("g1 --expect-delta 0.025 -> the expected-delta row FAILs, exit 1", rc == 1 and [(r["item"]) for r in G1.ROWS if r["verdict"] == "FAIL"]
   == ["Phase(13) delta == expected 0.025"])
rc, _ = captured(G1.main, argv13)
ok("g1 after restoring -> exit 0 again", rc == 0)

# ================================================================ G. launcher / README command lines vs stage_neckopt's argparse
src_txt = (ROOT / "v2" / "stage_neckopt.py").read_text(encoding="utf-8")
blk = src_txt[src_txt.index("    ap = argparse.ArgumentParser()"):src_txt.index("    a = ap.parse_args()")]
ns_ = {"argparse": __import__("argparse")}
exec("\n".join(ln[4:] for ln in blk.splitlines()), ns_)                     # the CLI's own parser, nothing else of __main__
AP = ns_["ap"]


def parse(argv):
    try:
        return AP.parse_args(argv), None
    except SystemExit as e_:
        return None, f"SystemExit {e_.code}"


g11b = (SCRIPTS / "g11b_run.sh").read_text(encoding="utf-8")
g12 = (SCRIPTS / "g12_run.sh").read_text(encoding="utf-8")


def launcher_argv(text, env_):
    m = re.search(r'v2/stage_neckopt\.py (async .*?--workers "\$WORKERS")', text.replace("\\\n", " "), re.S)
    words = m.group(1).split()
    out_ = []
    for w in words:
        w = w.strip('"')
        out_.append(re.sub(r"\$\{?([A-Z_0-9]+)\}?", lambda mm: env_[mm.group(1)], w))
    return out_


d13 = {"SRC": "13", "DST": "14", "B": "107", "BUDGET": "75", "INFLIGHT": "2", "POOL": "16384", "SEED": "0", "REFRESH": "32", "REFRESH_RAD": "0.08",
       "WORKERS": "4"}
a13, e13 = parse(launcher_argv(g11b, d13))
d14 = {**d13, "SRC": "13", "DST": "14"}
a14, e14 = parse(launcher_argv(g12, d14))
ok("g11b_run.sh (SRC 13) async line parses: async --phase 13 --budget 107 --inflight 2 --pool 16384 --seed 0 --refresh 32 --refresh-rad 0.08 "
   "--warm none --workers 4", e13 is None and (a13.cmd, a13.phase, a13.budget, a13.inflight, a13.pool, a13.seed, a13.refresh, a13.refresh_rad,
                                                a13.warm, a13.workers) == ("async", 13, 107, 2, 16384, 0, 32, 0.08, "none", 4), e13 or "")
ok("g12_run.sh (DST 14) async line parses: async --phase 14 --budget 75 --inflight 2 --pool 16384 --seed 0 --refresh 32 --refresh-rad 0.08 "
   "--warm family --workers 4", e14 is None and (a14.cmd, a14.phase, a14.budget, a14.inflight, a14.pool, a14.seed, a14.refresh, a14.refresh_rad,
                                                  a14.warm, a14.workers) == ("async", 14, 75, 2, 16384, 0, 32, 0.08, "family", 4), e14 or "")
w13 = (SCRIPTS / "g13b_run.sh").read_text(encoding="utf-8")
w14 = (SCRIPTS / "g14_run.sh").read_text(encoding="utf-8")
ok("g13b_run.sh = SRC 13 DST 14 NEW 75 EXPECT_DELTA 0.1 -> g11b_run.sh; g14_run.sh = SRC 13 DST 14 EXPECT_DELTA 0.1, budget 75 -> g12_run.sh",
   'SRC=13 DST=14 NEW="${NEW:-75}" EXPECT_DELTA="${EXPECT_DELTA-0.1}"' in w13 and 'exec sh "$HERE/g11b_run.sh"' in w13
   and 'SRC=13 DST=14 EXPECT_DELTA="${EXPECT_DELTA-0.1}"' in w14 and 'exec sh "$HERE/g12_run.sh" "${1:-75}" "${2:-2}"' in w14)
readme = (SCRIPTS / "README_p11_ops.md").read_text(encoding="utf-8")
init_cmd = "bo --phase 13 --init 32 --rounds 0 --pool 16384 --seed 0 --workers 6 --warm none"
ai, ei = parse(init_cmd.split())
ok("README phase-13 init command present and parses: bo --phase 13 --init 32 --rounds 0 --pool 16384 --seed 0 --workers 6 --warm none",
   init_cmd in readme and ei is None and (ai.cmd, ai.phase, ai.init, ai.rounds, ai.pool, ai.seed, ai.workers, ai.warm)
   == ("bo", 13, 32, 0, 16384, 0, 6, "none"), ei or "")
cmds = re.findall(r"stage_neckopt\.py ((?:bo|async|warm|status|pool) --phase 1[34][^`\"\n]*)", readme)
cmds = [c.replace("<n_init + n_adopted + 75>", "107") for c in cmds]       # the README writes the phase-13 budget as a formula
bad_c = [c for c in cmds if parse(c.split())[1] is not None]
ok(f"every 'stage_neckopt.py <cmd> --phase 13 / 14 ...' line in the README parses ({len(cmds)} found)", cmds and not bad_c, str(bad_c)[:120])

# ================================================================ CLI: warm --phase 14 (read-only dry run on the fake tree)
import runpy  # noqa: E402
_argv = sys.argv
sys.argv = ["stage_neckopt.py", "warm", "--phase", "14"]
snap_w = snapshot(env, BASE / "none")
try:
    _, out_cli = captured(runpy.run_path, str(ROOT / "v2" / "stage_neckopt.py"), run_name="__main__")
    _lines = out_cli.splitlines()
    cli = json.loads("\n".join(_lines[max(i for i, ln_ in enumerate(_lines) if ln_ == "{"):]))
except Exception as ex_:                                                     # noqa: BLE001
    cli = {"error": f"{type(ex_).__name__}: {ex_}"}
sys.argv = _argv
ok("CLI 'warm --phase 14' (restart case): prints the frozen ids, warm_from phase 13, writes nothing",
   cli.get("ids") == frozen and (cli.get("warm_from") or {}).get("phase") == 13 and snapshot(env, BASE / "none") == snap_w, str(cli)[:120])

# ================================================================ fixture reset
J.submit = _real_submit
ok("fixture reset: PHASES[11]-[14] back to the module definitions", N.PHASES[11] == P11_ORIG and N.PHASES[12] == P12_ORIG
   and N.PHASES[13] == P13_ORIG and N.PHASES[14] == P14_ORIG and 99 not in N.PHASES)
bad = [k_ for k_, v in checks if not v]
print(f"\n{len(checks) - len(bad)}/{len(checks)} checks passed in {time.perf_counter() - T_START:.0f} s" + (f"; FAILED: {bad}" if bad else ""))
sys.exit(1 if bad else 0)
