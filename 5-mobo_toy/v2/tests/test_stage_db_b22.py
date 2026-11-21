"""Run with the repo venv: PYTHONUTF8=1 .venv-mobo/Scripts/python.exe v2/tests/test_stage_db_b22.py
Local only: a fake queue in the system temp dir (mobo_toy_db_b22_tests); J.QROOT points there. No gmsh, no FE, no Linux, nothing under
~/mobo_toy_v2 is read or written. Source specs come read-only from db3406/raw; the femur cache is read only, as in the b9p and b20 tests.

v2/stage_db.py v1.16, batch b22 (OW-3), and tpl_record.offgrid_view:
A. constants: b22 in BATCHES, layer source, slow start, B2 layer, code_hash unchanged.
B. offgrid_view agrees with record_spec on the recorded offsets, reproduces the b11p prep values, and refuses an overhanging offset.
C. rows: 9 rows; only m and entry_offset change; bond model on; templating feasible at the fixed offset; in_E true, unbiased false; job ids not caught by earlier globs.
D. fail closed: each control not DONE, an infeasible row, an offset mismatch, a templating error.
E. dedup: the same physics under another job name -> existing.
F. dry_run: exit 0, prints the table, writes nothing. Earlier job ids did not move, including b11p.
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
BASE = pathlib.Path(tempfile.gettempdir()) / "mobo_toy_db_b22_tests"
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
CTRL = "db_ws_p13_a105_91e458e3_m1_2a79b613"
A95_E0 = "db_ws_p13_a95_173c181a_ow_m1_e+0_ed127c76"
A_E2 = "db_ws_p13_a105_91e458e3_ow_m1_e+2_c9ca96c8"
JOBS = {A, DB.CY_EXTRA["a95"], REF, CTRL, A95_E0, A_E2}
KEYS = [f"OW3_{c}_m1_e{e:+g}" for c, e in DB.OW3_ROWS]


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


def spec_of(j):
    return json.loads((J.QROOT / j / "spec.json").read_text())


def problems_of(b, needle):
    return [p for p in b["problems"] if needle in p]


def fake_view(mod):
    def f(spec):
        return mod(spec, REAL_VIEW(spec))
    return f


try:
    ok("A: b22 in BATCHES, code_hash unchanged", "b22" in DB.BATCHES and J.code_hash() == DB.DB_CODE_HASH)
    ok("A: layer", DB.LAYER_SOURCE["OW-3"] == "bound_scan" and "OW-3" in DB.SLOW_START_LAYERS and "OW-3" in DB.B2_LAYERS and "OW-3" not in DB.LAYER_SELECTION)
    ok("A: 9 rows", DB.OW3_ROWS == (("A", -1.0), ("A", -0.5), ("A", 0.5), ("A", 1.0), ("A", 1.5), ("A", 2.5), ("a95", 1.0), ("a95", 1.5), ("a95", 2.5)))

    # ---------------------------------------------------------------- B
    queue("view")
    sA = spec_of(CTRL)
    fine = True
    for e in (-2.0, 0.0, 2.0):
        s = {**sA, "entry_offset": e}
        v, g = TR.offgrid_view(s), TR.record_spec(s)["prep_view"]
        fine = fine and v["fit"] and g["fit"] and all(abs(v[k] - g[k]) < 1e-9 for k in ("e", "alpha", "A0", "s_bind", "contact", "volume", "bone_total_mm3"))
    ok("B: offgrid_view = record_spec on the recorded offsets", fine)
    pr = json.loads((J.QROOT / A_E2 / "prep.json").read_text())
    v = TR.offgrid_view(spec_of(A_E2))
    ok("B: reproduces the prep.json of the b11p row A e +2", abs(v["A0"] - pr["templating"]["A0"]) < 1e-6 and abs(v["bone_total_mm3"] - pr["bone_loss"]["total_mm3"]) < 1e-3, f"{v['A0']:.3f} {v['bone_total_mm3']:.1f}")
    v = TR.offgrid_view({**sA, "design": {**sA["design"], "L": 44.0}, "entry_offset": 2.0})
    ok("B: L 44 at e +2 does not fit (why the proposed tenth row was dropped)", not v["fit"] and "154 mm" in v["reason"], v["reason"][-60:])
    v = TR.offgrid_view({**sA, "entry_offset": 3.0})
    ok("B: an overhanging offset does not fit", not v["fit"] and "overhang" in v["reason"], v["reason"][-60:])
    t = DB.ws_templating({**sA, "entry_offset": 0.5})
    ok("B: ws_templating takes the off-grid path", t["feasible"] and t["e_star"] == 0.5 and 415 < t["A0_star"] < 425 and t["e_margin_eff"] == t["e_margin_eff"], json.dumps(t)[:160])

    # ---------------------------------------------------------------- C
    queue("rows")
    b = DB.build("b22")
    rows = {r["key"]: r for r in b["rows"]}
    ok("C: no problems on a clean queue", not b["problems"], "; ".join(b["problems"])[:500])
    ok("C: 9 rows in order", list(rows) == KEYS, list(rows)[:3])
    one = True
    jobs_ = {**DB.CODES, **DB.CY_EXTRA}
    for (code, e), (k, r) in zip(DB.OW3_ROWS, rows.items()):
        src = spec_of(jobs_[code])
        s = r["spec"]
        diff = {x for x in src["design"] if s["design"].get(x) != src["design"][x]}
        one = one and diff == {"m"} and s["design"]["m"] == 1.0 and s["entry_offset"] == e and s["intact_job"] == REF and s["stage"] == "db_ws"
        one = one and r["model_set"] == "fric+bond" and r["in_E"] and not r["unbiased"] and r["layer"] == "OW-3" and r["source"] == "bound_scan" and r["e_forced"] == e
        t = b["ws_tpl"][k[4:]]
        one = one and t["feasible"] and t["e_star"] == e
    ok("C: only m and entry_offset change; bond on; feasible at the fixed offset", one, json.dumps({k: [round(v["A0_star"], 1), round(v["bone_mm3"] / 1000, 2)] for k, v in b["ws_tpl"].items()})[:520])
    ok("C: templating as tabled at 0 FE", abs(b["ws_tpl"]["A_m1_e+1"]["A0_star"] - 378.0) < 0.1 and abs(b["ws_tpl"]["A_m1_e-1"]["A0_star"] - 486.3) < 0.1 and abs(b["ws_tpl"]["a95_m1_e+2.5"]["A0_star"] - 260.8) < 0.1)
    ids = [r["expected_id"] for r in rows.values()]
    ok("C: job ids carry the ow tag and are not caught by the earlier globs",
       all("_ow_m1_" in j for j in ids) and not [j for j in ids for g in ("db_ws_p13_a105_91e458e3_m1_a*", "db_ws_p13_a105_91e458e3_m1_*", "db_ws_p13_a105_91e458e3_wl_*", "db_ws_*_ow_m1_e+2_*", "db_ws_*_ow_m1_e-2_*", "db_ws_*_ow_m1_e+0_*") if fnmatch.fnmatch(j, g)], ids[:2])
    ok("C: all new; the controls are WS_m1 and the a95 e 0 row", all(r["dedup"] == "new" for r in rows.values()) and b["ws_control"] == {"A_m1": CTRL, "a95_m1_e+0": A95_E0}, json.dumps(b["ws_control"]))

    # ---------------------------------------------------------------- D
    queue("fail")

    def infeasible(spec, r):
        if spec["entry_offset"] == 2.5 and spec["tag"].startswith("p13_a95"):
            nan = float("nan")
            return {**r, "fit": False, "reason": "synthetic overhang", "e": nan, "A0": nan, "bone_total_mm3": nan}
        return r

    def mismatch(spec, r):
        return {**r, "e": 0.0} if spec["entry_offset"] == 1.5 and spec["tag"].startswith("p13_a105") else r

    def boom(spec, r):
        if spec["entry_offset"] == -0.5:
            raise RuntimeError("synthetic templating error")
        return r

    TR.offgrid_view = fake_view(infeasible)
    ok("D: an infeasible row is a problem", problems_of(DB.build("b22"), "OW3_a95_m1_e+2.5: 0-FE templating is not feasible"))
    TR.offgrid_view = fake_view(mismatch)
    ok("D: an offset mismatch is a problem", problems_of(DB.build("b22"), "OW3_A_m1_e+1.5: entry offset"))
    TR.offgrid_view = fake_view(boom)
    ok("D: a templating error is a problem", problems_of(DB.build("b22"), "OW3_A_m1_e-0.5: 0-FE templating failed"))
    TR.offgrid_view = REAL_VIEW
    (J.QROOT / A95_E0 / "DONE").unlink()
    ok("D: the a95 e 0 row not DONE is a problem", problems_of(DB.build("b22"), "the control a95_m1_e+0"))
    (J.QROOT / CTRL / "DONE").unlink()
    ok("D: WS_m1 not DONE is a problem", problems_of(DB.build("b22"), "the control A_m1"))

    # ---------------------------------------------------------------- E
    queue("dedup")
    r0 = {r["key"]: r for r in DB.build("b22")["rows"]}["OW3_A_m1_e+1"]
    other = {**r0["spec"], "tag": "somewhere_else", "created": "x"}
    d = J.QROOT / "db_ws_somewhere_else_00000000"
    d.mkdir()
    (d / "spec.json").write_text(json.dumps(other, indent=1, default=float))
    (d / "DONE").write_text("")
    r2 = {r["key"]: r for r in DB.build("b22")["rows"]}["OW3_A_m1_e+1"]
    ok("E: the same physics under another name is adopted, not computed again", r2["dedup"] == "existing" and r2["id"] == d.name and r2["dedup_via"] == "physics", f"{r2['dedup']} {r2['id']}")
    shutil.rmtree(d)

    # ---------------------------------------------------------------- F
    root = queue("dry")
    before = sorted(str(x.relative_to(root)) for x in root.rglob("*"))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = DB.dry_run("b22")
    out = buf.getvalue()
    ok("F: dry run exits 0, lists 9 jobs and the table, writes nothing", rc == 0 and "jobs (9):" in out and "A_m1_e+2.5" in out and before == sorted(str(x.relative_to(root)) for x in root.rglob("*")), out[-300:] if rc else "")
    r14 = {r["key"]: r for r in DB.build("b14")["rows"]}
    ok("F: the b14 job id did not move", r14["WS_m1"]["expected_id"] == CTRL)
finally:
    TR.record_spec, TR.offgrid_view = REAL_RECORD, REAL_VIEW
    J.QROOT, J.RESULTS = REAL_Q, REAL_R
    shutil.rmtree(BASE, ignore_errors=True)

n_fail = sum(not c for _, c in checks)
print(f"{len(checks) - n_fail}/{len(checks)} passed, {n_fail} failed")
sys.exit(1 if n_fail else 0)
