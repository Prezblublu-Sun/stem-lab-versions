"""Run with the repo venv: PYTHONUTF8=1 .venv-mobo/Scripts/python.exe v2/tests/test_stage_db_b28.py
Local only: a fake queue in the system temp dir (mobo_toy_db_b28_tests); J.QROOT points there. No gmsh, no FE, no Linux, nothing under
~/mobo_toy_v2 is read or written. Source specs come read-only from db3406/raw; the femur cache is read only, as in the b25 test.

v2/stage_db.py v1.21, batch b28 (FAM-1):
A. constants: b28 in BATCHES, layer sources and selection, slow start, B2 layer, code_hash unchanged; 15 rows = 5 families x 3 roles inside the unit cube with m >= 1; 2 controls.
B. rows: no problems on a clean queue; ring rows = Phase(13).spec_of plus the offset, friction only; templating equals the recorded size and bone; controls copy their
   baseline and change only h_int, carry the bond model and point at the h 1.94 stair reference; in_E true, unbiased false.
C. fail closed: an infeasible row, an offset mismatch, a size mismatch, a templating error, m below 1, the A row not DONE, the h 1.94 reference not DONE, a control baseline not DONE.
D. dedup: the same physics under another job name -> existing.
E. dry_run: exit 0, lists 17 jobs, writes nothing. Earlier job ids did not move.
F. job ids pass the archive name rule and are not caught by the earlier globs.
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
BASE = pathlib.Path(tempfile.gettempdir()) / "mobo_toy_db_b28_tests"
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
R194 = "db_ref_intact_h1.94_0df7c4b7"
CTRL = "db_ws_p13_a105_91e458e3_m1_2a79b613"
JOBS = {A, REF, CTRL, R194} | {j for _, j in DB.FAM1_CTRL}
LABS = [x[0] for x in DB.FAM1_ROWS]
KEYS = [f"FAM1_{lab}" for lab in LABS] + [f"FAM1C_{lab}" for lab, _ in DB.FAM1_CTRL]
snap = sorted(p for p in (RAW / "results").iterdir() if p.is_dir() and "." not in p.name)[-1]


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
    shutil.copy2(snap / "db_manifest_b1.json", J.RESULTS / "db_manifest_b1.json")
    return root


def spec_of(j):
    return json.loads((J.QROOT / j / "spec.json").read_text())


def problems_of(b, needle):
    return [p for p in b["problems"] if needle in p]


def refused(batch):
    try:
        DB.build(batch)
    except SystemExit as e:
        return str(e)
    return ""


def fake_view(mod):
    def f(spec):
        return mod(spec, REAL_VIEW(spec))
    return f


try:
    ok("A: b28 in BATCHES, code_hash unchanged", "b28" in DB.BATCHES and J.code_hash() == DB.DB_CODE_HASH)
    ok("A: layers", DB.LAYER_SOURCE["FAM-1"] == "al_adaptive" and DB.LAYER_SELECTION["FAM-1"] == "adaptive" and DB.LAYER_SOURCE["FAM-1 ctrl"] == "noise"
       and {"FAM-1", "FAM-1 ctrl"} <= set(DB.SLOW_START_LAYERS) and "FAM-1" in DB.B2_LAYERS)
    ok("A: 15 rows = 5 families x 3 roles, labels unique", len(LABS) == 15 and len(set(LABS)) == 15 and sorted(LABS) == sorted(f"{f}{r}" for f in range(5) for r in "box"))
    ok("A: inside the unit cube, 13 variables, u_m at or above m 1.0, e from -1 to +2.5",
       all(len(x[4]) == 13 and min(x[4]) >= 0.0 and max(x[4]) <= 1.0 and x[4][3] >= 1 / 3 - 1e-12 and -1.0 <= x[1] <= 2.5 for x in DB.FAM1_ROWS))
    ok("A: 2 controls at h 1.94", len(DB.FAM1_CTRL) == 2 and DB.FAM1_CTRL_H == 1.94)

    # ---------------------------------------------------------------- B
    queue("rows")
    b = DB.build("b28")
    rows = {r["key"]: r for r in b["rows"]}
    ok("B: no problems on a clean queue", not b["problems"], "; ".join(b["problems"])[:500])
    ok("B: 17 rows in order", list(rows) == KEYS, list(rows)[:3])
    ph = DB.b2_phase()
    import numpy as np
    same = True
    for (lab, e, A0, bone, u) in DB.FAM1_ROWS:
        r = rows[f"FAM1_{lab}"]
        s = r["spec"]
        ref = DB._phys(ph.spec_of(np.asarray(u, float), "x", bonded=True), "x")
        same = same and {**ref, "entry_offset": float(e)} == {x: s[x] for x in s if x in DB.PHYS_KEYS}
        same = same and s["design"]["m"] >= 1.0 - 1e-9 and s["entry_offset"] == e and s.get("fric_only") and "intact_job" not in s and s["stage"] == "db_al" and s["kind"] == "variant"
        same = same and r["model_set"] == "fric" and r["in_E"] and not r["unbiased"] and r["layer"] == "FAM-1" and r["source"] == "al_adaptive" and r["e_forced"] == e and r["source_job"] == CTRL
        t = b["ws_tpl"][s["tag"]]
        same = same and t["feasible"] and t["e_star"] == e and abs(t["A0_star"] - A0) <= 0.01 and abs(t["bone_mm3"] - bone) <= 0.5
    ok("B: ring rows = Phase(13).spec_of + offset; m >= 1; friction only; size and bone as recorded", same,
       json.dumps({k: [round(v["A0_star"], 1), round(v["bone_mm3"] / 1000, 2)] for k, v in b["ws_tpl"].items()})[:400])
    fine = True
    for lab, j in DB.FAM1_CTRL:
        r = rows[f"FAM1C_{lab}"]
        s, src = r["spec"], spec_of(j)
        phys = lambda x: {a: v for a, v in x.items() if a in DB.PHYS_KEYS and a != "h_int"}  # noqa: E731
        fine = fine and phys(s) == phys(src) and s["h_int"] == 1.94 and s["stage"] == "db_nz" and r["model_set"] == "fric+bond" and not s.get("fric_only")
        fine = fine and s["intact_job"] == R194 and r["ref_key"] == "REF_h1.94" and r["source"] == "noise" and r["layer"] == "FAM-1 ctrl" and r["in_E"] and not r["unbiased"]
        fine = fine and not DB.ref_mismatch(s, spec_of(R194))
    ok("C: controls copy the baseline, change only h_int, bond model on, the h 1.94 stair reference", fine)
    ids = [r["expected_id"] for r in rows.values()]
    ok("B: readable job ids", ids[0].startswith("db_al_fam1_0b_e+1.5_") and ids[-1].startswith("db_nz_p13_a105_91e458e3_ow_m1_e+2_h1.94_"), f"{ids[0]} {ids[-1]}")
    ok("B: all new and distinct", all(r["dedup"] == "new" for r in rows.values()) and len(set(ids)) == 17)

    # ---------------------------------------------------------------- C
    queue("fail")

    def infeasible(spec, r):
        if spec["tag"].startswith("fam1_3b"):
            nan = float("nan")
            return {**r, "fit": False, "reason": "synthetic overhang", "e": nan, "A0": nan, "bone_total_mm3": nan}
        return r

    # offgrid_view only sees offsets off the 2 mm production grid (e 0 and +2 go through record_spec), so the fakes use rows at +0.5 and +1.5
    def mismatch(spec, r):
        return {**r, "e": 9.0} if spec["tag"].startswith("fam1_1o") else r

    def size(spec, r):
        return {**r, "A0": r["A0"] + 1.0} if spec["tag"].startswith("fam1_0b") else r

    def boom(spec, r):
        if spec["tag"].startswith("fam1_4x"):
            raise RuntimeError("synthetic templating error")
        return r

    TR.offgrid_view = fake_view(infeasible)
    ok("C: an infeasible row is a problem", problems_of(DB.build("b28"), "FAM1_3b: 0-FE templating is not feasible"))
    TR.offgrid_view = fake_view(mismatch)
    ok("C: an offset mismatch is a problem", problems_of(DB.build("b28"), "FAM1_1o: entry offset"))
    TR.offgrid_view = fake_view(size)
    ok("C: a size that differs from the record is a problem", problems_of(DB.build("b28"), "FAM1_0b: size"))
    TR.offgrid_view = fake_view(boom)
    ok("C: a templating error is a problem", problems_of(DB.build("b28"), "FAM1_4x: 0-FE templating failed"))
    TR.offgrid_view = REAL_VIEW
    saved = DB.FAM1_ROWS
    u_low = list(saved[0][4])
    u_low[3] = 0.2
    DB.FAM1_ROWS = ((*saved[0][:4], tuple(u_low)), *saved[1:])
    ok("C: m below 1 is a problem", problems_of(DB.build("b28"), "FAM1_0b: m "))
    DB.FAM1_ROWS = saved
    real_b2 = DB.b2_phase

    class _Ph:            # a Phase whose specs carry another interference: the row must be refused (review R8)
        def __init__(self, ph):
            self.ph = ph

        def spec_of(self, u, tag, bonded=True):
            s = self.ph.spec_of(u, tag, bonded=bonded)
            return {**s, "delta": 0.05}
    DB.b2_phase = lambda: _Ph(real_b2())
    ok("C: a condition that differs from the A row is a problem", problems_of(DB.build("b28"), "physics differs from the A row"))
    DB.b2_phase = real_b2
    (J.QROOT / CTRL / "DONE").unlink()
    ok("C: the A row not DONE is a problem", problems_of(DB.build("b28"), "the A family row WS_m1"))
    queue("fail2")
    (J.QROOT / R194 / "DONE").unlink()
    ok("C: the h 1.94 reference not DONE is a problem", problems_of(DB.build("b28"), "reference REF_h1.94"))
    queue("fail3")
    (J.QROOT / DB.FAM1_CTRL[1][1] / "DONE").unlink()
    ok("C: a control baseline not DONE refuses", "not DONE" in refused("b28"), refused("b28")[:90])

    # ---------------------------------------------------------------- D
    queue("dedup")
    r0 = {r["key"]: r for r in DB.build("b28")["rows"]}["FAM1_3b"]
    other = {**r0["spec"], "tag": "somewhere_else", "created": "x"}
    d = J.QROOT / "db_al_somewhere_else_00000000"
    d.mkdir()
    (d / "spec.json").write_text(json.dumps(other, indent=1, default=float))
    (d / "DONE").write_text("")
    r2 = {r["key"]: r for r in DB.build("b28")["rows"]}["FAM1_3b"]
    ok("D: the same physics under another name is adopted, not computed again", r2["dedup"] == "existing" and r2["id"] == d.name and r2["dedup_via"] == "physics", f"{r2['dedup']} {r2['id']}")
    shutil.rmtree(d)

    # ---------------------------------------------------------------- E
    root = queue("dry")
    before = sorted(str(x.relative_to(root)) for x in root.rglob("*"))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = DB.dry_run("b28")
    out = buf.getvalue()
    ok("E: dry run exits 0, lists 17 jobs, writes nothing", rc == 0 and "jobs (17):" in out and "FAM1C_e+2" in out and before == sorted(str(x.relative_to(root)) for x in root.rglob("*")), out[-300:] if rc else "")
    r14 = {r["key"]: r for r in DB.build("b14")["rows"]}
    ok("E: the b14 job id did not move", r14["WS_m1"]["expected_id"] == CTRL)

    # ---------------------------------------------------------------- F
    ok("F: the job ids pass the archive name rule", all(AR.JOB_RE.match(j) for j in ids), ids[2])
    ok("F: not caught by the earlier globs", not [j for j in ids for g in ("db_al_al*", "db_al_opt1_*", "db_ws_*", "sb13_*", "sb14_*", "db_cd_*") if fnmatch.fnmatch(j, g)])
finally:
    TR.record_spec, TR.offgrid_view = REAL_RECORD, REAL_VIEW
    J.QROOT, J.RESULTS = REAL_Q, REAL_R
    shutil.rmtree(BASE, ignore_errors=True)

n_fail = sum(not c for _, c in checks)
print(f"{len(checks) - n_fail}/{len(checks)} passed, {n_fail} failed")
sys.exit(1 if n_fail else 0)
