"""Run with the repo venv: PYTHONUTF8=1 .venv-mobo/Scripts/python.exe v2/tests/test_s7_phase11_3406.py
Local only: fake queue in the system temp dir; jobs.femur_for / collar_rule templating / resorption.design_rows / mobo monkeypatched or stubbed;
no gmsh, no FE, no Linux, nothing under ~/mobo_toy_v2 is touched; single process (serial Pool stand-in). PHASES[11] is restored at the end
of every block that patches it.

S7 (2026-10-24): stage_neckopt phase 11 on the Sawbones 3406 (femur_id sawbone3406, neck_axis isthmus, stage prefix sb11, explicit intact_job).
A. PHASES[11] production definition; Phase(11) fields (femur_id / neck_axis explicit or hook default / intact_job None / stage sb11);
   Phase(10) unchanged (CT, stage neck10); intact_job on a CT phase -> ValueError.
B. spec_of: keys, stage sb11, neck_axis always explicit, intact_job ONLY on bonded specs, fric_only per bonded=False, bonded spec without
   intact_job -> ValueError; job ids: sb11_ prefix, fric_only id independent of intact_job, J.submit accepts sb11 (fake queue).
C. in_family isolation: CT neck11 record never enters phase 11; sb11 record with another / omitted neck_axis never enters; own specs enter;
   other sb* stages enter (warm start within the femur), mis-staged neck11 3406 record does not; Phase(10) rejects sb11 records and CT
   records staged sb11; intact_job is not a family key (documented).
D. pool_key: phase 10 == old formula; phase 11 changes with femur_id and with neck_axis (independently); restored values reproduce the key.
E. _feasible / refresh_pool / gated_pool obtain the femur via jobs.femur_for({"femur_id", "neck_axis"}) (monkeypatched, calls recorded),
   cache per (femur_id, neck_axis), with_cut per design, templating sees the 3406 femur under the (20, 2000) cap with margin_check dense,
   loss = resected_volume(ref_cut_mm=16) + stem volume; pool json records femur_id / neck_axis / margin_check; CT phase 10 asks femur_for
   with femur_id None and neck_axis None.
F. _calcar: femur_id record -> resorption.design_rows(job_id, iname=spec intact_job); CT record -> design_rows(job_id) with no iname;
   femur_id record without intact_job -> (None, None) and design_rows not called.
G. launcher refusal: check_launch / bo / bo_async raise ValueError while intact_job is None (gated_pool never reached, nothing written);
   missing dir / wrong femur / wrong neck_axis / wrong kind / wrong h_int / cfg refused; the S3 intact spec (DONE) passes; bo_async with that
   intact (mobo stubbed, budget 0) adopts sb11_* jobs and ignores neck11_* ones; state carries stage / neck_axis / intact_job.
H. dataset (record_of monkeypatched): DONE CT neck11 record is not a phase-11 warm start; own sb11 records are excluded (records take over);
   a DONE sb10 3406 record of the same family is.
"""
import copy
import hashlib
import json
import math
import pathlib
import shutil
import sys
import tempfile
import types

import numpy as np

ROOT = pathlib.Path(r"H:/projects/Femoral implant generation/sandbox/mobo_toy")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "v2"))
SCR = pathlib.Path(tempfile.gettempdir()) / "mobo_toy_s7_tests" / "fake_queue"      # fake queue outside the repo and outside ~/mobo_toy_v2
shutil.rmtree(SCR, ignore_errors=True)
(SCR / "queue").mkdir(parents=True)
(SCR / "results").mkdir()

import jobs as J  # noqa: E402
import geom3d as G  # noqa: E402
import femur_3406 as F6  # noqa: E402
import collar_rule as CR  # noqa: E402
import stage_neckopt as N  # noqa: E402
import stage_v2a as S  # noqa: E402

J.QROOT, J.RESULTS = SCR / "queue", SCR / "results"
assert J.QROOT.exists() and not str(J.QROOT).startswith(str(pathlib.Path.home() / "mobo_toy_v2"))
FID = "sawbone3406"
HASHED = tuple(float(x) for x in G.A_BOUNDS)
CAP = (HASHED[0], 2000.0)
P11_ORIG = copy.deepcopy(N.PHASES[11])
checks = []


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


