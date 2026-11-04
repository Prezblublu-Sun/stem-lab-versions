"""Run with the repo venv: PYTHONUTF8=1 .venv-mobo/Scripts/python.exe v2/tests/test_stage_db_b23.py
Local only: a fake queue in the system temp dir (mobo_toy_db_b23_tests); J.QROOT points there. No gmsh, no FE, no Linux, nothing under
~/mobo_toy_v2 is read or written. Source specs come read-only from db3406/raw; the e rows are written into the fake queue as DONE; the femur cache is read only.

v2/stage_db.py v1.17, batch b23 (OW-4):
A. constants: b23 in BATCHES, layer sources, slow start, h 1.4 layer, code_hash unchanged.
B. rows: 14 rows in order; each differs from its e row only by delta, cfg.load, cycles or h_int and slip_tol; friction only except the h 1.4 row; design keeps m 1.0, entry offset as written.
C. fail closed: a baseline e row not DONE, the h 1.4 reference not DONE, an infeasible offset, an offset mismatch, a templating error.
D. dedup: the same physics under another job name -> existing. Earlier job ids did not move.
E. dry_run: exit 0, writes nothing, lists the heavy row.
"""
import contextlib
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
BASE = pathlib.Path(tempfile.gettempdir()) / "mobo_toy_db_b23_tests"
shutil.rmtree(BASE, ignore_errors=True)
BASE.mkdir(parents=True)

import jobs as J  # noqa: E402
import stage_db as DB  # noqa: E402
import tpl_record as TR  # noqa: E402

T_START = time.perf_counter()
REAL_Q, REAL_R = J.QROOT, J.RESULTS
REAL_RECORD, REAL_VIEW = TR.record_spec, TR.offgrid_view
checks = []
A, REF = DB.CODES["A"], DB.REF_H2
TAG = "p13_a105_91e458e3"
REF14 = "db_ref_intact_h1.4_b7b166b8"
JOBS = {A, REF, REF14}
KEYS = [f"OW4_{c}_e{e:+g}" for e in (1.0, 2.0, 2.5) for c in ("d0.05", "F3839", "both", "S40")] + ["OW4_c10_e+2", "OW4_h1.4_e+2"]
snap = sorted((RAW / "results").iterdir())[-1]


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
    shutil.copy2(snap / "db_manifest_b1.json", J.RESULTS / "db_manifest_b1.json")
    ids = {}
    src = json.loads((J.QROOT / A / "spec.json").read_text())
    for e in DB.OW4_E:
        p_ = DB._phys(src, A)
        p_["design"] = {**p_["design"], "m": 1.0}
        p_["entry_offset"] = float(e)
        s = DB._variant(p_, "db_ws", f"{TAG}_ow_m1_e{e:+g}", "full", intact_job=REF)
        i = DB.expected_id(s)
        d = J.QROOT / i
        d.mkdir()
        (d / "spec.json").write_text(json.dumps({**s, "created": "x"}, indent=1, default=float))
        (d / "DONE").write_text("")
        ids[e] = i
    return root, ids


def spec_of(j):
    return json.loads((J.QROOT / j / "spec.json").read_text())


def problems_of(b, needle):
    return [p for p in b["problems"] if needle in p]


def fake_view(mod):
    def f(spec):
        return mod(spec, REAL_VIEW(spec))
    return f


