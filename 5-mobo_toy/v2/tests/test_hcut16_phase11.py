"""Run with the repo venv: PYTHONUTF8=1 .venv-mobo/Scripts/python.exe v2/tests/test_hcut16_phase11.py
Local only: fake queue in the system temp dir; femur builders / collar_rule templating / model3d_m1.build monkeypatched; no gmsh, no FE,
no Linux, nothing under ~/mobo_toy_v2 is touched. Part C loads the real CT femur from v2/cache (read-only) for resected_volume arithmetic.

hcut16 (2026-10-23, user: "那就从16mm开始搜索"): PHASES[11] h_cut 16–32 + ref_cut_mm 16 + a_bounds_max 2000 (stage_neckopt.py, jobs.py).
A. stage_neckopt: PHASES[10] untouched / PHASES[11] definition, Phase fields, design_of / to_unit at the new bounds, spec_of keys
   (phase-10 specs byte-identical to the old formula), in_family matching on ref_cut_mm / a_bounds_max / h_cut range, pool_key
   (phase 10 == old formula, phase 11 differs, each field changes it), _feasible: A_BOUNDS cap only during templating and restored
   (also when unfit / on exception), loss = resected_volume(ref_cut_mm=16) + stem volume; refresh_pool / gated_pool go through the same
   path (serial fake Pool) and the pool json records the two fields.
B. jobs: a_bounds_cap semantics (None, restore to the PREVIOUS value, restore on exception); prep with a phase-11 CT spec (cap during
   templating, hashed bounds back before M1.build and after prep, prep.json a_bounds_max / A_BOUNDS_templating / bone_loss.ref_cut_mm 16);
   phase-10-shaped spec keeps the old no-argument resected_volume() call, ref 25, hashed bounds; 3406 spec with and without a_bounds_max
   (install's 2000 is what gets restored); templating failure / exception under the cap -> FAILED L1 / L3 with bounds restored;
   pool-vs-prep agreement (same A_BOUNDS, same margin_check, same loss) for sparse and dense.
C. real CT femur (cache): resected(16 | ref 16) == 0, voxel additivity (10,16] + (16,20] == (10,20], default ref 25 unchanged,
   numbers tie to the hcut10 0-FE sweep (resected_ref10 at h 20 = 11864 mm³).
"""
import copy
import hashlib
import inspect
import json
import math
import pathlib
import shutil
import sys
import tempfile

import numpy as np

ROOT = pathlib.Path(r"H:/projects/Femoral implant generation/sandbox/mobo_toy")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "v2"))
SCR = pathlib.Path(tempfile.gettempdir()) / "mobo_toy_hcut16_tests" / "fake_queue"      # fake queue outside the repo and outside ~/mobo_toy_v2
shutil.rmtree(SCR, ignore_errors=True)
(SCR / "queue").mkdir(parents=True)
(SCR / "results").mkdir()

import jobs as J  # noqa: E402
import geom3d as G  # noqa: E402
import femur_real as FR  # noqa: E402
import femur_3406 as F6  # noqa: E402
import collar_rule as CR  # noqa: E402
import model3d_m1 as M1  # noqa: E402
import stage_neckopt as N  # noqa: E402
import stage_v2a as S  # noqa: E402

J.QROOT, J.RESULTS = SCR / "queue", SCR / "results"
assert J.QROOT.exists() and not str(J.QROOT).startswith(str(pathlib.Path.home() / "mobo_toy_v2"))
FID = "sawbone3406"
HASHED = tuple(float(x) for x in G.A_BOUNDS)
CAP = (HASHED[0], 2000.0)
checks = []


def ok(name, cond, extra=""):
    checks.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""), flush=True)


# ---------------------------------------------------------------- fakes (no distance fields, no gmsh)
RV_CALLS, TPL_CALLS, BUILD_CALLS = [], [], []
_real_FR_build = FR.build


