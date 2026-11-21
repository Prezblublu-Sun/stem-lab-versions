"""Run with the repo venv: PYTHONUTF8=1 .venv-mobo/Scripts/python.exe v2/tests/test_s3_femur_dispatch.py
Local only: fake queue in the system temp dir; femur_3406.build / femur_real.build / model builders monkeypatched; no FE, no Linux,
nothing under ~/mobo_toy_v2 is touched.

S3 (2026-10-23) femur_id dispatch + reference isolation (jobs.py, stage_v2a.py, shielding.py, resorption.py):
1. jobs.femur_hook / femur_for dispatch (CT path = FR.build unchanged; femur_id -> femur_3406.install + build(neck_axis)); job_id isolation.
2. jobs.submit stage guard (femur_id + stage "ref" / "neck*" refused, nothing created; "sb..." accepted; CT stage "ref" unaffected).
3. jobs.explicit_ref femur mismatch -> ValueError both directions; same femur -> ok; not DONE -> FileNotFoundError.
4. jobs.intact_ref isolation both directions (CT never picks a 3406 ref even if mis-staged and newer; femur_id -> ValueError, never
   auto-picks); jobs.ref_for keeps the two-argument CT call.
5. jobs.prep with femur_id (intact + design): prep.json carries femur_id / femur_hook.A_BOUNDS [20, 2000] / neck_axis; A_BOUNDS cap
   active while the model is built; CT prep.json unchanged (femur_id None, no femur_hook).
6. jobs.post: 3406 design with an explicit 3406 intact_job -> DONE, runs_v2a.jsonl carries femur_id; without intact_job -> FAILED L5;
   CT bonded path still calls intact_ref with two arguments (old monkeypatch signature keeps working).
7. stage_v2a.serve pre-check, one iteration: not-DONE reference -> job stays SOLVED; femur mismatch -> post -> FAILED L5, serve returns.
8. shielding.intact_job / design_jobs filter by femur_id (both directions); shielding.design_rows refuses a 3406 design.
9. resorption._CTX keyed by femur_id: grid + intact reference per femur, base_femur per (femur, neck_axis), design_rows takes the
   femur from the design's spec, intact_grid refuses a cross-femur reference.
"""
import copy
import json
import os
import pathlib
import shutil
import sys
import tempfile
import time
import types

import numpy as np

ROOT = pathlib.Path(r"H:/projects/Femoral implant generation/sandbox/mobo_toy")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "v2"))
SCR = pathlib.Path(tempfile.gettempdir()) / "mobo_toy_s3_tests" / "fake_queue"      # fake queue outside the repo and outside ~/mobo_toy_v2
shutil.rmtree(SCR, ignore_errors=True)
(SCR / "queue").mkdir(parents=True)
(SCR / "results").mkdir()

import jobs as J  # noqa: E402
import geom3d as G  # noqa: E402
import femur_real as FR  # noqa: E402
import femur_3406 as F6  # noqa: E402
import collar_rule as CR  # noqa: E402
import model3d_v2 as M  # noqa: E402
import model3d_m1 as M1  # noqa: E402
import post_m1 as PM1  # noqa: E402
import stage_v2a as S  # noqa: E402
import shielding as SH  # noqa: E402
import resorption as R  # noqa: E402

J.QROOT, J.RESULTS = SCR / "queue", SCR / "results"
assert J.QROOT.exists() and not str(J.QROOT).startswith(str(pathlib.Path.home() / "mobo_toy_v2"))
FID = "sawbone3406"
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


# ---------------------------------------------------------------- fake femurs (RealFemur / Femur3406 stand-ins; no distance fields)
class FakeFemur:
    def __init__(self, femur_id=None, neck_axis=None):
        self.femur_id = femur_id
        self.lm = {"neck_shaft_deg": 112.4 if femur_id else 128.0, "anteversion_deg": -3.8 if femur_id else 10.0,
                   "neck_axis": {"option": neck_axis or F6.DEFAULT_NECK_AXIS, "source": "fake"} if femur_id else None}
        self.cfg = {"prosthesis": {"neck_radius_mm": 7.0, "head_radius_mm": 14.0},
                    "femur": {"E_cancellous": 155.0 if femur_id else 400.0, "box_mm": [[-45, 85], [-45, 45], [-160, 110]],
                              "cut_from_head_mm": 25.0},
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

    def resected_volume(self):
        return 1234.5

    def pose(self, a, e):
        return np.array([0.0, 0.0, 29.5]), np.array([0.0, 0.0, -1.0]), np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])

    def below_cut(self, P):
        return np.atleast_2d(P)[:, 2] <= 29.5


