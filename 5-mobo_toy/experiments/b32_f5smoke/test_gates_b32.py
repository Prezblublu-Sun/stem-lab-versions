"""Tests of b32's gate G52 before it is frozen. Local, read only on db3406 v0.12; writes a temp dir only.

    PYTHONUTF8=1 ../../.venv-mobo/Scripts/python.exe test_gates_b32.py

A. constants: mesh_F, N3, U_NECK, CREF as b28; BASE = stage_db.F5_SMOKE_BASE, H_LEVELS = F5_SMOKE_H; the h 2.0, h 1.94, h 1.4 rows exist in v0.12.
B. v0.12: NA.
C. synthetic rows (v0.12 rows plus two made-up F5 rows; their mesh F patched in): PASS, FAIL (micromotion x 2.5, a failed row, foam_refine
   missing from the export, negative micromotion, F nan), NA (a row still running, a row never submitted).
"""
import csv
import importlib.util
import inspect
import json
import math
import pathlib
import shutil
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
V12 = pathlib.Path(r"H:/projects/Femoral implant generation/db3406/v0.12")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "v2"))
import numpy as np  # noqa: E402
import stage_db as DB  # noqa: E402

checks = []


def ok(name, cond, extra=""):
    checks.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""), flush=True)


def load(path, name):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


g = load(HERE / "gates.py", "g_b32")
g28 = load(ROOT / "experiments" / "b28_fam" / "gates.py", "g_b28")
REAL = g.mesh_F
ok("A: mesh_F, N3, U_NECK, CREF as b28", inspect.getsource(g.mesh_F) == inspect.getsource(g28.mesh_F) and all(np.array_equal(getattr(g, k), getattr(g28, k)) for k in ("N3", "U_NECK", "CREF")))
ok("A: BASE, H_LEVELS and slip_tol as stage_db", g.BASE == DB.F5_SMOKE_BASE and tuple(g.H_LEVELS) == tuple(h for hs in DB.F5_SMOKE_H.values() for h in hs)
   and g.SLIP_REF == DB.F5_SLIP_REF and g.H_PROD == DB.H_PROD)
with open(V12 / "scalars.csv", encoding="utf-8") as fh:
    R12 = list(csv.DictReader(fh))
by_id = {r["job_id"]: r for r in R12}
ok("A: the h 2.0, h 1.94, h 1.4 rows are DONE in v0.12", all(by_id.get(j, {}).get("status") == "DONE" for j in (g.BASE, *g.OTHERS.values())))
sys.path.insert(0, str(ROOT / "tools"))
import db_export as DX  # noqa: E402
ok("A: exporter 0.2.5 or later writes a foam_refine column from the spec", tuple(int(x) for x in DX.EXPORTER_VERSION.split()[1].split(".")) >= (0, 2, 5)
   and '_c("foam_refine"' in inspect.getsource(DX) and 'foam_refine=spec.get("foam_refine")' in inspect.getsource(DX))
v = g.judge(str(V12))["G52"]
ok("B: v0.12 -> NA", v["status"] == "NA", v["note"][:100])

cols = list(R12[0].keys()) + (["foam_refine"] if "foam_refine" not in R12[0] else [])
KEEP = {g.BASE, *g.OTHERS.values()}
REAL_F = REAL(str(V12), KEEP)
fb = float(by_id[g.BASE]["f1_p95_um"])
TMP = pathlib.Path(tempfile.mkdtemp(prefix="gates_b32_"))


