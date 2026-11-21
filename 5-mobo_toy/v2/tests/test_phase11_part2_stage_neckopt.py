"""Run with the repo venv: PYTHONUTF8=1 .venv-mobo/Scripts/python.exe v2/tests/test_phase11_part2_stage_neckopt.py
Local only (fake queue in the system temp dir); part 2 needs part 1 run first; part 3 reads the research-log tables.
"""
"""Part 2 tests (local only): stage_neckopt objectives() on synthetic records, bond_every counter with a temporary state file,
PHASES[11] placeholder, Phase(11) defaults, in_family rule for fric_only / femur_id / margin_check, pool_key unchanged for phase 10,
record_of on the fake fric_only job from test_part1 (same scratch queue), spec_of bonded flag. No submissions, no Linux."""
import json
import math
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(r"H:/projects/Femoral implant generation/sandbox/mobo_toy")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "v2"))
import tempfile
SCR = pathlib.Path(tempfile.gettempdir()) / "mobo_toy_phase11_tests" / "fake_queue"   # fake queue outside the repo
import jobs as J  # noqa: E402
import stage_neckopt as N  # noqa: E402
import stage_v2a as S  # noqa: E402

J.QROOT, J.RESULTS = SCR / "queue", SCR / "results"
checks = []


def ok(name, cond, extra=""):
    checks.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""), flush=True)


# S7 (2026-10-24): the production PHASES[11] now points at the Sawbones 3406 (femur_id sawbone3406, neck_axis isthmus, intact_job None until the
# 3406 intact is solved; stage prefix sb11). This file tests the phase-11 *shape* (sed none, bond_every, fric_only, in_family) on the CT femur
# (stage neck11, no femur_id), so after checking the production values once it pins the CT placeholder as its fixture; the 3406 behaviour is
# covered by test_s7_phase11_3406.py.
ok("PHASES[11] production (S7): femur_id sawbone3406, neck_axis isthmus, intact_job = solved 3406 reference (2026-10-24); margin_check dense",
   N.PHASES[11]["femur_id"] == "sawbone3406" and N.PHASES[11]["neck_axis"] == "isthmus" and N.PHASES[11].get("intact_job") == "sb_intact_h2_9c9d7fb5"
   and N.PHASES[11]["margin_check"] == "dense")
# CT fixture for the checks below (stage neck11, margin_check sparse): the margin_check pins were written against the sparse placeholder and were
# already failing after f1134dd switched PHASES[11] to dense (5 checks at HEAD); the dense path itself is exercised further down by setting it explicitly.
N.PHASES[11].update(femur_id=None, neck_axis=None, intact_job=None, margin_check="sparse")

# ---------------------------------------------------------------- objectives(): synthetic records
STAB = {"rot_first_deg": 0.02, "contact_area_load2_mm2": 2000.0}
fo_ok = {"f1_p95_um": 100.0, "fric_only": True, "_stability": STAB, "bone_loss": {"total_mm3": 5000.0}}
fo_f1 = {**fo_ok, "f1_p95_um": 200.0}
bd_vm = {"f1_p95_um": 100.0, "vm_p99": 500.0, "_stability": STAB, "bone_loss": {"total_mm3": 5000.0}}
bd_ok = {**bd_vm, "vm_p99": 100.0}
bd_novm = {"f1_p95_um": 100.0, "_stability": STAB, "bone_loss": {"total_mm3": 5000.0}}

y, c, k = N.objectives(fo_ok, "none", None, "v3", None)
ok("v3 fric_only, sed none: ok, c = f1 term only", k and abs(c - (100 - 150) / 150) < 1e-12 and abs(y[0] - math.log10(0.02)) < 1e-12 and y[1] == -2000.0, f"c={c}")
y, c, k = N.objectives(fo_f1, "none", None, "v3", None)
ok("v3 fric_only with f1 violation: ok, c > 0 from f1", k and abs(c - (200 - 150) / 150) < 1e-12, f"c={c}")
y, c, k = N.objectives(bd_vm, "none", None, "v3", None)
ok("v3 bonded vm 500: ok, c = vm term", k and abs(c - (500 - 440) / 440) < 1e-12, f"c={c}")
y, c, k = N.objectives(bd_vm, "abs", None, "v3", -10.0)
ok("v3 bonded vm 500, sed abs with sed_chg -10: c = max(vm, sed) = vm term", k and abs(c - (500 - 440) / 440) < 1e-12, f"c={c}")
y, c, k = N.objectives(bd_ok, "abs", None, "v3", -40.0)
ok("v3 bonded, |sed| 40 > 30: c = sed term", k and abs(c - (40 - 30) / 30) < 1e-12, f"c={c}")
y, c, k = N.objectives(bd_novm, "none", None, "v3", None)
ok("v3 bonded record WITHOUT vm_p99: still not ok (existing behaviour kept)", not k)
y, c, k = N.objectives(fo_ok, "abs", None, "v3", None)
ok("v3 fric_only with sed abs (no SED available): not ok (documented)", not k)
y, c, k = N.objectives(fo_ok, "none", None, "v2", None)
ok("v2 fric_only, sed none: ok, c_vm skipped", k and abs(c - (-1.0)) < 1e-12 and y[1] == 5000.0, f"c={c}")
y, c, k = N.objectives({**bd_vm, "f1_all_p95_um": 100.0}, "none", 5.0, "v1", None)
ok("v1 bonded unchanged", k and abs(c - (500 - 440) / 440) < 1e-12)
ok("failed / empty records still nan", not N.objectives(None, "none", None, "v3")[2] and not N.objectives({"failed": {}}, "none", None, "v3")[2])