calls = []
FR.build = lambda verbose=False: calls.append(("ct",)) or FakeFemur()
F6.build = lambda verbose=False, neck_axis=None: calls.append(("3406", neck_axis)) or FakeFemur(FID, neck_axis)
_real_install = F6.install
F6.install = lambda a_cap=F6.A_BOUNDS_CAP: calls.append(("install",)) or _real_install(a_cap)

DESIGN = {"L": 48.25, "rho_tip": 0.35, "q": 1.45, "lam": 1.67, "g_ml": 0.43, "g_ap": 0.51, "n_a": 2.96, "n_p": 5.40,
          "tau_a": -0.05, "tau_p": 0.106, "alpha": 29.7, "m": 0.5, "cap_h": 1.5}
CT_D = {"kind": "design", "design": DESIGN, "h_int": 2.0, "min_A0": S.MIN_A0, "model": "m1", "h_cut": 25.25,
        "slip_tol": 2.5e-4, "delta": 0.025, "collar_rule": "neck_in_shoulder"}
SB_D = {**CT_D, "h_cut": 25.0, "femur_id": FID, "neck_axis": "isthmus"}
SB_I = {"kind": "intact", "h_int": 2.0, "stage": "sb", "tag": "intact_h2", "femur_id": FID, "neck_axis": "isthmus"}
TPL = {"fit": True, "alpha": 29.7, "e": 0.0, "A0": 292.19, "contact": 0.0, "s_bind": 0.0, "volume": 3300.0, "margin": 0.5}

# ================================================================ 1. dispatch
A0 = tuple(G.A_BOUNDS)
ok("femur_hook({}) == (None, None)", J.femur_hook({}) == (None, None))
fm = J.femur_for({"h_cut": 26.0})
ok("CT path: FR.build only, cut 26, no install, A_BOUNDS untouched",
   fm.femur_id is None and fm.cut_from_head_mm == 26.0 and calls == [("ct",)] and tuple(G.A_BOUNDS) == A0, str(calls))
calls.clear()
f6 = J.femur_for({"femur_id": FID, "h_cut": 25.0, "neck_axis": "isthmus"})
ok("3406 path: install, then build(neck_axis='isthmus'), then cut 25",
   f6.femur_id == FID and calls == [("install",), ("3406", "isthmus")] and f6.cut_from_head_mm == 25.0
   and f6.lm["neck_axis"]["option"] == "isthmus", str(calls))
ok("install raised the A_BOUNDS cap to 2000 and kept the lower bound", tuple(G.A_BOUNDS) == (A0[0], 2000.0), str(G.A_BOUNDS))
F6.uninstall()
ok("uninstall restores the hashed A_BOUNDS", tuple(G.A_BOUNDS) == A0)
calls.clear()
f6b = J.femur_for({"femur_id": FID})
ok("3406 without neck_axis -> build(neck_axis=None) (module default), no cut", calls[-1] == ("3406", None) and f6b.cut_from_head_mm == 25.0)
F6.uninstall()
f6c = J.femur_for({"femur_id": FID, "cfg": {"load": {"F": 2.0}}})
ok("cfg override still applied on the 3406 copy", f6c.cfg["load"]["F"] == 2.0 and f6c.cfg["femur"]["E_cancellous"] == 155.0)
F6.uninstall()
ok("unknown femur_id -> KeyError", raises(KeyError, J.femur_for, {"femur_id": "nope"}) is not None)
spec_ct = {**CT_D, "stage": "sb11", "tag": "t"}
ok("job_id: same design, CT vs 3406 vs 3406+neck_axis all differ",
   len({J.job_id(spec_ct), J.job_id({**spec_ct, "femur_id": FID}), J.job_id({**spec_ct, "femur_id": FID, "neck_axis": "isthmus"})}) == 3)
ok("job_id: CT spec unchanged by the patch (hash ignores stage/tag only)", J.job_id(spec_ct) == J.job_id({**spec_ct, "tag": "other"}).replace("_other_", "_t_"))

