"""Run with the repo venv: PYTHONUTF8=1 .venv-mobo/Scripts/python.exe v2/tests/test_stage_db_b14.py
Local only: a fake queue in the system temp dir (mobo_toy_db_b14_tests); J.QROOT points there. No gmsh, no FE, no Linux, nothing under
~/mobo_toy_v2 is read or written. The specs of A and of the h 2.0 intact reference come read-only from db3406/raw.

v2/stage_db.py v1.8, batch b14 (the m / alpha one-factor scan of candidate A):
A. constants: b14 in BATCHES, db_ws in DB_STAGES, both layers source bound_scan, selection stratum, slow start, code_hash unchanged.
B. rows: 6 rows, each = A's physics with exactly one design key changed and the bond model added; reference REF_H2; templating feasible with
   e* = A's e*; not in any optimisation family; in_E true, unbiased false; job ids db_ws_p13_a105_...; m rows inside the v1 box, alpha rows outside.
C. fail closed: infeasible row, offset jump, templating error, prep.json disagreeing with tpl_record, A not DONE -> problems / SystemExit.
D. dedup: the same physics under another job name -> existing, already queued under the expected id -> queued; neither duplicated.
E. dry_run: exit 0, prints the templating table, writes nothing (queue listing unchanged, no manifest, no log).
F. stage_al.load_training drops in_bounds_v1 false rows before anything else can use them; other rows are not affected.
G. db_export: stage db_ws classifies as bound_scan / stratum and a bound_scan source enters the exclusion set.
"""
import contextlib
import csv
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
V05 = pathlib.Path(r"H:/projects/Femoral implant generation/db3406/v0.5")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "v2"))
sys.path.insert(0, str(ROOT / "tools"))
BASE = pathlib.Path(tempfile.gettempdir()) / "mobo_toy_db_b14_tests"
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
    for j in (A, REF):
        extract(j, J.QROOT)
    return root


def problems_of(b, needle):
    return [p for p in b["problems"] if needle in p]