def restore_p11():
    N.PHASES[11].clear()
    N.PHASES[11].update(copy.deepcopy(P11_ORIG))


# ---------------------------------------------------------------- fakes (no distance fields, no gmsh, no FE)
FEMUR_FOR_CALLS, TPL_CALLS, RV_CALLS = [], [], []


class FakeFemur:
    def __init__(self, femur_id=None, neck_axis=None):
        self.femur_id, self.neck_axis = femur_id, neck_axis
        self.lm = {"neck_axis": {"option": neck_axis or F6.DEFAULT_NECK_AXIS, "source": "fake"} if femur_id else None}
        self.cfg = {"prosthesis": {"neck_radius_mm": 7.0, "head_radius_mm": 14.0},
                    "femur": {"E_cancellous": 155.0 if femur_id else 400.0, "cut_from_head_mm": 25.0}, "load": {"F": 1.0}}
        self.H = np.array([50.0, 2.0, 48.0])
        u = np.array([0.92, 0.06, 0.38])
        self.u3 = u / np.linalg.norm(u)
        self.cut_from_head_mm = 25.0
        self.C03 = self.H - 25.0 * self.u3

    def with_cut(self, h):
        f = copy.copy(self)
        f.cut_from_head_mm = float(h)
        f.C03 = f.H - float(h) * f.u3
        return f

    def resected_volume(self, cut_from_head_mm=None, ref_cut_mm=25.0):          # femur_real.RealFemur signature
        RV_CALLS.append((self.femur_id, round(self.cut_from_head_mm, 6), float(ref_cut_mm)))
        return 1000.0 + 100.0 * (25.0 - float(ref_cut_mm))                      # ref 25 -> 1000, ref 16 -> 1900

    def pose(self, a, e):
        return np.array([0.0, 0.0, 29.5]), np.array([0.0, 0.0, -1.0]), np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])


def fake_femur_for(spec):
    """jobs.femur_for stand-in: records the spec, runs the real femur_hook (import + install, as the real femur_for does), returns a fake."""
    FEMUR_FOR_CALLS.append(dict(spec))
    J.femur_hook(spec)
    fm = FakeFemur(spec.get("femur_id"), spec.get("neck_axis"))
    return fm.with_cut(spec["h_cut"]) if spec.get("h_cut") is not None else fm


TPL = {"fit": True, "alpha": 35.26, "e": -2.0, "A0": 760.0, "contact": 0.0, "s_bind": 0.0, "volume": 3300.0, "margin": 0.5147}


def fake_tpl(stem, fem, **kw):
    mc = kw.get("margin_check") or CR.MARGIN_CHECK
    TPL_CALLS.append({"A_BOUNDS": tuple(G.A_BOUNDS), "margin_check": mc, "cut": round(fem.cut_from_head_mm, 6), "femur_id": fem.femur_id,
                      "neck_axis": fem.neck_axis})
    return {**TPL, "margin_check": mc, "pose": fem.pose(35.26, -2.0), "collar_rule": "neck_in_shoulder"}


class SerialPool:                                                                # multiprocessing.Pool stand-in: same _feasible, same process
    def __init__(self, n):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def map(self, f, it, chunksize=1):
        return [f(x) for x in it]


J.femur_for = fake_femur_for
CR.template_neck_in_shoulder = fake_tpl
N.Pool = SerialPool

# ================================================================ A. PHASES[11] / Phase fields
p10, p11 = N.PHASES[10], N.PHASES[11]
ok("PHASES[11] production: femur_id sawbone3406, neck_axis isthmus, intact_job = the solved 3406 reference (2026-10-24); everything else as before",
   p11["femur_id"] == FID and p11["neck_axis"] == "isthmus" and p11.get("intact_job") == "sb_intact_h2_9c9d7fb5"
   and p11["sed"] == "none" and p11["bond_every"] == 5 and p11["margin_check"] == "dense" and p11["ref_cut_mm"] == 16.0 and p11["a_bounds_max"] == 2000.0
   and p11["vars"]["h_cut"] == (16.0, 32.0) and p11["fixed"] == p10["fixed"] and p11["collar_rule"] == "neck_in_shoulder" and p11["metric"] == "v3")