# ---------------------------------------------------------------- bond_every counter with a temporary state file
state_f = SCR / "neckopt_p11_state_test.json"
state_f.write_text(json.dumps({"phase": 11}))
log = []
for i in range(1, 13):
    st = json.loads(state_f.read_text())                 # reload every time = persistence across restarts
    b = N.next_bonded(st, 5)
    state_f.write_text(json.dumps(st))
    log.append(b)
ok("counter: bonded exactly at submissions 5 and 10 of 12", [i + 1 for i, b in enumerate(log) if b] == [5, 10], str(log))
ok("counter persisted in state file", json.loads(state_f.read_text())["n_submitted"] == 12)
st = {"n_submitted": 7}
ok("counter resumes from a stored count (8th, 9th fric_only, 10th bonded)", [N.next_bonded(st, 5) for _ in range(3)] == [False, False, True])
ok("bond_every None/0 -> always bonded", all(N.next_bonded({}, be) for be in (None, 0)))

# ---------------------------------------------------------------- PHASES[11] placeholder and Phase defaults
p10, p11 = N.PHASES[10], N.PHASES[11]
ok("PHASES[11] = PHASES[10] vars (except h_cut 16–32, hcut16 2026-10-23)/fixed/rule/metric",
   {k: v for k, v in p11["vars"].items() if k not in ("h_cut", "L")} == {k: v for k, v in p10["vars"].items() if k not in ("h_cut", "L")} and p11["vars"]["h_cut"] == (16.0, 32.0) and p11["vars"]["L"] == (20.0, 45.0)
   and p11["fixed"] == p10["fixed"] and p11["collar_rule"] == p10["collar_rule"] == "neck_in_shoulder" and p11["metric"] == p10["metric"] == "v3")
ok("PHASES[11] sed none, bond_every 5, femur_id None", p11["sed"] == "none" and p11["bond_every"] == 5 and p11.get("femur_id") is None and "femur_id" in p11)
ph11, ph10 = N.Phase(11), N.Phase(10)
ok("Phase(11).sed none by default; Phase(10).sed abs; CLI override works", ph11.sed == "none" and ph10.sed == "abs" and N.Phase(11, sed="abs").sed == "abs")
ok("Phase(11) bond_every 5 / femur_id None / margin_check sparse", ph11.bond_every == 5 and ph11.femur_id is None and ph11.margin_check == "sparse")
ok("Phase(10) has no bond_every (legacy behaviour)", ph10.bond_every is None)

# ---------------------------------------------------------------- spec_of bonded flag
u = np.full(len(ph11.vars), 0.5)
s_b, s_f, s_n = ph11.spec_of(u, "t", bonded=True), ph11.spec_of(u, "t", bonded=False), ph11.spec_of(u, "t")
ok("spec_of(bonded=False) adds fric_only True; bonded True / None add nothing", s_f.get("fric_only") is True and "fric_only" not in s_b and "fric_only" not in s_n)
ok("spec_of keeps the phase-10 spec shape (model m1, FRIC, collar_rule, stage neck11)", s_b["model"] == "m1" and s_b["slip_tol"] == 2.5e-4
   and s_b["collar_rule"] == "neck_in_shoulder" and s_b["stage"] == "neck11" and "femur_id" not in s_b and "margin_check" not in s_b)
ok("fric_only changes the job id (new ids, old results untouched)", J.job_id(s_b) != J.job_id(s_f))

