"""Run with the repo venv: PYTHONUTF8=1 .venv-mobo/Scripts/python.exe v2/tests/test_stage_db_b33.py
Local only: a fake queue in the system temp dir (mobo_toy_db_b33_tests); J.QROOT points there. No gmsh, no FE, no Linux, nothing under
~/mobo_toy_v2 is read or written. Source specs come read-only from db3406/raw.

v2/stage_db.py v1.25, batch b33 (conditional rows of the R2 candidates; build_cond, shared with b28c):
A. constants: b33 in BATCHES, layer sources, slow start; R2C_WINNERS = experiments/b33_r2cand/data/picks.json; the list refuses when empty, too long,
   repeated or unknown.
B. rows: 3 per candidate in order; each copies the R2 main row and changes only h_int (and slip_tol at h 1.4) or cfg.load; references and model sets
   as written; the tags are the ones experiments/b33_r2cand/gates.py looks for; no problems on a clean queue.
C. fail closed: a main row not DONE, the h 1.94 reference not DONE.
D. dry run exits 0, lists the 9 rows, writes nothing.
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
BASE = pathlib.Path(tempfile.gettempdir()) / "mobo_toy_db_b33_tests"
shutil.rmtree(BASE, ignore_errors=True)
BASE.mkdir(parents=True)

import jobs as J  # noqa: E402
import stage_db as DB  # noqa: E402

spec_g = importlib.util.spec_from_file_location("gates_b33", ROOT / "experiments" / "b33_r2cand" / "gates.py")
GB = importlib.util.module_from_spec(spec_g)
spec_g.loader.exec_module(GB)

T_START = time.perf_counter()
REAL_Q, REAL_R = J.QROOT, J.RESULTS
checks = []
A, REF = DB.CODES["A"], DB.REF_H2
R194, R14 = "db_ref_intact_h1.94_0df7c4b7", "db_ref_intact_h1.4_b7b166b8"
JOBS = {A, REF, R194, R14, *DB.UROW_CURVE}
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


def queue(name, mains=True):
    root = BASE / name
    J.QROOT, J.RESULTS = root / "queue", root / "results"
    assert not str(J.QROOT).startswith(str(pathlib.Path.home() / "mobo_toy_v2"))
    J.QROOT.mkdir(parents=True)
    J.RESULTS.mkdir(parents=True)
    for j in JOBS:
        shutil.copytree(CACHE / j, J.QROOT / j)
    shutil.copy2(snap / "db_manifest_b1.json", J.RESULTS / "db_manifest_b1.json")
    if mains:                       # the R2 main rows, DONE, with the spec build_urows writes for b31
        for r in DB.build("b31")["rows"]:
            d = J.QROOT / r["expected_id"]
            d.mkdir()
            (d / "spec.json").write_text(json.dumps(r["spec"], indent=1, default=float))
            (d / "DONE").write_text("")
    return root


def refused():
    try:
        DB.build("b33")
    except SystemExit as e:
        return str(e)
    return ""


try:
    picks = json.load(open(ROOT / "experiments" / "b33_r2cand" / "data" / "picks.json", encoding="utf-8"))["picks"]
    ok("A: b33 in BATCHES, code_hash unchanged, R2C_WINNERS = picks.json = the gates' CAND", "b33" in DB.BATCHES and J.code_hash() == DB.DB_CODE_HASH
       and list(DB.R2C_WINNERS) == picks == list(GB.CAND), f"{DB.R2C_WINNERS} {picks} {list(GB.CAND)}")
    ok("A: layers", DB.LAYER_SOURCE["R2 rep"] == "noise" and DB.LAYER_SOURCE["R2 h1.4"] == "fid_h14" and DB.LAYER_SOURCE["R2 sts"] == "cond_anchor"
       and {"R2 rep", "R2 h1.4", "R2 sts"} <= set(DB.SLOW_START_LAYERS))
    queue("refuse", mains=False)
    saved = DB.R2C_WINNERS
    for bad, why in (((), "empty"), (("r2_01", "r2_02", "r2_03", "r2_04", "r2_05", "r2_06"), "six"), (("r2_01", "r2_01"), "repeated"), (("r2_99",), "unknown")):
        DB.R2C_WINNERS = bad
        ok(f"A: a candidate list that is {why} refuses", "R2C_WINNERS" in refused())
    DB.R2C_WINNERS = saved

    # ---------------------------------------------------------------- B
    queue("rows")
    b = DB.build("b33")
    rows = {r["key"]: r for r in b["rows"]}
    ok("B: no problems on a clean queue", not b["problems"], "; ".join(b["problems"])[:500])
    want_keys = [f"R2{x}_{lab}" for lab in saved for x in "RHS"]
    ok("B: 9 rows in order", list(rows) == want_keys, list(rows))
    mains = {r["key"][3:]: r for r in DB.build("b31")["rows"]}           # key R2_01 -> 01
    phys = lambda s, drop: {k: v for k, v in s.items() if k in DB.PHYS_KEYS and k not in drop}  # noqa: E731
    good = True
    for lab in saved:
        main = mains[lab[3:]]
        mp = {k: v for k, v in main["spec"].items() if k in DB.PHYS_KEYS}
        rr, rh, rs = rows[f"R2R_{lab}"], rows[f"R2H_{lab}"], rows[f"R2S_{lab}"]
        good = good and phys(rr["spec"], {"h_int"}) == phys(mp, {"h_int"}) and rr["spec"]["h_int"] == 1.94 and rr["spec"]["stage"] == "db_nz" and rr["model_set"] == "fric+bond" \
            and rr["spec"]["intact_job"] == R194 and rr["ref_key"] == "REF_h1.94" and rr["source"] == "noise" and rr["source_job"] == main["expected_id"]
        good = good and phys(rh["spec"], {"h_int", "slip_tol"}) == phys(mp, {"h_int", "slip_tol"}) and rh["spec"]["h_int"] == 1.4 and rh["spec"]["slip_tol"] == DB.H14_SLIP_TOL \
            and rh["spec"]["stage"] == "db_fd" and rh["heavy"] and rh["spec"]["intact_job"] == R14 and rh["ref_key"] == "REF_h1.4" and rh["source"] == "fid_h14"
        good = good and phys(rs["spec"], {"cfg"}) == phys(mp, {"cfg"}) and rs["spec"]["cfg"] == {"load": DB.STS_LOADS["F1714"]} and rs["spec"].get("fric_only") \
            and "intact_job" not in rs["spec"] and rs["spec"]["stage"] == "db_cd" and rs["source"] == "cond_anchor"
        good = good and [r["spec"]["tag"] for r in (rr, rh, rs)] == [GB.tag_of(lab) + s for s in ("_h1.94", "_h1.4", "_F1714")] and main["spec"]["tag"] == GB.tag_of(lab)
    frozen31 = {r["label"][3:]: r["job_id"] for r in json.load(open(ROOT / "experiments" / "b31_r2" / "rows.json", encoding="utf-8"))["rows"]}
    ok("B: the main rows' ids equal experiments/b31_r2/rows.json (what was fed and judged)", all(mains[lab[3:]]["expected_id"] == frozen31[lab[3:]] for lab in saved)
       and all(rows[f"R2R_{lab}"]["source_job"] == frozen31[lab[3:]] for lab in saved), str({lab: frozen31[lab[3:]] for lab in saved}))
    ok("B: each row copies its R2 main row and changes only h_int (+ slip_tol) or cfg.load; references, model sets, tags as the gates expect", good)
    ok("B: rows pass the reference rule", not [m for r in rows.values() if r["spec"].get("intact_job")
                                                for m in DB.ref_mismatch(r["spec"], json.loads((J.QROOT / r["spec"]["intact_job"] / "spec.json").read_text()))])
    ok("B: in_E true, unbiased false, all new", all(r["in_E"] and not r["unbiased"] and r["dedup"] == "new" for r in rows.values()))

    # ---------------------------------------------------------------- C
    queue("fail")
    m0 = mains[saved[0][3:]]["expected_id"]
    (J.QROOT / m0 / "DONE").unlink()
    ok("C: a main row not DONE is a problem", [p for p in DB.build("b33")["problems"] if "the b31 row" in p and m0 in p])
    queue("fail2")
    (J.QROOT / R194 / "DONE").unlink()
    ok("C: the h 1.94 reference not DONE is a problem", [p for p in DB.build("b33")["problems"] if "reference REF_h1.94" in p])

    # ---------------------------------------------------------------- D
    root = queue("dry")
    before = sorted(str(x.relative_to(root)) for x in root.rglob("*"))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = DB.dry_run("b33")
    out = buf.getvalue()
    ok("D: dry run exits 0, lists 9 jobs, writes nothing", rc == 0 and "jobs (9):" in out and before == sorted(str(x.relative_to(root)) for x in root.rglob("*")), out[-300:] if rc else "")
finally:
    J.QROOT, J.RESULTS = REAL_Q, REAL_R
    shutil.rmtree(BASE, ignore_errors=True)

n_fail = sum(not c for _, c in checks)
print(f"{len(checks) - n_fail}/{len(checks)} passed, {n_fail} failed")
sys.exit(1 if n_fail else 0)
