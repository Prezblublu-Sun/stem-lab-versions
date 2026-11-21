"""Run with the repo venv: PYTHONUTF8=1 .venv-mobo/Scripts/python.exe v2/tests/test_stage_db_b2.py
Local only: fake queues / results in the system temp dir (mobo_toy_db_b2_tests) built from fixtures_stage_db.json (the b1 fixture: source
jobs and reduced phase-13 / 14 state files) and fixtures_stage_db_b2.json (read-only copy of the Linux queue 2026-10-26 01:36 UTC plus the
0-FE tpl_record runs of 01:45-02:05 UTC: the pool's 2169 feasible Sobol positions and losses, the two arm jobs of pool_idx 51, the arm
records with pool_idx 32..159, the CR / widened templating arrays, the selection and counts that 'select b2' wrote, the b2 dry-run ids).
J.QROOT / J.RESULTS point there for every check; a simulated serve + worker advances the fake jobs. No gmsh, no FE, no Abaqus, no Linux,
nothing under ~/mobo_toy_v2 is read or written. Trees opt out of the b1 seed check (stage_db.SEEDS = {"b1": ()}).

v2/stage_db.py batch b2 (D2 of the database plan, research-log/neck_implant_2026-10-02/3406数据库规划_两天一周一月_2026-10-25.md):
A. G2: the pool (regenerated from the Sobol positions) passes; a perturbed row, swapped rows, a wrong 65k prefix and a different 65k
   feasible set are each caught; the 65k file with the same feasible set passes.
B. SF-1 rows: 128 rows pool_idx 32..159 in Sobol order, every 5th bonded (planned 25), spec = Phase(13).spec_of physics + kind variant +
   stage db_sf, expected ids = the dry run on the 01:36 UTC copy, source sf / selection iid, never in a phase 11-14 family.
C. adoption: pool_idx 51 (both arms, fric_only) -> SF1_p0051 existing via physics -> sb13_a33_016e3ffa, its fric-only model kept (planned
   bonded), sf_bo_overlap, unbiased false, no new FE; a bonded arm twin makes a planned-fric row bonded; FAILED twins -> problem unless
   DB_ACK_FAILED_<key>; an arm record without a queue twin and a record whose x differs from the pool row -> problems.
D. CR selection: with the frozen evaluated list the CR-1 / CR-T lists and the CR expected ids equal the real dry run's; 16 + 16 and
   15 + 15 by e*; greedy-maximin invariant recomputed by brute force; CR-T disjoint from CR-1, farther than the floor from CR-1 and the
   evaluated designs; the literal 'distance >= CR-1 spacing' rule reported infeasible (0 candidates) as on the real copy; an evaluated design
   planted next to a candidate excludes it; replay identical; a tampered frozen list / sha256, a missing selection file with a manifest and
   a templating file of another point list are refused.
E. widened counts: the regions add up to 4096 and equal the counts 'select b2' wrote on the real copy.
F. dry run writes nothing; select writes the two files, is idempotent, refuses a different existing file; CLI.
G. feed_pass gate / per-pass cap / probe mode (no submission, no manifest write, ProbeHalt instead of a halt).
H. b2 alone with no b1 manifest: submits nothing, logs PRIORITY 'no manifest yet'.
I. two feeders on one fake queue (threads, lockstep with the simulated world): b1 (84 rows) and a reduced b2 (20 SF + 5 CR) both finish;
   every expected id submitted exactly once; the global depth cap, heavy / reference / h1.4 / exclusive / slow-start / REF-priority gates
   hold at every submission; at every b2 submission an independent oracle finds no b1 row submittable and no exclusive due (drain);
   b2 submitted while b1 still had rows pending (real concurrency); REF_h1.4 still went alone on an idle queue.
   I2: STOP_DB_FEED mid-run stops both cleanly; a restart of both finishes with nothing submitted twice, b2's order / ids / frozen
   selection unchanged.
J. b1 unchanged: 84 rows, the pinned ids; jobs.code_hash() == 6d7af243d0.
"""
import contextlib
import copy
import hashlib
import io
import json
import os
import pathlib
import shutil
import sys
import tempfile
import threading
import time

ROOT = pathlib.Path(r"H:/projects/Femoral implant generation/sandbox/mobo_toy")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "v2"))
BASE = pathlib.Path(tempfile.gettempdir()) / "mobo_toy_db_b2_tests"
shutil.rmtree(BASE, ignore_errors=True)
BASE.mkdir(parents=True)
FIX = json.loads((ROOT / "v2" / "tests" / "fixtures_stage_db.json").read_text(encoding="utf-8"))
FX2 = json.loads((ROOT / "v2" / "tests" / "fixtures_stage_db_b2.json").read_text(encoding="utf-8"))
EXP2 = FX2["expected"]

import numpy as np  # noqa: E402
import jobs as J  # noqa: E402
import stage_neckopt as SN  # noqa: E402
import stage_db as DB  # noqa: E402

T_START = time.perf_counter()
REAL_Q, REAL_R = J.QROOT, J.RESULTS
REAL_SUBMIT = J.submit
REAL_SEEDS = dict(DB.SEEDS)
REAL_CONST = {k: getattr(DB, k) for k in ("SF1_RANGE", "CR1_QUOTA", "CRT_QUOTA")}
checks = []


def ok(name, cond, extra=""):
    checks.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + f"(t={time.perf_counter() - T_START:.0f}s) " + name + (f"  [{extra}]" if extra else ""), flush=True)


def use(root: pathlib.Path):
    J.QROOT, J.RESULTS = root / "queue", root / "results"
    assert not str(J.QROOT).startswith(str(pathlib.Path.home() / "mobo_toy_v2"))