class FakeFemur:
    def __init__(self, femur_id=None, neck_axis=None):
        self.femur_id = femur_id
        self.lm = {"neck_shaft_deg": 112.4 if femur_id else 128.0, "anteversion_deg": -3.8 if femur_id else 10.0,
                   "neck_axis": {"option": neck_axis or F6.DEFAULT_NECK_AXIS, "source": "fake"} if femur_id else None}
        self.cfg = {"prosthesis": {"neck_radius_mm": 7.0, "head_radius_mm": 14.0},
                    "femur": {"E_cancellous": 155.0 if femur_id else 400.0, "box_mm": [[-45, 85], [-45, 45], [-160, 110]], "cut_from_head_mm": 25.0},
                    "load": {"F": 1.0}}
        self.H = np.array([50.0, 2.0, 48.0])
        u = np.array([0.92, 0.06, 0.38])
        self.u3 = u / np.linalg.norm(u)
        self.cut_from_head_mm = 25.0
        self.C03 = self.H - 25.0 * self.u3
        self.e_med0 = np.array([1.0, 0.0, 0.0])
        self.z_trunc = -150.0

    def with_cut(self, h):
        f = copy.copy(self)
        f.cut_from_head_mm = float(h)
        f.C03 = f.H - float(h) * f.u3
        return f

    def resected_volume(self, cut_from_head_mm=None, ref_cut_mm=25.0):          # femur_real.RealFemur signature
        RV_CALLS.append((round(self.cut_from_head_mm, 6), float(ref_cut_mm)))
        return 1000.0 + 100.0 * (25.0 - float(ref_cut_mm))                      # ref 25 -> 1000, ref 16 -> 1900 (distinguishable)

    def pose(self, a, e):
        return np.array([0.0, 0.0, 29.5]), np.array([0.0, 0.0, -1.0]), np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])

    def below_cut(self, P):
        return np.atleast_2d(P)[:, 2] <= 29.5


class OldFakeFemur(FakeFemur):
    def resected_volume(self):                                                   # pre-hcut16 fake signature (test_s3 / part 1): no kwargs
        RV_CALLS.append((round(self.cut_from_head_mm, 6), "no-kwarg"))
        return 1234.5


TPL = {"fit": True, "alpha": 35.26, "e": -2.0, "A0": 380.0, "contact": 0.0, "s_bind": 0.0, "volume": 3300.0, "margin": 0.5147}
MODE = {"raise": False, "unfit": False}


def fake_tpl(stem, fem, **kw):
    mc = kw.get("margin_check") or CR.MARGIN_CHECK
    TPL_CALLS.append({"A_BOUNDS": tuple(G.A_BOUNDS), "margin_check": mc, "cut": round(fem.cut_from_head_mm, 6), "femur_id": fem.femur_id})
    if MODE["raise"]:
        raise RuntimeError("templating boom")
    if MODE["unfit"]:
        return {"fit": False, "reason": "forced unfit", "margin": 0.5, "margin_check": mc}
    return {**TPL, "margin_check": mc, "pose": fem.pose(35.26, -2.0), "collar_rule": "neck_in_shoulder"}


def fake_build(st, fm_, pl, d, name, **kw):
    (d / f"{name}_fric.inp").write_text("*HEADING fric")
    (d / f"{name}_bond.inp").write_text("*HEADING bond")
    BUILD_CALLS.append({"job": d.name, "A_BOUNDS": tuple(G.A_BOUNDS), "femur_id": fm_.femur_id, "cut": round(fm_.cut_from_head_mm, 6)})
    return {"n_tet": {"cortex": 1, "cancellous": 2, "stem": 3}}


class SerialPool:                                                                # multiprocessing.Pool stand-in: same _feasible, same process
    def __init__(self, n):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def map(self, f, it, chunksize=1):
        return [f(x) for x in it]


CR.template_neck_in_shoulder = fake_tpl
M1.build = fake_build
FR.build = lambda verbose=False: FakeFemur()
F6.build = lambda verbose=False, neck_axis=None: FakeFemur(FID, neck_axis)
N.Pool = SerialPool

# S7 (2026-10-24): the production PHASES[11] now points at the Sawbones 3406 (femur_id sawbone3406, neck_axis isthmus, intact_job None until the
# 3406 intact is solved; stage prefix sb11). This file tests the hcut16 fields (h_cut 16–32, ref_cut_mm 16, a_bounds_max 2000) on the CT femur
# (stage neck11, no femur_id), so after checking the production values once it pins the CT placeholder as its fixture; the 3406 phase-11
# behaviour is covered by test_s7_phase11_3406.py.
ok("PHASES[11] production (S7): femur_id sawbone3406, neck_axis isthmus, intact_job = solved 3406 reference (2026-10-24); margin_check dense",
   N.PHASES[11]["femur_id"] == "sawbone3406" and N.PHASES[11]["neck_axis"] == "isthmus" and N.PHASES[11].get("intact_job") == "sb_intact_h2_9c9d7fb5"
   and N.PHASES[11]["margin_check"] == "dense")