# ================================================================ 2. submit stage guard
n0 = len(list(J.QROOT.glob("*")))
for st in ("ref", "neck11", "neck", "neckopt"):
    ok(f"submit femur_id + stage {st!r} -> ValueError", raises(ValueError, J.submit, {**SB_D, "stage": st, "tag": "x"}) is not None)
ok("refused submits created nothing", len(list(J.QROOT.glob("*"))) == n0)
jd_sb11 = J.submit({**SB_D, "stage": "sb11", "tag": "guardok"})
ok("submit femur_id + stage 'sb11' accepted, dir prefix sb11_", jd_sb11.startswith("sb11_guardok_") and (J.QROOT / jd_sb11 / "spec.json").exists())
ct_ref = J.submit(S.intact_spec(2.0))
ok("CT intact with stage 'ref' still accepted (ref_intact_h2_*)", ct_ref.startswith("ref_intact_h2_"))
ok("3406 'ref' tag with 'sb' stage accepted", J.submit(SB_I).startswith("sb_intact_h2_"))

# ---------------------------------------------------------------- fake references in the queue
def mark_done(jid, result, load_s=True):
    d = J.QROOT / jid
    (d / "result.json").write_text(json.dumps({**result, "job_id": jid}))
    (d / "DONE").write_text("x")
    (d / "intact_csv").mkdir(exist_ok=True)
    (d / "intact_csv" / "LOAD_ENER.csv").write_text("elem,else,evol\n")
    if load_s:
        (d / "intact_csv" / "LOAD_S.csv").write_text("elem,mises\n")


mark_done(ct_ref, {"gruen7": 1.0, "gruen1": 1.0})
sb_ref = J.submit(SB_I)
mark_done(sb_ref, {"gruen7": 2.0, "gruen1": 2.0})
# a mis-staged 3406 reference (cannot be submitted any more; created by hand) that the CT glob WOULD see, newer than ct_ref
bad = J.QROOT / "ref_intact_h2_bad_deadbeef"
bad.mkdir()
(bad / "spec.json").write_text(json.dumps({**SB_I, "stage": "ref"}))
mark_done(bad.name, {"gruen7": 9.0, "gruen1": 9.0}, load_s=False)
later = time.time() + 600
os.utime(bad, (later, later))
pending = J.submit({**SB_I, "tag": "intact_h2_pending"})                   # 3406 intact that is NOT done

# ================================================================ 3. explicit_ref
ok("explicit_ref: no intact_job -> None", J.explicit_ref(SB_D) is None)
ok("explicit_ref: 3406 design + 3406 ref -> ok", J.explicit_ref({**SB_D, "intact_job": sb_ref})["intact_job"] == sb_ref)
ok("explicit_ref: CT design + CT ref -> ok", J.explicit_ref({**CT_D, "intact_job": ct_ref})["gruen7"] == 1.0)
e = raises(ValueError, J.explicit_ref, {**SB_D, "intact_job": ct_ref})
ok("explicit_ref: 3406 design + CT ref -> ValueError", e is not None and "is for femur CT" in e, e)
e = raises(ValueError, J.explicit_ref, {**CT_D, "intact_job": sb_ref})
ok("explicit_ref: CT design + 3406 ref -> ValueError", e is not None and f"is for femur {FID}" in e, e)
ok("explicit_ref: reference not DONE -> FileNotFoundError", raises(FileNotFoundError, J.explicit_ref, {**SB_D, "intact_job": pending}) is not None)