def captured(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = fn(*a, **k)
    return r, buf.getvalue()


def raises(fn, *a, **k):
    try:
        captured(fn, *a, **k)
    except SystemExit as e:                                                      # noqa: PERF203
        return str(e.code if e.code is not None else "")
    return None


def tree_hash(root: pathlib.Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        h.update(p.relative_to(root).as_posix().encode())
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()


MARKS = {"NEW": (), "READY": ("READY",), "CLAIMED": ("CLAIMED",), "SOLVED": ("CLAIMED", "SOLVED"), "DONE": ("CLAIMED", "SOLVED", "DONE")}
NAN = float("nan")


def arr(xs, dtype=float):
    return np.array([NAN if x is None else x for x in xs], dtype=dtype)


def write_tpl(rel: str, U, X, a: dict, phase: int = 13):
    """A tpl_record-format npz with the arrays stage_db reads (u13, x13, var_names, done, error, feasible, e_star, ...) and the meta."""
    p = J.RESULTS / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    n = len(U)
    meta = {"tool": "tpl_record", "format": 2, "phase": phase, "rule": DB._tpl_rule_expect(), "n": n, "complete": True,
            "provenance": {"code_hash": J.code_hash(), "host": "fake", "femur_geom_key": "fake"}, "started_utc": "2026-10-26T00:00:00Z",
            "updated_utc": "2026-10-26T00:00:01Z"}
    fields = {"feasible": np.array(a["feasible"], bool), "error": np.array(a["error"], bool), "done": np.ones(n, bool),
              "e_star": arr(a["e_star"]), "A0_star": arr(a["A0_star"]), "bone_mm3": arr(a["bone_mm3"]),
              "e_margin": arr(a.get("e_margin", [NAN] * n)), "e_margin_eff": arr(a.get("e_margin_eff", [NAN] * n))}
    with open(p, "wb") as fh:
        np.savez_compressed(fh, u13=np.asarray(U, float), x13=np.asarray(X, float), var_names=np.array(DB.b2_phase().vars), **fields,
                            meta_json=np.array(json.dumps(meta)))
    return p


def cr_phys(U):
    ph = DB.b2_phase()
    out = []
    for u in U:
        d, h = ph.design_of(u)
        out.append([h if k == "h_cut" else d[k] for k in ph.vars])
    return np.array(out)


def add_job(name, spec, state="NEW", reason="simulated"):
    d = J.QROOT / name
    d.mkdir()
    (d / "spec.json").write_text(json.dumps({**spec, "created": "2026-10-26 00:00:00"}))
    if state == "FAILED":
        (d / "FAILED.json").write_text(json.dumps({"level": "L3", "stage": "prep", "reason": reason}))
        return
    for m in MARKS[state]:
        (d / m).write_text("x")
    if state == "DONE":
        (d / "result.json").write_text(json.dumps({"gruen7": 1.0, "gruen1": 1.0}))


POOL_U = DB.sobol(DB.POOL_N, DB.POOL_SOBOL_SEED)[FX2["pool_positions"]]


def write_tree(root: pathlib.Path, twins=True, recs=True, tpl=True, wide=True, sel=False, pool_U=None, pool65k=None) -> pathlib.Path:
    """Fake queue: the b1 fixture jobs (spec + markers + reduced results) and state files, plus for b2: the pool file (regenerated from the
    fixture's Sobol positions), the two arm twins of pool_idx 51 (DONE) and their records, the CR / widened templating files (real arrays,
    u13 regenerated from the seeds), optionally the frozen selection of the real copy (sel=True) and a 65k file."""
    shutil.rmtree(root, ignore_errors=True)
    DB._SPEC_CACHE.clear()
    DB.SEEDS = {"b1": ()}
    use(root)
    J.QROOT.mkdir(parents=True)
    J.RESULTS.mkdir(parents=True)
    for n, j in FIX["jobs"].items():
        d = J.QROOT / n
        d.mkdir()
        (d / "spec.json").write_text(json.dumps(j["spec"], indent=1))
        if j["state"] == "DONE":
            for m in MARKS["DONE"]:
                (d / m).write_text("x")
            (d / "result.json").write_text(json.dumps({**j["result"], "job_id": n}))
    states = copy.deepcopy(FIX["states"])
    if recs:
        for p, rs in FX2["arm_records"].items():
            states[p]["records"] += copy.deepcopy(rs)
    for p, st in states.items():
        (J.RESULTS / f"neckopt_p{p}.json").write_text(json.dumps(st))
    if twins:
        for n, t in FX2["twins"].items():
            d = J.QROOT / n
            d.mkdir()
            (d / "spec.json").write_text(json.dumps(t["spec"], indent=1))
            for m in MARKS[t["state"]]:
                (d / m).write_text("x")
            (d / "result.json").write_text(json.dumps({**t["result"], "job_id": n}))
    pl = J.RESULTS / "pools"
    pl.mkdir()
    U = POOL_U if pool_U is None else pool_U
    np.savez(pl / DB.POOL_NAME, U=U, loss=np.array(FX2["pool_loss"], float))
    (pl / DB.POOL_NAME).with_suffix(".json").write_text(json.dumps(FX2["pool_meta"]))
    if tpl:
        Uc = DB.cr_points()
        write_tpl(DB.CR_TPL, Uc, cr_phys(Uc), FX2["cr_tpl"])
    if wide:
        W = DB.wide_points()
        for (rel, a, z), w in zip(DB.WIDE_PARTS, FX2["wide"]):
            write_tpl(rel, W[a:z], DB.wide_physical(W[a:z]), w, phase=99)
    if sel:
        doc = copy.deepcopy(FX2["selection"])
        doc["tpl_file"]["sha256"] = DB._sha256_path(J.RESULTS / DB.CR_TPL)          # the fake npz is not byte-identical to the real one
        DB._write_json(DB.crt_file_path(), doc)
    if pool65k is not None:
        p = J.RESULTS / DB.POOL65K
        p.parent.mkdir(parents=True, exist_ok=True)
        u65, feas = pool65k
        with open(p, "wb") as fh:
            np.savez_compressed(fh, u13=u65, feasible=feas, done=np.ones(len(u65), bool), error=np.zeros(len(u65), bool),
                                meta_json=np.array(json.dumps({"complete": True, "n": len(u65)})))
    return root


DB._ALLOW_NON_LINUX = True
DB.disk_free_gib = lambda *a: 100.0

# ================================================================ A. G2
FA = write_tree(BASE / "fa", sel=True)
b, _ = captured(DB.build, "b2")
g2 = b["g2"]
ok("A: G2 on the fake pool: every pool row is bit-identical to a row of the regenerated Sobol draw (seed 51100), in increasing order; "
   "pool_idx 0 = Sobol index 21; no 65k file -> recorded as absent; no problems",
   g2["ok"] and g2["all_found"] and g2["increasing"] and g2["sobol_index_of_pool_idx0"] == 21 and g2["pool65k"] == {"file": DB.POOL65K, "present": False}
   and b["problems"] == [], (g2, b["problems"][:3]))
Ub = POOL_U.copy()
Ub[100, 3] = np.nextafter(Ub[100, 3], 2.0)
write_tree(BASE / "fa1", pool_U=Ub, sel=True)
b1_, _ = captured(DB.build, "b2")
Us = POOL_U.copy()
Us[[200, 201]] = Us[[201, 200]]
write_tree(BASE / "fa2", pool_U=Us, sel=True)
b2_, _ = captured(DB.build, "b2")
D = DB.sobol(DB.POOL_N, DB.POOL_SOBOL_SEED)
feas65 = np.zeros(DB.POOL_N, bool)
feas65[FX2["pool_positions"]] = True
write_tree(BASE / "fa3", pool65k=(D, feas65), sel=True)
b3_, _ = captured(DB.build, "b2")
f2 = feas65.copy()
f2[FX2["pool_positions"][7]] = False
f2[5] = True
write_tree(BASE / "fa4", pool65k=(D, f2), sel=True)
b4_, _ = captured(DB.build, "b2")
D2 = D.copy()
D2[9, 0] += 1e-9
write_tree(BASE / "fa5", pool65k=(D2, feas65), sel=True)
b5_, _ = captured(DB.build, "b2")
ok("A: G2 catches a pool row off by one ulp, two swapped rows, a 65k file with a different feasible set (1 only in the pool, 1 only in the "
   "65k file) and a 65k prefix that is not the draw; the 65k file with the same feasible set passes (index sets equal)",
   any("not bit-identical" in p for p in b1_["problems"]) and any("not in Sobol order" in p for p in b2_["problems"])
   and b3_["g2"]["ok"] and b3_["g2"]["pool65k"]["feasible_index_set_equal"] and b3_["problems"] == []
   and any("differ from the pool's 2169" in p and "1 only in the pool, 1 only in the 65k file" in p for p in b4_["problems"])
   and any("are not the regenerated Sobol draw" in p for p in b5_["problems"]),
   ([p[:80] for p in b1_["problems"] + b2_["problems"] + b4_["problems"] + b5_["problems"]]))

# ================================================================ B. SF-1 rows
use(FA)
rows = {r["key"]: r for r in b["rows"]}
sf = [r for r in b["rows"] if r["layer"] == "SF-1"]
cr = [r for r in b["rows"] if r["layer"] == "CR-1"]
ph13 = SN.Phase(13)
spec_ok = True
for r in sf:
    planned = r["layer_pos"] % 5 == 0
    want = ph13.spec_of(POOL_U[r["pool_idx"]], f"p{r['pool_idx']}", bonded=planned if not r["sf_bo_overlap"] else False)
    body = {k: v for k, v in r["spec"].items() if k not in ("stage", "tag", "kind")}
    wb = {k: v for k, v in want.items() if k not in ("stage", "tag", "kind")}
    spec_ok &= DB._norm(body) == DB._norm(wb) and r["spec"]["stage"] == "db_sf" and r["spec"]["kind"] == "variant" \
        and r["spec"]["tag"] == f"p{r['pool_idx']}"
ok("B: SF-1 = 128 rows, pool_idx 32..159 in order (layer_pos 1..128), keys SF1_p0032..SF1_p0159; spec = Phase(13).spec_of(pool row) "
   "minus stage / tag / kind + kind variant + stage db_sf (+ tag p<idx>); planned bonded = layer_pos % 5 == 0 (25 rows)",
   [r["pool_idx"] for r in sf] == list(range(32, 160)) and [r["layer_pos"] for r in sf] == list(range(1, 129))
   and [r["key"] for r in sf] == [f"SF1_p{i:04d}" for i in range(32, 160)] and spec_ok
   and sum(r["bonded_planned"] for r in sf) == 25 and all(r["bonded_planned"] == (r["layer_pos"] % 5 == 0) for r in sf))
ok("B: every SF / CR expected id equals the b2 dry run on the 2026-10-26 01:36 UTC copy, and so does the interleaved order (4 SF : 1 CR)",
   {r["key"]: r["expected_id"] for r in b["rows"]} == EXP2["ids"] and [r["key"] for r in b["rows"]] == EXP2["order"]
   and EXP2["order"][:5] == ["SF1_p0032", "SF1_p0033", "SF1_p0034", "SF1_p0035", EXP2["order"][4]] and EXP2["order"][4].startswith("CR1_")
   and EXP2["order"][-1].startswith("CR1_") and EXP2["order"][-2] == "SF1_p0159")
ok("B: record fields: SF source sf / selection iid / stage db_sf, CR source corner / selection stratum / stage db_cr (= tools/db_export "
   "DB_STAGE_RULES); none in a phase 11-14 family (stage prefix); bonded rows point at sb_intact_h2_9c9d7fb5; unbiased only for SF rows "
   "without an arm twin; CR rows in E",
   all(r["source"] == "sf" and r["selection"] == "iid" and r["stage"] == "db_sf" for r in sf)
   and all(r["source"] == "corner" and r["selection"] == "stratum" and r["stage"] == "db_cr" for r in cr)
   and not any(SN.Phase(p).in_family(r["spec"]) for p in (11, 12, 13, 14) for r in b["rows"])
   and all(r["spec"].get("intact_job") == DB.REF_H2 for r in b["rows"] if r["bonded"])
   and all(r["unbiased"] == (not r["sf_bo_overlap"]) and r["in_E"] == r["sf_bo_overlap"] for r in sf)
   and all(not r["unbiased"] and r["in_E"] for r in cr))

# ================================================================ C. adoption
r51 = rows["SF1_p0051"]
ok("C: pool_idx 51 (solved by both arms as sb13_a33 / sb14_a2, fric_only, same hash8): SF1_p0051 is existing via the physics key -> "
   "sb13_a33_016e3ffa (= the real dry run), keeps the fric-only model although bonded was planned (layer_pos 20), sf_bo_overlap with both "
   "twins, unbiased false; the only adopted row; cost counts 127 new SF + 32 new CR",
   r51["dedup"] == "existing" and r51["dedup_via"] == "physics" and r51["id"] == "sb13_a33_016e3ffa" == EXP2["resolved"]["SF1_p0051"]
   and r51["model_set"] == "fric" and r51["bonded_planned"] and r51["layer_pos"] == 20 and r51["sf_bo_overlap"]
   and r51["bo_twins"] == ["sb13_a33_016e3ffa", "sb14_a2_016e3ffa"] and not r51["unbiased"]
   and [r["key"] for r in b["rows"] if r["dedup"] != "new"] == ["SF1_p0051"]
   and b["cost"]["SF-1"]["new"] == 127 and b["cost"]["CR-1"]["new"] == 32 and b["cost"]["SF-1"]["bonded_all_rows"] == 24
   and b["cost"] == EXP2["cost"], (r51["dedup"], r51["id"], b["cost"]["total"]))
# a bonded arm twin of a planned-fric row (pool_idx 40, layer_pos 9) -> the row takes the bonded model and is adopted
write_tree(BASE / "fc1", sel=True)
x40 = POOL_U[40]
sp40 = ph13.spec_of(x40, "a99", bonded=True)
add_job("sb14_a99_aaaaaaaa", {**sp40, "stage": "sb14"}, "DONE")
st14 = json.loads((J.RESULTS / "neckopt_p14.json").read_text())
st14["records"].append({"job_id": "sb14_a99_aaaaaaaa", "round": 99, "ok": True, "rot_first_deg": 0.1, "pool_idx": 40, "x": [float(v) for v in x40]})
(J.RESULTS / "neckopt_p14.json").write_text(json.dumps(st14))
bc1, _ = captured(DB.build, "b2")
r40 = {r["key"]: r for r in bc1["rows"]}["SF1_p0040"]
ok("C: a bonded arm twin of a planned-fric SF row (pool_idx 40) -> the row becomes bonded (intact_job of the twin) and is adopted; no "
   "problems; 2 adopted rows now",
   r40["model_set"] == "fric+bond" and not r40["bonded_planned"] and r40["dedup"] == "existing" and r40["id"] == "sb14_a99_aaaaaaaa"
   and r40["sf_bo_overlap"] and bc1["problems"] == [] and bc1["cost"]["SF-1"]["adopted"] == 2, (r40["dedup"], bc1["problems"][:2]))
# FAILED twins -> problem unless acknowledged
write_tree(BASE / "fc2", sel=True)
for n in FX2["twins"]:
    d = J.QROOT / n
    for f in ("DONE", "SOLVED", "CLAIMED", "result.json"):
        (d / f).unlink()
    (d / "FAILED.json").write_text(json.dumps({"level": "L4", "stage": "solve", "reason": "simulated"}))
bc2, _ = captured(DB.build, "b2")
(J.QROOT.parent / "DB_ACK_FAILED_SF1_p0051").write_text("accepted")
bc2b, _ = captured(DB.build, "b2")
ok("C: both arm twins FAILED -> problem (same physics = a permanent hole) naming DB_ACK_FAILED_SF1_p0051; with that operator file -> "
   "accepted (no problem, ack recorded)",
   any(p.startswith("SF1_p0051: resolves to existing job sb13_a33_016e3ffa, which is FAILED") and "DB_ACK_FAILED_SF1_p0051" in p for p in bc2["problems"])
   and bc2b["problems"] == [] and {r["key"]: r for r in bc2b["rows"]}["SF1_p0051"]["ack_failed"] is not None, [p[:100] for p in bc2["problems"]])
# an arm record in 32..159 without a queue twin; a record whose x is another pool row
write_tree(BASE / "fc3", sel=True)
st13 = json.loads((J.RESULTS / "neckopt_p13.json").read_text())
st13["records"] += [{"job_id": "sb13_a98_bbbbbbbb", "round": 98, "ok": True, "rot_first_deg": 1.0, "pool_idx": 45, "x": [float(v) for v in POOL_U[45]]},
                    {"job_id": "sb13_a33_016e3ffa", "round": 34, "ok": True, "rot_first_deg": 1.0, "pool_idx": 46, "x": [float(v) for v in POOL_U[47]]}]
(J.RESULTS / "neckopt_p13.json").write_text(json.dumps(st13))
bc3, _ = captured(DB.build, "b2")
ok("C: an arm record with pool_idx 45 but no same-physics queue job, and a record whose x is not its pool row -> one problem each",
   any(p.startswith("SF1_p0045: arm record sb13_a98_bbbbbbbb (pool_idx 45) is not found") for p in bc3["problems"])
   and any(p.startswith("SF1_p0046: arm record sb13_a33_016e3ffa has pool_idx 46 but its x differs") for p in bc3["problems"]), bc3["problems"][:3])

# ================================================================ D. CR selection
use(FA)
s = b["cr"]
st = s["stats"]
ok("D: with the frozen evaluated list of the real copy, CR-1 and CR-T equal the real dry run's lists (cr_idx, selection order); CR rows' "
   "expected ids equal the real ones (spec depends on the point only); stats as on the real copy (1467 feasible, 348 e*=0, 0 within 0.02)",
   s["cr1"] == EXP2["cr1"] and s["crt"] == EXP2["crt"] and [r["cr_idx"] for r in cr] == EXP2["cr1"]
   and all(r["expected_id"] == EXP2["ids"][r["key"]] for r in cr)
   and (st["feasible"], st["feasible_e0"], st["excluded_near_evaluated"]) == (1467, 348, 0) == (EXP2["cr_stats"]["feasible"],
                                                                                              EXP2["cr_stats"]["feasible_e0"],
                                                                                              EXP2["cr_stats"]["excluded_near_evaluated"]),
   (s["cr1"][:4], s["crt"][:4]))
grp = s["group"]
ok("D: CR-1 = 16 e*=0 + 16 e*!=0 alternating (first = e*=0), CR-T = 15 + 15 alternating; CR-T disjoint from CR-1; bonded = every 5th "
   "CR-1 row (6)",
   [int(grp[i]) for i in s["cr1"]] == [0, 1] * 16 and [int(grp[i]) for i in s["crt"]] == [0, 1] * 15 and not set(s["cr1"]) & set(s["crt"])
   and len(set(s["crt"])) == 30 and [r["bonded"] for r in cr] == [(i + 1) % 5 == 0 for i in range(32)])
Uc = DB.cr_points()
E_all = np.array([e["u13"] for e in b["evaluated"]] + [r["u13"] for r in sf])
feas = np.array(FX2["cr_tpl"]["feasible"], bool)


def brute_check(sel, cand, pre):
    """Greedy invariant: the k-th pick has the largest distance to (pre + earlier picks) among the remaining candidates of its group."""
    chosen = []
    for i in sel:
        P = np.vstack([pre] + ([Uc[chosen]] if chosen else [])) if len(pre) or chosen else None
        g = grp[i]
        rem = [c for c in cand if grp[c] == g and c not in chosen]
        if P is None or len(P) == 0:
            if i != min(rem):
                return False
        else:
            d = {c: float(np.sqrt(((P - Uc[c]) ** 2).sum(1)).min()) for c in rem}
            best = max(d.values())
            if d[i] < best - 1e-12:
                return False
        chosen.append(i)
    return True


cand1 = [int(i) for i in np.flatnonzero(feas)]
cand_t = [i for i in cand1 if i not in s["cr1"]]
ok("D: greedy-maximin invariant recomputed by brute force: CR-1 (no pre-placed points, first = lowest Sobol index of group e*=0) and "
   "CR-T (CR-1 + evaluated designs pre-placed)",
   brute_check(s["cr1"], cand1, np.zeros((0, 13))) and brute_check(s["crt"], cand_t, np.vstack([Uc[s["cr1"]], E_all])))
dmin_t_c1 = min(float(np.sqrt(((Uc[s["cr1"]] - Uc[i]) ** 2).sum(1)).min()) for i in s["crt"])
dmin_t_ev = min(float(np.sqrt(((E_all - Uc[i]) ** 2).sum(1)).min()) for i in s["crt"])
ok("D: CR-T distances: min to CR-1 and to the evaluated designs (recomputed) = the reported ones, both > the floor 0.02; the literal rule "
   "(>= the CR-1 spacing to CR-1 and every evaluated design) has 0 candidates -> reported infeasible, as on the real copy",
   abs(dmin_t_c1 - st["crt_min_dist_cr1"]) < 1e-12 and abs(dmin_t_ev - st["crt_min_dist_evaluated"]) < 1e-12 and dmin_t_c1 > 0.02
   and dmin_t_ev > 0.02 and st["crt_literal_candidates"] == 0 == EXP2["cr_stats"]["crt_literal_candidates"] and not st["crt_literal_feasible"]
   and abs(st["cr1_spacing"] - EXP2["cr_stats"]["cr1_spacing"]) < 1e-12, (dmin_t_c1, dmin_t_ev, st["cr1_spacing"]))
rp, _ = captured(DB.replay_b2, b)
ok("D: replay with the same seeds: pool draw, sub-box points, SF-1 rows, CR-1 and CR-T identical", rp["ok"] and all(rp.values()), rp)
# an evaluated design planted 0.01 from the first CR-1 pick (no frozen file) -> that candidate is excluded
write_tree(BASE / "fd1")
first = s["cr1"][0]
u = Uc[first].copy()
u[5] += 0.01
d_, h_ = ph13.design_of(u)
add_job("zz_planted_cccccccc", {"kind": "design", "design": d_, "h_cut": h_, "femur_id": DB.FEMUR_ID, "stage": "zz", "tag": "planted"}, "DONE")
bd1, _ = captured(DB.build, "b2")
ok("D: no frozen file: a 3406 design planted 0.01 from the first CR-1 pick (any stage, here 'zz') is an evaluated design -> that candidate "
   "is excluded (within 0.02), the selection changes; source = the queue now",
   bd1["cr"]["stats"]["excluded_near_evaluated"] >= 1 and first in bd1["cr"]["stats"]["excluded_near_jobs_idx"] and first not in bd1["cr"]["cr1"]
   and bd1["evaluated_source"].startswith("the queue now"), (bd1["cr"]["stats"]["excluded_near_evaluated"], bd1["cr"]["cr1"][:3]))
# frozen file: tampered CR-T list, tampered evaluated list, manifest without the file, a templating file of another point list
write_tree(BASE / "fd2", sel=True)
doc = json.loads(DB.crt_file_path().read_text())
doc["crt"] = doc["crt"][::-1]
DB._write_json(DB.crt_file_path(), doc)
bd2, _ = captured(DB.build, "b2")
doc["crt"] = doc["crt"][::-1]
doc["evaluated"][0]["u13"][0] += 1e-6
DB._write_json(DB.crt_file_path(), doc)
e_ev = raises(DB.build, "b2")
DB.crt_file_path().unlink()
DB._write_json(DB.manifest_path("b2"), {"batch": "b2", "rows": {}})
e_man = raises(DB.build, "b2")
write_tree(BASE / "fd3", sel=True)
Uo = DB.cr_points()
Uo[7, 2] = 0.5
write_tpl(DB.CR_TPL, Uo, cr_phys(Uo), FX2["cr_tpl"])
e_tpl = raises(DB.build, "b2")
ok("D: frozen selection: a reordered CR-T list -> problem; an edited evaluated list (sha256) -> refused; a b2 manifest without the selection "
   "file -> refused ('restore it'); a CR templating file whose u13 is not the seed's point list -> refused",
   any("frozen crt list" in p for p in bd2["problems"]) and e_ev is not None and "does not match its sha256" in e_ev
   and e_man is not None and "is missing: the CR selection was frozen" in e_man
   and e_tpl is not None and "u13 is not the point list regenerated from the seed" in e_tpl, (bd2["problems"][:1], e_ev, e_man, e_tpl))

# ================================================================ E. widened counts
use(FA)
wr = b["wide"]["regions"]
ok("E: widened box: inside-old-box + alpha>45 only + m<0.5 only + both = 4096 points; the counts equal what 'select b2' wrote on the real "
   "copy (827 feasible of 4096; inside the old box 355 of 2633)",
   sum(wr[k]["n"] for k in ("inside_old_box", "alpha_gt_45_only", "m_lt_0.5_only", "alpha_gt_45_and_m_lt_0.5")) == 4096 == wr["all"]["n"]
   and wr == FX2["wide_counts"]["regions"] and b["wide"]["corner"] == FX2["wide_counts"]["corner"]
   and (wr["all"]["feasible"], wr["inside_old_box"]["feasible"], wr["inside_old_box"]["n"]) == (827, 355, 2633), wr["all"])

# ================================================================ F. dry run writes nothing; select; CLI
FF = write_tree(BASE / "ff")
h0 = tree_hash(FF)
rc, od = captured(DB.main, ["dry-run", "b2", "--root", str(FF)])
h1 = tree_hash(FF)
dj = json.loads(od.split("DRY-RUN-JSON", 1)[1])
ok("F: CLI dry-run b2 --root: exit 0, the tree is byte-identical afterwards (no job dirs, manifest, log, selection or counts file); JSON "
   "has 160 jobs, the G2 / replay / cost / CR / widened sections; the text names the CR-T list, the literal-rule check and the b1 priority",
   rc == 0 and h0 == h1 and dj["n_jobs"] == 160 and dj["per_layer"] == {"SF-1": 128, "CR-1": 32} and dj["g2"]["ok"] and dj["replay"]["ok"]
   and dj["cost"]["total"]["slot_h"] == EXP2["cost"]["total"]["slot_h"] and len(dj["crt"]) == 30 and dj["wide"] is not None
   and "CR-T list (would be written" in od and "literal rule" in od and "b1 priority now:" in od and not (FF / "logs").exists()
   and not DB.crt_file_path().exists())
rc1, os1 = captured(DB.main, ["select", "b2", "--root", str(FF)])
sel1 = json.loads(DB.crt_file_path().read_text())
wc1 = json.loads((J.RESULTS / DB.WIDE_COUNTS_FILE).read_text())
rc2, os2 = captured(DB.main, ["select", "b2", "--root", str(FF)])
w2 = json.loads((J.RESULTS / DB.WIDE_COUNTS_FILE).read_text())
w2["regions"]["all"]["n"] = 1
DB._write_json(J.RESULTS / DB.WIDE_COUNTS_FILE, w2)
e_sel = raises(DB.main, ["select", "b2", "--root", str(FF)])
e_cli = raises(DB.main, ["select", "b1", "--root", str(FF)])
ok("F: select b2 writes results/db_crt_selection.json (CR-1 32 + CR-T 30, the frozen evaluated list and its sha256) and "
   "results/db_widened_counts.json; a second select is idempotent ('unchanged'); a different existing counts file is refused; select b1 -> "
   "argparse error",
   rc1 == 0 and "wrote" in os1 and len(sel1["cr1"]) == 32 and len(sel1["crt"]) == 30 and sel1["evaluated_sha256"] == DB._ev_sha(sel1["evaluated"])
   and [x["cr_idx"] for x in sel1["crt"]] == [x["cr_idx"] for x in dj["crt"]] and not sel1["crt_submitted_in_b2"]
   and wc1["regions"] == dj["wide"]["regions"] and rc2 == 0 and os2.count("unchanged") == 2
   and e_sel is not None and "exists with different counts" in e_sel and e_cli == "2", (os1, os2, e_sel))

# ================================================================ G. feed_pass gate / per-pass cap / probe
FG = write_tree(BASE / "fg", sel=True)
bg, _ = captured(DB.build, "b2")
man_g = {"batch": "b2", "order": [r["key"] for r in bg["rows"]], "rows": {r["key"]: DB._man_row(r) for r in bg["rows"]}, "gates": {}, "events": []}
snap_g = DB.queue_snapshot()
calls_g = []
J.submit = lambda s_: calls_g.append(s_) or REAL_SUBMIT(s_)
try:
    w_g = {}
    out_g = DB.feed_pass(bg, copy.deepcopy(man_g), snap_g, lambda m: None, waits=w_g, gate=lambda: "simulated: b1 submitted meanwhile")
    w_p = {}
    out_p = DB.feed_pass(bg, copy.deepcopy(man_g), DB.queue_snapshot(), lambda m: None, waits=w_p, probe=True)
    mg2 = copy.deepcopy(man_g)
    w_c = {}
    out_c = DB.feed_pass(bg, mg2, DB.queue_snapshot(), lambda m: None, waits=w_c, max_submit=1)
finally:
    J.submit = REAL_SUBMIT
first_cr = [k for k in man_g["order"] if k.startswith("CR1_")][:2]
ok("G: feed_pass consults the gate right before each submission (gate says no -> nothing submitted, waits['gate']); probe mode returns "
   "the rows it would submit (2 SF + 2 CR: the slow-start cap per layer) without calling jobs.submit or writing anything; max_submit 1 -> "
   "exactly one submission and waits['per_pass']",
   out_g == [] and "gate" in w_g and w_g["gate"]["text"].startswith("simulated") and out_p == ["SF1_p0032", "SF1_p0033", *first_cr]
   and len(calls_g) == 1 and out_c == ["SF1_p0032"] and "per_pass" in w_c and mg2["rows"]["SF1_p0032"]["status"] == "submitted"
   and not DB.manifest_path("b2").exists(), (out_g, out_p, out_c, len(calls_g)))
# probe of a b1 pass that would halt -> ProbeHalt (not a manifest write)
FG2 = write_tree(BASE / "fg2")
bb1, _ = captured(DB.build, "b1")
add_job("other_ref_dddddddd", {**{r["key"]: r for r in bb1["rows"]}["REF_h1.94"]["spec"], "stage": "other", "tag": "x"}, "DONE")
man_b1 = {"batch": "b1", "order": [r["key"] for r in bb1["rows"]], "rows": {r["key"]: DB._man_row(r) for r in bb1["rows"]}, "gates": {}, "events": []}
keys_h, waits_h, why_h = DB.probe_pass(bb1, man_b1, DB.queue_snapshot())
ok("G: probing a b1 pass that would stop (REF_h1.94 now resolves to another id) -> probe_pass returns the reason (ProbeHalt), writes no "
   "manifest", keys_h is None and why_h is not None and "would stop here" in why_h and not DB.manifest_path("b1").exists(), why_h)

# ================================================================ H. b2 alone, b1 never started
FH = write_tree(BASE / "fh", sel=True)
rh, oh = captured(DB.feed, "b2", poll=0, once=True)
mh = json.loads(DB.manifest_path("b2").read_text())
lh = DB.log_path("b2").read_text(encoding="utf-8")
ok("H: feed b2 --once with no b1 manifest: b1 (all 84 rows pending) has priority -> nothing submitted; PRIORITY line names 'no manifest yet'; "
   "the WAIT line carries the reason; the manifest records the b2 inputs (pool / tpl sha256, frozen evaluated sha256); log is "
   "logs/db_feed_b2.log, lock logs/db_feed_b2.lock; b1's log untouched",
   rh == 0 and sum(m["status"] == "submitted" for m in mh["rows"].values()) == 0 and "PRIORITY b1 priority:" in lh and "no manifest yet" in lh
   and "WAIT idle pass 1" in lh and mh["b2"]["evaluated_sha256"] == FX2["selection"]["evaluated_sha256"] and DB.lock_path("b2").exists()
   and not DB.log_path("b1").exists(), lh[-400:])
(J.QROOT.parent / "STOP_DB_FEED_b2").write_text("x")
e_stop = raises(DB.feed, "b2", poll=0, once=True)
ok("H: STOP_DB_FEED_b2 present at start -> b2 refused", e_stop is not None and "STOP_DB_FEED_b2 exists" in e_stop, e_stop)

# ================================================================ I. two feeders on one fake queue
OKF = lambda: J.QROOT.parent / DB.H14_OK_NAME                                    # noqa: E731


class World:
    """Simulated serve / 3-slot worker / post (as in test_stage_db.py) shared by the b1 and b2 feeders. submit() checks every gate at the moment
    of submission for rows of either batch, and for b2 rows an independent b1 oracle (b1 manifest on disk + queue state): no b1 row may be
    submittable and b1 must not be down to its exclusive rows (drain)."""

    def __init__(self, b1rows, b2rows, slots=3, max_steps=400, stop_at=None):        # a normal run takes ~60-70 steps
        self.slots, self.max_steps, self.stop_at = slots, max_steps, stop_at
        self.b1 = {r["key"]: r for r in b1rows}
        self.id2 = {r["expected_id"]: ("b1", r["layer"], r["key"]) for r in b1rows}
        self.id2.update({r["expected_id"]: ("b2", r["layer"], r["key"]) for r in b2rows})
        self.refid = {float(r["spec"]["h_int"]): r["expected_id"] for r in b1rows if r["layer"] == "REF"}
        self.ref_ids = set(self.refid.values())
        self.prio_refs = [self.refid[h] for h in (1.94, 2.06, 2.5)]
        self.calls, self.viol, self.steps, self.timed_out = [], [], 0, False
        self.b2_while_b1_pending = 0
        self.lock = threading.Lock()

    def _dirs(self):
        return [d for d in sorted(J.QROOT.iterdir()) if d.is_dir()]

    @staticmethod
    def _spec(d):
        try:
            return json.loads((d / "spec.json").read_text())
        except (OSError, ValueError):
            return None

    def counts(self):
        unc, heavy, busy = 0, 0, []
        for d in self._dirs():
            s = J.state(d)
            if d.name.startswith("db_") and s in ("NEW", "READY"):
                unc += 1
            if s in ("NEW", "READY", "CLAIMED"):
                busy.append(d.name)
                if DB.is_heavy(self._spec(d)):
                    heavy += 1
        return unc, heavy, busy

    def b1_oracle(self):
        """b1 rows submittable now (independent re-statement of the b1 gates) and whether b1 is down to its exclusive rows."""
        p = DB.manifest_path("b1")
        if not p.exists():
            return ["<b1 has no manifest>"], False
        man = json.loads(p.read_text())
        unc, heavy, busy = self.counts()
        st = lambda j: J.state(J.QROOT / j)                                      # noqa: E731
        excl_id = self.refid[1.4]
        if man["rows"]["REF_h1.4"]["status"] in ("submitted", "existing") and st(excl_id) in ("NEW", "READY", "CLAIMED"):
            return ["<exclusive in flight>"], False
        pend = [k for k in man["order"] if man["rows"][k]["status"] == "pending"]
        drain = "REF_h1.4" in pend and all(k == "REF_h1.4" or k.startswith("FD0_h1.4_") for k in pend)
        prio = [k for k in ("REF_h1.94", "REF_h2.06", "REF_h2.5") if man["rows"][k]["status"] == "pending"
                or (man["rows"][k]["status"] in ("submitted", "existing") and st(man["rows"][k]["id"]) in ("NEW", "READY"))]
        other_unc = sum(1 for d in self._dirs() if d.name.startswith("db_") and d.name not in self.ref_ids and J.state(d) in ("NEW", "READY"))
        out = []
        for k in pend:
            r = self.b1[k]
            s_ = r["spec"]
            if (J.QROOT / r["expected_id"]).exists():
                continue
            if DB.needs_ref(s_) and st(s_["intact_job"]) != "DONE":
                continue
            if s_.get("kind") != "intact" and s_["h_int"] <= 1.4 and (st(excl_id) != "DONE" or not OKF().exists()):
                continue
            L = r["layer"]
            if L in DB.SLOW_START_LAYERS:
                ids = [man["rows"][x]["id"] for x in man["order"] if self.b1[x]["layer"] == L and man["rows"][x]["status"] in ("submitted", "existing")]
                sts = [st(i) for i in ids]
                if sts.count("DONE") < DB.SLOW_START_DONE and sum(x not in ("DONE", "FAILED") for x in sts) >= DB.SLOW_START_CAP:
                    continue
            if k == "REF_h1.4":
                if busy:
                    continue
            elif prio and L != "REF" and other_unc >= DB.REF_PRIORITY_CAP:
                continue
            if r["heavy"] and heavy >= 1:
                continue
            if unc >= DB.MAX_UNCLAIMED:
                continue
            out.append(k)
        return out, drain

    def submit(self, spec):
        with self.lock:
            unc, heavy, busy = self.counts()
            jid = DB.expected_id(spec)
            batch, L, key = self.id2.get(jid, ("?", "?", "?"))
            if unc >= DB.MAX_UNCLAIMED:
                self.viol.append(f"{jid}: submitted with {unc} unclaimed db jobs (global cap)")
            if DB.is_heavy(spec) and heavy >= 1:
                self.viol.append(f"{jid}: heavy submitted with {heavy} heavy in flight")
            if DB.needs_ref(spec) and J.state(J.QROOT / spec["intact_job"]) != "DONE":
                self.viol.append(f"{jid}: submitted before its reference is DONE")
            if spec.get("kind") != "intact" and spec["h_int"] <= 1.4 and (J.state(J.QROOT / self.refid[1.4]) != "DONE" or not OKF().exists()):
                self.viol.append(f"{jid}: h1.4 row before the h1.4 reference / operator file")
            if jid == self.refid[1.4] and busy:
                self.viol.append(f"{jid}: exclusive submitted with {len(busy)} jobs NEW / READY / CLAIMED")
            if J.state(J.QROOT / self.refid[1.4]) in ("NEW", "READY", "CLAIMED"):
                self.viol.append(f"{jid}: submitted while the exclusive REF_h1.4 is in flight")
            if L in DB.SLOW_START_LAYERS:
                sts = [J.state(J.QROOT / i) for i, v in self.id2.items() if v[1] == L]
                if sts.count("DONE") < DB.SLOW_START_DONE and sum(s in ("NEW", "READY", "CLAIMED", "SOLVED") for s in sts) >= DB.SLOW_START_CAP:
                    self.viol.append(f"{jid}: slow start {L}")
            if batch == "b1" and jid not in self.ref_ids:
                active = [r for r in self.prio_refs if J.state(J.QROOT / r) in ("MISSING", "NEW", "READY")]
                other = [d.name for d in self._dirs() if d.name.startswith("db_") and d.name not in self.ref_ids and J.state(d) in ("NEW", "READY")]
                if active and len(other) >= DB.REF_PRIORITY_CAP:
                    self.viol.append(f"{jid}: REF priority")
            if batch == "b2":
                sub1, drain = self.b1_oracle()
                if sub1:
                    self.viol.append(f"{jid}: b2 submitted while b1 could submit {sub1[:3]}")
                if drain:
                    self.viol.append(f"{jid}: b2 submitted while b1 was down to its exclusive rows (drain)")
                man1 = json.loads(DB.manifest_path("b1").read_text()) if DB.manifest_path("b1").exists() else {"rows": {}}
                if any(m["status"] == "pending" for m in man1["rows"].values()):
                    self.b2_while_b1_pending += 1
            self.calls.append((batch, jid, self.steps))
        return REAL_SUBMIT(spec)

    def step(self):
        self.steps += 1
        for d in self._dirs():                                                   # post
            if J.state(d) == "SOLVED":
                sp = self._spec(d)
                if sp.get("kind") in ("design", "variant") and not sp.get("fric_only") and J.state(J.QROOT / sp["intact_job"]) != "DONE":
                    continue
                (d / "result.json").write_text(json.dumps({"gruen7": 1.0, "gruen1": 1.0, "job_id": d.name}))
                (d / "DONE").write_text("x")
        for d in self._dirs():
            if J.state(d) == "CLAIMED":
                (d / "SOLVED").write_text("x")
        busy = sum(J.state(d) == "CLAIMED" for d in self._dirs())
        for d in self._dirs():
            if J.state(d) == "READY" and busy < self.slots:
                (d / "READY").rename(d / "CLAIMED")
                busy += 1
        for d in self._dirs():
            if J.state(d) == "NEW" and self._spec(d) is not None:
                (d / "READY").write_text("x")
        if J.state(J.QROOT / self.refid[1.4]) == "DONE" and not OKF().exists():
            OKF().write_text("operator read the .dat estimate")
        if self.steps >= self.max_steps:
            self.timed_out = True
            (J.QROOT.parent / DB.STOP_NAME).write_text("stop")
        if self.stop_at is not None and self.steps == self.stop_at:
            (J.QROOT.parent / DB.STOP_NAME).write_text("stop (restart test)")


class Lockstep:
    """Each feeder's sleep() waits until every active feeder has finished its pass; the last one to arrive advances the world one step.
    The passes themselves run concurrently in two threads (serialised only by the feeders' own pass mutex)."""

    def __init__(self, world, n):
        self.world, self.active, self.arrived, self.gen = world, n, 0, 0
        self.cv = threading.Condition()

    def _advance(self):
        self.world.step()
        self.arrived = 0
        self.gen += 1
        self.cv.notify_all()

    def sleep(self, _poll=0):
        with self.cv:
            self.arrived += 1
            g = self.gen
            if self.arrived >= self.active:
                self._advance()
            else:
                t0 = time.monotonic()
                while self.gen == g:
                    self.cv.wait(timeout=1.0)
                    if time.monotonic() - t0 > 300:
                        raise RuntimeError("lockstep stuck for 300 s")

    def leave(self):
        with self.cv:
            self.active -= 1
            if self.active > 0 and self.arrived >= self.active:
                self._advance()


def run_two(world, batches=("b1", "b2")):
    """Both feeders in their own threads, lockstepped with the world; returns (exit codes, exceptions, seconds)."""
    ls = Lockstep(world, len(batches))
    res, errs = {}, {}

    def run(bt):
        try:
            res[bt] = DB.feed(bt, poll=0, sleep=ls.sleep)
        except BaseException as e:                                           # noqa: BLE001 -- re-reported by the caller
            errs[bt] = e
        finally:
            ls.leave()

    J.submit = world.submit
    buf = io.StringIO()
    t0 = time.perf_counter()
    try:
        with contextlib.redirect_stdout(buf):
            ths = [threading.Thread(target=run, args=(bt,), name=bt) for bt in batches]
            for t in ths:
                t.start()
            for t in ths:
                t.join()
    finally:
        J.submit = REAL_SUBMIT
    return res, errs, time.perf_counter() - t0


DB.SF1_RANGE, DB.CR1_QUOTA, DB.CRT_QUOTA = (32, 52), (3, 2), (2, 2)          # reduced b2: 20 SF (p51 adopted) + 5 CR
try:
    FI = write_tree(BASE / "fi")
    bi1, _ = captured(DB.build, "b1")
    bi2, _ = captured(DB.build, "b2")
    world = World(bi1["rows"], bi2["rows"])
    res, errs, t_i = run_two(world)
    m1 = json.loads(DB.manifest_path("b1").read_text())
    m2 = json.loads(DB.manifest_path("b2").read_text())
    c1 = [j for bt, j, _ in world.calls if bt == "b1"]
    c2 = [j for bt, j, _ in world.calls if bt == "b2"]
    new2 = {r["expected_id"] for r in bi2["rows"] if r["dedup"] == "new"}
    l2 = DB.log_path("b2").read_text(encoding="utf-8")
    print(f"   (concurrency run: {world.steps} steps, {t_i:.0f} s; errors {errs})", flush=True)
    ok("I: two feeders (threads) on one fake queue: both exit 0, every row of b1 (84) and of the reduced b2 (25 = 20 SF incl. the adopted "
       "p51 + 5 CR) DONE; every expected id submitted exactly once (b1 84, b2 24 new; the adopted twin never); no submission outside the batches",
       res == {"b1": 0, "b2": 0} and not errs and not world.timed_out and all(m["state"] == "DONE" for m in m1["rows"].values())
       and all(m["state"] == "DONE" for m in m2["rows"].values()) and len(c1) == 84 == len(set(c1)) and set(c1) == {r["expected_id"] for r in bi1["rows"]}
       and len(c2) == len(set(c2)) == 24 and set(c2) == new2 and "sb13_a33_016e3ffa" not in c2 and all(bt in ("b1", "b2") for bt, _, _ in world.calls),
       (res, errs, len(c1), len(c2), world.steps))
    ok("I: no gate violated at any submission of either batch (global depth cap 6 over all db_*, heavy, references, h1.4 + operator file, "
       "exclusive REF_h1.4 on an idle queue and nothing beside it, slow start per layer incl. SF-1 / CR-1, REF priority), and at every b2 "
       "submission the independent b1 oracle found no b1 row submittable and no drain due",
       world.viol == [], world.viol[:4])
    allc = [j for _, j, _ in world.calls]
    pos_ = lambda j: allc.index(j) if j in allc else -1                         # noqa: E731
    i14 = pos_(world.refid[1.4])
    ok("I: real concurrency: b2 submitted while b1 still had pending rows (b1 gated: references, slow start, REF priority, operator file); "
       "REF_h1.4 went after b2 drained the queue ('draining' in the b2 log) and both FD h1.4 rows after it; PRIORITY lines logged",
       world.b2_while_b1_pending > 0 and "draining" in l2 and "PRIORITY b1 priority:" in l2 and "PRIORITY clear" in l2 and i14 >= 0
       and all(pos_(FIX["expected"]["ids"][k]) > i14 for k in ("FD0_h1.4_A", "FD0_h1.4_init29")),
       (world.b2_while_b1_pending, i14))
    ok("I: b2's manifest rows carry sf_bo_overlap / bo_twins / layer_pos / bonded_planned / unbiased / in_E; SF1_p0051 existing -> sb13_a33; "
       "the selection file was written at b2's first start (frozen evaluated list); b1's manifest has no b2 rows",
       m2["rows"]["SF1_p0051"]["status"] == "existing" and m2["rows"]["SF1_p0051"]["id"] == "sb13_a33_016e3ffa" and m2["rows"]["SF1_p0051"]["sf_bo_overlap"]
       and all(set(DB.B2_ROW_FIELDS) <= set(m) for m in m2["rows"].values()) and DB.crt_file_path().exists()
       and "wrote" in l2 and not any(k.startswith(("SF1_", "CR1_")) for k in m1["rows"]))
    # I2. restart: STOP_DB_FEED at step 20 stops both feeders cleanly; restart both; finish; nothing submitted twice; order and selection kept
    FI2 = write_tree(BASE / "fi2")
    w2 = World(bi1["rows"], bi2["rows"], stop_at=20)
    ra, ea, _ = run_two(w2)
    ma2 = json.loads(DB.manifest_path("b2").read_text())
    sel_a = DB.crt_file_path().read_bytes()
    n_a = len(w2.calls)
    (J.QROOT.parent / DB.STOP_NAME).unlink()
    w2.stop_at = None
    rb, eb, _ = run_two(w2)
    mb1, mb2 = json.loads(DB.manifest_path("b1").read_text()), json.loads(DB.manifest_path("b2").read_text())
    cc = [j for _, j, _ in w2.calls]
    ok("I2: STOP_DB_FEED at step 20 -> both feeders exit 0 with their manifests written (some rows of each still pending); restart of both "
       "-> both finish; every expected id submitted once across the two runs (b1 84 + b2 24); b2's order, expected ids and the frozen "
       "selection file are unchanged by the restart; no gate / priority violation",
       ra == {"b1": 0, "b2": 0} and rb == {"b1": 0, "b2": 0} and not ea and not eb and 0 < n_a < 108
       and any(m["status"] == "pending" for m in ma2["rows"].values())
       and len(cc) == len(set(cc)) == 108 and all(m["state"] == "DONE" for m in mb1["rows"].values())
       and all(m["state"] == "DONE" for m in mb2["rows"].values()) and mb2["order"] == ma2["order"]
       and {k: m["expected_id"] for k, m in mb2["rows"].items()} == {k: m["expected_id"] for k, m in ma2["rows"].items()}
       and DB.crt_file_path().read_bytes() == sel_a and w2.viol == [] and not w2.timed_out,
       (ra, rb, ea, eb, n_a, len(cc), w2.viol[:3]))
finally:
    for k, v in REAL_CONST.items():
        setattr(DB, k, v)

# ================================================================ J. b1 unchanged; code hash
write_tree(BASE / "fj")
bj, _ = captured(DB.build, "b1")
ok("J: b1 unchanged by the b2 code: 84 rows, the pinned expected ids of test_stage_db.py, selection reference / stratum only",
   len(bj["rows"]) == 84 and {r["key"]: r["expected_id"] for r in bj["rows"]} == FIX["expected"]["ids"]
   and {r["selection"] for r in bj["rows"]} == {"reference", "stratum"})
ok("J: jobs.code_hash() == 6d7af243d0 (the 8 hashed files untouched)", J.code_hash() == "6d7af243d0" == DB.DB_CODE_HASH == FX2["code_hash"])

# ================================================================ reset
J.QROOT, J.RESULTS = REAL_Q, REAL_R
J.submit = REAL_SUBMIT
DB.SEEDS = dict(REAL_SEEDS)
ok("fixture reset: J.QROOT / J.RESULTS back to ~/mobo_toy_v2 (never written by this test); SEEDS and the b2 sizes restored",
   J.QROOT == REAL_Q and J.RESULTS == REAL_R and DB.SEEDS == {"b1": ("db_seed_CD0.json",)} and DB.SF1_RANGE == (32, 160)
   and DB.CR1_QUOTA == (16, 16) and DB.CRT_QUOTA == (15, 15))
n_fail = sum(not c for _, c in checks)
print(f"\n{len(checks) - n_fail}/{len(checks)} checks passed in {time.perf_counter() - T_START:.0f} s")
sys.exit(1 if n_fail else 0)