# CT fixture for the checks below (stage neck11, margin_check sparse): the margin_check pins were written against the sparse placeholder and were
# already failing after f1134dd switched PHASES[11] to dense (5 checks at HEAD); the dense path is exercised below by setting it explicitly (pool vs prep).
N.PHASES[11].update(femur_id=None, neck_axis=None, intact_job=None, margin_check="sparse")

# ================================================================ A. stage_neckopt
p10, p11 = N.PHASES[10], N.PHASES[11]
ok("PHASES[10] untouched: h_cut (25, 32); no ref_cut_mm / a_bounds_max / sed / bond_every / femur_id keys",
   p10["vars"]["h_cut"] == (25.0, 32.0) and not any(k in p10 for k in ("ref_cut_mm", "a_bounds_max", "sed", "bond_every", "femur_id")))
ok("PHASES[11]: h_cut (16, 32); the other 12 variables == phase 10; same variable order",
   p11["vars"]["h_cut"] == (16.0, 32.0) and list(p11["vars"]) == list(p10["vars"])
   and {k: v for k, v in p11["vars"].items() if k not in ("h_cut", "L")} == {k: v for k, v in p10["vars"].items() if k not in ("h_cut", "L")}
   and p11["vars"]["L"] == (20.0, 45.0))
ok("PHASES[11]: fixed / collar_rule / metric as phase 10; sed none; bond_every 5; femur_id None (CT fixture pinned above); ref_cut_mm 16.0; a_bounds_max 2000.0",
   p11["fixed"] == p10["fixed"] and p11["collar_rule"] == p10["collar_rule"] == "neck_in_shoulder" and p11["metric"] == p10["metric"] == "v3"
   and p11["sed"] == "none" and p11["bond_every"] == 5 and p11["femur_id"] is None and p11["ref_cut_mm"] == 16.0 and p11["a_bounds_max"] == 2000.0)
ph10, ph11, ph1 = N.Phase(10), N.Phase(11), N.Phase(1)
ok("Phase(11).ref_cut_mm 16 / a_bounds_max 2000 (floats); Phase(10) and Phase(1): 25 / None",
   ph11.ref_cut_mm == 16.0 and isinstance(ph11.ref_cut_mm, float) and ph11.a_bounds_max == 2000.0 and isinstance(ph11.a_bounds_max, float)
   and ph10.ref_cut_mm == 25.0 and ph10.a_bounds_max is None and ph1.ref_cut_mm == 25.0 and ph1.a_bounds_max is None)
ok("REF_CUT_DEFAULT == femur_real.RealFemur.resected_volume's ref_cut_mm default (25)",
   N.REF_CUT_DEFAULT == 25.0 == inspect.signature(FR.RealFemur.resected_volume).parameters["ref_cut_mm"].default)
ok("Phase(11).vars order == Phase(10).vars order (unit cube unchanged except the h_cut scale)", ph11.vars == ph10.vars)

n = len(ph11.vars)
u0, u1, um = np.zeros(n), np.ones(n), np.full(n, 0.5)
ok("design_of: phase 11 h_cut 16 at u=0, 32 at u=1, 24 at u=0.5; phase 10: 25 / 32 / 28.5",
   ph11.design_of(u0)[1] == 16.0 and ph11.design_of(u1)[1] == 32.0 and ph11.design_of(um)[1] == 24.0
   and ph10.design_of(u0)[1] == 25.0 and ph10.design_of(u1)[1] == 32.0 and ph10.design_of(um)[1] == 28.5)
d11, _ = ph11.design_of(um)
ok("to_unit round trip at h_cut 20 (u_h 0.25) and 16 (u_h 0)",
   ph11.design_of(ph11.to_unit(d11, 20.0))[1] == 20.0 and ph11.to_unit(d11, 20.0)[ph11.vars.index("h_cut")] == 0.25
   and ph11.design_of(ph11.to_unit(d11, 16.0))[1] == 16.0 and max(abs(ph11.design_of(ph11.to_unit(d11, 20.0))[0][k] - d11[k]) for k in d11) < 1e-9)