ok("PHASES[10] untouched: no femur_id / neck_axis / intact_job keys", not any(k in p10 for k in ("femur_id", "neck_axis", "intact_job")))
ok("PHASES[11].neck_axis == femur_3406.DEFAULT_NECK_AXIS (explicit copy of the S0 decision)", p11["neck_axis"] == F6.DEFAULT_NECK_AXIS == "isthmus")
ph11, ph10 = N.Phase(11), N.Phase(10)
ok("Phase(11): femur_id, neck_axis isthmus, intact_job = 3406 reference, stage sb11 / prefix sb, bond_every 5, margin dense, ref 16, amax 2000",
   ph11.femur_id == FID and ph11.neck_axis == "isthmus" and ph11.intact_job == "sb_intact_h2_9c9d7fb5" and ph11.stage == "sb11" and ph11.stage_prefix == "sb"
   and ph11.bond_every == 5 and ph11.margin_check == "dense" and ph11.ref_cut_mm == 16.0 and ph11.a_bounds_max == 2000.0)
ok("Phase(10): femur_id None, neck_axis None, intact_job None, stage neck10 / prefix neck",
   ph10.femur_id is None and ph10.neck_axis is None and ph10.intact_job is None and ph10.stage == "neck10" and ph10.stage_prefix == "neck")
del N.PHASES[11]["neck_axis"]
ok("Phase(11) without a neck_axis entry falls back to the hook default (femur_3406.DEFAULT_NECK_AXIS)", N.Phase(11).neck_axis == F6.DEFAULT_NECK_AXIS)
N.PHASES[11]["neck_axis"] = [0.76, -0.23, 0.60]
ok("Phase(11) accepts a vector neck_axis", N.Phase(11).neck_axis == [0.76, -0.23, 0.60])
restore_p11()
N.PHASES[11]["femur_id"] = None
N.PHASES[11]["intact_job"] = None
ok("neck_axis is ignored for a CT phase (femur_id None -> neck_axis None)", N.Phase(11).neck_axis is None)
N.PHASES[11]["intact_job"] = "ref_intact_h2_x"
ok("intact_job on a CT phase -> ValueError (CT phases auto-pick ref_intact_h*)", raises(ValueError, N.Phase, 11) is not None)
restore_p11()
ok("femur_default_axis: None -> None, sawbone3406 -> isthmus, unknown -> KeyError",
   N.femur_default_axis(None) is None and N.femur_default_axis(FID) == "isthmus" and raises(KeyError, N.femur_default_axis, "nope") is not None)

# ================================================================ B. spec_of
n = len(ph11.vars)
um = np.full(n, 0.5)
s_fo = ph11.spec_of(um, "a0", bonded=False)
ok("spec_of(11, fric_only): stage sb11, femur_id, neck_axis isthmus (explicit), fric_only True, NO intact_job, ref 16 / amax 2000 / margin dense, m1 + FRIC",
   s_fo["stage"] == "sb11" and s_fo["femur_id"] == FID and s_fo["neck_axis"] == "isthmus" and s_fo["fric_only"] is True and "intact_job" not in s_fo
   and s_fo["ref_cut_mm"] == 16.0 and s_fo["a_bounds_max"] == 2000.0 and s_fo["margin_check"] == "dense" and s_fo["model"] == "m1"
   and s_fo["slip_tol"] == 2.5e-4 and s_fo["delta"] == 0.025 and s_fo["collar_rule"] == "neck_in_shoulder" and s_fo["h_cut"] == 24.0
   and s_fo["kind"] == "design" and s_fo["h_int"] == S.H_PROD and s_fo["min_A0"] == S.MIN_A0 and s_fo["tag"] == "a0", json.dumps(sorted(s_fo)))
