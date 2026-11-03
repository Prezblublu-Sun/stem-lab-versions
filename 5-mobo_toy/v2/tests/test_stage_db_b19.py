"""Run with the repo venv: PYTHONUTF8=1 .venv-mobo/Scripts/python.exe v2/tests/test_stage_db_b19.py
Local only: a fake queue in the system temp dir (mobo_toy_db_b19_tests); J.QROOT points there. No gmsh, no FE, no Linux, nothing under
~/mobo_toy_v2 is read or written. The specs of A, of the h 2.0 intact reference and of the control WS_m1 come read-only from db3406/raw;
the controls WS_m1_a50 and WS_m1_a55 are the b15 rows, written into the fake queue as DONE.

v2/stage_db.py v1.13, batch b19 (WL-1, candidate A at m 1.0 x L x alpha, entry offset fixed at 0):
A. constants: b19 in BATCHES, the layer has source bound_scan, selection stratum, slow start, code_hash unchanged.
B. rows: 5 rows; each = the physics of A with only m, L, alpha and entry_offset changed and the bond model added; templating feasible at e 0;
   in_E true, unbiased false; job ids start with db_ws_p13_a105_91e458e3_wl_ and are not caught by the m1_a* glob of b15.
C. fail closed: infeasible row, offset jump, A0 jump, templating error, control absent, control not DONE, A not DONE.
D. dedup: the same physics under another job name -> existing; b14 and b15 ids unchanged.
E. dry_run: exit 0, prints the templating table, writes nothing.
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
BASE = pathlib.Path(tempfile.gettempdir()) / "mobo_toy_db_b19_tests"
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
KEYS = ["WL_m1_L44", "WL_m1_a50_L44", "WL_m1_L43.5", "WL_m1_a50_L43.5", "WL_m1_a55_L44.75"]
WANT = {"WL_m1_L44": (None, 44.0), "WL_m1_a50_L44": (50.0, 44.0), "WL_m1_L43.5": (None, 43.5), "WL_m1_a50_L43.5": (50.0, 43.5), "WL_m1_a55_L44.75": (55.0, 44.75)}


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
    ids = {}
    for r in DB.build("b15")["rows"]:
        if r["key"] in ("WS_m1_a50", "WS_m1_a55"):
            d = J.QROOT / r["expected_id"]
            d.mkdir()
            (d / "spec.json").write_text(json.dumps({**r["spec"], "created": "x"}, indent=1, default=float))
            (d / "DONE").write_text("")
            ids[r["key"]] = r["expected_id"]
    return root, ids


def problems_of(b, needle):
    return [p for p in b["problems"] if needle in p]


def fake(mod):
    def f(spec):
        return mod(spec, REAL_RECORD(spec))
    return f


try:
    ok("A: b19 in BATCHES, code_hash unchanged", "b19" in DB.BATCHES and J.code_hash() == DB.DB_CODE_HASH)
    L = "WL-1"
    ok("A: layer source bound_scan, selection stratum, slow start, manifest field",
       DB.LAYER_SOURCE[L] == "bound_scan" and DB.LAYER_SELECTION.get(L, "stratum") == "stratum" and L in DB.SLOW_START_LAYERS and L in DB.B2_LAYERS)

    # ---------------------------------------------------------------- B
    _, ctrl_ids = queue("rows")
    src = json.loads((J.QROOT / A / "spec.json").read_text())
    b = DB.build("b19")
    rows = {r["key"]: r for r in b["rows"]}
    ok("B: no problems on a clean queue", not b["problems"], "; ".join(b["problems"])[:500])
    ok("B: the 5 expected keys in order", [r["key"] for r in b["rows"]] == KEYS, [r["key"] for r in b["rows"]])
    one = True
    for k, (alpha, L_) in WANT.items():
        s = rows[k]["spec"]
        diff = {x for x in src["design"] if s["design"].get(x) != src["design"][x]}
        rest = all(s.get(x) == src.get(x) for x in ("h_int", "min_A0", "model", "h_cut", "slip_tol", "delta", "collar_rule", "femur_id", "neck_axis", "margin_check", "ref_cut_mm", "a_bounds_max"))
        want_diff = {"m", "L"} | ({"alpha"} if alpha is not None else set())
        one = one and diff == want_diff and s["design"]["m"] == 1.0 and s["design"]["L"] == L_ and rest and s["entry_offset"] == 0.0 \
            and s["design"]["alpha"] == (src["design"]["alpha"] if alpha is None else alpha)
    ok("B: each row changes only m, L, alpha and entry_offset", one)
    ok("B: friction + bond with reference REF_H2, kind variant, stage db_ws",
       all(r["model_set"] == "fric+bond" and r["spec"]["intact_job"] == REF and r["spec"]["kind"] == "variant" and r["stage"] == "db_ws" for r in rows.values()))
    ok("B: in_E true, unbiased false, source bound_scan, forced offset recorded",
       all(r["in_E"] and not r["unbiased"] and r["source"] == "bound_scan" and r["e_forced"] == 0.0 for r in rows.values()))
    ids = [r["expected_id"] for r in rows.values()]
    ok("B: job ids start with the wl tag and all new", all(j.startswith("db_ws_p13_a105_91e458e3_wl_m1_") for j in ids) and all(r["dedup"] == "new" for r in rows.values()), ids)
    ok("B: not caught by the b15 or b14 globs", not [j for j in ids for g in ("db_ws_p13_a105_91e458e3_m1_a*", "db_ws_p13_a105_91e458e3_m1_*", "db_ws_p13_a105_91e458e3_a50_*", "db_ws_p13_a105_91e458e3_L44_*") if fnmatch.fnmatch(j, g)])
    ok("B: not in any optimisation family", not [k for k, r in rows.items() for p in DB.CHECK_PHASES if SN.Phase(p).in_family(r["spec"])])
    t = b["ws_tpl"]
    ok("B: templating feasible at e 0, A0 within 5 % of the control",
       all(t[k[3:]]["feasible"] and t[k[3:]]["e_star"] == 0.0 for k in KEYS)
       and t["m1_L44"]["A0_star"] >= 0.95 * t["ctrl"]["A0_star"] and t["m1_a50_L44"]["A0_star"] >= 0.95 * t["ctrl_a50"]["A0_star"] and t["m1_a55_L44.75"]["A0_star"] >= 0.95 * t["ctrl_a55"]["A0_star"],
       json.dumps({k: [round(v["A0_star"], 1), round(v["bone_mm3"] / 1000, 2), v["e_star"]] for k, v in t.items()}))
    ok("B: the controls are WS_m1 and the b15 rows", b["ws_control"] == {"": CTRL, "_a50": ctrl_ids["WS_m1_a50"], "_a55": ctrl_ids["WS_m1_a55"]}, b["ws_control"])

    # ---------------------------------------------------------------- C
    _, ctrl_ids = queue("fail")

    def infeasible(spec, r):
        if spec["design"]["L"] == 44.0 and spec["design"]["alpha"] == 50.0:
            r["prep_view"] = {**r["prep_view"], "fit": False, "e": float("nan"), "A0": float("nan"), "bone_total_mm3": float("nan")}
        return r

    def e_jump(spec, r):
        if spec["design"]["L"] == 43.5 and spec["design"]["alpha"] == 50.0:
            r["prep_view"] = {**r["prep_view"], "e": -2.0}
        return r

    def a0_jump(spec, r):
        if spec["design"]["L"] == 44.75:
            r["prep_view"] = {**r["prep_view"], "A0": 400.0}
        return r

    def boom(spec, r):
        if spec["design"]["L"] == 43.5 and spec["design"]["alpha"] != 50.0:
            raise RuntimeError("synthetic templating error")
        return r

    TR.record_spec = fake(infeasible)
    ok("C: an infeasible row is a problem", problems_of(DB.build("b19"), "WL_m1_a50_L44: 0-FE templating is not feasible"))
    TR.record_spec = fake(e_jump)
    ok("C: an entry-offset jump is a problem", problems_of(DB.build("b19"), "WL_m1_a50_L43.5: entry offset"))
    TR.record_spec = fake(a0_jump)
    ok("C: an A0 jump is a problem", problems_of(DB.build("b19"), "WL_m1_a55_L44.75: A0"))
    TR.record_spec = fake(boom)
    ok("C: a templating error is a problem", problems_of(DB.build("b19"), "WL_m1_L43.5: 0-FE templating failed"))
    TR.record_spec = REAL_RECORD
    (J.QROOT / ctrl_ids["WS_m1_a50"] / "DONE").unlink()
    ok("C: a control not DONE is a problem", problems_of(DB.build("b19"), f"the control {ctrl_ids['WS_m1_a50']}"))
    shutil.rmtree(J.QROOT / ctrl_ids["WS_m1_a55"])
    ok("C: a control absent is a problem", problems_of(DB.build("b19"), "is absent"))
    (J.QROOT / A / "DONE").unlink()
    try:
        DB.build("b19")
        ok("C: A not DONE refuses", False)
    except SystemExit as e:
        ok("C: A not DONE refuses", "not DONE" in str(e), str(e)[:90])

    # ---------------------------------------------------------------- D
    queue("dedup")
    r0 = {r["key"]: r for r in DB.build("b19")["rows"]}["WL_m1_L44"]
    other = {**r0["spec"], "stage": "db_fd", "tag": "same_physics", "created": "x", "kind": "variant"}
    d = J.QROOT / "db_fd_same_physics_00000000"
    d.mkdir()
    (d / "spec.json").write_text(json.dumps(other, indent=1, default=float))
    (d / "DONE").write_text("")
    r2 = {r["key"]: r for r in DB.build("b19")["rows"]}["WL_m1_L44"]
    ok("D: the same physics under another job name -> existing", r2["dedup"] == "existing" and r2["id"] == d.name and r2["dedup_via"] == "physics", f"{r2['dedup']} {r2['id']}")
    shutil.rmtree(d)
    r14 = {r["key"]: r for r in DB.build("b14")["rows"]}
    ok("D: the b14 job id did not move", r14["WS_m1"]["expected_id"] == CTRL, r14["WS_m1"]["expected_id"])
    r15 = {r["key"]: r for r in DB.build("b15")["rows"]}
    ok("D: the b15 job ids did not move", r15["WS_m1_a50"]["expected_id"] == "db_ws_p13_a105_91e458e3_m1_a50_baa53da3" and r15["WS_m1_a55"]["expected_id"] == "db_ws_p13_a105_91e458e3_m1_a55_4e7054aa")

    # ---------------------------------------------------------------- E
    root, _ = queue("dry")
    before = sorted(str(x.relative_to(root)) for x in root.rglob("*"))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = DB.dry_run("b19")
    out = buf.getvalue()
    after = sorted(str(x.relative_to(root)) for x in root.rglob("*"))
    ok("E: dry run exits 0", rc == 0, out[-400:] if rc else "")
    ok("E: prints the templating table and 5 jobs", "0-FE templating" in out and "jobs (5):" in out)
    ok("E: writes nothing", before == after, str(set(after) ^ set(before))[:200])
finally:
    TR.record_spec = REAL_RECORD
    J.QROOT, J.RESULTS = REAL_Q, REAL_R
    shutil.rmtree(BASE, ignore_errors=True)

n_fail = sum(not c for _, c in checks)
print(f"{len(checks) - n_fail}/{len(checks)} passed, {n_fail} failed")
sys.exit(1 if n_fail else 0)