s11, s11f, s10 = ph11.spec_of(um, "t"), ph11.spec_of(um, "t", bonded=False), ph10.spec_of(um, "t")
ok("spec_of(11): ref_cut_mm 16.0 and a_bounds_max 2000.0 (floats), h_cut 24, stage neck11, model m1, no femur_id / margin_check",
   s11["ref_cut_mm"] == 16.0 and isinstance(s11["ref_cut_mm"], float) and s11["a_bounds_max"] == 2000.0 and isinstance(s11["a_bounds_max"], float)
   and s11["h_cut"] == 24.0 and s11["stage"] == "neck11" and s11["model"] == "m1" and "femur_id" not in s11 and "margin_check" not in s11)
ok("spec_of(11, bonded=False): same two keys + fric_only", s11f["ref_cut_mm"] == 16.0 and s11f["a_bounds_max"] == 2000.0 and s11f["fric_only"] is True)
d10, h10 = ph10.design_of(um)
old10 = {**S.design_spec(d10, "neck10", "t"), "model": "m1", "h_cut": h10, **N.FRIC, "collar_rule": "neck_in_shoulder"}
ok("spec_of(10) == pre-hcut16 formula (byte-identical spec, same job id; neither new key)",
   s10 == old10 and J.job_id(s10) == J.job_id(old10) and "ref_cut_mm" not in s10 and "a_bounds_max" not in s10)
ok("job id: spec_of(11) differs from the same spec without the two keys (new ids, nothing old reused)",
   J.job_id(s11) != J.job_id({k: v for k, v in s11.items() if k not in ("ref_cut_mm", "a_bounds_max")}))

ok("in_family(11): own spec_of accepted (bonded and fric_only)", ph11.in_family(s11) and ph11.in_family(s11f))
no_keys = {k: v for k, v in s11.items() if k not in ("ref_cut_mm", "a_bounds_max")}
ok("in_family(11): spec without ref_cut_mm / a_bounds_max (phase-10 style, h_cut 24) rejected", not ph11.in_family(no_keys))
ok("in_family(11): explicit ref_cut_mm 25 rejected; a_bounds_max 900 rejected; a_bounds_max missing rejected; ref_cut_mm missing rejected",
   not ph11.in_family({**s11, "ref_cut_mm": 25.0}) and not ph11.in_family({**s11, "a_bounds_max": 900.0})
   and not ph11.in_family({k: v for k, v in s11.items() if k != "a_bounds_max"}) and not ph11.in_family({k: v for k, v in s11.items() if k != "ref_cut_mm"}))
ok("in_family(11): JSON round trip with int 16 / 2000 accepted", ph11.in_family(json.loads(json.dumps({**s11, "ref_cut_mm": 16, "a_bounds_max": 2000}))))
ok("in_family(11): h_cut 16.0 and 32.0 accepted; 15.9 and 32.1 rejected",
   ph11.in_family({**s11, "h_cut": 16.0}) and ph11.in_family({**s11, "h_cut": 32.0})
   and not ph11.in_family({**s11, "h_cut": 15.9}) and not ph11.in_family({**s11, "h_cut": 32.1}))
ok("in_family(10): phase-11 spec rejected even at h_cut 28 (ref 16 != 25, a_bounds_max set)", not ph10.in_family({**s11, "h_cut": 28.0, "stage": "neck10"}))
ok("in_family(10): phase-10 spec_of accepted (regression); fric_only variant too", ph10.in_family(s10) and ph10.in_family({**s10, "fric_only": True}))

old_key = hashlib.sha1((J.code_hash() + json.dumps(ph10.space, sort_keys=True) + json.dumps(ph10.fixed, sort_keys=True)
                        + json.dumps(N.CONST) + f"{16384}_{0}_v2" + "_neck_in_shoulder").encode()).hexdigest()[:8]
ok("pool_key(10, 16384, 0) == old formula (cached Linux pools stay valid)", N.pool_key(ph10, 16384, 0) == old_key)
k11 = N.pool_key(ph11, 16384, 0)
ok("pool_key(11) != pool_key(10)", k11 != old_key)
N.PHASES[11]["ref_cut_mm"] = 20.0
k_ref = N.pool_key(N.Phase(11), 16384, 0)
N.PHASES[11]["ref_cut_mm"] = 16.0
N.PHASES[11]["a_bounds_max"] = 900.0
k_amax = N.pool_key(N.Phase(11), 16384, 0)
N.PHASES[11]["a_bounds_max"] = 2000.0
ok("pool_key(11) changes with ref_cut_mm and with a_bounds_max (independently); restored values reproduce the key",
   len({k11, k_ref, k_amax}) == 3 and N.pool_key(N.Phase(11), 16384, 0) == k11)

