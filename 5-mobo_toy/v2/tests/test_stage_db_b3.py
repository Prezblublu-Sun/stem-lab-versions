"""Run with the repo venv: PYTHONUTF8=1 .venv-mobo/Scripts/python.exe v2/tests/test_stage_db_b3.py
Local only: a fake queue in the system temp dir (mobo_toy_db_b3_tests); J.QROOT points there. No gmsh, no FE, no Linux, nothing under
~/mobo_toy_v2 is read or written. The b3 rows themselves are checked by the dry run on the live Linux queue (they need b1 / b2 manifests,
the frozen CR-T file and the sub-box points); this file checks the v1.5 logic that does not need them.

v2/stage_db.py v1.5 (one-week plan 2026-10-29, user-approved):
A. known_failure on the 11 real db3406 FAILED reasons of 2026-10-29 (texts copied from the queue): the 5 L4 'TOO MANY ATTEMPTS' short stems
   (L 20.9-26.3 mm) and the 3 L3 'degenerate tetrahedra' (two designs, the h 2.5 reference) are known; the 3 L3 'overlapping facets' are not.
   Synthetic: L4 on a 40 mm stem -> not known; L4 with alpha 18 deg and m 0.55 mm on a 35 mm stem -> known; 'TIME INCREMENT ... MINIMUM' on
   a short stem -> known; L3 naming both degenerate tetrahedra and overlapping facets -> not known; L5 export -> not known; no FAILED.json
   or an unreadable spec -> not known.
B. gate_pass with AUTO_ACK: 2 known of 20 finished (10 %) -> no hold, both acknowledged, AUTO-ACK logged, auto_ack events; a later pass
   logs nothing new. 1 known + 1 unknown -> no hold (1 unacknowledged < 2); a second unknown -> hold. 4 known of 20 (20 % > 15 %) ->
   not acknowledged, held, one WARNING (not repeated on the next pass). A layer held for 2 known failures while AUTO_ACK was off ->
   AUTO_ACK on -> acknowledged and released (pending again, release event 'auto'). AUTO_ACK off -> the v1.4 behaviour (hold).
C. constants: b3 in BATCHES; CR-T / NZ-2 / FD-1 h1.4 have sources corner_test / noise / fid_h14, CR-T selection corner_test; the three
   layers slow-start; FD-1 h1.4 is an h 1.4 layer for the exclusive mode; quantile_pick picks distinct (i + 0.5) / n positions, honours
   exclude, refuses too few candidates; jobs.code_hash() == 6d7af243d0.
"""
import json
import pathlib
import shutil
import sys
import tempfile
import time

ROOT = pathlib.Path(r"H:/projects/Femoral implant generation/sandbox/mobo_toy")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "v2"))
BASE = pathlib.Path(tempfile.gettempdir()) / "mobo_toy_db_b3_tests"
shutil.rmtree(BASE, ignore_errors=True)
BASE.mkdir(parents=True)

import jobs as J  # noqa: E402
import stage_db as DB  # noqa: E402

T_START = time.perf_counter()
REAL_Q, REAL_R = J.QROOT, J.RESULTS
REAL_AUTO = DB.AUTO_ACK
checks = []


def ok(name, cond, extra=""):
    checks.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + f"(t={time.perf_counter() - T_START:.0f}s) " + name + (f"  [{extra}]" if extra else ""), flush=True)


def use(root: pathlib.Path):
    J.QROOT, J.RESULTS = root / "queue", root / "results"
    assert not str(J.QROOT).startswith(str(pathlib.Path.home() / "mobo_toy_v2"))
    J.QROOT.mkdir(parents=True, exist_ok=True)
    J.RESULTS.mkdir(parents=True, exist_ok=True)


TMA = ("m_fric: TOO MANY ATTEMPTS MADE FOR THIS INCREMENT ANALYSIS SUMMARY: TOTAL OF 41 INCREMENTS 13 CUTBACKS IN AUTOMATIC "
       "INCREMENTATION 381 ITERATIONS INCLUDING CONTACT ITERATIONS IF PRESENT 381 PASSES THROUGH THE EQUATION S")
DEG = ("BuildError: L3: meshing failed after retries: algo 1, h 2, m 40: L3: degenerate tetrahedra: {'cortex': {'min_vol': 1.3e-10, "
       "'n_tiny': 9}, 'cancellous': {'min_vol': 0.00014, 'n_tiny': 0}}")