# ================================================================ 4. intact_ref / ref_for
r = J.intact_ref(2.0)
ok("intact_ref(2.0) picks the CT reference, not the newer mis-staged 3406 one", r["intact_job"] == ct_ref and r["gruen7"] == 1.0, r["intact_job"])
r = J.intact_ref(1.4)
ok("intact_ref(1.4) falls back to the CT 2.0 reference (substituted), still not the 3406 one", r["intact_job"] == ct_ref and r["intact_substituted_h"] == 2.0)
e = raises(ValueError, J.intact_ref, 2.0, None, FID)
ok("intact_ref(..., femur_id) -> ValueError (never auto-picks)", e is not None and "explicit intact_job" in e, e)
ok("intact_ref(h, E_canc, femur_id): E_canc variant for 3406 also refused", raises(ValueError, J.intact_ref, 2.0, 155.0, FID) is not None)
e = raises(ValueError, J.ref_for, SB_D)
ok("ref_for(3406 design without intact_job) -> ValueError", e is not None and "explicit intact_job" in e, e)
ok("ref_for(3406 design + 3406 ref) -> that ref", J.ref_for({**SB_D, "intact_job": sb_ref})["intact_job"] == sb_ref)
ok("ref_for(3406 design + CT ref) -> ValueError", raises(ValueError, J.ref_for, {**SB_D, "intact_job": ct_ref}) is not None)
seen = []
_ir = J.intact_ref
J.intact_ref = lambda h, E=None: seen.append((h, E)) or {"intact_job": "two_arg", "gruen7": 1.0, "gruen1": 1.0, "intact_substituted_h": None}
ok("ref_for(CT design) calls intact_ref with the old two arguments", J.ref_for(CT_D)["intact_job"] == "two_arg" and seen == [(2.0, None)], str(seen))
ok("ref_for(CT design, E_canc) passes E_canc", J.ref_for({**CT_D, "E_canc": 300.0})["intact_job"] == "two_arg" and seen[-1] == (2.0, 300.0))
J.intact_ref = _ir

# ================================================================ 5. prep with femur_id (model builders monkeypatched)
built = {}


def fake_build(st, fm_, pl, d, name, **kw):
    (d / f"{name}_fric.inp").write_text("*HEADING fric")
    (d / f"{name}_bond.inp").write_text("*HEADING bond")
    built[d.name] = {"femur_id": fm_.femur_id, "A_BOUNDS": tuple(G.A_BOUNDS), "cut": fm_.cut_from_head_mm, "kw": kw}
    return {"n_tet": {"cortex": 1, "cancellous": 2, "stem": 3}}


def fake_intact(fm_, d, name, h_roi, h_far=6.0, E_canc=None):
    (d / f"{name}.inp").write_text("*HEADING intact")
    built[d.name] = {"femur_id": fm_.femur_id, "A_BOUNDS": tuple(G.A_BOUNDS), "h_roi": h_roi, "E_canc": E_canc}
    return {"n_tet": {"cortex": 10, "cancellous": 20}, "n_fixed": 12}


M1.build = fake_build
M.build_intact = fake_intact
CR.template_neck_in_shoulder = lambda stem, fem, **kw: {**TPL, "margin_check": kw.get("margin_check") or CR.MARGIN_CHECK,
                                                        "pose": fem.pose(29.7, 0.0), "collar_rule": "neck_in_shoulder"}

ji = J.submit({**SB_I, "tag": "intact_h2_prep"})
ok("prep 3406 intact -> READY", J.prep(ji) == "READY")
pi = json.loads((J.QROOT / ji / "prep.json").read_text())
ok("prep.json (intact): femur_id, femur_hook.A_BOUNDS [20, 2000], hashed bounds, E_canc 155",
   pi["femur_id"] == FID and pi["femur_hook"]["A_BOUNDS"] == [20.0, 2000.0] and pi["femur_hook"]["A_BOUNDS_hashed"] == list(A0)
   and pi["femur_hook"]["E_cancellous"] == 155.0, json.dumps(pi.get("femur_hook")))
ok("prep.json (intact): neck_axis_spec 'isthmus', resolved neck_axis, cut centre, angles",
   pi["femur_hook"]["neck_axis_spec"] == "isthmus" and pi["femur_hook"]["neck_axis"]["option"] == "isthmus"
   and len(pi["femur_hook"]["cut_centre_m"]) == 3 and pi["femur_hook"]["neck_shaft_deg"] == 112.4 and pi["femur_hook"]["anteversion_deg"] == -3.8)
ok("build_intact saw the 3406 femur with the cap active", built[ji]["femur_id"] == FID and built[ji]["A_BOUNDS"] == (A0[0], 2000.0))
F6.uninstall()

