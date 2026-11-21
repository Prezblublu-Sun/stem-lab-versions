"""Run with the repo venv: PYTHONUTF8=1 .venv-mobo/Scripts/python.exe v2/tests/test_stage_db_urows.py
Local only: a fake queue in the system temp dir (mobo_toy_db_urows_tests); J.QROOT points there. No gmsh, no FE, no Linux, nothing under
~/mobo_toy_v2 is read or written. Source specs come read-only from db3406/raw; the femur cache is read only.

v2/stage_db.py v1.23, batches b29 (RS-1), b30 (OF-1), b31 (R2), built by build_urows:
A. constants: in BATCHES, layer sources and selection, slow start; row counts; inside the unit cube with m >= 1.
B. each batch: no problems on a clean queue; rows = Phase(13).spec_of + the offset, friction only, stage as written; templating equals the record;
   the tags are the ones the batch's gates.py looks for; in_E true, unbiased false.
C. fail closed: the A row not DONE; a curve row not DONE; a size that differs from the record; OF-1 rows that are not one factor at a time.
D. dry run exits 0, lists every row, writes nothing.
"""
import contextlib
import importlib.util
import io
import json
import pathlib
import shutil
import sys
import tarfile
import tempfile
import time

ROOT = pathlib.Path(r"H:/projects/Femoral implant generation/sandbox/mobo_toy")
RAW = pathlib.Path(r"H:/projects/Femoral implant generation/db3406/raw")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "v2"))
BASE = pathlib.Path(tempfile.gettempdir()) / "mobo_toy_db_urows_tests"
shutil.rmtree(BASE, ignore_errors=True)
BASE.mkdir(parents=True)

import jobs as J  # noqa: E402
import stage_db as DB  # noqa: E402
import tpl_record as TR  # noqa: E402

T_START = time.perf_counter()
REAL_Q, REAL_R = J.QROOT, J.RESULTS
REAL_VIEW = TR.offgrid_view
checks = []
A, REF = DB.CODES["A"], DB.REF_H2
CTRL = "db_ws_p13_a105_91e458e3_m1_2a79b613"
JOBS = {A, REF, CTRL, *DB.UROW_CURVE}
GATE_DIRS = {"b29": "b29_rs1", "b30": "b30_of1", "b31": "b31_r2"}
N_ROWS = {"b29": 48, "b30": 12, "b31": 15}


def ok(name, cond, extra=""):
    checks.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + f"(t={time.perf_counter() - T_START:.0f}s) " + name + (f"  [{extra}]" if extra else ""), flush=True)


def extract(job, dest):
    d = dest / job
    d.mkdir(parents=True)
    with tarfile.open(RAW / f"{job}.tar.xz", "r:xz") as tf:
        for member in ("spec.json", "prep.json", "DONE"):
            try:
                f = tf.extractfile(f"{job}/{member}")
            except KeyError:
                continue
            (d / member).write_bytes(f.read())


CACHE = BASE / "_cache"
for j_ in sorted(JOBS):
    extract(j_, CACHE)


def queue(name):
    root = BASE / name
    J.QROOT, J.RESULTS = root / "queue", root / "results"
    assert not str(J.QROOT).startswith(str(pathlib.Path.home() / "mobo_toy_v2"))
    J.QROOT.mkdir(parents=True)
    J.RESULTS.mkdir(parents=True)
    for j in JOBS:
        shutil.copytree(CACHE / j, J.QROOT / j)
    return root


