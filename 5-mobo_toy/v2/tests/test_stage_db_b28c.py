"""Run with the repo venv: PYTHONUTF8=1 .venv-mobo/Scripts/python.exe v2/tests/test_stage_db_b28c.py
Local only: a fake queue in the system temp dir (mobo_toy_db_b28c_tests); J.QROOT points there. No gmsh, no FE, no Linux, nothing under
~/mobo_toy_v2 is read or written. Source specs come read-only from db3406/raw.

v2/stage_db.py v1.22, batch b28c (conditional rows of b28):
A. constants: b28c in BATCHES, layer sources, slow start; the winner list refuses when empty, too long, repeated or unknown.
B. rows for one winner: 3 rows in order; each copies the b28 main row and changes only h_int (and slip_tol at h 1.4) or cfg.load; references and
   model sets as written; the tags are the ones experiments/b28_fam/gates.py looks for; no problems on a clean queue.
C. fail closed: the main row not DONE, the h 1.4 reference not DONE.
D. dry run exits 0, lists the rows, writes nothing.
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
BASE = pathlib.Path(tempfile.gettempdir()) / "mobo_toy_db_b28c_tests"
shutil.rmtree(BASE, ignore_errors=True)
BASE.mkdir(parents=True)

import jobs as J  # noqa: E402
import stage_db as DB  # noqa: E402

spec_g = importlib.util.spec_from_file_location("gates_b28", ROOT / "experiments" / "b28_fam" / "gates.py")
GB = importlib.util.module_from_spec(spec_g)
spec_g.loader.exec_module(GB)

T_START = time.perf_counter()
REAL_Q, REAL_R = J.QROOT, J.RESULTS
checks = []
A, REF = DB.CODES["A"], DB.REF_H2
R194, R14 = "db_ref_intact_h1.94_0df7c4b7", "db_ref_intact_h1.4_b7b166b8"
CTRL = "db_ws_p13_a105_91e458e3_m1_2a79b613"
JOBS = {A, REF, CTRL, R194, R14} | {j for _, j in DB.FAM1_CTRL}
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
    if mains:                       # the b28 main rows, DONE, with the spec build_b28 would write
        for r in DB.build("b28")["rows"]:
            if r["layer"] == "FAM-1":
                d = J.QROOT / r["expected_id"]
                d.mkdir()
                (d / "spec.json").write_text(json.dumps(r["spec"], indent=1, default=float))
                (d / "DONE").write_text("")
    return root


def refused():
    try:
        DB.build("b28c")
    except SystemExit as e:
        return str(e)
    return ""


try:
    ok("A: b28c in BATCHES, code_hash unchanged", "b28c" in DB.BATCHES and J.code_hash() == DB.DB_CODE_HASH)
    ok("A: layers", DB.LAYER_SOURCE["FAM-1 rep"] == "noise" and DB.LAYER_SOURCE["FAM-1 h1.4"] == "fid_h14" and DB.LAYER_SOURCE["FAM-1 sts"] == "cond_anchor"
       and {"FAM-1 rep", "FAM-1 h1.4", "FAM-1 sts"} <= set(DB.SLOW_START_LAYERS))
    queue("refuse", mains=False)
    saved = DB.FAM1C_WINNERS
    for bad, why in (((), "empty"), (("0b", "1b", "2b", "3b", "4b", "0x"), "six"), (("3b", "3b"), "repeated"), (("9z",), "unknown")):
        DB.FAM1C_WINNERS = bad
        ok(f"A: a winner list that is {why} refuses", "FAM1C_WINNERS" in refused())
    DB.FAM1C_WINNERS = ("3b",)

    # ---------------------------------------------------------------- B
    queue("rows")
    b = DB.build("b28c")
    rows = {r["key"]: r for r in b["rows"]}
    ok("B: no problems on a clean queue", not b["problems"], "; ".join(b["problems"])[:500])
    ok("B: 3 rows in order", list(rows) == ["FAM1R_3b", "FAM1H_3b", "FAM1S_3b"], list(rows))
    main = next(r for r in DB.build("b28")["rows"] if r["key"] == "FAM1_3b")
    mp = {k: v for k, v in main["spec"].items() if k in DB.PHYS_KEYS}
    phys = lambda s, drop: {k: v for k, v in s.items() if k in DB.PHYS_KEYS and k not in drop}  # noqa: E731
    rr, rh, rs = rows["FAM1R_3b"], rows["FAM1H_3b"], rows["FAM1S_3b"]
    ok("B: replicate = main row at h 1.94, bond model on, the h 1.94 reference",
       phys(rr["spec"], {"h_int"}) == phys(mp, {"h_int"}) and rr["spec"]["h_int"] == 1.94 and rr["spec"]["stage"] == "db_nz" and rr["model_set"] == "fric+bond"
       and rr["spec"]["intact_job"] == R194 and rr["ref_key"] == "REF_h1.94" and rr["source"] == "noise" and rr["source_job"] == main["expected_id"])
    ok("B: h 1.4 row = main row at h 1.4 with the h 1.4 slip tolerance, heavy, the h 1.4 reference",
       phys(rh["spec"], {"h_int", "slip_tol"}) == phys(mp, {"h_int", "slip_tol"}) and rh["spec"]["h_int"] == 1.4 and rh["spec"]["slip_tol"] == DB.H14_SLIP_TOL
       and rh["spec"]["stage"] == "db_fd" and rh["heavy"] and rh["spec"]["intact_job"] == R14 and rh["ref_key"] == "REF_h1.4" and rh["source"] == "fid_h14")
    ok("B: sit-to-stand row = main row at 1714 N, friction only",
       phys(rs["spec"], {"cfg"}) == phys(mp, {"cfg"}) and rs["spec"]["cfg"] == {"load": DB.STS_LOADS["F1714"]} and rs["spec"].get("fric_only") and "intact_job" not in rs["spec"]
       and rs["spec"]["stage"] == "db_cd" and rs["source"] == "cond_anchor")
    ok("B: the tags are the ones the b28 gates look for",
       [r["spec"]["tag"] for r in rows.values()] == [GB.tag_of("3b") + s for s in ("_h1.94", "_h1.4", "_F1714")], [r["spec"]["tag"] for r in rows.values()])
    ok("B: rows pass the reference rule", not [m for r in (rr, rh) for m in DB.ref_mismatch(r["spec"], json.loads((J.QROOT / r["spec"]["intact_job"] / "spec.json").read_text()))])
    ok("B: in_E true, unbiased false, all new", all(r["in_E"] and not r["unbiased"] and r["dedup"] == "new" for r in rows.values()))
    DB.FAM1C_WINNERS = saved                            # 11-08 review of b33: the shared build_cond must give b28c's frozen job ids
    frozen = [r["job_id"] for r in json.load(open(ROOT / "experiments" / "b28c_cond" / "rows.json", encoding="utf-8"))["rows"]]
    ok("B: with the real winner list the job ids equal experiments/b28c_cond/rows.json", [r["expected_id"] for r in DB.build("b28c")["rows"]] == frozen, str(frozen[:2]))
    DB.FAM1C_WINNERS = ("3b",)

    # ---------------------------------------------------------------- C
    queue("fail")
    (J.QROOT / main["expected_id"] / "DONE").unlink()
    ok("C: the main row not DONE is a problem", [p for p in DB.build("b28c")["problems"] if "the b28 row" in p])
    queue("fail2")
    (J.QROOT / R14 / "DONE").unlink()
    ok("C: the h 1.4 reference not DONE is a problem", [p for p in DB.build("b28c")["problems"] if "reference REF_h1.4" in p])

    # ---------------------------------------------------------------- D
    root = queue("dry")
    before = sorted(str(x.relative_to(root)) for x in root.rglob("*"))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = DB.dry_run("b28c")
    out = buf.getvalue()
    ok("D: dry run exits 0, lists 3 jobs, writes nothing", rc == 0 and "jobs (3):" in out and before == sorted(str(x.relative_to(root)) for x in root.rglob("*")), out[-300:] if rc else "")
    DB.FAM1C_WINNERS = saved
finally:
    J.QROOT, J.RESULTS = REAL_Q, REAL_R
    shutil.rmtree(BASE, ignore_errors=True)

n_fail = sum(not c for _, c in checks)
print(f"{len(checks) - n_fail}/{len(checks)} passed, {n_fail} failed")
sys.exit(1 if n_fail else 0)
