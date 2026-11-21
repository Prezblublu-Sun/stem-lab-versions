"""Run with the repo venv: PYTHONUTF8=1 .venv-mobo/Scripts/python.exe v2/tests/test_phase11_part3_dense_margin.py
Local only (fake queue in the system temp dir); part 2 needs part 1 run first; part 3 reads the research-log tables.
"""
"""Part 3 acceptance test: collar_rule dense margin check must reproduce failures/tables/tplfine_nis_all.csv for
neck10_a69_e394e85c (unchanged), neck10_a64_2649f8de (-5.29 %), neck10_a57_09bff191 (-2.39 %), neck10_a68_2302d773 (infeasible).
Designs are rebuilt from the BO records' unit coordinates (failures/bo_records.json) with Phase(10).design_of, exactly as the
specs were generated; sparse templating must first reproduce the stored A0 (data/metrics_all.csv tpl_A0).
Also checks: set_margin_check / install_neck(margin_check) switch the default; template_base restores geom3d.penetration.
Read-only on the research-log; nothing written outside scratch."""
import csv
import json
import pathlib
import sys
import time
import tempfile

import numpy as np

ROOT = pathlib.Path(r"H:/projects/Femoral implant generation/sandbox/mobo_toy")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "v2"))
ML = pathlib.Path(r"H:/projects/application/research-log/neck_implant_2026-10-02/ml_efficiency_2026-10-22")

import femur_real as FR  # noqa: E402
import geom3d as G  # noqa: E402
import collar_rule as CR  # noqa: E402
import stage_neckopt as N  # noqa: E402
import stage_v2a as S  # noqa: E402

checks = []


def ok(name, cond, extra=""):
    checks.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""), flush=True)


JOBS = ["neck10_a69_e394e85c", "neck10_a64_2649f8de", "neck10_a57_09bff191", "neck10_a68_2302d773"]
recs = {}


def walk(o):
    if isinstance(o, dict):
        if o.get("job_id") in JOBS or o.get("job") in JOBS:
            recs[o.get("job_id") or o.get("job")] = o
        for v in o.values():
            walk(v)
    elif isinstance(o, list):
        for v in o:
            walk(v)


walk(json.load(open(ML / "failures" / "bo_records.json", encoding="utf-8")))
tpl = {r["job"]: r for r in csv.DictReader(open(ML / "failures" / "tables" / "tplfine_nis_all.csv", encoding="utf-8"))}
met = {r["job"]: r for r in csv.DictReader(open(ML / "data" / "metrics_all.csv", encoding="utf-8"))}
ok("all four jobs found in bo_records / tplfine / metrics", all(j in recs and j in tpl and j in met for j in JOBS))

t0 = time.time()
fm0 = FR.build()
print(f"FR.build {time.time() - t0:.1f} s", flush=True)
ph = N.Phase(10)
ok("collar_rule default is sparse", CR.MARGIN_CHECK == "sparse")
pen0 = G.penetration
out = {}
for j in JOBS:
    x = np.asarray(recs[j]["x"], float)
    d, h = ph.design_of(x)
    fm = fm0.with_cut(h)
    st = G.Stem3D(**d)
    t1 = time.time()
    sp = CR.template_neck_in_shoulder(st, fm, min_A0=S.MIN_A0)                       # module default (sparse)
    t2 = time.time()
    dn = CR.template_neck_in_shoulder(st, fm, min_A0=S.MIN_A0, margin_check="dense")
    t3 = time.time()
    out[j] = {"h_cut": h, "sparse": sp, "dense": dn, "t_sparse": t2 - t1, "t_dense": t3 - t2}
    A_stored = float(met[j]["tpl_A0"])
    ok(f"{j}: h_cut matches metrics", abs(h - float(met[j]["h_cut"])) < 1e-9, f"{h} vs {met[j]['h_cut']}")
    ok(f"{j}: sparse reproduces stored A0 ({A_stored:.6f})", sp.get("fit") and abs(sp["A0"] - A_stored) < 1e-6 * A_stored, f"got {sp.get('A0')}")
    ok(f"{j}: sparse result tagged margin_check sparse; dense tagged dense", sp.get("margin_check") == "sparse" and dn.get("margin_check") == "dense")
    row = tpl[j]
    if row["dense_fit"] == "True":
        want = float(row["dA0_pct"])
        got = 100.0 * (dn["A0"] / A_stored - 1.0) if dn.get("fit") else None
        ok(f"{j}: dense dA0 {want:+.4f} % reproduced", got is not None and abs(got - want) < 1e-4, f"got {got}")
        ok(f"{j}: dense A0 {float(row['dense_A0']):.6f} reproduced", dn.get("fit") and abs(dn["A0"] - float(row["dense_A0"])) < 1e-6 * A_stored, f"got {dn.get('A0')}")
        ok(f"{j}: dense e unchanged (de_mm {row['de_mm']})", dn.get("fit") and abs((dn["e"] - sp["e"]) - float(row["de_mm"])) < 1e-9)
    else:
        ok(f"{j}: dense infeasible as in tplfine", not dn.get("fit"), str(dn.get("reason"))[:120])
        ok(f"{j}: dense reason starts like tplfine's", str(dn.get("reason", ""))[:60] == row["dense_reason"][:60], str(dn.get("reason"))[:90])
    print(f"   {j}: sparse A0 {sp.get('A0')} e {sp.get('e')} ({out[j]['t_sparse']:.2f} s); dense A0 {dn.get('A0')} e {dn.get('e')} fit {dn.get('fit')} ({out[j]['t_dense']:.2f} s)", flush=True)