N.PHASES[11]["intact_job"] = None
ph_noref = N.Phase(11)
restore_p11()
e_b = raises(ValueError, ph_noref.spec_of, um, "a4", True)
e_n = raises(ValueError, ph_noref.spec_of, um, "a4")
ok("spec_of(11, bonded True / None) with intact_job None -> ValueError naming PHASES[11]['intact_job']",
   e_b is not None and "intact_job" in e_b and e_n is not None and "intact_job" in e_n, (e_b or "")[:100])
INTACT = {"kind": "intact", "h_int": 2.0, "stage": "sb", "tag": "intact_h2", "femur_id": FID, "neck_axis": "isthmus"}   # S3_done.md form
iid = J.job_id(INTACT)
N.PHASES[11]["intact_job"] = iid
ph11 = N.Phase(11)
s_b, s_n = ph11.spec_of(um, "a4", bonded=True), ph11.spec_of(um, "a4")
ok("spec_of(11, bonded True / None) with intact_job set: carries intact_job == the intact id, no fric_only; both identical",
   s_b.get("intact_job") == iid and "fric_only" not in s_b and s_b == s_n)
ok("spec_of(11, fric_only) with intact_job set: still NO intact_job (fric_only post never reads a reference)", "intact_job" not in ph11.spec_of(um, "a0", bonded=False))
ok("bonded and fric_only specs differ only in fric_only / intact_job (and the tag)",
   {k: v for k, v in s_b.items() if k not in ("intact_job", "tag")} == {k: v for k, v in s_fo.items() if k not in ("fric_only", "tag")})
ok("fric_only job id does not depend on intact_job (same id before and after filling it in); bonded id does",
   J.job_id(ph11.spec_of(um, "a0", bonded=False)) == J.job_id(s_fo) and J.job_id(s_b) != J.job_id({**s_b, "intact_job": "sb_intact_h2_other"}))
ok("job ids start with sb11_ (stage not hashed, prefix from Phase.stage)", J.job_id(s_fo).startswith("sb11_a0_") and J.job_id(s_b).startswith("sb11_a4_"))
ok("neck_axis is part of the id (omitting it is another job, S3)", J.job_id(s_fo) != J.job_id({k: v for k, v in s_fo.items() if k != "neck_axis"}))
jid_fo = J.submit(s_fo)
ok("J.submit accepts the sb11 fric_only spec (fake queue), id == job_id(spec)", jid_fo == J.job_id(s_fo) and (J.QROOT / jid_fo / "spec.json").exists())
ok("J.submit still refuses the same spec staged neck11 (S3 guard)", raises(ValueError, J.submit, {**s_fo, "stage": "neck11"}) is not None)

# ================================================================ C. in_family isolation
ct11 = {k: v for k, v in s_fo.items() if k not in ("femur_id", "neck_axis")} | {"stage": "neck11"}     # the pre-S7 CT phase-11 shape
ok("in_family(11): own fric_only and bonded specs accepted", ph11.in_family(s_fo) and ph11.in_family(s_b))
ok("in_family(11): CT neck11 record (no femur_id) rejected", not ph11.in_family(ct11))
ok("in_family(11): CT record with the right stage prefix but no femur_id rejected", not ph11.in_family({**ct11, "stage": "sb11"}))
ok("in_family(11): sb11 record with neck_axis detector / readme / vector / None / omitted rejected",
   not ph11.in_family({**s_fo, "neck_axis": "detector"}) and not ph11.in_family({**s_fo, "neck_axis": "readme"})
   and not ph11.in_family({**s_fo, "neck_axis": [0.76, -0.23, 0.60]}) and not ph11.in_family({**s_fo, "neck_axis": None})
   and not ph11.in_family({k: v for k, v in s_fo.items() if k != "neck_axis"}))
ok("in_family(11): 3406 record mis-staged neck11 rejected (prefix sb required); other sb* stages accepted (sb10, sb)",
   not ph11.in_family({**s_fo, "stage": "neck11"}) and ph11.in_family({**s_fo, "stage": "sb10"}) and ph11.in_family({**s_fo, "stage": "sb"}))
