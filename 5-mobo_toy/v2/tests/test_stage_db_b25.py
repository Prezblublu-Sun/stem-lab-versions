"""Run with the repo venv: PYTHONUTF8=1 .venv-mobo/Scripts/python.exe v2/tests/test_stage_db_b25.py
Local only: a fake queue in the system temp dir (mobo_toy_db_b25_tests); J.QROOT points there. No gmsh, no FE, no Linux, nothing under
~/mobo_toy_v2 is read or written. Source specs come read-only from db3406/raw; the femur cache is read only, as in the b22 test.

v2/stage_db.py v1.19, batch b25 (OPT-1):
A. constants: b25 in BATCHES, layer source and selection, slow start, B2 layer, code_hash unchanged; 8 rows inside the unit cube, sorted by bone, e from 0 to +2.
B. rows: no problems on a clean queue; m >= 1; bond model on; templating equals the recorded size and bone at the fixed offset; in_E true, unbiased false; physics equals Phase(13).spec_of plus the offset.
C. fail closed: the control not DONE, m below 1, an infeasible row, an offset mismatch, a size mismatch, a templating error.
D. dedup: the same physics under another job name -> existing.
E. dry_run: exit 0, prints the rows, writes nothing. Earlier job ids did not move.
F. the rows the exporter and stage_al see: a forced offset is recorded, the job id passes the archive name rule.
"""
import contextlib
import fnmatch
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
sys.path.insert(0, str(ROOT / "tools"))
BASE = pathlib.Path(tempfile.gettempdir()) / "mobo_toy_db_b25_tests"
shutil.rmtree(BASE, ignore_errors=True)
BASE.mkdir(parents=True)

import db_archive as AR  # noqa: E402
import jobs as J  # noqa: E402
import stage_db as DB  # noqa: E402
import tpl_record as TR  # noqa: E402

T_START = time.perf_counter()
REAL_Q, REAL_R = J.QROOT, J.RESULTS
REAL_RECORD, REAL_VIEW = TR.record_spec, TR.offgrid_view
checks = []
A, REF = DB.CODES["A"], DB.REF_H2
CTRL = "db_ws_p13_a105_91e458e3_m1_2a79b613"
JOBS = {A, REF, CTRL}
KEYS = [f"OPT1_{n:02d}" for n in range(1, 9)]


def ok(name, cond, extra=""):
    checks.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + f"(t={time.perf_counter() - T_START:.0f}s) " + name + (f"  [{extra}]" if extra else ""), flush=True)


def extract(job, dest):
    d = dest / job
    d.mkdir(parents=True)
    with tarfile.open(RAW / f"{job}.tar.xz", "r:xz") as tf:
        for member in ("spec.json", "prep.json", "DONE"):
            f = tf.extractfile(f"{job}/{member}")
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


def problems_of(b, needle):
    return [p for p in b["problems"] if needle in p]


def fake_view(mod):
    def f(spec):
        return mod(spec, REAL_VIEW(spec))
    return f


