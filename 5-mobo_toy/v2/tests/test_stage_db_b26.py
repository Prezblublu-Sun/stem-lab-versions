"""Run with the repo venv: PYTHONUTF8=1 .venv-mobo/Scripts/python.exe v2/tests/test_stage_db_b26.py
Local only: a fake queue in the system temp dir (mobo_toy_db_b26_tests); J.QROOT points there. No gmsh, no FE, no Linux, nothing under
~/mobo_toy_v2 is read or written. Source specs come read-only from db3406/raw.

v2/stage_db.py v1.20, batches b26 (STS-1) and b27 (STS-1 mesh):
A. constants: both in BATCHES, layer sources, slow start, code_hash unchanged; the sit-to-stand load is 1714 N, 24 / 8 deg; 15 + 4 rows.
B. b26: no problems; each row differs from its baseline only by cfg.load, friction only, stage db_cd; the offset is kept; job ids readable; all new.
C. b27: 2 references + 4 mesh rows; references copy the stair h 1.94 / 2.06 reference and change only the load; mesh rows carry the bond model and point at the reference of their own mesh and load.
D. fail closed: a baseline not DONE, a wrong kind of baseline, a stair reference not DONE.
E. dedup: the same physics under another name is adopted, not computed again.
F. dry run exits 0 and writes nothing, for both. Earlier job ids did not move.
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
BASE = pathlib.Path(tempfile.gettempdir()) / "mobo_toy_db_b26_tests"
shutil.rmtree(BASE, ignore_errors=True)
BASE.mkdir(parents=True)

import jobs as J  # noqa: E402
import stage_db as DB  # noqa: E402

T_START = time.perf_counter()
REAL_Q, REAL_R = J.QROOT, J.RESULTS
checks = []
A, REF = DB.CODES["A"], DB.REF_H2
R194, R206 = "db_ref_intact_h1.94_0df7c4b7", "db_ref_intact_h2.06_f1de5f78"
CTRL = "db_ws_p13_a105_91e458e3_m1_2a79b613"
JOBS = {A, REF, R194, R206} | {j for _, j in DB.STS1_ROWS}
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


try:
    ok("A: both in BATCHES, code_hash unchanged", {"b26", "b27"} <= set(DB.BATCHES) and J.code_hash() == DB.DB_CODE_HASH)
    ok("A: layers", DB.LAYER_SOURCE["STS-1"] == "cond_anchor" and DB.LAYER_SOURCE["STS-1 mesh"] == "noise" and {"STS-1", "STS-1 mesh"} <= set(DB.SLOW_START_LAYERS))
    ok("A: the load", DB.STS_LOADS[DB.STS1_LOAD] == {"resultant_N": 1714.0, "alpha_front_deg": 24.0, "alpha_sagit_deg": 8.0})
    ok("A: 15 + 4 rows, no repeated baseline", len(DB.STS1_ROWS) == 15 and len({j for _, j in DB.STS1_ROWS}) == 15 and len(DB.STS1M_ROWS) * len(DB.STS1M_H) == 4)

    # ---------------------------------------------------------------- B
    queue("rows")
    b = DB.build("b26")
    rows = {r["key"]: r for r in b["rows"]}
    ok("B: no problems on a clean queue", not b["problems"], "; ".join(b["problems"])[:500])
    ok("B: 15 rows in order", list(rows) == [f"STS1_{lab}" for lab, _ in DB.STS1_ROWS])
    same = True
    for (lab, j), r in zip(DB.STS1_ROWS, rows.values()):
        src, s = spec_of(j), r["spec"]
        phys = lambda x: {k: v for k, v in x.items() if k in DB.PHYS_KEYS and k != "cfg"}  # noqa: E731
        same = same and phys(src) == phys(s) and s["cfg"] == {"load": DB.STS_LOADS["F1714"]} and s["fric_only"] and "intact_job" not in s and s["stage"] == "db_cd" and s["kind"] == "variant"
        same = same and s.get("entry_offset") == src.get("entry_offset") and r["model_set"] == "fric" and r["layer"] == "STS-1" and r["source"] == "cond_anchor" and r["in_E"] and not r["unbiased"] and r["source_job"] == j
    ok("B: only the load changes; friction only; the offset is kept", same)
    ids = [r["expected_id"] for r in rows.values()]
    ok("B: readable job ids", ids[1].startswith("db_cd_p13_a105_91e458e3_m1_F1714_") and "db_cd_opt1_08_e+0_F1714_" in ids[-1] and all("_db_" not in j for j in ids), ids[1])
    ok("B: all new and distinct", all(r["dedup"] == "new" for r in rows.values()) and len(set(ids)) == 15)

    # ---------------------------------------------------------------- C
    b7 = DB.build("b27")
    r7 = {r["key"]: r for r in b7["rows"]}
    ok("C: no problems on a clean queue", not b7["problems"], "; ".join(b7["problems"])[:500])
    ok("C: 2 references first, then 4 mesh rows", list(r7)[:2] == ["REF_h1.94_sts1714", "REF_h2.06_sts1714"] and len(r7) == 6)
    fine = True
    for h, src in ((1.94, R194), (2.06, R206)):
        k = f"REF_h{h:g}_sts1714"
        s, s0 = r7[k]["spec"], spec_of(src)
        phys = lambda x: {a: v for a, v in x.items() if a in DB.PHYS_KEYS and a != "cfg"}  # noqa: E731
        fine = fine and phys(s) == phys(s0) and s["kind"] == "intact" and s["stage"] == "db_ref" and s["cfg"] == {"load": DB.STS_LOADS["F1714"]} and r7[k]["layer"] == "REF" and b7["ref_by_key"][k] == r7[k]["id"]
    ok("C: references copy the stair reference and change only the load", fine)
    fine = True
    for lab, j in DB.STS1M_ROWS:
        src = spec_of(j)
        for h in DB.STS1M_H:
            r = r7[f"STS1M_h{h:g}_{lab}"]
            s = r["spec"]
            phys = lambda x: {a: v for a, v in x.items() if a in DB.PHYS_KEYS and a not in ("cfg", "h_int")}  # noqa: E731
            fine = fine and phys(s) == phys(src) and s["h_int"] == h and s["cfg"] == {"load": DB.STS_LOADS["F1714"]} and s["stage"] == "db_nz" and r["model_set"] == "fric+bond" and not s.get("fric_only")
            fine = fine and s["intact_job"] == r7[f"REF_h{h:g}_sts1714"]["id"] and r["ref_key"] == f"REF_h{h:g}_sts1714" and r["source"] == "noise"
    ok("C: mesh rows carry the bond model and the reference of their own mesh and load", fine)
    ok("C: the rows pass the reference rule", not [m for r in r7.values() if r["spec"].get("intact_job") for m in DB.ref_mismatch(r["spec"], r7[f"REF_h{r['spec']['h_int']:g}_sts1714"]["spec"])])

    # ---------------------------------------------------------------- D
    queue("fail")
    (J.QROOT / DB.STS1_ROWS[3][1] / "DONE").unlink()
    ok("D: a baseline not DONE refuses", "not DONE" in refused("b26"), refused("b26")[:90])
    queue("fail2")
    p = J.QROOT / DB.STS1_ROWS[0][1] / "spec.json"
    s = json.loads(p.read_text())
    s["cfg"] = {"load": DB.STS_LOADS["F3839"]}
    p.write_text(json.dumps(s))
    ok("D: a baseline with its own load refuses", "want a db_ws / db_al baseline row" in refused("b26"))
    queue("fail3")
    (J.QROOT / R194 / "DONE").unlink()
    ok("D: a stair reference not DONE is a problem", problems_of(DB.build("b27"), "reference REF_h1.94"))

    # ---------------------------------------------------------------- E
    queue("dedup")
    r0 = {r["key"]: r for r in DB.build("b26")["rows"]}["STS1_A_m1_e+1"]
    other = {**r0["spec"], "tag": "somewhere_else", "created": "x"}
    d = J.QROOT / "db_cd_somewhere_else_00000000"
    d.mkdir()
    (d / "spec.json").write_text(json.dumps(other, indent=1, default=float))
    (d / "DONE").write_text("")
    r2 = {r["key"]: r for r in DB.build("b26")["rows"]}["STS1_A_m1_e+1"]
    ok("E: the same physics under another name is adopted", r2["dedup"] == "existing" and r2["id"] == d.name and r2["dedup_via"] == "physics", f"{r2['dedup']} {r2['id']}")
    shutil.rmtree(d)

    # ---------------------------------------------------------------- F
    root = queue("dry")
    before = sorted(str(x.relative_to(root)) for x in root.rglob("*"))
    for batch, n in (("b26", 15), ("b27", 6)):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = DB.dry_run(batch)
        out = buf.getvalue()
        ok(f"F: {batch} dry run exits 0, lists {n} jobs, writes nothing", rc == 0 and f"jobs ({n}):" in out and before == sorted(str(x.relative_to(root)) for x in root.rglob("*")), out[-400:] if rc else "")
    r14 = {r["key"]: r for r in DB.build("b14")["rows"]}
    ok("F: the b14 job id did not move", r14["WS_m1"]["expected_id"] == CTRL)
    ok("F: not caught by the earlier globs", not [j for j in ids for g in ("db_cd_*_F3839_*", "db_ws_*", "db_al_*", "sb13_*") if fnmatch.fnmatch(j, g)])
finally:
    J.QROOT, J.RESULTS = REAL_Q, REAL_R
    shutil.rmtree(BASE, ignore_errors=True)

n_fail = sum(not c for _, c in checks)
print(f"{len(checks) - n_fail}/{len(checks)} passed, {n_fail} failed")
sys.exit(1 if n_fail else 0)
