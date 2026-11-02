"""Run with the repo venv: PYTHONUTF8=1 .venv-mobo/Scripts/python.exe v2/tests/test_stage_db_b8_b12.py
Local only: a fake queue in the system temp dir (mobo_toy_db_b8_tests); J.QROOT points there. No gmsh, no FE, no Linux, nothing under
~/mobo_toy_v2 is read or written. The source specs and the b1 manifest come read-only from db3406/raw.

v2/stage_db.py v1.9, batches b8 and b12 (second-week plan, second version):
A. constants and layers; code_hash unchanged; no m below 0.5 anywhere in b8; A x alpha 50 is not repeated (it is b14's WS_a50).
B. b8: NZ-3 = 4 designs x h 1.94 / 2.06 with the b1 mesh references; W-0 alpha rows change only alpha; W-0 L rows change only L and fix the entry offset.
C. b8 fail closed: a missing or unfinished reference, an offset jump on an alpha row, a templating error; an infeasible L row is dropped with a warning.
D. b12: friction only, cycles 4 first then 10, only the cycles key differs (Am1 also has m 1.0); condition ids carry the cycle count; job ids are new.
E. dry runs exit 0 and write nothing.
F. stage_al.load_training drops cycles != 2 rows; v0.5 is not affected.
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
BASE = pathlib.Path(tempfile.gettempdir()) / "mobo_toy_db_b8_tests"
shutil.rmtree(BASE, ignore_errors=True)
BASE.mkdir(parents=True)

import jobs as J  # noqa: E402
import stage_db as DB  # noqa: E402
import tpl_record as TR  # noqa: E402

T_START = time.perf_counter()
REAL_Q, REAL_R = J.QROOT, J.RESULTS
REAL_RECORD = TR.record_spec
checks = []


def ok(name, cond, extra=""):
    checks.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + f"(t={time.perf_counter() - T_START:.0f}s) " + name + (f"  [{extra}]" if extra else ""), flush=True)


snap = sorted(p for p in (RAW / "results").iterdir() if p.is_dir())[-1]
b1 = json.loads((snap / "db_manifest_b1.json").read_text(encoding="utf-8"))
REFS = {k: b1["rows"][k]["id"] for k in ("REF_h1.94", "REF_h2.06")}
JOBS = sorted({*DB.NZ3_JOBS, DB.CODES["A"], DB.CODES["a62"], DB.CODES["init29"], DB.CODES["C"], DB.REF_H2, *DB.CY_EXTRA.values(), *REFS.values()})
CACHE = BASE / "_src"
CACHE.mkdir()
for j in JOBS:
    d = CACHE / j
    d.mkdir()
    with tarfile.open(RAW / f"{j}.tar.xz", "r:xz") as tf:
        for member in ("spec.json", "prep.json", "DONE"):
            try:
                (d / member).write_bytes(tf.extractfile(f"{j}/{member}").read())
            except KeyError:
                pass
print(f"sources extracted: {len(JOBS)} jobs, {time.perf_counter() - T_START:.0f} s", flush=True)


def queue(name):
    root = BASE / name
    J.QROOT, J.RESULTS = root / "queue", root / "results"
    assert not str(J.QROOT).startswith(str(pathlib.Path.home() / "mobo_toy_v2"))
    J.RESULTS.mkdir(parents=True)
    shutil.copytree(CACHE, J.QROOT)
    shutil.copy2(snap / "db_manifest_b1.json", J.RESULTS / "db_manifest_b1.json")
    return root


try:
    # ---------------------------------------------------------------- A
    ok("A: b8 and b12 in BATCHES, code_hash unchanged", {"b8", "b12"} <= set(DB.BATCHES) and J.code_hash() == DB.DB_CODE_HASH)
    ok("A: layers and sources", DB.LAYER_SOURCE["NZ-3"] == "noise" and DB.LAYER_SOURCE["W-0 alpha"] == DB.LAYER_SOURCE["W-0 L"] == "bound_scan"
       and DB.LAYER_SOURCE["CY-1"] == "cycle_variant" and all(L in DB.SLOW_START_LAYERS for L in ("NZ-3", "W-0 alpha", "W-0 L", "CY-1")))

    # ---------------------------------------------------------------- B
    queue("b8")
    src = {j: json.loads((J.QROOT / j / "spec.json").read_text()) for j in JOBS}
    b = DB.build("b8")
    rows = {r["key"]: r for r in b["rows"]}
    ok("B: no problems on a clean queue", not b["problems"], "; ".join(b["problems"])[:500])
    nz = [r for r in b["rows"] if r["layer"] == "NZ-3"]
    ok("B: NZ-3 = 4 designs x 2 meshes, bonded, stage db_nz, the b1 reference of the same mesh",
       len(nz) == 8 and all(r["stage"] == "db_nz" and r["model_set"] == "fric+bond" and r["spec"]["intact_job"] == REFS[f"REF_h{r['spec']['h_int']:g}"] for r in nz))
    ok("B: NZ-3 rows change only h_int", all(r["spec"]["design"] == src[r["source_job"]]["design"] and r["spec"]["h_cut"] == src[r["source_job"]]["h_cut"] for r in nz))
    al = [r for r in b["rows"] if r["layer"] == "W-0 alpha"]
    ok("B: W-0 alpha = A x 47, a62 x 47 / 50; A x 50 not repeated",
       sorted(k for k in rows if rows[k]["layer"] == "W-0 alpha") == ["W0_A_a47", "W0_a62_a47", "W0_a62_a50"] and "W0_A_a50" not in rows)
    ok("B: W-0 alpha rows change only alpha, entry offset free",
       all({x for x in src[r["source_job"]]["design"] if r["spec"]["design"][x] != src[r["source_job"]]["design"][x]} == {"alpha"} and "entry_offset" not in r["spec"] for r in al))
    ll = [r for r in b["rows"] if r["layer"] == "W-0 L"]
    ok("B: W-0 L rows change only L and fix the entry offset to the base e*",
       ll and all({x for x in src[r["source_job"]]["design"] if r["spec"]["design"][x] != src[r["source_job"]]["design"][x]} == {"L"} and r["spec"]["entry_offset"] == r["e_forced"] for r in ll),
       [(r["key"], round(b["ws_tpl"][r["key"][3:]]["A0_star"], 1)) for r in ll])
    ok("B: the dropped m rows are gone: every m stays at or above the box minimum", all(r["spec"]["design"]["m"] >= 0.5 for r in b["rows"]))
    ok("B: all new, in_E on the scan rows", all(r["dedup"] == "new" for r in b["rows"]) and all(r["in_E"] and not r["unbiased"] for r in al + ll))

    # ---------------------------------------------------------------- C
    queue("b8fail")
    J_ref = REFS["REF_h1.94"]
    (J.QROOT / J_ref / "DONE").unlink()
    ok("C: an unfinished mesh reference is a problem", [p for p in DB.build("b8")["problems"] if "REF_h1.94" in p and "must be DONE" in p])
    (J.QROOT / J_ref / "DONE").write_text("")

    def fake(mod):
        def f(spec):
            return mod(spec, REAL_RECORD(spec))
        return f

    def jump(spec, r):
        if spec["design"]["alpha"] == 50.0:
            r["e_star"] = -2.0
        return r

    def boom(spec, r):
        if spec["design"]["alpha"] == 47.0:
            raise RuntimeError("synthetic")
        return r

    def l_bad(spec, r):
        if spec["design"]["L"] == 44.5:
            r["prep_view"] = {**r["prep_view"], "fit": False, "e": float("nan"), "A0": float("nan"), "bone_total_mm3": float("nan")}
        return r

    TR.record_spec = fake(jump)
    ok("C: an offset jump on an alpha row is a problem", [p for p in DB.build("b8")["problems"] if "W0_a62_a50: entry offset" in p])
    TR.record_spec = fake(boom)
    ok("C: a templating error on an alpha row is a problem", [p for p in DB.build("b8")["problems"] if "W0_A_a47: 0-FE templating failed" in p])
    TR.record_spec = fake(l_bad)
    b_ = DB.build("b8")
    ok("C: an infeasible L row is dropped with a warning, no problem",
       not [r for r in b_["rows"] if r["spec"]["design"]["L"] == 44.5] and [w for w in b_["warnings"] if "L44.5: not feasible" in w] and not b_["problems"], b_["problems"][:2])
    TR.record_spec = REAL_RECORD

    # ---------------------------------------------------------------- D
    queue("b12")
    b = DB.build("b12")
    rows = {r["key"]: r for r in b["rows"]}
    ok("D: no problems on a clean queue", not b["problems"], "; ".join(b["problems"])[:500])
    ok("D: 7 rows x 4 cycles first, then 4 rows x 10 cycles", [r["spec"]["cycles"] for r in b["rows"]] == [4] * 7 + [10] * 4)
    ok("D: friction only, stage db_cd, source cycle_variant, no reference",
       all(r["model_set"] == "fric" and r["stage"] == "db_cd" and r["source"] == "cycle_variant" and "intact_job" not in r["spec"] for r in b["rows"]))
    same = True
    for k, r in rows.items():
        want = dict(src[r["source_job"]]["design"])
        if k.endswith("Am1"):
            want["m"] = 1.0
        same = same and r["spec"]["design"] == want
    ok("D: designs equal the sources (Am1 = A with m 1.0)", same)
    ok("D: the smoke rows come first: A and Am1 at 4 cycles", [r["key"] for r in b["rows"][:2]] == ["CY_c4_A", "CY_c4_Am1"])
    ok("D: condition ids carry the cycle count; other batches' ids unchanged", all(r["condition_id"].endswith(f"|c{r['spec']['cycles']}") for r in b["rows"])
       and DB.cond_id({"kind": "variant", "delta": 0.1, "h_int": 2.0, "slip_tol": 0.00025}) == "d0.1|stair|h2|slip0.00025")
    ok("D: all new", all(r["dedup"] == "new" for r in b["rows"]))

    # ---------------------------------------------------------------- E
    for batch, name in (("b8", "dry8"), ("b12", "dry12")):
        root = queue(name)
        before = sorted(str(x.relative_to(root)) for x in root.rglob("*"))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = DB.dry_run(batch)
        ok(f"E: {batch} dry run exits 0 and writes nothing", rc == 0 and before == sorted(str(x.relative_to(root)) for x in root.rglob("*")), buf.getvalue()[-300:] if rc else "")

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
                w.writerow({**r, "cycles": "10"} if flip and i == k else r)
        return AL.load_training(d, {})[1]["dropped"]

    d0, d1 = run(False), run(True)
    ok("F: v0.5 has no cycles != 2 row", "cycles != 2" not in d0, json.dumps(d0))
    ok("F: a cycles 10 row is dropped from the training rows", d1.get("cycles != 2") == 1, json.dumps(d1))
finally:
    TR.record_spec = REAL_RECORD
    J.QROOT, J.RESULTS = REAL_Q, REAL_R

n_fail = sum(not c for _, c in checks)
print(f"\n{len(checks) - n_fail} / {len(checks)} passed, {n_fail} failed, {time.perf_counter() - T_START:.0f} s")
sys.exit(1 if n_fail else 0)