ok("in_family(11): other femur_id rejected; margin sparse rejected; ref 25 rejected; h_cut 15.9 rejected",
   not ph11.in_family({**s_fo, "femur_id": "other"}) and not ph11.in_family({k: v for k, v in s_fo.items() if k != "margin_check"})
   and not ph11.in_family({**s_fo, "ref_cut_mm": 25.0}) and not ph11.in_family({**s_fo, "h_cut": 15.9}))
ok("in_family(11): intact_job is not a family key (bonded record against another reference still enters; metric v3 does not use it)",
   ph11.in_family({**s_b, "intact_job": "sb_intact_h2_other"}))
ok("in_family(11): JSON round trip of the own spec accepted", ph11.in_family(json.loads(json.dumps(s_fo))))
ok("in_family(10): sb11 3406 records rejected (femur_id); CT record staged sb11 rejected (prefix neck); own neck10 spec accepted",
   not ph10.in_family(s_fo) and not ph10.in_family({**ct11, "ref_cut_mm": 25.0, "stage": "sb11", "h_cut": 28.0})
   and ph10.in_family(ph10.spec_of(um, "t")))

# ================================================================ D. pool_key
old10 = hashlib.sha1((J.code_hash() + json.dumps(ph10.space, sort_keys=True) + json.dumps(ph10.fixed, sort_keys=True)
                      + json.dumps(N.CONST) + f"{16384}_{0}_v2" + "_neck_in_shoulder").encode()).hexdigest()[:8]
ok("pool_key(10, 16384, 0) == old formula (cached Linux pools stay valid)", N.pool_key(ph10, 16384, 0) == old10)
k11 = N.pool_key(ph11, 8192, 0)
N.PHASES[11]["neck_axis"] = "detector"
k_axis = N.pool_key(N.Phase(11), 8192, 0)
N.PHASES[11]["neck_axis"] = "isthmus"
N.PHASES[11]["femur_id"] = None
N.PHASES[11]["neck_axis"] = None
N.PHASES[11]["intact_job"] = None
k_ct = N.pool_key(N.Phase(11), 8192, 0)
restore_p11()
N.PHASES[11]["intact_job"] = iid
ok("pool_key(11): differs between isthmus / detector / CT; restored values reproduce the key; intact_job not in the key",
   len({k11, k_axis, k_ct}) == 3 and N.pool_key(N.Phase(11), 8192, 0) == k11, f"{k11} {k_axis} {k_ct}")

# ================================================================ E. _feasible / refresh_pool / gated_pool via jobs.femur_for
N._FM.clear(); FEMUR_FOR_CALLS.clear(); TPL_CALLS.clear(); RV_CALLS.clear()
G.A_BOUNDS = HASHED
okf, loss = N._feasible((um, 11, None))
ok("_feasible(11): femur via jobs.femur_for({'femur_id': 'sawbone3406', 'neck_axis': 'isthmus'}) exactly once, no h_cut in that call",
   FEMUR_FOR_CALLS == [{"femur_id": FID, "neck_axis": "isthmus"}], str(FEMUR_FOR_CALLS))
ok("_feasible(11): templating saw the 3406 femur (isthmus) cut at 24 under A_BOUNDS (20, 2000) with margin_check dense; feasible",
   okf and TPL_CALLS[-1] == {"A_BOUNDS": CAP, "margin_check": "dense", "cut": 24.0, "femur_id": FID, "neck_axis": "isthmus"}, str(TPL_CALLS[-1]))
ok("_feasible(11): loss = resected_volume(ref_cut_mm=16) on the 3406 cut femur + stem volume",
   RV_CALLS[-1] == (FID, 24.0, 16.0) and abs(loss - (1900.0 + 3300.0)) < 1e-9, f"{RV_CALLS[-1]} {loss}")