jd = J.submit({**SB_D, "stage": "sb11", "tag": "d0", "intact_job": sb_ref})
ok("prep 3406 design -> READY", J.prep(jd) == "READY")
pd = json.loads((J.QROOT / jd / "prep.json").read_text())
ok("prep.json (design): femur_id, femur_hook, margin_check sparse, templating A0, bone_loss",
   pd["femur_id"] == FID and pd["femur_hook"]["A_BOUNDS"] == [20.0, 2000.0] and pd["margin_check"] == "sparse"
   and pd["templating"]["A0"] == 292.19 and pd["bone_loss"]["h_cut_mm"] == 25.0)
ok("M1.build saw the 3406 femur, cut 25, cap active, slip_tol/delta from spec",
   built[jd]["femur_id"] == FID and built[jd]["cut"] == 25.0 and built[jd]["A_BOUNDS"] == (A0[0], 2000.0)
   and built[jd]["kw"]["slip_tol"] == 2.5e-4 and built[jd]["kw"]["delta"] == 0.025)
F6.uninstall()

jc = J.submit({**CT_D, "stage": "neck11", "tag": "c0"})
ok("prep CT design -> READY (regression)", J.prep(jc) == "READY")
pc = json.loads((J.QROOT / jc / "prep.json").read_text())
ok("prep.json (CT): femur_id None, no femur_hook, A_BOUNDS hashed during build",
   pc["femur_id"] is None and "femur_hook" not in pc and built[jc]["femur_id"] is None and built[jc]["A_BOUNDS"] == A0)

# ================================================================ 6. post
PM1.evaluate = lambda dd, name, fm_, ref: {"f1_p95_um": 11.0, "vm_p99": 100.0, "model": "m1", "_ref": ref["intact_job"], "_femur": fm_.femur_id}


def solved(jid):
    (J.QROOT / jid / "solve.json").write_text(json.dumps({"m_fric": {"status": "OK"}, "m_bond": {"status": "OK"}}))
    (J.QROOT / jid / "SOLVED").write_text("x")


solved(jd)
ok("post 3406 design with explicit 3406 intact_job -> DONE", J.post(jd) == "DONE")
res = json.loads((J.QROOT / jd / "result.json").read_text())
ok("result: intact_job = 3406 ref, evaluate got the 3406 femur, h_cut 25",
   res["intact_job"] == sb_ref and res["_ref"] == sb_ref and res["_femur"] == FID and res["h_cut_mm"] == 25.0)
line = json.loads((J.RESULTS / "runs_v2a.jsonl").read_text().strip().splitlines()[-1])
ok("runs_v2a.jsonl record carries femur_id + intact_job", line["femur_id"] == FID and line["job_id"] == jd and line["variant"]["intact_job"] == sb_ref)
F6.uninstall()

jd2 = J.submit({**SB_D, "stage": "sb11", "tag": "noref"})
J.prep(jd2)
solved(jd2)
ok("post 3406 design WITHOUT intact_job -> FAILED", J.post(jd2) == "FAILED")
fj = json.loads((J.QROOT / jd2 / "FAILED.json").read_text())
ok("  FAILED.json: L5 post, reason names the explicit intact_job rule", fj["level"] == "L5" and fj["stage"] == "post" and "explicit intact_job" in fj["reason"], fj["reason"][:120])
F6.uninstall()

solved(jc)
J.intact_ref = lambda h, E=None: {"gruen7": 1.0, "gruen1": 1.0, "intact_job": "ref_fake", "intact_substituted_h": None}
ok("post CT bonded design -> DONE through a two-argument intact_ref monkeypatch (old signature still works)",
   J.post(jc) == "DONE" and json.loads((J.QROOT / jc / "result.json").read_text())["intact_job"] == "ref_fake")
line = json.loads((J.RESULTS / "runs_v2a.jsonl").read_text().strip().splitlines()[-1])
ok("runs_v2a.jsonl CT record: femur_id None", line["job_id"] == jc and line["femur_id"] is None)
J.intact_ref = _ir

# ================================================================ 7. stage_v2a.serve pre-check (one iteration, no subprocesses)
jd3 = J.submit({**SB_D, "stage": "sb11", "tag": "ctref", "intact_job": ct_ref})     # femur mismatch
J.prep(jd3)
solved(jd3)
F6.uninstall()
jd4 = J.submit({**SB_D, "stage": "sb11", "tag": "wait", "intact_job": pending})     # reference not DONE
J.prep(jd4)
solved(jd4)
F6.uninstall()
for d in J.QROOT.glob("*"):                                                          # serve must not see NEW jobs (Popen/preexec_fn is Linux-only)
    if d.is_dir() and J.state(d) == "NEW":
        (d / "READY").write_text("x")