def gates_of(batch):
    s = importlib.util.spec_from_file_location(f"g_{batch}", ROOT / "experiments" / GATE_DIRS[batch] / "gates.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


try:
    ok("A: b29, b30, b31 in BATCHES, code_hash unchanged", {"b29", "b30", "b31"} <= set(DB.BATCHES) and J.code_hash() == DB.DB_CODE_HASH)
    ok("A: layers", DB.LAYER_SOURCE["RS-1"] == "corner" and DB.LAYER_SOURCE["OF-1"] == "bound_scan" and DB.LAYER_SOURCE["R2"] == "al_adaptive"
       and DB.LAYER_SELECTION["R2"] == "adaptive" and DB.LAYER_SELECTION.get("RS-1", "stratum") == "stratum" and {"RS-1", "OF-1", "R2"} <= set(DB.SLOW_START_LAYERS))
    for b, n in N_ROWS.items():
        rows_def = getattr(DB, DB.UROW_BATCHES[b][3])
        ok(f"A: {b} has {n} rows inside the unit cube with m >= 1, labels unique",
           len(rows_def) == n and len({x[0] for x in rows_def}) == n and all(len(x[4]) == 13 and min(x[4]) >= 0 and max(x[4]) <= 1 and x[4][3] >= 1 / 3 - 1e-12 for x in rows_def))
    import numpy as np
    ph = DB.b2_phase()
    queue("rows")
    for b in N_ROWS:
        layer, stage, prefix, const, _, _ = DB.UROW_BATCHES[b]
        rows_def = getattr(DB, const)
        out = DB.build(b)
        rows = out["rows"]
        ok(f"B: {b} no problems on a clean queue", not out["problems"], "; ".join(out["problems"])[:400])
        same, tags = True, []
        for (lab, e, A0, bone, u), r in zip(rows_def, rows):
            s = r["spec"]
            ref = DB._phys(ph.spec_of(np.asarray(u, float), "x", bonded=True), "x")
            same = same and {**ref, "entry_offset": float(e)} == {x: s[x] for x in s if x in DB.PHYS_KEYS} and s.get("fric_only") and "intact_job" not in s
            same = same and s["stage"] == stage and r["layer"] == layer and r["in_E"] and not r["unbiased"] and r["e_forced"] == e and r["source_job"] == CTRL
            t = out["ws_tpl"][s["tag"]]
            same = same and t["feasible"] and t["e_star"] == e and abs(t["A0_star"] - A0) <= 0.01 and abs(t["bone_mm3"] - bone) <= 0.5
            tags.append(s["tag"])
        ok(f"B: {b} rows = spec_of + offset, friction only, templating as recorded", same)
        g = gates_of(b)
        want = [g.tag_of(lab) for lab in (getattr(g, "PRED", None) or {x: None for x in g.LABELS})]
        ok(f"B: {b} tags are the ones its gates look for", sorted(tags) == sorted(want), f"{tags[:2]} vs {want[:2]}")
        e_of = {lab: v[0] for lab, v in g.PRED.items()} if hasattr(g, "PRED") else dict(g.E)
        ok(f"B: {b} gates and builder agree on (label, entry offset)", e_of == {x[0]: x[1] for x in rows_def})
        ok(f"B: {b} all new and distinct", all(r["dedup"] == "new" for r in rows) and len({r["expected_id"] for r in rows}) == len(rows))

    # ---------------------------------------------------------------- C
    queue("fail")
    (J.QROOT / CTRL / "DONE").unlink()
    ok("C: the A row not DONE is a problem", [p for p in DB.build("b30")["problems"] if "the A family row" in p])
    queue("fail2")
    first = DB.OF1_ROWS[0]
    DB.OF1_ROWS = ((first[0], first[1], first[2] + 1.0, first[3], first[4]), *DB.OF1_ROWS[1:])
    ok("C: a size that differs from the record is a problem", [p for p in DB.build("b30")["problems"] if ": size " in p])
    DB.OF1_ROWS = (first, *DB.OF1_ROWS[1:])
    queue("fail3")
    (J.QROOT / DB.UROW_CURVE[0] / "DONE").unlink()
    ok("C: a curve row not DONE is a problem", [p for p in DB.build("b31")["problems"] if "curve row" in p and DB.UROW_CURVE[0] in p])
    ph1 = DB.b2_phase()
    ref1 = {k: v for k, v in DB._phys(ph1.spec_of(np.asarray(DB.OF1_U_A, float), "x", bonded=True), "x").items() if k in DB.PHYS_KEYS}
    ok("C: the frozen OF-1 rows are one factor at a time", DB._of1_single_factor(DB.OF1_ROWS, ph1, ref1) == [])
    two = [list(x) for x in DB.OF1_ROWS]
    u = list(two[4][4]); u[0] += 0.01; two[4][4] = tuple(u)
    u = list(two[0][4]); u[4] += 0.01; two[0][4] = tuple(u)
    u = list(two[-1][4]); u[12] += 0.01; two[-1][4] = tuple(u)
    two[2][1] = 1.0
    bad = DB._of1_single_factor([tuple(x) for x in two], ph1, ref1)
    ok("C: OF-1 two coordinates moved, a wrong step, a 3b_back row that moves another factor, a one-factor row off e 0: four problems", len(bad) == 4, "; ".join(bad)[:300])

    # ---------------------------------------------------------------- D
    root = queue("dry")
    before = sorted(str(x.relative_to(root)) for x in root.rglob("*"))
    for b, n in N_ROWS.items():
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = DB.dry_run(b)
        out = buf.getvalue()
        ok(f"D: {b} dry run exits 0, lists {n} jobs, writes nothing", rc == 0 and f"jobs ({n}):" in out and before == sorted(str(x.relative_to(root)) for x in root.rglob("*")), out[-300:] if rc else "")
finally:
    TR.offgrid_view = REAL_VIEW
    J.QROOT, J.RESULTS = REAL_Q, REAL_R
    shutil.rmtree(BASE, ignore_errors=True)

n_fail = sum(not c for _, c in checks)
print(f"{len(checks) - n_fail}/{len(checks)} passed, {n_fail} failed")
sys.exit(1 if n_fail else 0)