ok("after a 3406 _feasible: A_BOUNDS == install's (20, 2000) (femur_hook ran inside femur_for, as in jobs.prep)", tuple(G.A_BOUNDS) == CAP)
ok("_FM cache keyed by (femur_id, neck_axis)", (FID, json.dumps("isthmus")) in N._FM and len(N._FM) == 1, str(list(N._FM)))
u2 = np.full(n, 0.25)
N._feasible((u2, 11, None))
ok("second _feasible(11): femur_for not called again (cache), cut follows the design (20)", len(FEMUR_FOR_CALLS) == 1 and TPL_CALLS[-1]["cut"] == 20.0)
TPL_CALLS.clear()
Un, Ln = N.refresh_pool(ph11, um[None], k=3, rad=0.05, workers=1, seed=1)
ok("refresh_pool(11): 3 templating calls on the 3406 femur, 3 feasible, loss ref 16, still one femur_for call",
   len(TPL_CALLS) == 3 and all(c["femur_id"] == FID and c["neck_axis"] == "isthmus" and c["A_BOUNDS"] == CAP for c in TPL_CALLS)
   and len(Un) == 3 and np.allclose(Ln, 5200.0) and len(FEMUR_FOR_CALLS) == 1)
TPL_CALLS.clear()
U, L = N.gated_pool(ph11, n=4, seed=0, workers=1)
pj_path = next((J.RESULTS / "pools").glob("neckopt_p11_n4_s0_*.json"))
pj = json.loads(pj_path.read_text())
ok("gated_pool(11, n 4): 4 templating calls on the 3406 femur, pool json records femur_id / neck_axis / margin_check / ref / amax, key in file name",
   len(TPL_CALLS) == 4 and all(c["femur_id"] == FID for c in TPL_CALLS) and len(U) == 4 and pj["femur_id"] == FID and pj["neck_axis"] == "isthmus"
   and pj["margin_check"] == "dense" and pj["ref_cut_mm"] == 16.0 and pj["a_bounds_max"] == 2000.0 and k11.replace(k11, N.pool_key(ph11, 4, 0)) in pj_path.name)
ok("gated_pool(11) h_cut of the Sobol points within 16–32", all(16.0 <= ph11.design_of(u)[1] <= 32.0 for u in U))
F6.uninstall()
G.A_BOUNDS = HASHED
FEMUR_FOR_CALLS.clear(); TPL_CALLS.clear()
okf10, loss10 = N._feasible((um, 10, None))
ok("_feasible(10): femur_for({'femur_id': None, 'neck_axis': None}) (CT path), templating on the CT femur at cut 28.5 under hashed bounds, ref 25",
   okf10 and FEMUR_FOR_CALLS == [{"femur_id": None, "neck_axis": None}] and TPL_CALLS[-1] == {"A_BOUNDS": HASHED, "margin_check": "sparse", "cut": 28.5, "femur_id": None, "neck_axis": None}
   and RV_CALLS[-1] == (None, 28.5, 25.0) and abs(loss10 - 4300.0) < 1e-9 and tuple(G.A_BOUNDS) == HASHED, f"{FEMUR_FOR_CALLS} {TPL_CALLS[-1]}")
ok("_FM now holds both femurs", set(N._FM) == {(FID, json.dumps("isthmus")), (None, "null")})

# ================================================================ F. _calcar -> resorption.design_rows(job_id, iname=intact_job)
RS_CALLS = []


def fake_design_rows(dname, *a, **kw):
    RS_CALLS.append((dname, a, kw))
    return [{"scheme": "fixed", "zone": "G7", "tissue": "cortex", "ssi_pct": 12.5, "sed_chg_pct": -8.0}], {}


rs_stub = types.ModuleType("resorption")
rs_stub.design_rows = fake_design_rows
_real_rs = sys.modules.get("resorption")
sys.modules["resorption"] = rs_stub
jid_b = J.submit(s_b)                                                        # sb11 bonded spec with intact_job
jid_ct = J.submit({**ph10.spec_of(um, "c0"), "tag": "c0"})                  # CT neck10 spec
noref = J.QROOT / "sb11_noref_fake"
noref.mkdir()
(noref / "spec.json").write_text(json.dumps({k: v for k, v in s_b.items() if k != "intact_job"}))
v = N._calcar(jid_b)
ok("_calcar(3406 bonded record): design_rows(job_id, iname=<spec intact_job>), G7 cortex fixed row -> (12.5, -8.0)",
   v == (12.5, -8.0) and RS_CALLS[-1] == (jid_b, (), {"iname": iid}), str(RS_CALLS[-1]))