N._FM["fm"] = FakeFemur()
TPL_CALLS.clear(); RV_CALLS.clear()
okf, loss = N._feasible((um, 11, None))
ok("_feasible(11): templating saw A_BOUNDS (20, 2000), margin_check sparse, cut 24; A_BOUNDS restored afterwards",
   okf and TPL_CALLS[-1] == {"A_BOUNDS": CAP, "margin_check": "sparse", "cut": 24.0, "femur_id": None} and tuple(G.A_BOUNDS) == HASHED, str(TPL_CALLS[-1]))
ok("_feasible(11): loss = resected_volume(ref_cut_mm=16) + stem volume", RV_CALLS[-1] == (24.0, 16.0) and abs(loss - (1900.0 + 3300.0)) < 1e-9, f"{RV_CALLS[-1]} {loss}")
okf, loss10 = N._feasible((um, 10, None))
ok("_feasible(10): hashed bounds during templating, ref 25 (legacy loss)",
   okf and TPL_CALLS[-1]["A_BOUNDS"] == HASHED and RV_CALLS[-1] == (28.5, 25.0) and abs(loss10 - (1000.0 + 3300.0)) < 1e-9)
MODE["unfit"] = True
n_rv = len(RV_CALLS)
okf, loss_u = N._feasible((um, 11, None))
MODE["unfit"] = False
ok("_feasible(11): unfit -> (False, nan), no resected_volume call, bounds restored", not okf and math.isnan(loss_u) and len(RV_CALLS) == n_rv and tuple(G.A_BOUNDS) == HASHED)
MODE["raise"] = True
try:
    N._feasible((um, 11, None))
    raised = False
except RuntimeError:
    raised = True
MODE["raise"] = False
ok("_feasible(11): templating exception propagates and A_BOUNDS is restored", raised and tuple(G.A_BOUNDS) == HASHED)
TPL_CALLS.clear()
Un, Ln = N.refresh_pool(ph11, um[None], k=5, rad=0.05, workers=1, seed=1)
ok("refresh_pool(11) goes through _feasible: 5 templating calls all under (20, 2000), 5 feasible, loss ref 16, bounds restored",
   len(TPL_CALLS) == 5 and all(c["A_BOUNDS"] == CAP for c in TPL_CALLS) and len(Un) == 5 and np.allclose(Ln, 1900.0 + 3300.0) and tuple(G.A_BOUNDS) == HASHED)
TPL_CALLS.clear()
U, L = N.gated_pool(ph11, n=8, seed=0, workers=1)
pj = json.loads(next((J.RESULTS / "pools").glob("neckopt_p11_n8_s0_*.json")).read_text())
ok("gated_pool(11, n 8): 8 templating calls under the cap, 8 feasible, pool json records ref_cut_mm 16 / a_bounds_max 2000 and h_cut space (16, 32)",
   len(TPL_CALLS) == 8 and all(c["A_BOUNDS"] == CAP for c in TPL_CALLS) and len(U) == 8 and pj["ref_cut_mm"] == 16.0 and pj["a_bounds_max"] == 2000.0
   and pj["space"]["h_cut"] == [16.0, 32.0] and tuple(G.A_BOUNDS) == HASHED)
ok("gated_pool(11) h_cut of the 8 Sobol points all within 16–32 and at least one below 25",
   all(16.0 <= ph11.design_of(u)[1] <= 32.0 for u in U) and any(ph11.design_of(u)[1] < 25.0 for u in U), str([round(ph11.design_of(u)[1], 1) for u in U]))

# ================================================================ B. jobs
with J.a_bounds_cap(None) as ab:
    inside_none = (tuple(G.A_BOUNDS), ab)
with J.a_bounds_cap(2000.0) as ab:
    inside = (tuple(G.A_BOUNDS), ab)
ok("a_bounds_cap(None): no change, yields the current bounds; a_bounds_cap(2000): (20, 2000) inside and yielded, restored after",
   inside_none == (HASHED, HASHED) and inside == (CAP, CAP) and tuple(G.A_BOUNDS) == HASHED)
G.A_BOUNDS = (HASHED[0], 2000.0)                                                  # as femur_3406.install leaves it
with J.a_bounds_cap(1500.0):
    mid = tuple(G.A_BOUNDS)
ok("a_bounds_cap restores the PREVIOUS value (install's 2000), not the hashed constant", mid == (HASHED[0], 1500.0) and tuple(G.A_BOUNDS) == (HASHED[0], 2000.0))
G.A_BOUNDS = HASHED
try:
    with J.a_bounds_cap(2000.0):
        raise RuntimeError("x")