try:
    # ---------------------------------------------------------------- A
    ok("A: b14 in BATCHES, db_ws in DB_STAGES, code_hash unchanged",
       "b14" in DB.BATCHES and "db_ws" in DB.DB_STAGES and J.code_hash() == DB.DB_CODE_HASH)
    ok("A: both layers source bound_scan, selection stratum, slow start, manifest fields",
       all(DB.LAYER_SOURCE[L] == "bound_scan" and DB.LAYER_SELECTION.get(L, "stratum") == "stratum" and L in DB.SLOW_START_LAYERS and L in DB.B2_LAYERS
           for L in ("WS m", "WS alpha")))

    # ---------------------------------------------------------------- B
    queue("rows")
    src = json.loads((J.QROOT / A / "spec.json").read_text())
    b = DB.build("b14")
    rows = {r["key"]: r for r in b["rows"]}
    ok("B: no problems on a clean queue", not b["problems"], "; ".join(b["problems"])[:400])
    ok("B: the 6 expected keys", set(rows) == {"WS_m0.75", "WS_m1", "WS_m1.5", "WS_a50", "WS_a55", "WS_a60"}, sorted(rows))
    want = {"WS_m0.75": ("m", 0.75), "WS_m1": ("m", 1.0), "WS_m1.5": ("m", 1.5), "WS_a50": ("alpha", 50.0), "WS_a55": ("alpha", 55.0), "WS_a60": ("alpha", 60.0)}
    one = True
    for k, (var, val) in want.items():
        s = rows[k]["spec"]
        diff = {x for x in src["design"] if s["design"].get(x) != src["design"][x]}
        rest = {x: s.get(x) == src.get(x) for x in ("h_int", "min_A0", "model", "h_cut", "slip_tol", "delta", "collar_rule", "femur_id", "neck_axis",
                                                    "margin_check", "ref_cut_mm", "a_bounds_max")}
        one = one and diff == {var} and s["design"][var] == val and all(rest.values()) and set(s["design"]) == set(src["design"])
    ok("B: each row changes exactly one design key, all other physics equal to A", one)
    ok("B: friction + bond with reference REF_H2, kind variant, stage db_ws",
       all(r["model_set"] == "fric+bond" and r["spec"]["intact_job"] == REF and r["spec"]["kind"] == "variant" and r["stage"] == "db_ws"
           and not r["spec"].get("fric_only") and not r["spec"].get("bond_only") for r in rows.values()))
    ok("B: job ids db_ws_p13_a105_91e458e3_<label>_<hash8>, all new",
       all(r["expected_id"].startswith(f"db_ws_p13_a105_91e458e3_{k[3:]}_") and r["dedup"] == "new" for k, r in rows.items()))
    ok("B: in_E true, unbiased false, source bound_scan", all(r["in_E"] and not r["unbiased"] and r["source"] == "bound_scan" for r in rows.values()))
    ok("B: not in any optimisation family", not [k for k, r in rows.items() for p in DB.CHECK_PHASES if SN.Phase(p).in_family(r["spec"])])
    t = b["ws_tpl"]
    ok("B: templating table has A and the 6 rows, all feasible at e* 0", set(t) == {"A", "m0.75", "m1", "m1.5", "a50", "a55", "a60"}
       and all(v["feasible"] and v["e_star"] == 0.0 for v in t.values()), json.dumps({k: round(v["A0_star"], 1) for k, v in t.items()}))
    ok("B: m shrinks the size and the bone removed", t["A"]["A0_star"] > t["m0.75"]["A0_star"] > t["m1"]["A0_star"] > t["m1.5"]["A0_star"]
       and t["A"]["bone_mm3"] > t["m1"]["bone_mm3"] > t["m1.5"]["bone_mm3"])
    ph = SN.Phase(13)
    box = lambda s: all(ph.space[k][0] - 1e-9 <= float(s["design"][k]) <= ph.space[k][1] + 1e-9 for k in ph.vars if k in s["design"])  # noqa: E731
    ok("B: m rows inside the v1 box, alpha rows outside", all(box(rows[k]["spec"]) for k in ("WS_m0.75", "WS_m1", "WS_m1.5"))
       and not any(box(rows[k]["spec"]) for k in ("WS_a50", "WS_a55", "WS_a60")))
    ok("B: the two layers alternate", [r["layer"] for r in b["rows"]] == ["WS m", "WS alpha"] * 3, [r["layer"] for r in b["rows"]])

    # ---------------------------------------------------------------- C
    queue("fail")

    def fake(mod):
        def f(spec):
            r = REAL_RECORD(spec)
            return mod(spec, r)
        return f

    def infeasible(spec, r):
        if spec["design"]["m"] == 1.5:
            r["feasible"], r["reason"] = False, "no_offset"
        return r

    def jump(spec, r):
        if spec["design"]["alpha"] == 60.0:
            r["e_star"] = -2.0
        return r

    def boom(spec, r):
        if spec["design"]["alpha"] == 55.0:
            raise RuntimeError("synthetic templating error")
        return r

    def base_boom(spec, r):
        raise FileNotFoundError("no femur cache")

    TR.record_spec = fake(infeasible)
    ok("C: an infeasible row is a problem", problems_of(DB.build("b14"), "WS_m1.5: 0-FE templating is not feasible"))
    TR.record_spec = fake(jump)
    ok("C: an entry-offset jump is a problem", problems_of(DB.build("b14"), "WS_a60: entry offset"))
    TR.record_spec = fake(boom)
    ok("C: a templating error on a row is a problem", problems_of(DB.build("b14"), "WS_a55: 0-FE templating failed"))
    TR.record_spec = fake(base_boom)
    ok("C: a templating error on the base design is a problem", problems_of(DB.build("b14"), "of the base design"))
    TR.record_spec = REAL_RECORD
    p = J.QROOT / A / "prep.json"
    good = p.read_text()
    d = json.loads(good)
    d["templating"]["A0"] += 5.0
    p.write_text(json.dumps(d))
    ok("C: prep.json disagreeing with tpl_record is a problem", problems_of(DB.build("b14"), "does not reproduce"))
    p.unlink()
    ok("C: A without prep.json is a problem", problems_of(DB.build("b14"), "no templating record"))
    p.write_text(good)
    (J.QROOT / A / "DONE").unlink()
    try:
        DB.build("b14")
        ok("C: A not DONE refuses", False)
    except SystemExit as e:
        ok("C: A not DONE refuses", "not DONE" in str(e), str(e)[:90])

    # ---------------------------------------------------------------- D
    queue("dedup")
    r0 = {r["key"]: r for r in DB.build("b14")["rows"]}["WS_a50"]
    d = J.QROOT / r0["expected_id"]
    d.mkdir()
    (d / "spec.json").write_text(json.dumps({**r0["spec"], "created": "x"}, indent=1, default=float))
    r1 = {r["key"]: r for r in DB.build("b14")["rows"]}["WS_a50"]
    ok("D: the expected id already in the queue -> queued, not resubmitted", r1["dedup"] == "queued" and r1["id"] == r0["expected_id"], r1["dedup"])
    shutil.rmtree(d)
    other = {**r0["spec"], "stage": "db_fd", "tag": "same_physics", "created": "x", "kind": "variant"}
    d = J.QROOT / "db_fd_same_physics_00000000"
    d.mkdir()
    (d / "spec.json").write_text(json.dumps(other, indent=1, default=float))
    (d / "DONE").write_text("")
    r2 = {r["key"]: r for r in DB.build("b14")["rows"]}["WS_a50"]
    ok("D: the same physics under another job name -> existing", r2["dedup"] == "existing" and r2["id"] == d.name and r2["dedup_via"] == "physics",
       f"{r2['dedup']} {r2['id']}")
    shutil.rmtree(d)

    # ---------------------------------------------------------------- E
    root = queue("dry")
    before = sorted(str(x.relative_to(root)) for x in root.rglob("*"))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = DB.dry_run("b14")
    out = buf.getvalue()
    after = sorted(str(x.relative_to(root)) for x in root.rglob("*"))
    ok("E: dry run exits 0", rc == 0, out[-300:] if rc else "")
    ok("E: prints the templating table and 6 jobs", "0-FE templating" in out and "jobs (6):" in out and '"ws_tpl"' in out)
    ok("E: writes nothing", before == after, str(set(after) ^ set(before))[:200])

    # ---------------------------------------------------------------- F
    import stage_al as AL
    d = BASE / "al"
    d.mkdir()
    rows_csv = list(csv.DictReader(open(V05 / "scalars.csv", newline="", encoding="utf-8")))
    fields = list(rows_csv[0])
    k = next(i for i, r in enumerate(rows_csv) if r["status"] == "DONE" and r["has_fric_model"] == "true" and r["kind"] == "variant"
             and r["selection"] != "corner_test" and float(r["h_int_mm"] or 0) == 2.0 and not r["cfg_override"])

    def run(flip):
        with open(d / "scalars.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            for i, r in enumerate(rows_csv):
                w.writerow({**r, "in_bounds_v1": "false"} if flip and i == k else r)
        return AL.load_training(d, {})[1]["dropped"]

    d0, d1 = run(False), run(True)
    ok("F: v0.5 has no out-of-box row, so nothing changes for it", "outside the v1 box" not in d0, json.dumps(d0))
    ok("F: an in_bounds_v1 false row is dropped from the training rows", d1.get("outside the v1 box") == 1, json.dumps(d1))

    # ---------------------------------------------------------------- G
    import db_export as X
    c = X.classify("db_ws_p13_a105_91e458e3_a50_00000000", {"stage": "db_ws", "kind": "variant"}, None)
    ok("G: db_export classifies db_ws as bound_scan / stratum", c["source"] == "bound_scan" and c["selection"] == "stratum", json.dumps(c)[:120])
    ok("G: bound_scan is in the exclusion set, db_ws_ in the E prefixes", "bound_scan" in X.E_SOURCES and "db_ws_" in X.E_JOB_PREFIXES)
    ok("G: alpha 60 is inside the exporter's column range", True if not hasattr(X, "_phys_rng") else X._phys_rng["alpha"][1] >= 60)
finally:
    TR.record_spec = REAL_RECORD
    J.QROOT, J.RESULTS = REAL_Q, REAL_R

n_fail = sum(not c for _, c in checks)
print(f"\n{len(checks) - n_fail} / {len(checks)} passed, {n_fail} failed, {time.perf_counter() - T_START:.0f} s")
sys.exit(1 if n_fail else 0)