v = N._calcar(jid_ct)
ok("_calcar(CT record): design_rows(job_id) with no iname (call unchanged)", v == (12.5, -8.0) and RS_CALLS[-1] == (jid_ct, (), {}), str(RS_CALLS[-1]))
n_rs = len(RS_CALLS)
v = N._calcar("sb11_noref_fake")
ok("_calcar(3406 record without intact_job): (None, None), design_rows not called", v == (None, None) and len(RS_CALLS) == n_rs)
ok("_calcar results cached in _SSI", N._SSI[jid_b] == (12.5, -8.0) and N._SSI["sb11_noref_fake"] == (None, None))
if _real_rs is not None:
    sys.modules["resorption"] = _real_rs
else:
    del sys.modules["resorption"]

# ================================================================ G. launcher refusal (check_launch / bo / bo_async)
mobo_stub = types.ModuleType("mobo")
mobo_stub.fit_gp = None
sys.modules["mobo"] = mobo_stub
_real_gated = N.gated_pool


def gated_trap(*a, **k):
    raise AssertionError("gated_pool reached although the launcher should have refused")


N.gated_pool = gated_trap
ok("check_launch(Phase(10)) is a no-op for CT phases", N.check_launch(ph10) is None)
N.PHASES[11]["intact_job"] = None
ph_none = N.Phase(11)
e = raises(ValueError, N.check_launch, ph_none)
ok("check_launch(11) with intact_job None -> ValueError that names intact_job and the femur", e is not None and "intact_job" in e and FID in e, (e or "")[:120])
e_async = raises(ValueError, N.bo_async, ph_none, 0, 1, 0, 1, None)
e_sync = raises(ValueError, N.bo, ph_none, 0, 0, 1, 0, 1, None)
ok("bo_async / bo with intact_job None -> ValueError before gated_pool / dataset / any write (no state file)",
   e_async is not None and "intact_job" in e_async and e_sync is not None and "intact_job" in e_sync and not N.out_path(11).exists(), (e_async or "")[:80])
N.PHASES[11]["intact_job"] = "sb_intact_h2_missing"
ok("check_launch(11): intact_job not in the queue -> ValueError", (raises(ValueError, N.check_launch, N.Phase(11)) or "").find("no spec.json") >= 0)
N.PHASES[11]["intact_job"] = iid
idir = J.QROOT / iid
idir.mkdir(exist_ok=True)
for name, bad in (("wrong femur", {**INTACT, "femur_id": None}), ("wrong axis", {**INTACT, "neck_axis": "detector"}),
                  ("wrong kind", {**INTACT, "kind": "design"}), ("wrong h_int", {**INTACT, "h_int": 1.4}), ("cfg override", {**INTACT, "cfg": {"load": {"F": 2.0}}})):
    (idir / "spec.json").write_text(json.dumps(bad))
    e = raises(ValueError, N.check_launch, N.Phase(11))
    ok(f"check_launch(11): intact with {name} -> ValueError", e is not None and "not this phase's reference" in e, (e or "")[:100])
(idir / "spec.json").write_text(json.dumps(INTACT))
ok("check_launch(11): the S3 intact spec, not yet DONE -> passes (warning only)", N.check_launch(N.Phase(11)) is None)
(idir / "DONE").write_text("x")
(idir / "result.json").write_text(json.dumps({"gruen7": 1.0, "gruen1": 1.0}))
ok("check_launch(11): the S3 intact spec, DONE -> passes", N.check_launch(N.Phase(11)) is None)
N.gated_pool = _real_gated