OVL = ("BuildError: L3: meshing failed after retries: algo 1, h 2, m 40: Exception: Invalid boundary mesh (overlapping facets) on surface "
       "2898 surface 2563 | algo 10, h 2, m 40: Exception: HXT 3D mesh failed")
REAL = {  # job: (level, stage, reason, L, alpha, m, kind) -- the 11 db3406 FAILED rows of 2026-10-29
    "db_cr_c593_5f21cad7": ("L3", "prep", OVL, 39.71, 44.81, 0.594, "variant"),
    "db_ref_intact_h2.5_8ea8a847": ("L3", "prep", "BuildError: L3: degenerate tetrahedra: {'cancellous': {'n_tiny': 2}}", None, None, None,
                                    "intact"),
    "db_sf_p103_4e8c58cb": ("L3", "prep", DEG, 38.48, 36.86, 0.619, "variant"),
    "db_sf_p115_a1f841ce": ("L4", "solve", TMA, 20.86, 40.29, 1.042, "variant"),
    "db_sf_p129_0d2da161": ("L3", "prep", DEG, 20.68, 38.88, 1.489, "variant"),
    "db_sf_p135_2a562b07": ("L3", "prep", OVL, 36.08, 37.41, 1.282, "variant"),
    "db_sf_p140_207de24d": ("L3", "prep", OVL, 22.19, 36.79, 0.724, "variant"),
    "db_sf_p33_b5741959": ("L4", "solve", TMA, 22.82, 20.71, 1.049, "variant"),
    "db_sf_p52_f4deee0e": ("L4", "solve", TMA, 23.03, 43.83, 1.654, "variant"),
    "db_sf_p75_24ce3ffd": ("L4", "solve", TMA, 22.92, 36.30, 0.652, "variant"),
    "db_sf_p82_4366d592": ("L4", "solve", TMA, 26.33, 18.78, 0.505, "variant"),
}
KNOWN_REAL = {"db_ref_intact_h2.5_8ea8a847", "db_sf_p103_4e8c58cb", "db_sf_p115_a1f841ce", "db_sf_p129_0d2da161", "db_sf_p33_b5741959",
              "db_sf_p52_f4deee0e", "db_sf_p75_24ce3ffd", "db_sf_p82_4366d592"}


def add_failed(name, level, stage, reason, L=None, alpha=None, m=None, kind="variant", spec_text=None):
    d = J.QROOT / name
    d.mkdir(parents=True, exist_ok=True)
    spec = {"kind": kind, "femur_id": "sawbone3406", "h_int": 2.0}
    if L is not None:
        spec["design"] = {"L": L, "alpha": alpha, "m": m}
    (d / "spec.json").write_text(spec_text if spec_text is not None else json.dumps(spec))
    if level is not None:
        (d / "FAILED.json").write_text(json.dumps({"level": level, "stage": stage, "reason": reason}))
    return name


def add_done(name):
    d = J.QROOT / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "spec.json").write_text(json.dumps({"kind": "variant", "design": {"L": 40.0, "alpha": 44.0, "m": 0.6}}))
    for f in ("CLAIMED", "SOLVED", "DONE"):
        (d / f).write_text("")
    return name


def fake_batch(layer, failed: dict, n_done: int):
    """b + manifest with one layer: n_done DONE rows, the failed rows (key -> job) FAILED, 3 pending rows; dedup 'existing' everywhere so
    the first-10 rule (feeder-submitted rows only) stays out of it."""
    rows, man_rows, order = [], {}, []
    jobs = [(f"D{i:02d}", add_done(f"db_x_done{i:02d}_{layer.replace(' ', '')}")) for i in range(n_done)] + list(failed.items())
    for k, jid in jobs + [(f"P{i}", None) for i in range(3)]:
        rows.append({"key": k, "layer": layer})
        st = None if jid is None else ("FAILED" if k in failed else "DONE")
        man_rows[k] = {"id": jid, "status": "pending" if jid is None else "existing", "state": st, "dedup": "existing", "finished_ts": 1.0}
        order.append(k)
    return {"batch": "bt", "rows": rows}, {"batch": "bt", "order": order, "rows": man_rows, "gates": {}, "events": []}


def run_gate(b, man):
    lines = []
    DB.gate_pass(b, man, lines.append)
    return lines


def held(man):
    return [k for k in man["order"] if man["rows"][k]["status"] == "held"]