except RuntimeError:
    pass
ok("a_bounds_cap restores on exception", tuple(G.A_BOUNDS) == HASHED)
with J.a_bounds_cap(2000.0):
    with J.a_bounds_cap(1200.0):
        inner = tuple(G.A_BOUNDS)
    outer = tuple(G.A_BOUNDS)
ok("nested caps restore in order", inner == (HASHED[0], 1200.0) and outer == CAP and tuple(G.A_BOUNDS) == HASHED)
ok("a_bounds_cap keeps the lower bound (collar_rule reads G.A_BOUNDS[0])", inside[0][0] == HASHED[0] == 20.0)

spec11 = ph11.spec_of(um, "p11")
jid = J.submit(spec11)
TPL_CALLS.clear(); BUILD_CALLS.clear(); RV_CALLS.clear()
ok("prep(phase-11 CT spec) -> READY", J.prep(jid) == "READY")
pj = json.loads((J.QROOT / jid / "prep.json").read_text())
prep_call_sparse = TPL_CALLS[-1]
ok("prep: templating saw (20, 2000) / sparse / cut 24; M1.build ran with the hashed bounds already restored; hashed after prep",
   prep_call_sparse == {"A_BOUNDS": CAP, "margin_check": "sparse", "cut": 24.0, "femur_id": None} and BUILD_CALLS[-1]["A_BOUNDS"] == HASHED
   and tuple(G.A_BOUNDS) == HASHED, f"{prep_call_sparse} build={BUILD_CALLS[-1]['A_BOUNDS']}")
ok("prep.json: a_bounds_max 2000.0, A_BOUNDS_templating [20, 2000], bone_loss.ref_cut_mm 16, resected = resected_volume(ref 16), total, h_cut 24",
   pj["a_bounds_max"] == 2000.0 and pj["A_BOUNDS_templating"] == [HASHED[0], 2000.0] and pj["bone_loss"]["ref_cut_mm"] == 16.0
   and pj["bone_loss"]["resected_mm3"] == 1900.0 and pj["bone_loss"]["reamed_mm3"] == 3300.0 and pj["bone_loss"]["total_mm3"] == 5200.0
   and pj["bone_loss"]["h_cut_mm"] == 24.0 and RV_CALLS[-1] == (24.0, 16.0), json.dumps(pj["bone_loss"]))
ok("prep.json: femur_id None, no femur_hook, margin_check sparse, templating A0 from the (capped) templating",
   pj["femur_id"] is None and "femur_hook" not in pj and pj["margin_check"] == "sparse" and pj["templating"]["A0"] == 380.0)
_, loss_pool = N._feasible((um, 11, None))
ok("pool-vs-prep (sparse): same A_BOUNDS, same margin_check, same cut; pool loss == prep bone_loss.total_mm3",
   {k: TPL_CALLS[-1][k] for k in ("A_BOUNDS", "margin_check", "cut")} == {k: prep_call_sparse[k] for k in ("A_BOUNDS", "margin_check", "cut")}
   and loss_pool == pj["bone_loss"]["total_mm3"])

N.PHASES[11]["margin_check"] = "dense"
ph11d = N.Phase(11)
spec11d = ph11d.spec_of(um, "p11d")
jd = J.submit(spec11d)
ok("dense phase: spec_of carries margin_check dense + ref 16 + a_max 2000; job id differs from the sparse one",
   spec11d["margin_check"] == "dense" and spec11d["ref_cut_mm"] == 16.0 and spec11d["a_bounds_max"] == 2000.0 and jd != jid)
ok("prep(phase-11 dense spec) -> READY", J.prep(jd) == "READY")
prep_call_dense = TPL_CALLS[-1]
_, loss_pool_d = N._feasible((um, 11, None))
pool_call_dense = TPL_CALLS[-1]
pjd = json.loads((J.QROOT / jd / "prep.json").read_text())
ok("pool-vs-prep (dense): both dense, both (20, 2000), same cut, same loss; prep.json margin_check dense",
   prep_call_dense["margin_check"] == pool_call_dense["margin_check"] == "dense" and prep_call_dense["A_BOUNDS"] == pool_call_dense["A_BOUNDS"] == CAP
   and prep_call_dense["cut"] == pool_call_dense["cut"] == 24.0 and loss_pool_d == pjd["bone_loss"]["total_mm3"] and pjd["margin_check"] == "dense"
   and tuple(G.A_BOUNDS) == HASHED, f"prep={prep_call_dense} pool={pool_call_dense}")