# bo_async adoption with a passing intact: sb11_* jobs adopted, neck11_* ignored (budget 0 -> nothing submitted; FAILED jobs -> no stability / calcar).
# Every sb11_* dir must be DONE / FAILED here: a NEW one would be adopted as pending and bo_async would poll it forever.
ph11 = N.Phase(11)
shutil.rmtree(noref)
for j in (jid_fo, jid_b):
    (J.QROOT / j / "FAILED.json").write_text(json.dumps({"level": "L1", "stage": "prep", "reason": "fake"}))
N.PHASES[11].update(femur_id=None, neck_axis=None, intact_job=None)
ct_spec = N.Phase(11).spec_of(um, "a0", bonded=False)                       # CT-shaped phase-11 job (pre-S7 form), stage neck11
restore_p11()
N.PHASES[11]["intact_job"] = iid
jid_ct11 = J.submit(ct_spec)
(J.QROOT / jid_ct11 / "FAILED.json").write_text(json.dumps({"level": "L1", "stage": "prep", "reason": "fake"}))
pool4 = np.random.default_rng(0).random((4, n))
N.gated_pool = lambda ph, n=8192, seed=0, workers=6: (pool4, np.full(4, 5200.0))
st = N.bo_async(ph11, budget=0, inflight=1, seed=0, workers=1, legacy_warm=None, poll=0.01)
N.gated_pool = _real_gated
ok("bo_async(11, budget 0): adopts the two FAILED sb11_* jobs only (neck11_* CT job ignored), pending empty, nothing submitted",
   sorted(r["job_id"] for r in st["records"]) == sorted([jid_fo, jid_b]) and st["pending"] == {} and st["n_submitted"] == 2
   and {d.name for d in J.QROOT.glob("sb11_*")} == {jid_fo, jid_b}, str([r["job_id"] for r in st["records"]]))
ok("bo_async state carries stage sb11 / femur_id / neck_axis / intact_job / bond_every 5",
   st["stage"] == "sb11" and st["femur_id"] == FID and st["neck_axis"] == "isthmus" and st["intact_job"] == iid and st["bond_every"] == 5)
rec_fo = next(r for r in st["records"] if r["job_id"] == jid_fo)
rec_b = next(r for r in st["records"] if r["job_id"] == jid_b)
ok("adopted records: bonded False for the fric_only spec / True for the bonded one, ok False (FAILED), x from to_unit of the spec",
   rec_fo["bonded"] is False and rec_b["bonded"] is True and not rec_fo["ok"] and not rec_b["ok"]
   and np.allclose(rec_fo["x"], ph11.to_unit(s_fo["design"], s_fo["h_cut"])))
ok("state file written in the fake results dir", N.out_path(11).exists() and json.loads(N.out_path(11).read_text())["stage"] == "sb11")
N.out_path(11).unlink()

# ================================================================ H. dataset (warm start) isolation with record_of monkeypatched
_real_record_of = N.record_of
N.record_of = lambda jid, sed, metric="v1": {"y": [0.0, -1.0], "c": [-1.0], "ok": True}
for j in (jid_fo, jid_ct11):                                                 # make both DONE for the dataset scan
    (J.QROOT / j / "FAILED.json").unlink()
    (J.QROOT / j / "DONE").write_text("x")
jid_sb10 = J.submit({**s_fo, "stage": "sb10", "tag": "w"})
(J.QROOT / jid_sb10 / "DONE").write_text("x")
X, Y, C, ids = N.dataset(ph11)
ok("dataset(11): the DONE sb10 3406 record is the only warm start (own sb11 excluded, CT neck11 excluded, intact excluded)", ids == [jid_sb10], str(ids))
X, Y, C, ids = N.dataset(ph10)
ok("dataset(10): no 3406 record enters the CT phase 10", ids == [] or all(not i.startswith("sb") for i in ids), str(ids))
N.record_of = _real_record_of
restore_p11()
ok("fixture reset: PHASES[11] back to the production definition", N.PHASES[11] == P11_ORIG and N.Phase(11).intact_job == "sb_intact_h2_9c9d7fb5")

bad = [k for k, v in checks if not v]
print(f"\n{len(checks) - len(bad)}/{len(checks)} checks passed" + (f"; FAILED: {bad}" if bad else ""))
sys.exit(1 if bad else 0)