try:
    use(BASE / "a")
    # ---------------------------------------------------------------- A. known_failure
    for name, (lv, stg, why, L, a, m, kind) in REAL.items():
        add_failed(name, lv, stg, why, L, a, m, kind)
    got = {n: DB.known_failure(n) for n in REAL}
    ok("A: the 8 known real failures (5 L4 short stems, 3 L3 degenerate tetrahedra) are known, the 3 overlapping-facets ones are not",
       {n for n, v in got.items() if v} == KNOWN_REAL, {n: v for n, v in got.items()})
    syn = {
        "s_l4_long": (("L4", "solve", TMA, 40.0, 44.0, 0.6), False),
        "s_l4_lowbounds": (("L4", "solve", TMA, 35.0, 18.0, 0.55), True),
        "s_l4_min_inc": (("L4", "solve", "m_fric: TIME INCREMENT REQUIRED IS LESS THAN THE MINIMUM SPECIFIED", 24.0, 40.0, 1.0), True),
        "s_l3_both": (("L3", "prep", DEG + " | " + OVL, 30.0, 40.0, 1.0), False),
        "s_l5": (("L5", "post", "missing export LOAD_CONTACT.csv", 22.0, 40.0, 1.0), False),
        "s_l4_alpha_only": (("L4", "solve", TMA, 35.0, 18.0, 0.9), False),
    }
    res = {}
    for n, (args, want) in syn.items():
        add_failed(n, *args)
        res[n] = (DB.known_failure(n), want)
    ok("A: synthetic: L4 on a 40 mm stem and alpha-only at the bound -> not known; alpha + m at the bounds and 'TIME INCREMENT ... MINIMUM' on "
       "a short stem -> known; L3 with overlapping facets too, and L5 -> not known", all(bool(v) == w for v, w in res.values()), res)
    add_failed("s_nofail", None, None, None, 20.0, 40.0, 1.0)
    add_failed("s_badspec", "L4", "solve", TMA, spec_text="{not json")
    ok("A: no FAILED.json, or an unreadable spec.json -> not known", DB.known_failure("s_nofail") is None and DB.known_failure("s_badspec") is None)

    # ---------------------------------------------------------------- B. gate_pass with AUTO_ACK
    DB.AUTO_ACK = True
    use(BASE / "b1")
    f2 = {"F1": add_failed("db_f_k1", "L4", "solve", TMA, 22.0, 40.0, 1.0), "F2": add_failed("db_f_k2", "L3", "prep", DEG, 38.0, 40.0, 0.7)}
    b, man = fake_batch("NZ-2", f2, 18)
    lines = run_gate(b, man)
    g = man["gates"]["NZ-2"]
    ok("B: 2 known of 20 finished (10 %) -> no hold, both acknowledged, 2 AUTO-ACK lines, 2 auto_ack events",
       not held(man) and set(g["ack_failed"]) == {"F1", "F2"} and sum("AUTO-ACK" in x for x in lines) == 2
       and [e["event"] for e in man["events"]].count("auto_ack") == 2, lines)
    lines2 = run_gate(b, man)
    ok("B: the next pass logs nothing new and still holds nothing", not lines2 and not held(man), lines2)

    use(BASE / "b2")
    f = {"F1": add_failed("db_f_k1", "L4", "solve", TMA, 22.0, 40.0, 1.0), "U1": add_failed("db_f_u1", "L3", "prep", OVL, 38.0, 40.0, 0.7)}
    b, man = fake_batch("CR-T", f, 18)
    run_gate(b, man)
    ok("B: 1 known + 1 unknown of 20 -> the known one acknowledged, no hold (1 unacknowledged < 2)",
       not held(man) and man["gates"]["CR-T"]["ack_failed"] == ["F1"])
    jid = add_failed("db_f_u2", "L3", "prep", OVL, 30.0, 40.0, 0.7)
    b["rows"].insert(0, {"key": "U2", "layer": "CR-T"})
    man["order"].insert(0, "U2")
    man["rows"]["U2"] = {"id": jid, "status": "existing", "state": "FAILED", "dedup": "existing", "finished_ts": 1.0}
    lines = run_gate(b, man)
    ok("B: a second unknown failure -> ERROR HOLD of the 3 pending rows", len(held(man)) == 3 and any("ERROR HOLD" in x for x in lines), lines)

    use(BASE / "b3")
    f4 = {f"F{i}": add_failed(f"db_f_k{i}", "L4", "solve", TMA, 22.0 + i, 40.0, 1.0) for i in range(4)}
    b, man = fake_batch("FD-1 h1.4", f4, 16)
    lines = run_gate(b, man)
    warn = [x for x in lines if x.startswith("WARNING") and "known pattern" in x]
    lines2 = run_gate(b, man)
    ok("B: 4 known of 20 (20 % > 15 %) -> not acknowledged, held, one WARNING not repeated on the next pass",
       len(held(man)) == 3 and not man["gates"][DB.layer_slug("FD-1 h1.4")]["ack_failed"] and len(warn) == 1
       and not any("WARNING" in x for x in lines2), lines + lines2)

    use(BASE / "b4")
    DB.AUTO_ACK = False
    f2 = {"F1": add_failed("db_f_k1", "L4", "solve", TMA, 22.0, 40.0, 1.0), "F2": add_failed("db_f_k2", "L4", "solve", TMA, 23.0, 40.0, 1.0)}
    b, man = fake_batch("NZ-2", f2, 18)
    run_gate(b, man)
    held_off = len(held(man)) == 3
    ok("B: AUTO_ACK off -> the v1.4 behaviour: 2 known failures of 20 hold the layer", held_off)
    DB.AUTO_ACK = True
    lines = run_gate(b, man)
    rel = [e for e in man["events"] if e["event"] == "release"]
    ok("B: AUTO_ACK on for that held layer -> both acknowledged and the layer released (3 rows pending, release event how 'auto')",
       held_off and not held(man) and sum(man["rows"][k]["status"] == "pending" for k in man["order"]) == 3 and len(rel) == 1
       and man["gates"]["NZ-2"]["releases"][-1]["how"] == "auto" and any(x.startswith("RELEASE layer NZ-2") for x in lines), lines)

    # ---------------------------------------------------------------- C. constants and helpers
    ok("C: b3 in BATCHES; CR-T / NZ-2 / FD-1 h1.4 sources corner_test / noise / fid_h14; CR-T selection corner_test",
       "b3" in DB.BATCHES and DB.LAYER_SOURCE["CR-T"] == "corner_test" and DB.LAYER_SOURCE["NZ-2"] == "noise"
       and DB.LAYER_SOURCE["FD-1 h1.4"] == "fid_h14" and DB.LAYER_SELECTION["CR-T"] == "corner_test")
    ok("C: the three b3 layers slow-start; FD-1 h1.4 is exclusive in DB_H14_EXCLUSIVE mode like FD-0 h1.4",
       all(L in DB.SLOW_START_LAYERS for L in ("CR-T", "NZ-2", "FD-1 h1.4"))
       and DB.exclusive_keys({"rows": [{"key": "FD1_h1.4_B", "layer": "FD-1 h1.4"}, {"key": "x", "layer": "NZ-2"}]}, True)
       == list(DB.EXCLUSIVE) + ["FD1_h1.4_B"])
    c = [(float(v), f"k{v:02d}", f"j{v}") for v in range(12)]
    p6 = DB.quantile_pick(c, 6)
    p4 = DB.quantile_pick(c, 4, exclude={x[1] for x in p6})
    try:
        DB.quantile_pick(c[:3], 4)
        refused = False
    except SystemExit:
        refused = True
    ok("C: quantile_pick: 6 of 12 at positions 1, 3, 5, 7, 9, 11; 4 more from the other 6 avoid them; too few candidates refused",
       [x[0] for x in p6] == [1.0, 3.0, 5.0, 7.0, 9.0, 11.0] and not ({x[1] for x in p4} & {x[1] for x in p6}) and len(p4) == 4 and refused,
       ([x[0] for x in p6], [x[0] for x in p4]))
    J.QROOT, J.RESULTS = REAL_Q, REAL_R
    ok("C: jobs.code_hash() == 6d7af243d0 (the 8 hashed files untouched)", J.code_hash() == DB.DB_CODE_HASH)
finally:
    J.QROOT, J.RESULTS = REAL_Q, REAL_R
    DB.AUTO_ACK = REAL_AUTO
    shutil.rmtree(BASE, ignore_errors=True)
    ok("fixture reset: J.QROOT / J.RESULTS back to ~/mobo_toy_v2 (never written by this test); AUTO_ACK restored", J.QROOT == REAL_Q
       and DB.AUTO_ACK == REAL_AUTO)

n_ok = sum(c for _, c in checks)
print(f"\n{n_ok}/{len(checks)} checks passed in {time.perf_counter() - T_START:.0f} s")
sys.exit(0 if n_ok == len(checks) else 1)