try:
    ok("A: b23 in BATCHES, code_hash unchanged", "b23" in DB.BATCHES and J.code_hash() == DB.DB_CODE_HASH)
    ok("A: layers", DB.LAYER_SOURCE["OW-4"] == "cond_anchor" and DB.LAYER_SOURCE["OW-4 cy"] == "cycle_variant" and DB.LAYER_SOURCE["OW-4 h1.4"] == "fid_h14"
       and all(x in DB.SLOW_START_LAYERS for x in ("OW-4", "OW-4 cy", "OW-4 h1.4")) and "OW-4 h1.4" in DB.H14_LAYERS)

    # ---------------------------------------------------------------- B
    _, ids = queue("rows")
    b = DB.build("b23")
    rows = {r["key"]: r for r in b["rows"]}
    ok("B: no problems on a clean queue", not b["problems"], "; ".join(b["problems"])[:600])
    ok("B: 14 rows in order", list(rows) == KEYS, list(rows)[:5])
    F3839, S40 = DB.STS_LOADS["F3839"], DB.TQ0_LOADS["S40"]
    fine = True
    for k, r in rows.items():
        e = float(k.split("_e")[1])
        s, b0 = r["spec"], spec_of(ids[e])
        cond = k.split("_")[1]
        same_design = s["design"] == b0["design"] and s["design"]["m"] == 1.0 and s["entry_offset"] == e
        want_delta = 0.05 if cond in ("d0.05", "both") else b0["delta"]
        want_load = F3839 if cond in ("F3839", "both") else S40 if cond == "S40" else None
        got_load = (s.get("cfg") or {}).get("load")
        fine = fine and same_design and s["delta"] == want_delta and got_load == want_load
        if cond == "h1.4":
            fine = fine and s["h_int"] == 1.4 and s["slip_tol"] == DB.H14_SLIP_TOL and s["intact_job"] == REF14 and s["stage"] == "db_fd" and r["model_set"] == "fric+bond" and r["heavy"] and r["layer"] == "OW-4 h1.4" and r["ref_key"] == "REF_h1.4"
        elif cond == "c10":
            fine = fine and s["cycles"] == 10 and s["fric_only"] and s["stage"] == "db_cd" and r["layer"] == "OW-4 cy" and r["source"] == "cycle_variant"
        else:
            fine = fine and s["fric_only"] and "intact_job" not in s and s["stage"] == "db_cd" and r["layer"] == "OW-4" and r["source"] == "cond_anchor" and "cycles" not in {x for x in s if s[x] != b0.get(x)}
    ok("B: each row differs from its e row only by the written condition", fine)
    tp = b["ws_tpl"]
    ok("B: templating at the three offsets", set(tp) == {"e+1", "e+2", "e+2.5"} and abs(tp["e+1"]["A0_star"] - 378.0) < 0.1 and abs(tp["e+2"]["A0_star"] - 298.8) < 0.1 and abs(tp["e+2.5"]["A0_star"] - 262.4) < 0.1, json.dumps({k: round(v["A0_star"], 1) for k, v in tp.items()}))
    ok("B: all new; the controls are the e rows", all(r["dedup"] == "new" for r in rows.values()) and b["ws_control"] == {f"e{e:+g}": i for e, i in ids.items()}, json.dumps(b["ws_control"])[:200])
    ok("B: job ids", rows["OW4_d0.05_e+1"]["expected_id"].startswith(f"db_cd_{TAG}_ow_m1_e+1_d0.05_") and rows["OW4_h1.4_e+2"]["expected_id"].startswith(f"db_fd_{TAG}_ow_m1_e+2_h1.4_") and rows["OW4_c10_e+2"]["expected_id"].startswith(f"db_cd_{TAG}_ow_m1_e+2_c10_"), rows["OW4_S40_e+2.5"]["expected_id"])
    ok("B: reference map has h 2 and h 1.4", b["ref_id"] == {"2": REF, "1.4": REF14}, json.dumps(b["ref_id"]))

    # ---------------------------------------------------------------- C
    _, ids = queue("fail")

    def infeasible(spec, r):
        if spec["entry_offset"] == 2.5:
            nan = float("nan")
            return {**r, "fit": False, "reason": "synthetic overhang", "e": nan, "A0": nan, "bone_total_mm3": nan}
        return r

    def mismatch(spec, r):
        return {**r, "e": 0.0} if spec["entry_offset"] == 1.0 else r

    def boom(spec, r):
        if spec["entry_offset"] == 2.5:
            raise RuntimeError("synthetic templating error")
        return r

    TR.offgrid_view = fake_view(infeasible)
    ok("C: an infeasible offset is a problem", problems_of(DB.build("b23"), "OW4 e+2.5: 0-FE templating is not feasible"))
    TR.offgrid_view = fake_view(mismatch)
    ok("C: an offset mismatch is a problem", problems_of(DB.build("b23"), "OW4 e+1: entry offset"))
    TR.offgrid_view = fake_view(boom)
    ok("C: a templating error is a problem", problems_of(DB.build("b23"), "OW4 e+2.5: 0-FE templating failed"))
    TR.offgrid_view = REAL_VIEW
    (J.QROOT / ids[2.0] / "DONE").unlink()
    ok("C: a baseline e row not DONE is a problem", problems_of(DB.build("b23"), "the baseline e+2"))
    (J.QROOT / REF14 / "DONE").unlink()
    ok("C: the h 1.4 reference not DONE is a problem", problems_of(DB.build("b23"), "reference REF_h1.4"))

    # ---------------------------------------------------------------- D
    queue("dedup")
    r0 = {r["key"]: r for r in DB.build("b23")["rows"]}["OW4_S40_e+1"]
    other = {**r0["spec"], "tag": "somewhere_else", "created": "x"}
    d = J.QROOT / "db_cd_somewhere_else_00000000"
    d.mkdir()
    (d / "spec.json").write_text(json.dumps(other, indent=1, default=float))
    (d / "DONE").write_text("")
    r2 = {r["key"]: r for r in DB.build("b23")["rows"]}["OW4_S40_e+1"]
    ok("D: the same physics under another name is adopted, not computed again", r2["dedup"] == "existing" and r2["id"] == d.name, f"{r2['dedup']} {r2['id']}")
    shutil.rmtree(d)
    r14 = {r["key"]: r for r in DB.build("b14")["rows"]}
    ok("D: the b14 job id did not move", r14["WS_m1"]["expected_id"] == "db_ws_p13_a105_91e458e3_m1_2a79b613")

    # ---------------------------------------------------------------- E
    root, _ = queue("dry")
    before = sorted(str(x.relative_to(root)) for x in root.rglob("*"))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = DB.dry_run("b23")
    out = buf.getvalue()
    ok("E: dry run exits 0, lists 14 jobs, one heavy, writes nothing", rc == 0 and "jobs (14):" in out and "heavy rows (one at a time): ['OW4_h1.4_e+2']" in out and before == sorted(str(x.relative_to(root)) for x in root.rglob("*")), out[-400:] if rc else "")
finally:
    TR.record_spec, TR.offgrid_view = REAL_RECORD, REAL_VIEW
    J.QROOT, J.RESULTS = REAL_Q, REAL_R
    shutil.rmtree(BASE, ignore_errors=True)

n_fail = sum(not c for _, c in checks)
print(f"{len(checks) - n_fail}/{len(checks)} passed, {n_fail} failed")
sys.exit(1 if n_fail else 0)
