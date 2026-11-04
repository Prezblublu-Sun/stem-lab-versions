"""Run with the repo venv: PYTHONUTF8=1 .venv-mobo/Scripts/python.exe v2/tests/test_stage_db_b16.py
Local only: a fake queue in the system temp dir (mobo_toy_db_b16_tests); J.QROOT points there. No gmsh, no FE, no Linux, nothing under
~/mobo_toy_v2 is read or written. The specs of the source jobs come read-only from db3406/raw.

v2/stage_db.py v1.12, batches b16 (VAL-1), b17 (TQ-0), b18 (MU-1):
A. constants: the three batches in BATCHES, layer sources and selection, slow start, code_hash unchanged.
B. b16: 3 intact rows, the 3406 h 2.0 reference with only cfg.load and h_far changed; the load directions have the intended signs; distinct condition ids.
C. b17: 12 friction-only rows; each differs from its source only by cfg.load (and by m or alpha for the A variants); the first 2 rows are A.
D. b18: 13 rows at mu 0.2 and 7 at mu 0.15; only mu changes; the condition id carries mu.
E. fail closed: a variant whose b14 baseline is absent or not DONE is a problem; a source not DONE refuses.
F. dedup: the same physics under another job name -> existing; condition ids of rows without mu and h_far did not move; b14 and b15 job ids did not move.
G. dry_run: exit 0, writes nothing, for all three batches.
H. stage_al.load_training drops alpha_sagit > 18 and mu != 0.3 rows, keeps the 3606 N stair-direction row; v0.6 is not affected.
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
DBROOT = pathlib.Path(r"H:/projects/Femoral implant generation/db3406")
RAW = DBROOT / "raw"
V06 = DBROOT / "v0.6"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "v2"))
BASE = pathlib.Path(tempfile.gettempdir()) / "mobo_toy_db_b16_tests"
shutil.rmtree(BASE, ignore_errors=True)
BASE.mkdir(parents=True)

import jobs as J  # noqa: E402
import stage_db as DB  # noqa: E402
import stage_neckopt as SN  # noqa: E402

T_START = time.perf_counter()
REAL_Q, REAL_R = J.QROOT, J.RESULTS
checks = []
A, REF = DB.CODES["A"], DB.REF_H2
TAG = "p13_a105_91e458e3"


def ok(name, cond, extra=""):
    checks.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + f"(t={time.perf_counter() - T_START:.0f}s) " + name + (f"  [{extra}]" if extra else ""), flush=True)


def raw_job(prefix):
    hits = [h for h in sorted(RAW.glob(prefix + "_*.tar.xz")) if len(h.name) == len(prefix) + 9 + len(".tar.xz")]   # <prefix>_<hash8> only: _m1_* also matches _m1_a50_<hash8>
    assert len(hits) == 1, (prefix, hits)
    return hits[0].name[:-len(".tar.xz")]


WS = {k: raw_job(f"db_ws_{TAG}_{k}") for k in ("m0.75", "m1", "m1.5", "a60")}
SOURCES = sorted({*DB.CODES.values(), *(DB.CY_EXTRA[c] for c in ("a82", "a96", "al1_07")), REF, *WS.values()})


def extract(job, dest):
    d = dest / job
    d.mkdir(parents=True)
    with tarfile.open(RAW / f"{job}.tar.xz", "r:xz") as tf:
        for member in ("spec.json", "prep.json", "DONE"):
            f = tf.extractfile(f"{job}/{member}")
            (d / member).write_bytes(f.read())


CACHE = BASE / "_cache"
for j_ in SOURCES:
    extract(j_, CACHE)


def queue(name):
    root = BASE / name
    J.QROOT, J.RESULTS = root / "queue", root / "results"
    assert not str(J.QROOT).startswith(str(pathlib.Path.home() / "mobo_toy_v2"))
    J.QROOT.mkdir(parents=True)
    J.RESULTS.mkdir(parents=True)
    for j in SOURCES:
        shutil.copytree(CACHE / j, J.QROOT / j)
    return root


def spec_of(j):
    return json.loads((J.QROOT / j / "spec.json").read_text())


try:
    ok("A: b16, b17, b18 in BATCHES, code_hash unchanged", all(b in DB.BATCHES for b in ("b16", "b17", "b18")) and J.code_hash() == DB.DB_CODE_HASH)
    ok("A: layer sources", DB.LAYER_SOURCE["VAL-1"] == "intact_ref" and DB.LAYER_SOURCE["TQ-0"] == "cond_anchor" and DB.LAYER_SOURCE["MU-1"] == "cond_anchor")
    ok("A: selection and slow start", DB.LAYER_SELECTION["VAL-1"] == "reference" and "TQ-0" in DB.SLOW_START_LAYERS and "MU-1" in DB.SLOW_START_LAYERS
       and "VAL-1" not in DB.SLOW_START_LAYERS)

    # ---------------------------------------------------------------- B
    queue("b16")
    ref_src = spec_of(REF)
    b = DB.build("b16")
    rows = {r["key"]: r for r in b["rows"]}
    ok("B: no problems on a clean queue", not b["problems"], "; ".join(b["problems"])[:400])
    ok("B: the 3 expected keys", list(rows) == ["VAL_n1200", "VAL_n1200_far2.5", "VAL_b500_far2.5"], list(rows))
    same = True
    for k, r in rows.items():
        s = r["spec"]
        extra = {x for x in s if x not in ref_src} - {"cfg", "h_far"}
        same = same and not extra and all(s.get(x) == ref_src.get(x) for x in ("h_int", "femur_id", "neck_axis", "kind")) and s["stage"] == "db_ref"
    ok("B: each row = the reference with only cfg.load and h_far", same, str({k: sorted(r["spec"]) for k, r in rows.items()})[:300])
    ok("B: far 6 row has no h_far key, the fine rows have 2.5",
       "h_far" not in rows["VAL_n1200"]["spec"] and rows["VAL_n1200_far2.5"]["spec"]["h_far"] == 2.5 and rows["VAL_b500_far2.5"]["spec"]["h_far"] == 2.5)
    ok("B: all intact, all new, job ids under db_ref_intact_val_",
       all(r["model_set"] == "intact" and r["dedup"] == "new" and r["expected_id"].startswith("db_ref_intact_val_") and r["heavy"] for r in rows.values()),
       [r["expected_id"] for r in rows.values()])
    ok("B: condition ids distinct", len({r["condition_id"] for r in rows.values()}) == 3, [r["condition_id"] for r in rows.values()])
    import model3d_v2 as M2
    Fn = M2.load_vector({"load": rows["VAL_n1200"]["spec"]["cfg"]["load"]})
    Fb = M2.load_vector({"load": rows["VAL_b500_far2.5"]["spec"]["cfg"]["load"]})
    # model axes: +x medial, +y posterior, +z proximal
    ok("B: Naghavi load points lateral, posterior, down, 1200 N", Fn[0] < 0 and Fn[1] > 0 and Fn[2] < 0 and abs(float((Fn ** 2).sum()) ** 0.5 - 1200.0) < 1e-6, Fn.round(1).tolist())
    ok("B: Bath load points medial, posterior, down, 500 N", Fb[0] > 0 and Fb[1] > 0 and Fb[2] < 0 and abs(float((Fb ** 2).sum()) ** 0.5 - 500.0) < 1e-6, Fb.round(1).tolist())

    # ---------------------------------------------------------------- C
    b = DB.build("b17")
    rows = {r["key"]: r for r in b["rows"]}
    a_src = spec_of(A)
    ok("C: no problems on a clean queue", not b["problems"], "; ".join(b["problems"])[:400])
    ok("C: 12 rows, the first 2 are A", len(rows) == 12 and list(rows)[:2] == ["TQ0_F3606_A", "TQ0_S40_A"], list(rows)[:3])
    only_load = True
    for k, r in rows.items():
        s = r["spec"]
        src = spec_of(r["source_job"])
        diff = {x for x in src["design"] if s["design"].get(x) != src["design"][x]}
        code = k.split("_", 2)[2]
        want = set(DB.A_WS.get(code, {}))
        rest = all(s.get(x) == src.get(x) for x in ("h_int", "model", "h_cut", "slip_tol", "delta", "femur_id", "neck_axis", "min_A0", "a_bounds_max", "ref_cut_mm"))
        only_load = only_load and diff == want and rest and s["fric_only"] and "intact_job" not in s and set(s["cfg"]) == {"load"} and s["stage"] == "db_cd"
    ok("C: each row differs from its source only by cfg.load, and by m or alpha for the A variants", only_load)
    ok("C: the two load cases", all(r["spec"]["cfg"]["load"] == DB.TQ0_LOADS[k.split("_")[1]] for k, r in rows.items()))
    ok("C: Am1 and Aa60 carry the b14 values", rows["TQ0_F3606_Am1"]["spec"]["design"]["m"] == 1.0 and rows["TQ0_S40_Aa60"]["spec"]["design"]["alpha"] == 60.0)
    ok("C: friction only, all new, job ids under db_cd_, not in any family",
       all(r["model_set"] == "fric" and r["dedup"] == "new" and r["expected_id"].startswith("db_cd_") for r in rows.values())
       and not [k for k, r in rows.items() for p in DB.CHECK_PHASES if SN.Phase(p).in_family(r["spec"])])

    # ---------------------------------------------------------------- D
    b = DB.build("b18")
    rows = {r["key"]: r for r in b["rows"]}
    ok("D: no problems on a clean queue", not b["problems"], "; ".join(b["problems"])[:400])
    n2 = [k for k, r in rows.items() if r["spec"]["mu"] == 0.2]
    n15 = [k for k, r in rows.items() if r["spec"]["mu"] == 0.15]
    ok("D: 13 rows at mu 0.2, 7 at mu 0.15, low-mu designs are a subset", len(n2) == 13 and len(n15) == 7 and set(DB.MU1_LOW) <= set(DB.MU1_CODES), f"{len(n2)} {len(n15)}")
    ok("D: the first 2 rows are A at both mu", list(rows)[:2] == ["MU1_mu0.2_A", "MU1_mu0.15_A"], list(rows)[:3])
    only_mu = True
    for k, r in rows.items():
        s = r["spec"]
        src = spec_of(r["source_job"])
        diff = {x for x in src["design"] if s["design"].get(x) != src["design"][x]}
        code = k.split("_", 2)[2]
        only_mu = only_mu and diff == set(DB.A_WS.get(code, {})) and "cfg" not in s and s["fric_only"] and s["delta"] == src["delta"] and s["h_int"] == src["h_int"]
    ok("D: each row differs from its source only by mu, and by m or alpha for the A variants", only_mu)
    ok("D: the condition id carries mu", rows["MU1_mu0.15_A"]["condition_id"].endswith("|mu0.15") and "mu" not in DB.cond_id(a_src), rows["MU1_mu0.15_A"]["condition_id"])
    ok("D: friction only, all new", all(r["model_set"] == "fric" and r["dedup"] == "new" for r in rows.values()))

    # ---------------------------------------------------------------- E
    queue("fail")
    (J.QROOT / WS["m1"] / "DONE").unlink()
    ok("E: b17 with Am1's baseline not DONE is a problem", [p for p in DB.build("b17")["problems"] if "Am1: its baseline" in p])
    shutil.rmtree(J.QROOT / WS["m1.5"])
    ok("E: b18 with Am1.5's baseline absent is a problem", [p for p in DB.build("b18")["problems"] if "Am1.5: its baseline" in p and "absent" in p])
    (J.QROOT / DB.CODES["init29"] / "DONE").unlink()
    try:
        DB.build("b17")
        ok("E: a source not DONE refuses", False)
    except SystemExit as e:
        ok("E: a source not DONE refuses", "not DONE" in str(e), str(e)[:90])
    (J.QROOT / REF / "DONE").unlink()
    try:
        DB.build("b16")
        ok("E: b16 with the reference not DONE refuses", False)
    except SystemExit as e:
        ok("E: b16 with the reference not DONE refuses", "not DONE" in str(e), str(e)[:90])

    # ---------------------------------------------------------------- F
    queue("dedup")
    r0 = {r["key"]: r for r in DB.build("b18")["rows"]}["MU1_mu0.2_A"]
    other = {**r0["spec"], "stage": "db_fd", "tag": "same_physics", "created": "x", "kind": "variant"}
    d = J.QROOT / "db_fd_same_physics_00000000"
    d.mkdir()
    (d / "spec.json").write_text(json.dumps(other, indent=1, default=float))
    (d / "DONE").write_text("")
    r1 = {r["key"]: r for r in DB.build("b18")["rows"]}["MU1_mu0.2_A"]
    ok("F: the same physics under another job name -> existing", r1["dedup"] == "existing" and r1["id"] == d.name and r1["dedup_via"] == "physics", f"{r1['dedup']} {r1['id']}")
    shutil.rmtree(d)
    ok("F: condition ids of rows without mu and h_far did not move",
       DB.cond_id({"delta": 0.1, "h_int": 2.0, "slip_tol": 0.00025}) == "d0.1|stair|h2|slip0.00025"
       and DB.cond_id({"kind": "intact", "h_int": 2.0}) == "intact|stair|h2"
       and DB.cond_id({"delta": 0.1, "h_int": 2.0, "slip_tol": 0.00025, "cycles": 4}) == "d0.1|stair|h2|slip0.00025|c4")
    r14 = {r["key"]: r for r in DB.build("b14")["rows"]}
    ok("F: the b14 job ids did not move", r14["WS_m1"]["expected_id"] == WS["m1"] and r14["WS_a60"]["expected_id"] == WS["a60"], r14["WS_m1"]["expected_id"])

    # ---------------------------------------------------------------- G
    for batch, n in (("b16", 3), ("b17", 12), ("b18", 20)):
        root = queue("dry" + batch)
        before = sorted(str(x.relative_to(root)) for x in root.rglob("*"))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = DB.dry_run(batch)
        out = buf.getvalue()
        ok(f"G: {batch} dry run exits 0, lists {n} jobs, writes nothing",
           rc == 0 and f"jobs ({n}):" in out and before == sorted(str(x.relative_to(root)) for x in root.rglob("*")), out[-300:] if rc else "")

    # ---------------------------------------------------------------- H
    import stage_al as AL
    d = BASE / "al"
    d.mkdir()
    rows_csv = list(csv.DictReader(open(V06 / "scalars.csv", newline="", encoding="utf-8")))
    fields = list(rows_csv[0])
    k = next(i for i, r in enumerate(rows_csv) if r["status"] == "DONE" and r["has_fric_model"] == "true" and r["kind"] == "variant"
             and r["selection"] != "corner_test" and float(r["h_int_mm"] or 0) == 2.0 and not r["cfg_override"] and r["in_bounds_v1"] != "false")

    def run(change):
        with open(d / "scalars.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            for i, r in enumerate(rows_csv):
                w.writerow({**r, **change} if i == k else r)
        return AL.load_training(d, {})[1]["dropped"]

    d0 = run({})
    ok("H: v0.6 has no alpha_sagit > 18 row", "alpha_sagit > 18" not in d0, json.dumps(d0))
    ok("H: a 40 deg row is dropped from the training rows", run({"alpha_sagit_deg": "40.0"}).get("alpha_sagit > 18") == 1)
    dm = run({"mu": "0.2"})
    ok("H: a mu 0.2 row is dropped from the training rows", dm.get("model / mesh condition", 0) == d0.get("model / mesh condition", 0) + 1, json.dumps(dm))
    ok("H: a 3606 N stair-direction row is not dropped by the new rule", "alpha_sagit > 18" not in run({"load_R_N": "3606.0"}))
finally:
    J.QROOT, J.RESULTS = REAL_Q, REAL_R
    shutil.rmtree(BASE, ignore_errors=True)

n_fail = sum(not c for _, c in checks)
print(f"{len(checks) - n_fail}/{len(checks)} passed, {n_fail} failed")
sys.exit(1 if n_fail else 0)