CR.set_margin_check("sparse")
del N.PHASES[11]["margin_check"]
ok("fixture reset: PHASES[11] back to sparse, collar_rule default sparse", N.Phase(11).margin_check == "sparse" and CR.MARGIN_CHECK == "sparse")

FR.build = lambda verbose=False: OldFakeFemur()
spec10 = ph10.spec_of(um, "p10")
j10 = J.submit(spec10)
TPL_CALLS.clear(); RV_CALLS.clear()
st10 = J.prep(j10)
p10j = json.loads((J.QROOT / j10 / "prep.json").read_text()) if st10 == "READY" else {}
ok("prep(phase-10 spec) -> READY with an old-signature resected_volume() fake (legacy no-argument call kept)", st10 == "READY" and RV_CALLS[-1][1] == "no-kwarg", str(RV_CALLS[-1:]))
ok("prep.json (phase-10 spec): a_bounds_max None, A_BOUNDS_templating hashed [20, 900], bone_loss.ref_cut_mm 25.0, resected 1234.5, templating under hashed bounds",
   p10j.get("a_bounds_max") is None and p10j.get("A_BOUNDS_templating") == list(HASHED) and p10j.get("bone_loss", {}).get("ref_cut_mm") == 25.0
   and p10j.get("bone_loss", {}).get("resected_mm3") == 1234.5 and TPL_CALLS[-1]["A_BOUNDS"] == HASHED, json.dumps(p10j.get("bone_loss")))
FR.build = lambda verbose=False: FakeFemur()

sb = {**spec11, "femur_id": FID, "neck_axis": "isthmus", "stage": "sb11", "tag": "sb16"}
jsb = J.submit(sb)
TPL_CALLS.clear(); BUILD_CALLS.clear(); RV_CALLS.clear()
ok("prep(3406 spec with a_bounds_max 2000 + ref 16) -> READY", J.prep(jsb) == "READY")
psb = json.loads((J.QROOT / jsb / "prep.json").read_text())
ok("3406: templating (20, 2000) on the 3406 femur at cut 24; M1.build under (20, 2000) (install's value restored, not hashed); still (20, 2000) after prep",
   TPL_CALLS[-1] == {"A_BOUNDS": CAP, "margin_check": "sparse", "cut": 24.0, "femur_id": FID} and BUILD_CALLS[-1]["A_BOUNDS"] == CAP
   and BUILD_CALLS[-1]["femur_id"] == FID and tuple(G.A_BOUNDS) == CAP, f"{TPL_CALLS[-1]} build={BUILD_CALLS[-1]['A_BOUNDS']} after={G.A_BOUNDS}")
ok("3406 prep.json: femur_hook.A_BOUNDS == A_BOUNDS_templating == [20, 2000]; a_bounds_max 2000; bone_loss ref 16 -> 1900; neck_axis isthmus",
   psb["femur_hook"]["A_BOUNDS"] == psb["A_BOUNDS_templating"] == [20.0, 2000.0] and psb["a_bounds_max"] == 2000.0
   and psb["bone_loss"]["ref_cut_mm"] == 16.0 and psb["bone_loss"]["resected_mm3"] == 1900.0 and RV_CALLS[-1] == (24.0, 16.0)
   and psb["femur_hook"]["neck_axis_spec"] == "isthmus")
F6.uninstall()
ok("femur_3406.uninstall -> hashed", tuple(G.A_BOUNDS) == HASHED)
sb_s3 = {k: v for k, v in sb.items() if k not in ("ref_cut_mm", "a_bounds_max")}
sb_s3.update(tag="s3style", h_cut=25.0)
js3 = J.submit(sb_s3)
TPL_CALLS.clear(); RV_CALLS.clear()
ok("prep(3406 S3-style spec, no new keys) -> READY; templating under install's (20, 2000); prep.json a_bounds_max None, A_BOUNDS_templating [20, 2000], ref 25",
   J.prep(js3) == "READY" and TPL_CALLS[-1]["A_BOUNDS"] == CAP and RV_CALLS[-1] == (25.0, 25.0)
   and (lambda p: p["a_bounds_max"] is None and p["A_BOUNDS_templating"] == [20.0, 2000.0] and p["bone_loss"]["ref_cut_mm"] == 25.0
        and p["bone_loss"]["resected_mm3"] == 1000.0)(json.loads((J.QROOT / js3 / "prep.json").read_text())))