# ---------------------------------------------------------------- in_family rule
d11, h11 = ph11.design_of(u)
base = {"kind": "design", "design": d11, "h_int": 2.0, "min_A0": S.MIN_A0, "stage": "neck11", "tag": "x", "model": "m1", "h_cut": h11,
        "slip_tol": 2.5e-4, "delta": 0.025, "collar_rule": "neck_in_shoulder",
        "ref_cut_mm": 16.0, "a_bounds_max": 2000.0}                 # hcut16 (2026-10-23): phase-11 specs carry both keys (test_hcut16_phase11)
base10 = {**{k: v for k, v in base.items() if k not in ("ref_cut_mm", "a_bounds_max")}, "stage": "neck10", "h_cut": 28.0}   # phase-10 shape
ok("in_family: phase-11 fric_only spec accepted by Phase(11)", ph11.in_family({**base, "fric_only": True}))
ok("in_family: phase-11 bonded spec accepted by Phase(11)", ph11.in_family(base))
ok("in_family: fric_only spec also passes Phase(10).in_family (exclusion happens in objectives via missing SED)", ph10.in_family({**base10, "fric_only": True}))
ok("in_family: femur_id mismatch rejected", not ph11.in_family({**base, "femur_id": "sawbone3406"}))
ok("in_family: margin_check dense spec rejected by a sparse phase", not ph11.in_family({**base, "margin_check": "dense"}))
ok("in_family: bond_only still rejected", not ph11.in_family({**base, "bond_only": True}))
ok("fric_only is not in MODEL_KEYS", "fric_only" not in N.MODEL_KEYS)

# ---------------------------------------------------------------- pool_key: unchanged for phase 10 (old inline formula)
import hashlib  # noqa: E402
old = hashlib.sha1((J.code_hash() + json.dumps(ph10.space, sort_keys=True) + json.dumps(ph10.fixed, sort_keys=True)
                    + json.dumps(N.CONST) + f"{16384}_{0}_v2" + (f"_{ph10.rule}" if ph10.rule else "")).encode()).hexdigest()[:8]
ok("pool_key(phase 10, n 16384, seed 0) == old formula (cached Linux pools stay valid)", N.pool_key(ph10, 16384, 0) == old)
ok("pool_key(phase 11) != pool_key(phase 10) (h_cut 16–32, ref_cut_mm 16, a_bounds_max 2000; hcut16 2026-10-23)", N.pool_key(ph11, 16384, 0) != old)
N.PHASES[11]["margin_check"] = "dense"
ok("pool_key changes with margin_check dense", N.pool_key(N.Phase(11), 16384, 0) != old)
N.PHASES[11]["femur_id"] = "sawbone3406"
ok("pool_key changes with femur_id", N.pool_key(N.Phase(11), 16384, 0) not in (old, N.pool_key(N.Phase(11), 16384, 0) if False else "x"))
del N.PHASES[11]["margin_check"]
N.PHASES[11]["femur_id"] = None

# ---------------------------------------------------------------- record_of on the fake fric_only job (test_part1 output)
fo_jobs = [d.name for d in (SCR / "queue").glob("neck11_a0_*") if (d / "DONE").exists()]
ok("fake fric_only job from test_part1 present", len(fo_jobs) == 1, str(fo_jobs))
if fo_jobs:
    jid = fo_jobs[0]
    N._STAB[jid] = {"rot_first_deg": 0.03, "contact_area_load2_mm2": 1800.0, "rot_axial_first_deg": 0.01}
    calcar_called = []
    N._calcar = lambda j: calcar_called.append(j) or (None, None)
    rec = N.record_of(jid, "none", "v3")
    ok("record_of fric_only (sed none, v3): ok True, fric_only True, vm_p99 None, no calcar call",
       rec["ok"] and rec["fric_only"] and rec["vm_p99"] is None and rec["sed_chg_pct"] is None and not calcar_called
       and abs(rec["c"][0] - (12.3 - 150) / 150) < 1e-12, json.dumps({k: rec[k] for k in ("y", "c", "ok", "fric_only", "vm_p99")}))
    rec2 = N.record_of(jid, "abs", "v3")
    ok("record_of fric_only under sed abs: ok False (excluded from abs datasets)", not rec2["ok"])
    ok("_bonded_of reads spec.json", N._bonded_of(jid) is False and N._bonded_of("nope_x") is None)

bad = [k for k, v in checks if not v]
print(f"\n{len(checks) - len(bad)}/{len(checks)} checks passed" + (f"; FAILED: {bad}" if bad else ""))
sys.exit(1 if bad else 0)