ok("geom3d.penetration restored after dense calls", G.penetration is pen0)

# ---------------------------------------------------------------- mode switching
j = "neck10_a64_2649f8de"
d, h = ph.design_of(np.asarray(recs[j]["x"], float))
fm, st = fm0.with_cut(h), G.Stem3D(**d)
CR.set_margin_check("dense")
r1 = CR.template_neck_in_shoulder(st, fm, min_A0=S.MIN_A0)
ok("set_margin_check('dense') makes the default call dense", r1.get("fit") and abs(r1["A0"] - out[j]["dense"]["A0"]) < 1e-9)
CR.set_margin_check("sparse")
r2 = CR.template_neck_in_shoulder(st, fm, min_A0=S.MIN_A0)
ok("back to sparse", r2.get("fit") and abs(r2["A0"] - out[j]["sparse"]["A0"]) < 1e-9)
tpl0 = G.template
CR.install_neck(min_A0=S.MIN_A0, margin_check="dense")
r3 = G.template(st, fm)
ok("install_neck(margin_check='dense'): G.template (as jobs.prep uses it) gives the dense A0", r3.get("fit") and abs(r3["A0"] - out[j]["dense"]["A0"]) < 1e-9 and CR.MARGIN_CHECK == "dense")
G.template = tpl0
CR.set_margin_check("sparse")
CR.install_neck(min_A0=S.MIN_A0)
r4 = G.template(st, fm)
ok("install_neck() without margin_check keeps the current default (sparse)", r4.get("fit") and abs(r4["A0"] - out[j]["sparse"]["A0"]) < 1e-9)
G.template = tpl0
# Phase.template honours the phase's margin_check
N.PHASES[10]["margin_check"] = "dense"
r5 = N.Phase(10).template(st, fm)
del N.PHASES[10]["margin_check"]
r6 = N.Phase(10).template(st, fm)
ok("Phase.template: dense phase -> dense A0; default phase -> sparse A0", abs(r5["A0"] - out[j]["dense"]["A0"]) < 1e-9 and abs(r6["A0"] - out[j]["sparse"]["A0"]) < 1e-9)
try:
    CR.set_margin_check("bogus")
    ok("set_margin_check rejects unknown mode", False)
except ValueError:
    ok("set_margin_check rejects unknown mode", True)

json.dump({j: {k: (v if not isinstance(v, dict) else {kk: vv for kk, vv in v.items() if kk != "pose"}) for k, v in o.items()} for j, o in out.items()},
          open(pathlib.Path(tempfile.gettempdir()) / "mobo_toy_phase11_tests_accept_part3.json", "w"), indent=1, default=float)
bad = [k for k, v in checks if not v]
print(f"\n{len(checks) - len(bad)}/{len(checks)} checks passed" + (f"; FAILED: {bad}" if bad else ""))
sys.exit(1 if bad else 0)