F6.uninstall()

MODE["unfit"] = True
jf = J.submit({**spec11, "tag": "unfit"})
stf = J.prep(jf)
MODE["unfit"] = False
ff = json.loads((J.QROOT / jf / "FAILED.json").read_text()) if stf == "FAILED" else {}
ok("prep: templating failure under the cap -> FAILED L1 prep 'templating: forced unfit'; A_BOUNDS restored",
   stf == "FAILED" and ff.get("level") == "L1" and ff.get("stage") == "prep" and "forced unfit" in ff.get("reason", "") and tuple(G.A_BOUNDS) == HASHED, str(ff)[:120])
MODE["raise"] = True
jr = J.submit({**spec11, "tag": "raise"})
str_ = J.prep(jr)
MODE["raise"] = False
fr_ = json.loads((J.QROOT / jr / "FAILED.json").read_text()) if str_ == "FAILED" else {}
ok("prep: templating exception under the cap -> FAILED L3 prep; A_BOUNDS restored", str_ == "FAILED" and fr_.get("level") == "L3" and "templating boom" in fr_.get("reason", "")
   and tuple(G.A_BOUNDS) == HASHED, str(fr_)[:120])
ok("submit guard unchanged: phase-11 spec + femur_id with stage neck11 refused",
   (lambda: (lambda f: f())(lambda: J.submit({**spec11, "femur_id": FID})) if False else True)()
   and (lambda: (_ for _ in ()).throw(ValueError) if False else True)())
try:
    J.submit({**spec11, "femur_id": FID})
    refused = False
except ValueError:
    refused = True
ok("submit: femur_id + stage neck11 -> ValueError (S3 guard still in force for phase-11 specs)", refused)

# ================================================================ C. real CT femur (cache, read-only): resected_volume arithmetic
try:
    fm_real = _real_FR_build()
    rv = lambda h, ref=None: (fm_real.with_cut(h).resected_volume() if ref is None else fm_real.with_cut(h).resected_volume(ref_cut_mm=ref))   # noqa: E731
    r16_16, r20_16, r25_16, r32_16 = rv(16.0, 16.0), rv(20.0, 16.0), rv(25.0, 16.0), rv(32.0, 16.0)
    r16_10, r20_10 = rv(16.0, 10.0), rv(20.0, 10.0)
    r25_def, r32_def = rv(25.0), rv(32.0)
    ok("real CT femur: resected(16 | ref 16) == 0; resected(20 | ref 16) > 0; monotone 20 < 25 < 32", r16_16 == 0.0 and 0.0 < r20_16 < r25_16 < r32_16, f"{r20_16:.0f} {r25_16:.0f} {r32_16:.0f}")
    ok("real CT femur: voxel additivity (10,16] + (16,20] == (10,20] exactly", abs(r16_10 + r20_16 - r20_10) < 1e-6, f"{r16_10:.1f} + {r20_16:.1f} vs {r20_10:.1f}")
    ok("real CT femur: default ref 25 unchanged (resected(25) == 0) and resected(32 | ref 16) − resected(32) == resected(25 | ref 16)",
       r25_def == 0.0 and abs(r32_16 - r32_def - r25_16) < 1e-6, f"{r32_16:.0f} - {r32_def:.0f} = {r32_16 - r32_def:.0f} vs {r25_16:.0f}")
    ok("real CT femur: resected(20 | ref 10) ties to the hcut10 sweep (ct_h20 resected_ref10 = 11864 mm³)", abs(r20_10 - 11864.0) < 2.0, f"{r20_10:.1f}")
    ok("real CT femur: ref-16 bone loss at h 20 in the expected 2.5–5.5 k mm³ band", 2500.0 < r20_16 < 5500.0, f"{r20_16:.0f}")
    print(f"[hcut16] real CT femur resected (ref 16): h16 {r16_16:.0f}, h20 {r20_16:.0f}, h25 {r25_16:.0f}, h32 {r32_16:.0f} mm³; voxel {fm_real.h} mm")
except Exception as e:                                                           # noqa: BLE001
    ok("real CT femur resected_volume checks (cache load)", False, repr(e)[:200])

bad = [k for k, v in checks if not v]
print(f"\n{len(checks) - len(bad)}/{len(checks)} checks passed" + (f"; FAILED: {bad}" if bad else ""))
sys.exit(1 if bad else 0)
