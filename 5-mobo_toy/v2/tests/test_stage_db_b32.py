"""Run with the repo venv: PYTHONUTF8=1 .venv-mobo/Scripts/python.exe v2/tests/test_stage_db_b32.py
Local only: a fake queue in the system temp dir (mobo_toy_db_b32_tests); J.QROOT points there. No gmsh, no FE, no Linux. Source specs come
read-only from db3406/raw.

v2/stage_db.py v1.24, batches b32 and b32b (F5 smoke, h 1.0 and h 0.7):
A. constants: b32 in BATCHES, layer F5 smoke -> source fid_f5, slow start; code_hash unchanged; foam_refine in PHYS_KEYS.
B. clean queue: no problems; 1 row each; = the base row's physics + foam_refine {"h": h} + slip_tol 2.5e-4 x 2 / h, friction only, stage db_fd,
   no intact_job; heavy; cond_id carries |f5h<h>;
   tags are the ones experiments/b32_f5smoke/gates.py looks for; new and distinct; in_E true, unbiased false.
C. fail closed: base row not DONE; base row with another entry offset.
D. dry run exits 0, lists 1 job each, writes nothing.
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
BASE = pathlib.Path(tempfile.gettempdir()) / "mobo_toy_db_b32_tests"
shutil.rmtree(BASE, ignore_errors=True)
BASE.mkdir(parents=True)

import jobs as J  # noqa: E402
import stage_db as DB  # noqa: E402

T_START = time.perf_counter()
REAL_Q, REAL_R = J.QROOT, J.RESULTS
checks = []
JOBS = {DB.F5_SMOKE_BASE, DB.REF_H2}


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


try:
    ok("A: b32 in BATCHES, layer F5 smoke -> fid_f5, slow start, code_hash unchanged, foam_refine a physics key",
       {"b32", "b32b"} <= set(DB.BATCHES) and DB.LAYER_SOURCE["F5 smoke"] == "fid_f5" and "F5 smoke" in DB.SLOW_START_LAYERS and J.code_hash() == DB.DB_CODE_HASH
       and "foam_refine" in DB.PHYS_KEYS and DB.F5_SMOKE_H == {"b32": (1.0,), "b32b": (0.7,)})
    queue("rows")
    rows, probs = [], []
    for b in ("b32", "b32b"):
        out = DB.build(b)
        rows += out["rows"]
        probs += out["problems"]
    ok("B: no problems on a clean queue, 1 row in each batch", not probs and len(rows) == 2, "; ".join(probs)[:300])
    src = json.loads((J.QROOT / DB.F5_SMOKE_BASE / "spec.json").read_text())
    ref = {k: v for k, v in src.items() if k in DB.PHYS_KEYS}
    same = True
    for h, r in zip((1.0, 0.7), rows):
        s = r["spec"]
        same = same and {k: v for k, v in s.items() if k in DB.PHYS_KEYS} == {**ref, "foam_refine": {"h": h}, "slip_tol": round(2.5e-4 * 2.0 / h, 9)}
        same = same and DB.cond_id(s).endswith(f"|f5h{h:g}") and f"|slip{round(2.5e-4 * 2.0 / h, 9):g}" in DB.cond_id(s)
        same = same and s.get("fric_only") is True and "intact_job" not in s and s["stage"] == "db_fd" and r["layer"] == "F5 smoke"
        same = same and DB.is_heavy(s) and r["in_E"] and not r["unbiased"] and r["source_job"] == DB.F5_SMOKE_BASE
    ok("B: rows = base physics + foam_refine, friction only, db_fd, heavy, in_E", same, str(rows[0]["spec"])[:300])
    gp = ROOT / "experiments" / "b32_f5smoke" / "gates.py"
    if gp.exists():
        sp = importlib.util.spec_from_file_location("g_b32", gp)
        g = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(g)
        ok("B: tags and slip_tol are the ones the gates look for", sorted(r["spec"]["tag"] for r in rows) == sorted(g.tag_of(h) for h in g.H_LEVELS)
           and all(r["spec"]["slip_tol"] == g.slip_of(r["spec"]["foam_refine"]["h"]) for r in rows),
           str([r["spec"]["tag"] for r in rows]))
    ok("B: new and distinct", all(r["dedup"] == "new" for r in rows) and len({r["expected_id"] for r in rows}) == 2)
    ok("B: is_heavy is unchanged for a production row and true for an h 1.4 row; cond_id of the base has no f5", not DB.is_heavy(src) and DB.is_heavy({**src, "h_int": 1.4})
       and "f5" not in DB.cond_id(src))
    # C
    queue("fail")
    (J.QROOT / DB.F5_SMOKE_BASE / "DONE").unlink()
    ok("C: base row not DONE is a problem", [p for p in DB.build("b32")["problems"] if "base row" in p])
    queue("fail2")
    sj = J.QROOT / DB.F5_SMOKE_BASE / "spec.json"
    sj.write_text(json.dumps({**src, "entry_offset": 1.5}))
    ok("C: base row at another entry offset is a problem", [p for p in DB.build("b32")["problems"] if "expected" in p])
    sj.write_text(json.dumps({**src, "slip_tol": 3e-4}))
    ok("C: base row with another slip_tol is a problem", [p for p in DB.build("b32b")["problems"] if "expected" in p])
    # D
    root = queue("dry")
    before = sorted(str(x.relative_to(root)) for x in root.rglob("*"))
    buf = io.StringIO()
    for b in ("b32", "b32b"):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = DB.dry_run(b)
        txt = buf.getvalue()
        ok(f"D: {b} dry run exits 0, lists 1 job, writes nothing", rc == 0 and "jobs (1):" in txt and before == sorted(str(x.relative_to(root)) for x in root.rglob("*")), txt[-300:] if rc else "")
finally:
    J.QROOT, J.RESULTS = REAL_Q, REAL_R
    shutil.rmtree(BASE, ignore_errors=True)

n_fail = sum(not c for _, c in checks)
print(f"{len(checks) - n_fail}/{len(checks)} passed, {n_fail} failed")
sys.exit(1 if n_fail else 0)
