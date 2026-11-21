"""Run with the repo venv: PYTHONUTF8=1 .venv-mobo/Scripts/python.exe v2/tests/test_stage_db_b20.py
Local only: a fake queue in the system temp dir (mobo_toy_db_b20_tests); J.QROOT points there. No gmsh, no FE, no Linux, nothing under
~/mobo_toy_v2 is read or written. The specs of A, of the h 2.0 intact reference and of the control WS_m1.5 come read-only from db3406/raw.

v2/stage_db.py v1.14, batch b20 (AL-4m part A, the shape of A at m 1.6 / 1.75 / 2.0) and batch b21 (AL-4m part B, the frozen al4m picks):
A. constants: b20 and b21 in BATCHES, layers have the right source and selection, slow start, code_hash unchanged.
B. rows: 3 rows, each = the physics of A with only m changed and the bond model added; reference REF_H2; templating as sized in the proposal;
   in the v1 box; in_E true, unbiased false; job ids db_ws_p13_a105_91e458e3_m<m>_<hash8>; the control is the b14 job WS_m1.5.
C. fail closed: infeasible row, unplanned offset jump at m 1.75, m 2.0 without its written offset, templating error, control absent, control not DONE, A not DONE.
D. dedup: the same physics under another job name -> existing; b14, b15 and b19 ids unchanged.
E. dry_run: exit 0, prints the templating table, writes nothing.
F. b21 refuses without the frozen picks file.
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
BASE = pathlib.Path(tempfile.gettempdir()) / "mobo_toy_db_b20_tests"
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
CTRL = "db_ws_p13_a105_91e458e3_m1.5_96e9b62a"
M1 = "db_ws_p13_a105_91e458e3_m1_2a79b613"
KEYS = ["WS_m1.6", "WS_m1.75", "WS_m2"]


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
    for j in (A, REF, CTRL, M1):
        extract(j, J.QROOT)
    return root


def problems_of(b, needle):
    return [p for p in b["problems"] if needle in p]


def fake(mod):
    def f(spec):
        return mod(spec, REAL_RECORD(spec))
    return f


try:
    ok("A: b20 and b21 in BATCHES, code_hash unchanged", {"b20", "b21"} <= set(DB.BATCHES) and J.code_hash() == DB.DB_CODE_HASH)
    ok("A: WS m2 has source bound_scan, selection stratum, slow start, manifest field",
       DB.LAYER_SOURCE["WS m2"] == "bound_scan" and DB.LAYER_SELECTION.get("WS m2", "stratum") == "stratum" and "WS m2" in DB.SLOW_START_LAYERS and "WS m2" in DB.B2_LAYERS)
    ok("A: AL-4m layers as AL-3m", DB.AL_BATCHES["b21"] == ("al4m", "AL-4m", "AL4M") and DB.LAYER_SOURCE["AL-4m"] == "al_adaptive" and DB.LAYER_SOURCE["AL-4m rand"] == "al_random"
       and DB.LAYER_SELECTION["AL-4m"] == "adaptive" and DB.LAYER_SELECTION["AL-4m rand"] == "iid" and all(L in DB.SLOW_START_LAYERS and L in DB.B2_LAYERS for L in ("AL-4m", "AL-4m sts", "AL-4m rand")))

    queue("rows")
    src = json.loads((J.QROOT / A / "spec.json").read_text())
    b = DB.build("b20")
    rows = {r["key"]: r for r in b["rows"]}
    ok("B: no problems on a clean queue", not b["problems"], "; ".join(b["problems"])[:500])
    ok("B: the 3 expected keys in m order", [r["key"] for r in b["rows"]] == KEYS, [r["key"] for r in b["rows"]])
    one = True
    for k, m in zip(KEYS, (1.6, 1.75, 2.0)):
        s = rows[k]["spec"]
        diff = {x for x in src["design"] if s["design"].get(x) != src["design"][x]}
        rest = all(s.get(x) == src.get(x) for x in ("h_int", "min_A0", "model", "h_cut", "slip_tol", "delta", "collar_rule", "femur_id", "neck_axis", "margin_check", "ref_cut_mm", "a_bounds_max"))
        one = one and diff == {"m"} and s["design"]["m"] == m and rest and set(s["design"]) == set(src["design"]) and "entry_offset" not in s
    ok("B: each row changes only m, the offset is not forced", one)
    ok("B: friction + bond with reference REF_H2, kind variant, stage db_ws",
       all(r["model_set"] == "fric+bond" and r["spec"]["intact_job"] == REF and r["spec"]["kind"] == "variant" and r["stage"] == "db_ws"
           and not r["spec"].get("fric_only") and not r["spec"].get("bond_only") for r in rows.values()))
    ids = [r["expected_id"] for r in rows.values()]
    ok("B: job ids and all new", all(rows[k]["expected_id"].startswith(f"db_ws_p13_a105_91e458e3_{k[3:]}_") for k in KEYS) and all(r["dedup"] == "new" for r in rows.values()), ids)
    ok("B: in_E true, unbiased false, source bound_scan, no forced offset", all(r["in_E"] and not r["unbiased"] and r["source"] == "bound_scan" and r["e_forced"] is None for r in rows.values()))
    t = b["ws_tpl"]
    want = {"m1.6": (0.0, 403.7, 7.19), "m1.75": (0.0, 388.5, 6.92), "m2": (-2.0, 374.6, 6.67)}
    ok("B: templating as sized in the proposal", all(t[k]["feasible"] and t[k]["e_star"] == e and abs(t[k]["A0_star"] - a0) < 0.1 and abs(t[k]["bone_mm3"] / 1000 - v) < 0.005 for k, (e, a0, v) in want.items()),
       json.dumps({k: [round(v["A0_star"], 1), round(v["bone_mm3"] / 1000, 2), v["e_star"]] for k, v in t.items()}))
    ph = SN.Phase(13)
    box = lambda s: all(ph.space[k][0] - 1e-9 <= float(s["design"][k]) <= ph.space[k][1] + 1e-9 for k in ph.vars if k in s["design"])  # noqa: E731
    ok("B: all 3 rows inside the v1 box", all(box(r["spec"]) for r in rows.values()))
    ok("B: the control is the b14 job WS_m1.5", b.get("ws_control") == CTRL, b.get("ws_control"))
    ok("B: not in any optimisation family", not [k for k, r in rows.items() for p in DB.CHECK_PHASES if SN.Phase(p).in_family(r["spec"])])
    ok("B: not caught by the b15 or b19 globs", not [j for j in ids for g in ("db_ws_p13_a105_91e458e3_m1_a*", "db_ws_p13_a105_91e458e3_wl_*", "db_ws_p13_a105_91e458e3_m1_*") if fnmatch.fnmatch(j, g)])

    queue("fail")

    def infeasible(spec, r):
        if spec["design"]["m"] == 1.6:
            r["feasible"], r["reason"] = False, "no_offset"
        return r

    def jump(spec, r):
        if spec["design"]["m"] == 1.75:
            r["e_star"] = -2.0
        return r

    def no_jump(spec, r):
        if spec["design"]["m"] == 2.0:
            r["e_star"] = 0.0
        return r

    def boom(spec, r):
        if spec["design"]["m"] == 2.0:
            raise RuntimeError("synthetic templating error")
        return r

    def base_boom(spec, r):
        raise FileNotFoundError("no femur cache")

    TR.record_spec = fake(infeasible)
    ok("C: an infeasible row is a problem", problems_of(DB.build("b20"), "WS_m1.6: 0-FE templating is not feasible"))
    TR.record_spec = fake(jump)
    ok("C: an unplanned offset jump at m 1.75 is a problem", problems_of(DB.build("b20"), "WS_m1.75: entry offset"))
    TR.record_spec = fake(no_jump)
    ok("C: m 2.0 without its written offset is a problem", problems_of(DB.build("b20"), "WS_m2: entry offset"))
    TR.record_spec = fake(boom)
    ok("C: a templating error on a row is a problem", problems_of(DB.build("b20"), "WS_m2: 0-FE templating failed"))
    TR.record_spec = fake(base_boom)
    ok("C: a templating error on the base design is a problem", problems_of(DB.build("b20"), "of the base design"))
    TR.record_spec = REAL_RECORD
    (J.QROOT / CTRL / "DONE").unlink()
    ok("C: control not DONE is a problem", problems_of(DB.build("b20"), "the control WS_m1.5"))
    shutil.rmtree(J.QROOT / CTRL)
    ok("C: control absent is a problem", problems_of(DB.build("b20"), "is absent"))
    (J.QROOT / A / "DONE").unlink()
    try:
        DB.build("b20")
        ok("C: A not DONE refuses", False)
    except SystemExit as e:
        ok("C: A not DONE refuses", "not DONE" in str(e), str(e)[:90])

    queue("dedup")
    r0 = {r["key"]: r for r in DB.build("b20")["rows"]}["WS_m1.75"]
    other = {**r0["spec"], "stage": "db_fd", "tag": "same_physics", "created": "x", "kind": "variant"}
    d = J.QROOT / "db_fd_same_physics_00000000"
    d.mkdir()
    (d / "spec.json").write_text(json.dumps(other, indent=1, default=float))
    (d / "DONE").write_text("")
    r2 = {r["key"]: r for r in DB.build("b20")["rows"]}["WS_m1.75"]
    ok("D: the same physics under another job name -> existing", r2["dedup"] == "existing" and r2["id"] == d.name and r2["dedup_via"] == "physics", f"{r2['dedup']} {r2['id']}")
    shutil.rmtree(d)
    r14 = {r["key"]: r for r in DB.build("b14")["rows"]}
    ok("D: the b14 ids did not move", r14["WS_m1"]["expected_id"] == M1 and r14["WS_m1.5"]["expected_id"] == CTRL, r14["WS_m1.5"]["expected_id"])
    r15 = {r["key"]: r for r in DB.build("b15")["rows"]}
    ok("D: the b15 ids did not move", r15["WS_m1_a50"]["expected_id"] == "db_ws_p13_a105_91e458e3_m1_a50_baa53da3")
    r19 = {r["key"]: r for r in DB.build("b19")["rows"]}
    ok("D: the b19 ids did not move", r19["WL_m1_L44"]["expected_id"] == "db_ws_p13_a105_91e458e3_wl_m1_L44_08f4c01a", r19["WL_m1_L44"]["expected_id"])

    root = queue("dry")
    before = sorted(str(x.relative_to(root)) for x in root.rglob("*"))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = DB.dry_run("b20")
    out = buf.getvalue()
    after = sorted(str(x.relative_to(root)) for x in root.rglob("*"))
    ok("E: dry run exits 0", rc == 0, out[-400:] if rc else "")
    ok("E: prints the templating table and 3 jobs", "0-FE templating" in out and "jobs (3):" in out)
    ok("E: writes nothing", before == after, str(set(after) ^ set(before))[:200])

    try:
        DB.build("b21")
        ok("F: b21 refuses without db_al_al4m.json", False)
    except SystemExit as e:
        ok("F: b21 refuses without db_al_al4m.json", "db_al_al4m.json" in str(e), str(e)[:120])
finally:
    TR.record_spec = REAL_RECORD
    J.QROOT, J.RESULTS = REAL_Q, REAL_R
    shutil.rmtree(BASE, ignore_errors=True)

n_fail = sum(not c for _, c in checks)
print(f"{len(checks) - n_fail}/{len(checks)} passed, {n_fail} failed")
sys.exit(1 if n_fail else 0)