def run(spec):
    """spec: h -> dict(status, f1 factor or value, fr, F); None = no row."""
    rows, fake = [], {}
    for h in g.H_LEVELS:
        s = spec.get(h, {})
        if s is None:
            continue
        r = {c: "" for c in cols}
        jid = f"j_f5_{h:g}"
        r.update(tag=g.tag_of(h), job_id=jid, status=s.get("status", "DONE"), rot_first_deg="0.093",
                 f1_p95_um=str(s["f1"]) if "f1" in s else repr(fb * s.get("x", 1.05)), foam_refine=s.get("fr", json.dumps({"h": h})),
                 slip_tol=repr(s.get("slip", g.slip_of(h))), n_pairs=str(int(float(by_id[g.BASE]["n_pairs"]) * s.get("pairs", {1.0: 3.2, 0.7: 6.2}[h]))),
                 fail_reason=s.get("why", ""), fail_level=s.get("lvl", ""), fail_stage=s.get("stg", ""), solve_wall_s_fric="7000")
        fake[jid] = s.get("F", REAL_F[g.BASE] + 1.0)
        rows.append(r)
    d = TMP / f"db{len(list(TMP.iterdir()))}"
    d.mkdir()
    with open(d / "scalars.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows([{**by_id[j], "foam_refine": ""} for j in sorted(KEEP)] + rows)
    g.mesh_F = lambda db_dir, want: {k: v for k, v in {**REAL_F, **fake}.items() if k in want}
    try:
        return g.judge(str(d))["G52"]
    finally:
        g.mesh_F = REAL


try:
    v = run({})
    ok("C: both rows DONE, x 1.05 -> PASS", v["status"] == "PASS" and all(abs(x - math.log10(1.05)) < 1e-4 for x in v["value"].values()), str(v["value"]))
    ok("C: note carries the h 1.94 and h 1.4 rows", "h1.94" in v["note"] and "h1.4" in v["note"])
    v = run({0.7: {"x": 2.5}})
    ok("C: h 0.7 micromotion x 2.5 (0.40 dex) -> FAIL", v["status"] == "FAIL" and "dex" in v["note"])
    v = run({0.7: {"x": 1.9}})
    ok("C: x 1.9 (0.28 dex) -> PASS", v["status"] == "PASS")
    v = run({1.0: {"status": "FAILED"}})
    ok("C: a failed row -> FAIL", v["status"] == "FAIL" and "算失败" in v["note"])
    v = run({1.0: {"fr": ""}})
    ok("C: foam_refine missing from the export -> FAIL", v["status"] == "FAIL" and "foam_refine" in v["note"])
    v = run({1.0: {"fr": json.dumps({"h": 0.7})}})
    ok("C: foam_refine with the wrong h -> FAIL", v["status"] == "FAIL")
    v = run({1.0: {"f1": -2.0}})
    ok("C: negative micromotion -> FAIL, no crash", v["status"] == "FAIL")
    v = run({1.0: {"F": float("nan")}})
    ok("C: F nan -> FAIL", v["status"] == "FAIL")
    v = run({0.7: {"status": "CLAIMED"}})
    ok("C: a row still running -> NA", v["status"] == "NA" and "没算完" in v["note"])
    v = run({0.7: None})
    ok("C: a row never submitted -> NA", v["status"] == "NA" and "没提交" in v["note"])
    v = run({1.0: {"pairs": 1.1}})
    ok("C: h 1.0 with 1.1 x the base contact pairs (hook not applied) -> FAIL", v["status"] == "FAIL" and "钩子可能没生效" in v["note"])
    v = run({0.7: {"pairs": 3.5}})
    ok("C: h 0.7 with 3.5 x the pairs (below 4.0) -> FAIL", v["status"] == "FAIL")
    v = run({1.0: {"slip": 2.5e-4}})
    ok("C: slip_tol not scaled -> FAIL", v["status"] == "FAIL" and "slip_tol" in v["note"])
    v = run({0.7: {"status": "FAILED", "why": "m_fric: timeout > 21600 s", "lvl": "L4", "stg": "solve"}})
    ok("C: h 0.7 solve timeout (the string run_abaqus writes) -> NA, not FAIL; the h 1.0 checks are still in the note", v["status"] == "NA" and "超时" in v["note"]
       and "n_pairs_ratio" in v["note"])
    v = run({1.0: {"status": "FAILED", "why": "odb export timeout", "lvl": "L5", "stg": "post"}})
    ok("C: an odb export timeout (stage post) is a failure, not a solve timeout -> FAIL", v["status"] == "FAIL")
    v = run({1.0: {"status": "FAILED", "why": "BuildError: L3", "lvl": "L3", "stg": "prep"}, 0.7: None})
    ok("C: h 1.0 failed while h 0.7 not submitted -> FAIL at once", v["status"] == "FAIL" and "算失败" in v["note"])
finally:
    shutil.rmtree(TMP, ignore_errors=True)

n_fail = sum(not c for _, c in checks)
print(f"{len(checks) - n_fail}/{len(checks)} passed, {n_fail} failed")
sys.exit(1 if n_fail else 0)