ok("fixture: no NEW jobs left for serve", all(J.state(d) != "NEW" for d in J.QROOT.glob("*") if d.is_dir()))
_time = S.time
S.time = types.SimpleNamespace(strftime=time.strftime, sleep=lambda s: (J.QROOT / "STOP_SERVE").write_text("x"))
try:
    S.serve(n_prep=0, poll=0.0)
    served = True
except Exception as ex:                                                              # noqa: BLE001
    served = False
    print("serve raised", repr(ex))
S.time = _time
(J.QROOT / "STOP_SERVE").unlink()
ok("serve ran one iteration and returned (no crash on the femur mismatch)", served)
ok("serve: femur-mismatch job -> post -> FAILED L5", J.state(J.QROOT / jd3) == "FAILED"
   and json.loads((J.QROOT / jd3 / "FAILED.json").read_text())["level"] == "L5")
ok("serve: job whose 3406 reference is not DONE stays SOLVED (waits)", J.state(J.QROOT / jd4) == "SOLVED")
F6.uninstall()

# ================================================================ 8. shielding.intact_job / design_jobs / design_rows guard
ok("shielding.intact_job(): CT ref (not the newer mis-staged 3406 dir)", SH.intact_job(True).name == ct_ref)
ok("shielding.intact_job(femur_id=3406): the sb ref, never the CT one", SH.intact_job(True, FID).name == sb_ref)
ok("shielding.intact_job(femur_id='other') -> FileNotFoundError", raises(FileNotFoundError, SH.intact_job, True, "other") is not None)
(J.QROOT / sb_ref / "intact_csv" / "LOAD_S.csv").unlink()
ok("shielding.intact_job(femur_id=3406) without LOAD_S -> FileNotFoundError (does not fall back to CT)",
   raises(FileNotFoundError, SH.intact_job, True, FID) is not None)
(J.QROOT / sb_ref / "intact_csv" / "LOAD_S.csv").write_text("elem,mises\n")
plain_ct = {"kind": "design", "design": DESIGN, "h_int": 2.0, "min_A0": S.MIN_A0, "model": "m1", "h_cut": 25.25, "stage": "e2e", "tag": "plain"}
plain_sb = {**plain_ct, "h_cut": 25.0, "femur_id": FID, "neck_axis": "isthmus", "stage": "sb11", "tag": "plain"}
RES = {"templating": TPL, "f1_p95_um": 10.0, "f2_g7_loss_pct": 5.0, "vm_p99": 90.0, "vm_max": 120.0}
jc2, jd5 = J.submit(plain_ct), J.submit(plain_sb)
for j in (jc2, jd5):
    (J.QROOT / j / "result.json").write_text(json.dumps({**RES, "job_id": j}))
    (J.QROOT / j / "DONE").write_text("x")
ok("shielding.design_jobs(): CT designs only", [d.name for d in SH.design_jobs()] == [jc2])
ok("shielding.design_jobs(femur_id=3406): 3406 designs only", [d.name for d in SH.design_jobs(FID)] == [jd5])
SH._CTX.update(fm=FakeFemur(), intact={})
ok("shielding.design_rows(3406 design) -> NotImplementedError (CT-only context)", raises(NotImplementedError, SH.design_rows, jd5) is not None)

# ================================================================ 9. resorption._CTX keyed by femur_id
xs, ys, zs = np.arange(-30, 31, 3.0), np.arange(-15, 16, 3.0), np.arange(-60, 31, 3.0)
X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
P0 = np.c_[X.ravel(), Y.ravel(), Z.ravel()]
R.build_grid = lambda fm_: (P0 + (np.array([10.0, 0.0, 0.0]) if fm_.femur_id else 0.0), P0[:, 0] > 5)
loaded, asked = [], []
_ij = SH.intact_job
SH.intact_job = lambda need_s=True, femur_id=None: asked.append((need_s, femur_id)) or _ij(need_s, femur_id)
TAG = {ct_ref: 1.0, sb_ref: 2.0}
SH.load_fields = lambda d: loaded.append(d.name) or {"tag": TAG.get(d.name, 3.0)}
R.to_grid = lambda fields, P, canc, k=1: {"sed": np.full(len(P), fields["tag"]), "vm": np.full(len(P), 1.0)}
R.stem_parts = lambda d, fm_, pose: {"fm_femur": fm_.femur_id, "fm_cut": fm_.cut_from_head_mm}
R._CTX.clear()
calls.clear()
R._init(1, None)
ok("resorption._init(k, None): CT grid + CT intact reference only", asked == [(True, None)] and loaded == [ct_ref]
   and list(R._CTX["grid"]) == [None] and R._CTX["k"] == 1 and calls == [("ct",)], f"{asked} {loaded} {calls}")
