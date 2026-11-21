"""Run with the repo venv: PYTHONUTF8=1 .venv-mobo/Scripts/python.exe v2/tests/test_stage_db_b15.py
Local only: a fake queue in the system temp dir (mobo_toy_db_b15_tests); J.QROOT points there. No gmsh, no FE, no Linux, nothing under
~/mobo_toy_v2 is read or written. The specs of A, of the h 2.0 intact reference and of the control WS_m1 come read-only from db3406/raw.

v2/stage_db.py v1.11, batch b15 (candidate A at m 1.0 x alpha 50 / 55 / 60):
A. constants: b15 in BATCHES, the new layer has source bound_scan, selection stratum, slow start, code_hash unchanged.
B. rows: 3 rows, each = the physics of A with only m and alpha changed and the bond model added; reference REF_H2; templating feasible with e* of A;
   outside the v1 box; in_E true, unbiased false; job ids db_ws_p13_a105_91e458e3_m1_a<alpha>_<hash8>; the control is the b14 job WS_m1.
C. fail closed: infeasible row, offset jump, templating error, control absent, control not DONE, A not DONE.
D. dedup: the same physics under another job name -> existing; already queued under the expected id -> queued.
E. dry_run: exit 0, prints the templating table, writes nothing.
F. b14 ids unchanged: this batch did not move the rows of the earlier batch.
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
BASE = pathlib.Path(tempfile.gettempdir()) / "mobo_toy_db_b15_tests"
shutil.rmtree(BASE, ignore_errors=True)
BASE.mkdir(parents=True)

import jobs as J  # noqa: E402
import stage_db as DB  # noqa: E402
import stage_neckopt as SN  # noqa: E402
import tpl_record as TR  # noqa: E402

T_START = time.perf_counter()
REAL_Q, REAL_R = J.QROOT, J.RESULTS
REAL_RECORD = TR.record_spec
checks = []
A, REF = DB.CODES["A"], DB.REF_H2
CTRL = "db_ws_p13_a105_91e458e3_m1_2a79b613"
KEYS = ["WS_m1_a50", "WS_m1_a55", "WS_m1_a60"]


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


def queue(name):
    root = BASE / name
    J.QROOT, J.RESULTS = root / "queue", root / "results"
    assert not str(J.QROOT).startswith(str(pathlib.Path.home() / "mobo_toy_v2"))
    J.QROOT.mkdir(parents=True)
    J.RESULTS.mkdir(parents=True)
    for j in (A, REF, CTRL):
        extract(j, J.QROOT)
    return root


def problems_of(b, needle):
    return [p for p in b["problems"] if needle in p]


def fake(mod):
    def f(spec):
        return mod(spec, REAL_RECORD(spec))
    return f


try:
    ok("A: b15 in BATCHES, code_hash unchanged", "b15" in DB.BATCHES and J.code_hash() == DB.DB_CODE_HASH)
    L = "WS m alpha"
    ok("A: layer source bound_scan, selection stratum, slow start, manifest field",
       DB.LAYER_SOURCE[L] == "bound_scan" and DB.LAYER_SELECTION.get(L, "stratum") == "stratum" and L in DB.SLOW_START_LAYERS and L in DB.B2_LAYERS)

    queue("rows")
    src = json.loads((J.QROOT / A / "spec.json").read_text())
    b = DB.build("b15")
    rows = {r["key"]: r for r in b["rows"]}
    ok("B: no problems on a clean queue", not b["problems"], "; ".join(b["problems"])[:500])
    ok("B: the 3 expected keys in alpha order", [r["key"] for r in b["rows"]] == KEYS, [r["key"] for r in b["rows"]])
    one = True
    for k, a in zip(KEYS, (50.0, 55.0, 60.0)):
        s = rows[k]["spec"]
        diff = {x for x in src["design"] if s["design"].get(x) != src["design"][x]}
        rest = {x: s.get(x) == src.get(x) for x in ("h_int", "min_A0", "model", "h_cut", "slip_tol", "delta", "collar_rule", "femur_id", "neck_axis",
                                                    "margin_check", "ref_cut_mm", "a_bounds_max")}
        one = one and diff == {"m", "alpha"} and s["design"]["m"] == 1.0 and s["design"]["alpha"] == a and all(rest.values()) and set(s["design"]) == set(src["design"])
    ok("B: each row changes only m and alpha, all other physics equal to A", one)
    ok("B: friction + bond with reference REF_H2, kind variant, stage db_ws",
       all(r["model_set"] == "fric+bond" and r["spec"]["intact_job"] == REF and r["spec"]["kind"] == "variant" and r["stage"] == "db_ws"
           and not r["spec"].get("fric_only") and not r["spec"].get("bond_only") for r in rows.values()))
    ok("B: job ids and all new", all(r["expected_id"].startswith(f"db_ws_p13_a105_91e458e3_m1_a{k[-2:]}_") and r["dedup"] == "new" for k, r in rows.items()))
    ok("B: in_E true, unbiased false, source bound_scan", all(r["in_E"] and not r["unbiased"] and r["source"] == "bound_scan" for r in rows.values()))
    ok("B: not in any optimisation family", not [k for k, r in rows.items() for p in DB.CHECK_PHASES if SN.Phase(p).in_family(r["spec"])])
    t = b["ws_tpl"]
    ok("B: templating table has A and the 3 rows, all feasible at e* 0", set(t) == {"A", "m1_a50", "m1_a55", "m1_a60"}
       and all(v["feasible"] and v["e_star"] == 0.0 for v in t.values()),
       json.dumps({k: [round(v["A0_star"], 1), round(v["bone_mm3"]), round(v["e_margin_eff"], 3), v["e_star"], v["feasible"]] for k, v in t.items()}))
    ph = SN.Phase(13)
    box = lambda s: all(ph.space[k][0] - 1e-9 <= float(s["design"][k]) <= ph.space[k][1] + 1e-9 for k in ph.vars if k in s["design"])  # noqa: E731
    ok("B: all 3 rows outside the v1 box", not any(box(r["spec"]) for r in rows.values()))
    ok("B: the control is the b14 job WS_m1", b.get("ws_control") == CTRL, b.get("ws_control"))

    queue("fail")

    def infeasible(spec, r):
        if spec["design"]["alpha"] == 55.0:
            r["feasible"], r["reason"] = False, "no_offset"
        return r

    def jump(spec, r):
        if spec["design"]["alpha"] == 60.0:
            r["e_star"] = -2.0
        return r

    def boom(spec, r):
        if spec["design"]["alpha"] == 50.0:
            raise RuntimeError("synthetic templating error")
        return r

    def base_boom(spec, r):
        raise FileNotFoundError("no femur cache")

    TR.record_spec = fake(infeasible)
    ok("C: an infeasible row is a problem", problems_of(DB.build("b15"), "WS_m1_a55: 0-FE templating is not feasible"))
    TR.record_spec = fake(jump)
    ok("C: an entry-offset jump is a problem", problems_of(DB.build("b15"), "WS_m1_a60: entry offset"))
    TR.record_spec = fake(boom)
    ok("C: a templating error on a row is a problem", problems_of(DB.build("b15"), "WS_m1_a50: 0-FE templating failed"))
    TR.record_spec = fake(base_boom)
    ok("C: a templating error on the base design is a problem", problems_of(DB.build("b15"), "of the base design"))
    TR.record_spec = REAL_RECORD
    (J.QROOT / CTRL / "DONE").unlink()
    ok("C: control not DONE is a problem", problems_of(DB.build("b15"), "the control WS_m1"))
    shutil.rmtree(J.QROOT / CTRL)
    ok("C: control absent is a problem", problems_of(DB.build("b15"), "is absent"))
    (J.QROOT / A / "DONE").unlink()
    try:
        DB.build("b15")
        ok("C: A not DONE refuses", False)
    except SystemExit as e:
        ok("C: A not DONE refuses", "not DONE" in str(e), str(e)[:90])

    queue("dedup")
    r0 = {r["key"]: r for r in DB.build("b15")["rows"]}["WS_m1_a50"]
    d = J.QROOT / r0["expected_id"]
    d.mkdir()
    (d / "spec.json").write_text(json.dumps({**r0["spec"], "created": "x"}, indent=1, default=float))
    r1 = {r["key"]: r for r in DB.build("b15")["rows"]}["WS_m1_a50"]
    ok("D: the expected id already in the queue -> queued", r1["dedup"] == "queued" and r1["id"] == r0["expected_id"], r1["dedup"])
    shutil.rmtree(d)
    other = {**r0["spec"], "stage": "db_fd", "tag": "same_physics", "created": "x", "kind": "variant"}
    d = J.QROOT / "db_fd_same_physics_00000000"
    d.mkdir()
    (d / "spec.json").write_text(json.dumps(other, indent=1, default=float))
    (d / "DONE").write_text("")
    r2 = {r["key"]: r for r in DB.build("b15")["rows"]}["WS_m1_a50"]
    ok("D: the same physics under another job name -> existing", r2["dedup"] == "existing" and r2["id"] == d.name and r2["dedup_via"] == "physics", f"{r2['dedup']} {r2['id']}")
    shutil.rmtree(d)

    root = queue("dry")
    before = sorted(str(x.relative_to(root)) for x in root.rglob("*"))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = DB.dry_run("b15")
    out = buf.getvalue()
    after = sorted(str(x.relative_to(root)) for x in root.rglob("*"))
    ok("E: dry run exits 0", rc == 0, out[-400:] if rc else "")
    ok("E: prints the templating table and 3 jobs", "0-FE templating" in out and "jobs (3):" in out and '"ws_tpl"' in out)
    ok("E: writes nothing", before == after, str(set(after) ^ set(before))[:200])

    queue("b14ids")
    r14 = {r["key"]: r for r in DB.build("b14")["rows"]}
    ok("F: the b14 job ids did not move", r14["WS_m1"]["expected_id"] == CTRL and r14["WS_a50"]["expected_id"] == "db_ws_p13_a105_91e458e3_a50_4f9e71ac",
       r14["WS_m1"]["expected_id"])
finally:
    TR.record_spec = REAL_RECORD
    J.QROOT, J.RESULTS = REAL_Q, REAL_R
    shutil.rmtree(BASE, ignore_errors=True)

n_fail = sum(not c for _, c in checks)
print(f"{len(checks) - n_fail}/{len(checks)} passed, {n_fail} failed")
sys.exit(1 if n_fail else 0)
