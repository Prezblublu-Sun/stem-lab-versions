"""Run with the repo venv: PYTHONUTF8=1 .venv-mobo/Scripts/python.exe v2/tests/test_stage_db_b9p.py
Local only: a fake queue in the system temp dir (mobo_toy_db_b9p_tests); J.QROOT points there. No gmsh, no FE, no Linux, nothing under
~/mobo_toy_v2 is read or written. Source specs come read-only from db3406/raw; the b7m rows and WL_m1_L44 are written into the fake queue as DONE.

v2/stage_db.py v1.14, batches b9p (CD-2'') and b11p (OW-2):
A. constants: both batches in BATCHES, layer sources, slow start, code_hash unchanged.
B. b9p: 34 rows, 13 designs x 2 conditions + 8 joint rows; each row differs from its source only by delta and / or cfg.load; friction only.
C. b11p: 12 rows; only m and entry_offset change; templating feasible at the fixed offset; in_E true, unbiased false; job ids not caught by the b14, b15 or b19 globs.
D. fail closed: a baseline not DONE, an infeasible row, an offset jump, a templating error, a source not DONE.
E. dedup: the same physics under another job name -> existing, so existing condition rows are not computed again.
F. dry_run: exit 0, writes nothing, for both batches. Earlier job ids did not move.
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
BASE = pathlib.Path(tempfile.gettempdir()) / "mobo_toy_db_b9p_tests"
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
TAG = "p13_a105_91e458e3"


def ok(name, cond, extra=""):
    checks.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + f"(t={time.perf_counter() - T_START:.0f}s) " + name + (f"  [{extra}]" if extra else ""), flush=True)


def raw_job(prefix):
    hits = sorted(RAW.glob(prefix + "_*.tar.xz"))
    assert len(hits) == 1, (prefix, hits)
    return hits[0].name[:-len(".tar.xz")]


WS = {k: raw_job(f"db_ws_{TAG}_{k}") for k in ("m0.75", "m1")}
JOBS = {*DB.CODES.values(), DB.CY_EXTRA["a82"], DB.CY_EXTRA["a96"], DB.CY_EXTRA["a100"], DB.CY_EXTRA["a95"], DB.CY_EXTRA["al1_07"], REF, *WS.values(),
        *(v for k, v in DB.CD2_EXTRA.items() if not k.startswith("al3m"))}


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
    al = json.loads((J.QROOT / DB.CY_EXTRA["al1_07"] / "spec.json").read_text())
    for i, (k, v) in enumerate(DB.CD2_EXTRA.items()):
        if k.startswith("al3m"):
            d = J.QROOT / v
            d.mkdir()
            (d / "spec.json").write_text(json.dumps({**al, "tag": k, "design": {**al["design"], "L": al["design"]["L"] + 0.1 * (i + 1)}}, indent=1, default=float))
            (d / "DONE").write_text("")
    p_ = DB._phys(json.loads((J.QROOT / A / "spec.json").read_text()), A)
    p_["design"] = {**p_["design"], "m": 1.0, "L": 44.0}
    p_["entry_offset"] = 0.0
    wl = DB._variant(p_, "db_ws", f"{TAG}_wl_m1_L44", "full", intact_job=REF)
    d = J.QROOT / DB.expected_id(wl)
    d.mkdir()
    (d / "spec.json").write_text(json.dumps({**wl, "created": "x"}, indent=1, default=float))
    (d / "DONE").write_text("")
    return root, d.name


def spec_of(j):
    return json.loads((J.QROOT / j / "spec.json").read_text())


def fake(mod):
    def f(spec):
        return mod(spec, REAL_RECORD(spec))
    return f


def problems_of(b, needle):
    return [p for p in b["problems"] if needle in p]


try:
    ok("A: b9p, b11p in BATCHES, code_hash unchanged", "b9p" in DB.BATCHES and "b11p" in DB.BATCHES and J.code_hash() == DB.DB_CODE_HASH)
    ok("A: layers", DB.LAYER_SOURCE["CD-2"] == "cond_anchor" and DB.LAYER_SOURCE["OW-2"] == "bound_scan" and "CD-2" in DB.SLOW_START_LAYERS and "OW-2" in DB.SLOW_START_LAYERS and "OW-2" in DB.B2_LAYERS)

    # ---------------------------------------------------------------- B
    _, wl_id = queue("b9p")
    b = DB.build("b9p")
    rows = {r["key"]: r for r in b["rows"]}
    ok("B: no problems on a clean queue", not b["problems"], "; ".join(b["problems"])[:500])
    ok("B: 34 rows", len(rows) == 34 and len(DB.CD2_SINGLE) == 13 and len(DB.CD2_JOINT) == 8, len(rows))
    ok("B: the first 2 rows are Am1 at delta 0.05 and at 3839 N", list(rows)[:2] == ["CD2_d0.05_Am1", "CD2_F3839_Am1"], list(rows)[:2])
    F3839 = DB.STS_LOADS["F3839"]
    fine = True
    for k, r in rows.items():
        s = r["spec"]
        cond = k.split("_")[1]
        want_d = cond in ("d0.05", "both")
        want_l = cond in ("F3839", "both")
        fine = fine and s["fric_only"] and "intact_job" not in s and s["stage"] == "db_cd" and r["model_set"] == "fric" and r["source"] == "cond_anchor"
        fine = fine and ((s["delta"] == 0.05) == want_d) and ((s.get("cfg", {}).get("load") == F3839) == want_l) and (want_l or "cfg" not in s)
    ok("B: friction only; delta 0.05 and load 3839 N exactly where intended", fine)
    a_src = spec_of(A)
    s = rows["CD2_both_A"]["spec"]
    ok("B: the joint row of A has the design of A", s["design"] == a_src["design"] and s["h_int"] == a_src["h_int"])
    s = rows["CD2_d0.05_AL44"]["spec"]
    ok("B: AL44 = WL_m1_L44: m 1.0, L 44, entry offset 0", s["design"]["m"] == 1.0 and s["design"]["L"] == 44.0 and s["entry_offset"] == 0.0, rows["CD2_d0.05_AL44"]["expected_id"])
    s = rows["CD2_F3839_c4055"]["spec"]
    c4 = spec_of(DB.CD2_EXTRA["c4055"])
    ok("B: c4055 keeps its own design", s["design"] == c4["design"])
    ok("B: not in any optimisation family, condition ids differ", not [k for k, r in rows.items() for p in DB.CHECK_PHASES if SN.Phase(p).in_family(r["spec"])]
       and rows["CD2_both_A"]["condition_id"] != rows["CD2_both_Am1"]["expected_id"])

    # ---------------------------------------------------------------- C
    b = DB.build("b11p")
    rows = {r["key"]: r for r in b["rows"]}
    ok("C: no problems on a clean queue", not b["problems"], "; ".join(b["problems"])[:500])
    ok("C: 12 rows", len(rows) == 12, len(rows))
    one = True
    for (code, e), (k, r) in zip(DB.OW2_ROWS, rows.items()):
        src = spec_of({**DB.CODES, **DB.CY_EXTRA}[code])
        s = r["spec"]
        diff = {x for x in src["design"] if s["design"].get(x) != src["design"][x]}
        one = one and diff == {"m"} and s["design"]["m"] == 1.0 and s["entry_offset"] == e and s["intact_job"] == REF and r["model_set"] == "fric+bond" and r["in_E"] and not r["unbiased"]
        t = b["ws_tpl"][k[4:]]
        one = one and t["feasible"] and t["e_star"] == e
    ok("C: only m and entry_offset change; feasible at the fixed offset; in_E true, unbiased false", one, json.dumps({k: [round(v["A0_star"], 1), round(v["bone_mm3"] / 1000, 2)] for k, v in b["ws_tpl"].items()})[:400])
    ids = [r["expected_id"] for r in rows.values()]
    ok("C: job ids carry the ow tag and are not caught by the earlier globs",
       all("_ow_m1_e" in j for j in ids) and not [j for j in ids for g in ("db_ws_p13_a105_91e458e3_m1_a*", "db_ws_p13_a105_91e458e3_m1_*", "db_ws_p13_a105_91e458e3_wl_*") if fnmatch.fnmatch(j, g)], ids[:2])
    ok("C: all new, the control is WS_m1", all(r["dedup"] == "new" for r in rows.values()) and b["ws_control"] == CTRL)

    # ---------------------------------------------------------------- D
    _, wl_id = queue("fail")

    def infeasible(spec, r):
        if spec["entry_offset"] == 2.0 and spec["tag"].startswith("p13_a100"):
            r["prep_view"] = {**r["prep_view"], "fit": False, "e": float("nan"), "A0": float("nan"), "bone_total_mm3": float("nan")}
        return r

    def jump(spec, r):
        if spec["entry_offset"] == -2.0 and spec["tag"].startswith("p13_a95"):
            r["prep_view"] = {**r["prep_view"], "e": 0.0}
        return r

    def boom(spec, r):
        if spec["tag"].startswith("p13_a82"):
            raise RuntimeError("synthetic templating error")
        return r

    TR.record_spec = fake(infeasible)
    ok("D: an infeasible row is a problem", problems_of(DB.build("b11p"), "OW2_a100_m1_e+2: 0-FE templating is not feasible"))
    TR.record_spec = fake(jump)
    ok("D: an offset jump is a problem", problems_of(DB.build("b11p"), "OW2_a95_m1_e-2: entry offset"))
    TR.record_spec = fake(boom)
    ok("D: a templating error is a problem", problems_of(DB.build("b11p"), "OW2_a82_m1_e+0: 0-FE templating failed"))
    TR.record_spec = REAL_RECORD
    (J.QROOT / wl_id / "DONE").unlink()
    ok("D: b9p with WL_m1_L44 not DONE is a problem", problems_of(DB.build("b9p"), "AL44: its baseline"))
    (J.QROOT / CTRL / "DONE").unlink()
    ok("D: b11p with WS_m1 not DONE is a problem", problems_of(DB.build("b11p"), "the control WS_m1"))
    (J.QROOT / DB.CD2_EXTRA["al3m_11"] / "DONE").unlink()
    try:
        DB.build("b9p")
        ok("D: a source not DONE refuses", False)
    except SystemExit as e:
        ok("D: a source not DONE refuses", "not DONE" in str(e), str(e)[:90])

    # ---------------------------------------------------------------- E
    queue("dedup")
    r0 = {r["key"]: r for r in DB.build("b9p")["rows"]}["CD2_F3839_al1_07"]
    other = {**r0["spec"], "stage": "db_al", "tag": "al1_07_F3839", "created": "x", "kind": "variant"}
    d = J.QROOT / "db_al_al1_07_F3839_00000000"
    d.mkdir()
    (d / "spec.json").write_text(json.dumps(other, indent=1, default=float))
    (d / "DONE").write_text("")
    r2 = {r["key"]: r for r in DB.build("b9p")["rows"]}["CD2_F3839_al1_07"]
    ok("E: an existing condition row is adopted, not computed again", r2["dedup"] == "existing" and r2["id"] == d.name and r2["dedup_via"] == "physics", f"{r2['dedup']} {r2['id']}")
    shutil.rmtree(d)

    # ---------------------------------------------------------------- F
    for batch, n in (("b9p", 34), ("b11p", 12)):
        root, _ = queue("dry" + batch)
        before = sorted(str(x.relative_to(root)) for x in root.rglob("*"))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = DB.dry_run(batch)
        out = buf.getvalue()
        ok(f"F: {batch} dry run exits 0, lists {n} jobs, writes nothing", rc == 0 and f"jobs ({n}):" in out and before == sorted(str(x.relative_to(root)) for x in root.rglob("*")), out[-300:] if rc else "")
    r14 = {r["key"]: r for r in DB.build("b14")["rows"]}
    ok("F: the b14 job id did not move", r14["WS_m1"]["expected_id"] == CTRL)
finally:
    TR.record_spec = REAL_RECORD
    J.QROOT, J.RESULTS = REAL_Q, REAL_R
    shutil.rmtree(BASE, ignore_errors=True)

n_fail = sum(not c for _, c in checks)
print(f"{len(checks) - n_fail}/{len(checks)} passed, {n_fail} failed")
sys.exit(1 if n_fail else 0)