c6 = R._ctx(FID)
ok("resorption._ctx(3406): own grid (shifted), 3406 intact reference, keyed separately",
   asked[-1] == (True, FID) and loaded[-1] == sb_ref and sorted(map(str, R._CTX["grid"])) == sorted(["None", FID])
   and float(c6["P"][:, 0].min()) == -20.0 and float(R._ctx(None)["P"][:, 0].min()) == -30.0
   and float(c6["gi"]["sed"][0]) == 2.0 and float(R._ctx(None)["gi"]["sed"][0]) == 1.0)
n_calls = len(calls)
R._ctx(FID)
R._ctx(None)
ok("resorption._ctx is cached (no rebuild)", len(calls) == n_calls and len(asked) == 2)
a, b, c = R.base_femur(None), R.base_femur(FID), R.base_femur(FID, "silhouette")
ok("resorption.base_femur: CT / 3406 default axis / 3406 silhouette are three cached objects",
   a is not b and b is not c and a.femur_id is None and b.femur_id == FID and c.lm["neck_axis"]["option"] == "silhouette"
   and R.base_femur(FID, "silhouette") is c and R.base_femur(FID) is b and R.base_femur(None) is a)
F6.uninstall()
ok("resorption.intact_grid: cross-femur reference refused both ways",
   raises(ValueError, R.intact_grid, ct_ref, FID) is not None and raises(ValueError, R.intact_grid, sb_ref, None) is not None)
ok("resorption.intact_grid: same-femur explicit reference accepted + cached",
   float(R.intact_grid(sb_ref, FID)["sed"][0]) == 2.0 and sb_ref in R._ctx(FID)["gi_by"] and float(R.intact_grid(ct_ref)["sed"][0]) == 1.0)
rows_ct, srow_ct = R.design_rows(jc2)
rows_sb, srow_sb = R.design_rows(jd5)
F6.uninstall()


def chg(rows):
    return {r["sed_chg_pct"] for r in rows if "sed_chg_pct" in r}


ok("resorption.design_rows(CT design): CT femur, cut 25.25, CT grid/intact (tag 3 vs 1 -> +200 %)",
   srow_ct["fm_femur"] is None and srow_ct["fm_cut"] == 25.25 and rows_ct and rows_ct[0]["femur_id"] is None
   and chg(rows_ct) and all(abs(v - 200.0) < 1e-6 for v in chg(rows_ct)), str(sorted(chg(rows_ct))[:3]))
ok("resorption.design_rows(3406 design): 3406 femur (isthmus axis), cut 25, 3406 grid/intact (tag 3 vs 2 -> +50 %)",
   srow_sb["fm_femur"] == FID and srow_sb["fm_cut"] == 25.0 and rows_sb[0]["femur_id"] == FID
   and chg(rows_sb) and all(abs(v - 50.0) < 1e-6 for v in chg(rows_sb)) and R.base_femur(FID, "isthmus").lm["neck_axis"]["option"] == "isthmus",
   str(sorted(chg(rows_sb))[:3]))
R._write(SCR / "zones_test.csv", rows_ct + rows_sb)
R.OUT = SCR
rr = R.read("zones_test.csv")
ok("resorption.read keeps femur_id as text (CSV round trip with the new column)",
   {r["femur_id"] for r in rr} == {"", FID} and isinstance(rr[0]["vol"], float))
SH.intact_job = _ij

bad_ = [k for k, v in checks if not v]
print(f"\n{len(checks) - len(bad_)}/{len(checks)} checks passed" + (f"; FAILED: {bad_}" if bad_ else ""))
sys.exit(1 if bad_ else 0)