try:
    ok("A: b25 in BATCHES, code_hash unchanged", "b25" in DB.BATCHES and J.code_hash() == DB.DB_CODE_HASH)
    ok("A: layer", DB.LAYER_SOURCE["OPT-1"] == "al_adaptive" and DB.LAYER_SELECTION["OPT-1"] == "adaptive" and "OPT-1" in DB.SLOW_START_LAYERS and "OPT-1" in DB.B2_LAYERS)
    es = [x[0] for x in DB.OPT1_ROWS]
    bones = [x[2] for x in DB.OPT1_ROWS]
    ok("A: 8 rows, sorted by bone, e from 0 to +2", len(DB.OPT1_ROWS) == 8 and bones == sorted(bones) and min(es) == 0.0 and max(es) <= 2.0, str(es))
    ok("A: inside the unit cube, 13 variables, u_m at or above m 1.0", all(len(x[3]) == 13 and min(x[3]) >= 0.0 and max(x[3]) <= 1.0 and x[3][3] >= 1 / 3 - 1e-12 for x in DB.OPT1_ROWS))

    # ---------------------------------------------------------------- B
    queue("rows")
    b = DB.build("b25")
    rows = {r["key"]: r for r in b["rows"]}
    ok("B: no problems on a clean queue", not b["problems"], "; ".join(b["problems"])[:500])
    ok("B: 8 rows in order", list(rows) == KEYS, list(rows)[:3])
    ph = DB.b2_phase()
    import numpy as np
    same = True
    for (e, A0, bone, u), (k, r) in zip(DB.OPT1_ROWS, rows.items()):
        s = r["spec"]
        ref = DB._phys(ph.spec_of(np.asarray(u, float), "x", bonded=True), "x")
        same = same and {**ref, "entry_offset": float(e)} == {x: s[x] for x in s if x in DB.PHYS_KEYS}
        same = same and s["design"]["m"] >= 1.0 - 1e-9 and s["entry_offset"] == e and s["intact_job"] == REF and s["stage"] == "db_al" and s["kind"] == "variant"
        same = same and r["model_set"] == "fric+bond" and r["in_E"] and not r["unbiased"] and r["layer"] == "OPT-1" and r["source"] == "al_adaptive" and r["e_forced"] == e
        t = b["ws_tpl"][s["tag"]]
        same = same and t["feasible"] and t["e_star"] == e and abs(t["A0_star"] - A0) <= 0.01 and abs(t["bone_mm3"] - bone) <= 0.5
    ok("B: physics = Phase(13).spec_of + offset; m >= 1; bond on; size and bone as recorded", same, json.dumps({k: [round(v["A0_star"], 1), round(v["bone_mm3"] / 1000, 2)] for k, v in b["ws_tpl"].items()})[:400])
    ids = [r["expected_id"] for r in rows.values()]
    ok("B: job ids carry the opt1 tag and are not caught by the earlier globs", all(j.startswith("db_al_opt1_") for j in ids) and not [j for j in ids for g in ("db_al_al*", "db_ws_*", "sb13_*", "sb14_*") if fnmatch.fnmatch(j, g)], ids[0])
    ok("B: all new, the control is WS_m1", all(r["dedup"] == "new" for r in rows.values()) and b["ws_control"] == CTRL)

    # ---------------------------------------------------------------- C
    queue("fail")

    def infeasible(spec, r):
        if spec["tag"].startswith("opt1_03"):
            nan = float("nan")
            return {**r, "fit": False, "reason": "synthetic overhang", "e": nan, "A0": nan, "bone_total_mm3": nan}
        return r

    def mismatch(spec, r):
        return {**r, "e": 9.0} if spec["tag"].startswith("opt1_04") else r

    def size(spec, r):
        return {**r, "A0": r["A0"] + 1.0} if spec["tag"].startswith("opt1_02") else r

    def boom(spec, r):
        if spec["tag"].startswith("opt1_05"):
            raise RuntimeError("synthetic templating error")
        return r

    TR.offgrid_view = fake_view(infeasible)
    ok("C: an infeasible row is a problem", problems_of(DB.build("b25"), "OPT1_03: 0-FE templating is not feasible"))
    TR.offgrid_view = fake_view(mismatch)
    ok("C: an offset mismatch is a problem", problems_of(DB.build("b25"), "OPT1_04: entry offset"))
    TR.offgrid_view = fake_view(size)
    ok("C: a size that differs from the record is a problem", problems_of(DB.build("b25"), "OPT1_02: size"))
    TR.offgrid_view = fake_view(boom)
    ok("C: a templating error is a problem", problems_of(DB.build("b25"), "OPT1_05: 0-FE templating failed"))
    TR.offgrid_view = REAL_VIEW
    saved = DB.OPT1_ROWS
    u_low = list(saved[0][3])
    u_low[3] = 0.2
    DB.OPT1_ROWS = ((saved[0][0], saved[0][1], saved[0][2], tuple(u_low)), *saved[1:])
    ok("C: m below 1 is a problem", problems_of(DB.build("b25"), "OPT1_01: m "))
    DB.OPT1_ROWS = saved
    (J.QROOT / CTRL / "DONE").unlink()
    ok("C: the control not DONE is a problem", problems_of(DB.build("b25"), "the control WS_m1"))

    # ---------------------------------------------------------------- D
    queue("dedup")
    r0 = {r["key"]: r for r in DB.build("b25")["rows"]}["OPT1_03"]
    other = {**r0["spec"], "tag": "somewhere_else", "created": "x"}
    d = J.QROOT / "db_al_somewhere_else_00000000"
    d.mkdir()
    (d / "spec.json").write_text(json.dumps(other, indent=1, default=float))
    (d / "DONE").write_text("")
    r2 = {r["key"]: r for r in DB.build("b25")["rows"]}["OPT1_03"]
    ok("D: the same physics under another name is adopted, not computed again", r2["dedup"] == "existing" and r2["id"] == d.name and r2["dedup_via"] == "physics", f"{r2['dedup']} {r2['id']}")
    shutil.rmtree(d)

    # ---------------------------------------------------------------- E
    root = queue("dry")
    before = sorted(str(x.relative_to(root)) for x in root.rglob("*"))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = DB.dry_run("b25")
    out = buf.getvalue()
    ok("E: dry run exits 0, lists 8 jobs, writes nothing", rc == 0 and "jobs (8):" in out and "OPT1_08" in out and before == sorted(str(x.relative_to(root)) for x in root.rglob("*")), out[-300:] if rc else "")
    r14 = {r["key"]: r for r in DB.build("b14")["rows"]}
    ok("E: the b14 job id did not move", r14["WS_m1"]["expected_id"] == CTRL)

    # ---------------------------------------------------------------- F
    ok("F: the job ids pass the archive name rule", all(AR.JOB_RE.match(j) for j in ids), ids[2])
finally:
    TR.record_spec, TR.offgrid_view = REAL_RECORD, REAL_VIEW
    J.QROOT, J.RESULTS = REAL_Q, REAL_R
    shutil.rmtree(BASE, ignore_errors=True)

n_fail = sum(not c for _, c in checks)
print(f"{len(checks) - n_fail}/{len(checks)} passed, {n_fail} failed")
sys.exit(1 if n_fail else 0)
