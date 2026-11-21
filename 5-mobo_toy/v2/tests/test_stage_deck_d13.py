"""Run with the repo venv: PYTHONUTF8=1 .venv-mobo/Scripts/python.exe v2/tests/test_stage_deck_d13.py
Local only: fake queues / results in the system temp dir (mobo_toy_d13_tests); J.QROOT / J.RESULTS are pointed there for every check.
No gmsh, no FE, no Abaqus, no Linux, nothing under ~/mobo_toy_v2 is read or written; single process.

Batch D13 of v2/stage_deck.py = segment D of the 50 h plan (front checks after the phase 13 / 14 arms):
A. d13_select on a synthetic finished state (phase 13 2-obj records + phase 14 3-obj records + frozen warm-start rows): F13 / F14 non-dominated
   sets, P3 = 3-obj non-dominated set of all feasible designs of both arms + the shared starting set (here P3 = the F14 designs + B, C: no
   design on P3 alone), infeasible / failed / no-bone rows excluded, the same design solved by both arms de-duplicated by x, 'already bonded'
   = a bonded ok record with sed_chg_pct and vm_p99 (a FAILED bonded record does not count), default cap 40 (2026-10-25; was 25) covers every
   uncovered design;
   when the cap bites: F13 first, then the 3 lowest-rotation F14 / P3 designs, then greedy farthest point in normalised (log10 rotation, bone
   removal) (hand-computed for cap 5 and cap 7), cap 1; sit-to-stand = (a) min rotation, (b) lowest-rotation F14 + P3 design with bone
   <= 6000 (fallback: lowest-bone F14 + P3 design with rotation < 1 deg; none -> warning), (c) P3 median bone excluding a and b;
   mesh = min rotation + F14 median bone removal (rule unchanged).
M. P3 coverage (2026-10-25 morning checkpoint: sb13_a78_b0f465da, the best design with bone <= 8 cm3 across both arms, is on neither F13 nor
   F14): a phase-13 design on P3 but on neither F13 nor F14 gets a bond_only job; earlier keys keep their ids; the representative of an F13 /
   F14 design does not change; P3 de-duplicates by x (one row per design, the phase-13 row first); phase-13 rows without bone_mm3 are not on
   P3; when the cap bites the P3 design competes in the lowest-rotation slots; (b) is drawn from F14 + P3 and never from a design that is only
   on F13; (c) is drawn from P3 only (a design on F14 that the other arm dominates in 3 objectives is not a candidate; no P3 design left ->
   warning, no (c)); an earlier D13_bond key of a P3 design is kept while the design is on P3 and stale once it is not.
N. the default cap 40 on a fresh read-only copy of the live state (fixture live_states, 2026-10-25 09:25, arms still running): nothing is
   dropped, sb13_a78_b0f465da / sb14_a25_69b437e2 / sb14_a46_6c55ace1 get bond_only picks; cap 25 would drop 9 designs on the same copy.
B. specs: bond_only specs (bond_only, no fric_only, explicit intact_job = PHASES[p]['intact_job'], everything else = source spec minus
   created / stage / tag / kind / fric_only), accepted by jobs.ref_for against a fake 3406 intact reference and by jobs.prep's fric_only / bond_only
   guard; sit-to-stand specs (fric_only, cfg.load 1714 / 3839 N at 24 / 8 deg, merged into the 3406 cfg by jobs._merge, |F| and angles by
   model3d_v2.load_vector); mesh specs (fric_only, h_int 1.94 / 2.06); all kind variant, stages d13bond / d13sts / d13mesh, no 'sb' / 'neck' /
   'ref' stage, no sb13_ / sb14_ id, not in_family of phases 10-14, never handed to stage_neckopt.record_of by dataset(), not matched by
   bo_async's adoption glob.
C. id stability: same state -> same ids; shuffled records -> same ids; an extra dominated record -> same ids; created ignored; ids unique.
D. guards: unfinished arms (pending, records < budget, queue job not DONE, DONE job not recorded) -> submit refuses and writes nothing;
   --allow-unfinished submits; source not DONE, design-space mismatch, wrong objective count, intact_job mismatch -> SystemExit.
E. dry run (function and CLI with --root): prints the job list and the DRY-RUN-JSON block, expected ids = the ids a real submit writes,
   writes nothing (file tree hash identical); CLI option errors (--root without --dry-run, status --dry-run, --allow-unfinished on another batch).
F. submit on the finished fake state: deck_D13_ids.json + job directories, ids = dry-run ids, re-submit idempotent, clash guard.
G. real snapshot (fixtures_stage_deck_d13.json, read-only copy of the Linux state at 2026-10-25 04:21, arms still running): the current rules
   give snapshot_expected_ids_v4 (32 jobs: P3 adds 8 phase-13 designs, 3 of them already bonded, so 5 new bond_only jobs; (c) = P3 median
   = sb14_a27, was sb13_a61 under F14 + P3 (v3) and sb14_a30 under F14 (v2)); every key of the P3 rules (v3, 32 jobs), of the segD_fix rules
   (snapshot_expected_ids_v2, 27 jobs) and of the first 04:21 dry run (22 jobs) that the current rules still select keeps its id;
   earlier batches SB / SBb / V3406 / SBdelta / MI reproduce the ids in their Linux deck_<batch>_ids.json
   from the same source specs (the submit / specs refactor did not change any existing id).
H. the cap bites (D.D13_BOND_CAP monkeypatched to 25 for this section, so d13_select's default and the submit path use it; with the default
   40 all 32 uncovered designs fit): both F13 designs, the 3 lowest-rotation remaining designs, then the farthest-point spread; the 7 dropped
   designs are printed by the dry run and by the real submit.
I. cumulative submissions: earlier D13_bond keys are matched to designs by the source job's x (also when the source is the other arm's job of
   the same design), kept (same key, same id) or stale, and counted against the cap; a source in no state file -> SystemExit; a real submit
   with new keys refuses without --reselect (prints new and stale keys, writes nothing); --reselect adds them; no design is bonded twice.
J. warnings and the one-line summary are printed on the real submit path; a warm-start id missing from the phase-13 records -> SystemExit;
   a bonded ok record without sed_chg_pct / vm_p99 is warned about and its design is not covered.
K. one submit / dry-run call reads each state file once and selects once.
L. dry-run 'variant' column = diff vs the source spec.json; the --allow-unfinished help / warning / refusal carry the queue-order note.
"""
import contextlib
import copy
import hashlib
import io
import json
import math
import pathlib
import random
import runpy
import shutil
import sys
import tempfile
import time

ROOT = pathlib.Path(r"H:/projects/Femoral implant generation/sandbox/mobo_toy")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "v2"))
BASE = pathlib.Path(tempfile.gettempdir()) / "mobo_toy_d13_tests"            # fake trees outside the repo and outside ~/mobo_toy_v2
shutil.rmtree(BASE, ignore_errors=True)
BASE.mkdir(parents=True)
FIX = json.loads((ROOT / "v2" / "tests" / "fixtures_stage_deck_d13.json").read_text(encoding="utf-8"))

import jobs as J  # noqa: E402
import stage_neckopt as N  # noqa: E402
import stage_deck as D  # noqa: E402

T_START = time.perf_counter()
REAL_Q, REAL_R = J.QROOT, J.RESULTS
checks = []


def ok(name, cond, extra=""):
    checks.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""), flush=True)


def use(root: pathlib.Path):
    J.QROOT, J.RESULTS = root / "queue", root / "results"
    J.QROOT.mkdir(parents=True, exist_ok=True)
    J.RESULTS.mkdir(parents=True, exist_ok=True)


def tree_hash(root: pathlib.Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        h.update(p.relative_to(root).as_posix().encode())
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()


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


def dry_json(out: str) -> dict:
    return json.loads(out.split("DRY-RUN-JSON", 1)[1])


# ================================================================ synthetic finished state
P13, P14 = N.Phase(13), N.Phase(14)
INTACT = N.PHASES[13]["intact_job"]
NV = len(P13.vars)
rng = random.Random(1234)
SPACE = {k: list(v) for k, v in P13.space.items()}


def xvec():
    return [round(rng.random(), 6) for _ in range(NV)]


def rec(job, x, rot, area, bone, phase, ok_=True, c=-1.0, bonded=False, round_=1):
    if not ok_:
        y = [math.nan] * (2 if phase == 13 else 3)
    else:
        y = [math.log10(max(rot, N.ROT_FLOOR)), -area] + ([bone] if phase == 14 else [])
    return {"job_id": job, "x": list(x), "y": y, "c": [c if ok_ else math.nan], "ok": ok_, "bonded": bonded, "fric_only": not bonded,
            "bone_mm3": bone, "rot_first_deg": rot if ok_ else None, "contact_area_load2_mm2": area if ok_ else None, "round": round_,
            "pool_idx": None, "vm_p99": 300.0 if bonded and ok_ else None, "sed_chg_pct": -10.0 if bonded and ok_ else None}


X = {k: xvec() for k in ("A", "B", "C", "D", "E", "G", "W1", "W2", "W3", "P1", "P2", "P5", "P6", "P7", "P8", "P9")}
JOB = {"A13": "sb13_a1_aaaa0001", "B13": "sb13_a2_bbbb0002", "C13": "sb13_a3_cccc0003", "D13": "sb13_a4_dddd0004", "E13": "sb13_a5_eeee0005",
       "G13": "sb13_a6_gggg0006", "W1": "sb13_init_11110001", "W2": "sb13_init_22220002", "W3": "sb13_init_33330003",
       "P1": "sb14_a1_p1p10001", "P2": "sb14_a2_p2p20002", "P3": "sb14_a3_p3p30003", "P4": "sb14_a4_p4p40004", "P5": "sb14_a5_p5p50005",
       "P6": "sb14_a6_p6p60006", "P7": "sb14_a7_p7p70007", "P8": "sb14_a8_p8p80008", "P9": "sb14_a9_p9p90009", "P10": "sb14_a10_pa000010"}
R13 = [rec(JOB["A13"], X["A"], 0.05, 2200, 8500, 13),
       rec(JOB["B13"], X["B"], 0.06, 2300, 9000, 13),
       rec(JOB["C13"], X["C"], 0.04, 2000, 9900, 13, bonded=True),                  # F13, already bonded -> no new job
       rec(JOB["D13"], X["D"], 0.20, 1500, 6000, 13),                               # dominated in 2-obj
       rec(JOB["E13"], X["E"], None, None, None, 13, ok_=False),                    # FAILED
       rec(JOB["G13"], X["G"], 0.01, 3000, 9500, 13, c=0.5, bonded=True),          # infeasible (vM over the limit): never on a front
       rec(JOB["W1"], X["W1"], 0.5, 900, 3000, 13, round_=0),
       rec(JOB["W2"], X["W2"], 1.0, 600, 3500, 13, round_=0),
       rec(JOB["W3"], X["W3"], 0.3, 1000, None, 13, round_=0)]                     # no bone: infeasible as a v4 warm row
R14 = [rec(JOB["P1"], X["P1"], 0.10, 1800, 6500, 14),
       rec(JOB["P2"], X["P2"], 2.00, 300, 2500, 14),
       rec(JOB["P3"], X["A"], 0.05, 2200, 8500, 14),                                # = design A solved again by the phase 14 arm
       rec(JOB["P4"], X["D"], 0.20, 1500, 6000, 14, bonded=True),                   # = design D, bonded in phase 14 -> D covered
       rec(JOB["P5"], X["P5"], 0.30, 1200, 7000, 14),                               # dominated by P1
       rec(JOB["P6"], X["P6"], 0.15, 1600, 7200, 14),                               # dominated by P1
       rec(JOB["P7"], X["P7"], 0.08, 1900, 7800, 14),
       rec(JOB["P8"], X["P8"], 0.70, 800, 2800, 14),
       rec(JOB["P9"], X["P9"], 0.25, 1400, 5000, 14),
       rec(JOB["P10"], X["B"], None, None, None, 14, ok_=False, bonded=True)]       # = design B, bonded but FAILED -> B not covered


def state(phase, records, warm=(), pending=None, budget=None):
    return {"phase": phase, "mode": "async", "space": copy.deepcopy(SPACE), "fixed": dict(P13.fixed), "sed": "none", "budget": budget or len(records),
            "records": copy.deepcopy(records), "pending": pending or {}, "warm_start_ids": list(warm), "stage": f"sb{phase}",
            "intact_job": INTACT, "femur_id": "sawbone3406", "neck_axis": "isthmus", "mm_limit": None, "updated": "2026-10-25 12:00:00"}


ST13 = state(13, R13)
ST14 = state(14, R14, warm=[JOB["W1"], JOB["W2"], JOB["W3"]])


def write_tree(root, st13, st14, states=None):
    shutil.rmtree(root, ignore_errors=True)
    use(root)
    states = states or {}
    for st, ph in ((st13, P13), (st14, P14)):
        for r in st["records"]:
            d = J.QROOT / r["job_id"]
            d.mkdir(parents=True, exist_ok=True)
            sp = ph.spec_of(r["x"], r["job_id"].split("_")[1], bonded=bool(r["bonded"]))
            (d / "spec.json").write_text(json.dumps({**sp, "created": "2026-10-25 01:00:00"}, indent=1))
            s_ = states.get(r["job_id"], "DONE" if r["ok"] else "FAILED")
            if s_:
                (d / ("FAILED.json" if s_ == "FAILED" else s_)).write_text("{}")
        (J.RESULTS / f"neckopt_p{st['phase']}.json").write_text(json.dumps(st, indent=1))
    ref = J.QROOT / INTACT                                                        # fake 3406 intact reference (for jobs.ref_for)
    ref.mkdir(parents=True, exist_ok=True)
    (ref / "spec.json").write_text(json.dumps({"kind": "intact", "h_int": 2.0, "stage": "sb", "tag": "intact_h2", "femur_id": "sawbone3406",
                                               "neck_axis": "isthmus", "created": "x"}))
    (ref / "result.json").write_text(json.dumps({"gruen7": 1.0, "gruen1": 1.0}))
    (ref / "DONE").write_text("x")


FIN = BASE / "finished"
write_tree(FIN, ST13, ST14)

# ================================================================ A. selection
sel, _ = captured(D.d13_select, ST13, ST14)
ids_of = lambda es: [e["job_id"] for e in es]                                    # noqa: E731
ok("F13 = {C13, A13, B13} by rotation (dominated D13, FAILED E13, infeasible G13, init rows excluded)",
   ids_of(sel["F13"]) == [JOB["C13"], JOB["A13"], JOB["B13"]], ids_of(sel["F13"]))
f14 = sorted(ids_of(sel["F14"]))
exp14 = sorted([JOB[k] for k in ("P1", "P2", "P3", "P4", "P7", "P8", "P9", "W1")])
ok("F14 = own ND rows + warm W1 (W2 dominated, W3 has no bone, P5 / P6 dominated, FAILED P10 out)", f14 == exp14, f14)
ok("F14 listed by bone removal", [e["bone_mm3"] for e in sel["F14"]] == sorted(e["bone_mm3"] for e in sel["F14"]))
ok("10 distinct designs (A on both fronts counted once)", sel["n_designs"] == 10, sel["n_designs"])
p3_ids = sorted(ids_of(sel["P3"]))
exp_p3 = sorted([JOB[k] for k in ("A13", "B13", "C13", "D13", "P1", "P2", "P7", "P8", "P9", "W1")])
ok("P3 = the F14 designs + B, C (3-obj ND over both arms + the starting set); designs solved by both arms listed once by their phase-13 row "
   "(A13 not P3-job, D13 not P4); W2 / P5 / P6 dominated, W3 (no bone), G13 (infeasible), FAILED E13 / P10 out; no design on P3 alone",
   p3_ids == exp_p3 and sel["n_p3_only"] == 0, p3_ids)
ok("P3 listed by bone removal", [e["bone_mm3"] for e in sel["P3"]] == sorted(e["bone_mm3"] for e in sel["P3"]))
ok("already bonded = C (bonded F13 record) and D (its bonded phase-14 twin P4 is on F14); FAILED bonded P10 does not cover B",
   sorted(ids_of(sel["covered"])) == sorted([JOB["C13"], JOB["P4"]]), ids_of(sel["covered"]))
cov_d = next(e for e in sel["covered"] if e["job_id"] == JOB["P4"])
ok("design D: representative = its F14 row P4 (P3 lists its phase-13 twin D13 but does not change the representative), bonded_jobs = [P4], "
   "fronts F14+P3", cov_d["bonded_jobs"] == [JOB["P4"]] and cov_d["fronts"] == ["F14", "P3"], cov_d)
a_e = next(e for e in sel["bond"] if e["job_id"] == JOB["A13"])
ok("design A (both arms): one entry, representative sb13 job, fronts F13+F14+P3", a_e["fronts"] == ["F13", "F14", "P3"]
   and JOB["P3"] not in ids_of(sel["bond"]), a_e)
ok("default cap 40 (2026-10-25, was 25): all 8 uncovered front designs get a bond_only job (F13 first, then by rotation), none dropped",
   D.D13_BOND_CAP == 40 and sel["bond_cap"] == 40 and sel["bond_slots"] == 40 and not sel["bond_left_out"]
   and ids_of(sel["bond"]) == [JOB[k] for k in ("A13", "B13", "P7", "P1", "P9", "W1", "P8", "P2")]
   and not ({JOB["C13"], JOB["D13"], JOB["P4"]} & set(ids_of(sel["bond"]))), ids_of(sel["bond"]))
ok("no earlier D13 submission: nothing kept, nothing stale", sel["bond_kept"] == [] and sel["bond_stale"] == [] and sel["n_prior_bond"] == 0)
s5, _ = captured(D.d13_select, ST13, ST14, bond_cap=5)
ok("cap 5: F13 first (A, B by rotation), then the 3 lowest-rotation remaining designs: P7 (0.08), P1 (0.10), P9 (0.25)",
   ids_of(s5["bond"]) == [JOB["A13"], JOB["B13"], JOB["P7"], JOB["P1"], JOB["P9"]], ids_of(s5["bond"]))
ok("cap 5: dropped = W1, P8, P2 (by rotation)", ids_of(s5["bond_left_out"]) == [JOB["W1"], JOB["P8"], JOB["P2"]], ids_of(s5["bond_left_out"]))
s7, _ = captured(D.d13_select, ST13, ST14, bond_cap=7)
# by hand, normalised over the 10 front designs: log10 rot -1.398 (C) .. 0.301 (P2), bone 2500 (P2) .. 9900 (C); anchors C, D, A, B, P7, P1, P9.
# nearest-anchor distance: P2 0.630 (to P9), P8 0.397, W1 0.323 -> P2; then W1 0.323 (P9), P8 0.271 (P2) -> W1; P8 dropped
ok("cap 7: the 2 slots after F13 + 3 by rotation go by farthest point in (log10 rotation, bone): P2 then W1; P8 dropped",
   ids_of(s7["bond"]) == [JOB[k] for k in ("A13", "B13", "P7", "P1", "P9", "P2", "W1")] and ids_of(s7["bond_left_out"]) == [JOB["P8"]],
   ids_of(s7["bond"]) + ids_of(s7["bond_left_out"]))
s1, _ = captured(D.d13_select, ST13, ST14, bond_cap=1)
ok("cap 1: only the lowest-rotation uncovered F13 design (A); 7 left out", ids_of(s1["bond"]) == [JOB["A13"]] and len(s1["bond_left_out"]) == 7)
ok("sit-to-stand = (a) min rotation C13 (bonded or not), (b) lowest-rotation F14 + P3 design with bone <= 6000 = D (P4, 0.20 deg, 6000; A / B / "
   "P7 / P1 have more bone), (c) P3 median bone removal without a and b = P9 (5000 of 2500..9000, 8 designs incl. B; every F14 design is on P3 "
   "here)",
   ids_of(sel["sts"]) == [JOB["C13"], JOB["P4"], JOB["P9"]] and [e["role"] for e in sel["sts"]] == ["a", "b", "c"], ids_of(sel["sts"]))
sb_, _ = captured(D.d13_select, ST13, ST14, sts_bone_max=2000.0)
ok("sit-to-stand (b) fallback (no F14 + P3 design with bone <= 2000): lowest-bone F14 + P3 design with rotation < 1 deg = P8 (2800; P2 2500 has "
   "2 deg); (c) = D (median of the 8 P3 designs other than a and b)", ids_of(sb_["sts"]) == [JOB["C13"], JOB["P8"], JOB["P4"]] and "rotation < 1" in sb_["sts"][1]["rule"],
   ids_of(sb_["sts"]))
sn_, _ = captured(D.d13_select, ST13, ST14, sts_bone_max=2000.0, sts_rot_max=0.01)
ok("sit-to-stand without any (b): warned, sit-to-stand = a + c (c = median of the 9 P3 designs other than a: the 8 F14 designs + B -> D, 6000)",
   ids_of(sn_["sts"]) == [JOB["C13"], JOB["P4"]] and [e["role"] for e in sn_["sts"]] == ["a", "c"]
   and any(w.startswith("sit-to-stand (b)") for w in sn_["warnings"]), ids_of(sn_["sts"]))
lo14 = copy.deepcopy(ST14)                                                       # (b) never repeats (a): make the min-rotation design a low-bone F14 one
lo14["records"].append(rec("sb14_a13_pd000013", xvec(), 0.02, 900, 2000, 14))
s_lo, _ = captured(D.d13_select, ST13, lo14)
ok("sit-to-stand (a) = a low-bone F14 design (0.02 deg, 2000 mm3) -> (b) is the next F14 design with bone <= 6000, not (a) again",
   ids_of(s_lo["sts"])[:2] == ["sb14_a13_pd000013", JOB["P4"]] and len(set(ids_of(s_lo["sts"]))) == 3, ids_of(s_lo["sts"]))
ok("mesh = min rotation (C) + F14 median bone removal (P9, 5000 of 2500..8500)", ids_of(sel["mesh"]) == [JOB["C13"], JOB["P9"]], ids_of(sel["mesh"]))
ok("no warnings on the clean synthetic state", sel["warnings"] == [], sel["warnings"])
st13_none = copy.deepcopy(ST13)
st13_none["records"][1]["bonded"] = None
s_n, _ = captured(D.d13_select, st13_none, ST14)
ok("a record with bonded None is warned about and counted as not bonded", any("bonded None" in w for w in s_n["warnings"])
   and JOB["B13"] in ids_of(s_n["bond"]))

# ================================================================ B. specs
use(FIN)
sp, out_sp = captured(D.specs, "D13")
keys = sorted(sp)
ok("D13 specs: 8 bond + 3 x 2 sit-to-stand + 2 x 2 mesh = 18", len(sp) == 18 and sum(k.startswith("D13_bond_") for k in sp) == 8
   and sum(k.startswith("D13_sts_") for k in sp) == 6 and sum(k.startswith("D13_mesh_") for k in sp) == 4, len(sp))
src_of = lambda s: json.loads((J.QROOT / s["source_job"] / "spec.json").read_text())   # noqa: E731
DROP = set(D.D13_DROP)
bond = {k: v for k, v in sp.items() if k.startswith("D13_bond_")}
bad_b = []
for k, s in bond.items():
    src = src_of(s)
    base = {kk: vv for kk, vv in src.items() if kk not in DROP}
    extra = {kk: vv for kk, vv in s.items() if kk not in base}
    if {kk: s[kk] for kk in base} != base:
        bad_b.append(f"{k}: source keys changed")
    if extra != {"kind": "variant", "stage": "d13bond", "tag": D._d13_tag(s["source_job"]), "bond_only": True, "intact_job": INTACT,
                 "source_job": s["source_job"], "gate": "segD"}:
        bad_b.append(f"{k}: extra keys {sorted(extra)}")
    if "fric_only" in s or s.get("femur_id") != "sawbone3406" or s.get("neck_axis") != "isthmus" or s.get("h_int") != 2.0 or s.get("model") != "m1":
        bad_b.append(f"{k}: fric_only / femur / mesh / model")
ok("bond_only specs = source spec minus created/stage/tag/kind/fric_only/intact_job + bond_only, intact_job PHASES[p], kind variant, d13bond",
   not bad_b, bad_b[:3])
srcs_bonded = [JOB[k] for k in ("C13", "D13", "P4")]
ok("no bond_only spec for an already bonded design (C, D); bonded sources are never re-bonded", not any(s["source_job"] in srcs_bonded for s in bond.values()))
ref_ok = []
for s in bond.values():
    try:
        r_ = J.ref_for(s)
        ref_ok.append(r_.get("intact_job") == INTACT)
    except Exception as e_:                                                      # noqa: BLE001
        ref_ok.append(f"{type(e_).__name__}: {e_}")
ok("jobs.ref_for accepts every bond_only spec (explicit 3406 intact_job, same femur) - the post path's reference lookup", all(x is True for x in ref_ok), ref_ok[:2])
guard = [bool(s.get("fric_only")) and (bool(s.get("bond_only")) or s.get("model") != "m1") for s in sp.values()]
ok("jobs.prep's guard 'fric_only needs model m1 and excludes bond_only' passes for all 18", not any(guard))
sts = {k: v for k, v in sp.items() if k.startswith("D13_sts_")}
import femur_3406 as F3  # noqa: E402
import model3d_v2 as MV  # noqa: E402
bad_s = []
for k, s in sts.items():
    src = src_of(s)
    base = {kk: vv for kk, vv in src.items() if kk not in DROP}
    L = s["cfg"]["load"]
    if {kk: s[kk] for kk in base} != base or not s.get("fric_only") or s.get("bond_only") or "intact_job" in s or s["stage"] != "d13sts":
        bad_s.append(f"{k}: keys")
    lc = "F1714" if "_F1714_" in k else "F3839"
    if L != D.D13_STS[lc] or set(s["cfg"]) != {"load"}:
        bad_s.append(f"{k}: cfg {s['cfg']}")
    cfg = F3.load_cfg("isthmus")
    J._merge(cfg, s["cfg"])                                                      # the same merge jobs.femur_for applies (KeyError on unknown keys)
    F = MV.load_vector(cfg)
    mag = math.sqrt(float(F @ F))
    af = math.degrees(math.atan(abs(F[0]) / abs(F[2])))
    asg = math.degrees(math.atan(abs(F[1]) / abs(F[2])))
    if abs(mag - L["resultant_N"]) > 1e-6 or abs(af - 24.0) > 1e-9 or abs(asg - 8.0) > 1e-9 or F[2] >= 0:
        bad_s.append(f"{k}: |F| {mag:.3f} front {af:.4f} sagit {asg:.4f}")
    if s.get("torque", True) is not True:
        bad_s.append(f"{k}: torque")
ok("sit-to-stand specs: fric_only, cfg.load {1714, 3839} N 24 / 8 deg merged into the 3406 cfg, |F| and angles exact, head force downward",
   not bad_s and len(sts) == 6, bad_s[:3])
ok("sit-to-stand loads: 1714 = AVER75 1600 x 2391 / 2232 (same scaling as the stair load), 3839 = HIGH100",
   abs(1600 * 2391 / 2232 - 1714) < 1.0 and D.D13_STS["F3839"]["resultant_N"] == 3839.0)
mesh = {k: v for k, v in sp.items() if k.startswith("D13_mesh_")}
bad_m = [k for k, s in mesh.items() if not s.get("fric_only") or s.get("bond_only") or s["h_int"] not in (1.94, 2.06) or s["stage"] != "d13mesh"
         or {kk: vv for kk, vv in s.items() if kk not in ("kind", "stage", "tag", "fric_only", "h_int", "source_job", "gate")}
         != {kk: vv for kk, vv in src_of(s).items() if kk not in DROP | {"h_int"}}]
ok("mesh specs: fric_only, h_int 1.94 / 2.06, rest = source", not bad_m and len(mesh) == 4, bad_m)
jids = {k: J.job_id({**v, "created": ""}) for k, v in sp.items()}
ok("every D13 spec: kind variant, stage in d13bond / d13sts / d13mesh (no sb / neck / ref), id not sb13_ / sb14_",
   all(v["kind"] == "variant" and v["stage"] in ("d13bond", "d13sts", "d13mesh") and not v["stage"].startswith(("sb", "neck")) and v["stage"] != "ref"
       for v in sp.values()) and not any(j.startswith(("sb13_", "sb14_", "sb")) for j in jids.values()))
fam = [(k, p) for k, v in sp.items() for p in (10, 11, 12, 13, 14) if N.Phase(p).in_family(v)]
ok("no D13 spec is in_family of phases 10-14", not fam, fam[:3])
_, _ = captured(D.submit, "D13")                                                 # finished state: real submit into the fake queue
for j in jids.values():                                                          # pretend they were solved: dataset() only looks at DONE jobs
    (J.QROOT / j / "DONE").write_text("x")
asked = []
_rec = N.record_of
N.record_of = lambda job, *a, **k: (asked.append(job), {"y": [math.nan] * 3, "c": [math.nan], "ok": False})[1]
try:
    for p in (13, 14):
        captured(N.dataset, N.Phase(p))
finally:
    N.record_of = _rec
ok("stage_neckopt.dataset (phases 13 / 14) never hands a D13 job to record_of", asked and not any(j.startswith("d13") for j in asked), asked[:3])
adopt = [d.name for p in (13, 14) for d in J.QROOT.glob(f"sb{p}_*") if d.name in jids.values()]
ok("bo_async's adoption glob sb13_* / sb14_* matches no D13 job", not adopt and all((J.QROOT / j / "spec.json").exists() for j in jids.values()))

# ================================================================ C. id stability
sp2, _ = captured(D.specs, "D13")
ok("same state -> same specs and ids", sp2 == sp and {k: J.job_id({**v, "created": ""}) for k, v in sp2.items()} == jids)
sh13, sh14 = copy.deepcopy(ST13), copy.deepcopy(ST14)
random.Random(7).shuffle(sh13["records"])
random.Random(8).shuffle(sh14["records"])
SHUF = BASE / "shuffled"
write_tree(SHUF, sh13, sh14)
sp3, _ = captured(D.specs, "D13")
ok("shuffled record order -> same keys and ids", {k: J.job_id({**v, "created": ""}) for k, v in sp3.items()} == jids)
ex14 = copy.deepcopy(ST14)
ex14["records"].append(rec("sb14_a11_pb000011", xvec(), 0.9, 500, 9000, 14))
ex14["budget"] = len(ex14["records"])
EXTRA = BASE / "extra"
write_tree(EXTRA, ST13, ex14)
sp4, _ = captured(D.specs, "D13")
ok("an extra dominated record -> same keys and ids", {k: J.job_id({**v, "created": ""}) for k, v in sp4.items()} == jids)
one = next(iter(sp.values()))
ok("job id ignores 'created'", J.job_id({**one, "created": "a"}) == J.job_id({**one, "created": "b"}) == J.job_id(one))
ok("all 18 ids distinct; tags carry the arm (p13_ / p14_)", len(set(jids.values())) == 18 and all(v["tag"].startswith(("p13_", "p14_")) for v in sp.values()))
use(FIN)

# ================================================================ D. guards
UNF = BASE / "unfinished"
u13 = state(13, R13, pending={"sb13_a7_hhhh0007": {"pool_idx": 1, "x": xvec(), "bonded": False}}, budget=len(R13) + 1)
write_tree(UNF, u13, ST14)
pj = J.QROOT / "sb13_a7_hhhh0007"
pj.mkdir()
(pj / "spec.json").write_text(json.dumps({**P13.spec_of(xvec(), "a7", bonded=False), "created": "x"}))
(pj / "CLAIMED").write_text("x")
h0 = tree_hash(UNF)
msg = raises(D.submit, "D13")
ok("unfinished (pending + records < budget + CLAIMED job): submit refuses, mentions all three, writes nothing",
   msg and "not finished" in msg and "pending" in msg and "< budget" in msg and "CLAIMED" in msg and tree_hash(UNF) == h0, (msg or "")[:200])
_, out_u = captured(D.submit, "D13", dry=True)
ok("unfinished: dry run warns and still lists the jobs, writes nothing", "WARNING: the phase 13 / 14 arms have not finished" in out_u
   and dry_json(out_u)["n_jobs"] == 18 and tree_hash(UNF) == h0)
STALE = BASE / "stale"
write_tree(STALE, ST13, ST14)
sj = J.QROOT / "sb14_a12_pc000012"
sj.mkdir()
(sj / "spec.json").write_text(json.dumps({**P14.spec_of(xvec(), "a12", bonded=False), "created": "x"}))
(sj / "DONE").write_text("x")
msg = raises(D.submit, "D13")
ok("a DONE sb14_ job missing from the records (stale state file) -> refuse", msg and "not in the state file's records" in msg, (msg or "")[:160])
_, out_a = captured(D.submit, "D13", allow_unfinished=True)
ok("--allow-unfinished submits anyway (and says so)", "--allow-unfinished" in out_a and (J.RESULTS / "deck_D13_ids.json").exists())
ND = BASE / "notdone"
write_tree(ND, ST13, ST14, states={JOB["A13"]: "SOLVED"})
msg = raises(D.specs, "D13")
ok("selected source not DONE -> SystemExit 'is not DONE'", msg and "is not DONE" in msg and JOB["A13"] in msg, msg)
bad_sp = copy.deepcopy(ST14)
bad_sp["space"][P13.vars[0]] = [0.0, 1.0]
ok("design spaces differ -> SystemExit", "different design spaces" in (raises(D.d13_select, ST13, bad_sp) or ""))
bad_y = copy.deepcopy(ST14)
bad_y["records"][0]["y"] = bad_y["records"][0]["y"][:2]
ok("phase-14 record with 2 objectives -> SystemExit", "wrong number of objectives" in (raises(D.d13_select, ST13, bad_y) or ""))
ok("state file of the wrong phase -> SystemExit", "holds phase" in (raises(D.d13_select, ST14, ST14) or ""))
IJ = BASE / "intact_mismatch"
ij14 = copy.deepcopy(ST14)
ij14["intact_job"] = "sb_intact_h2_00000000"
write_tree(IJ, ST13, ij14)
ok("state file intact_job != PHASES[14]['intact_job'] -> SystemExit", "intact_job" in (raises(D.specs, "D13") or ""))
EMPTY = BASE / "empty"
e13, e14 = state(13, [rec("sb13_a1_zz000001", xvec(), None, None, None, 13, ok_=False)]), state(14, [])
ok("no feasible front design -> SystemExit", "no feasible design" in (raises(D.d13_select, e13, e14) or ""))
use(FIN)

# ================================================================ E. dry run (function + CLI)
DRY = BASE / "dry"
write_tree(DRY, ST13, ST14)
h0 = tree_hash(DRY)
_, out_d = captured(D.submit, "D13", dry=True)
jd = dry_json(out_d)
exp_ids = {k: J.job_id({**v, "created": ""}) for k, v in sp.items()}
ok("dry run (function): 18 rows, expected ids = the spec ids, every row has source job / variant / stage / tag, queue 'absent', writes nothing",
   jd["n_jobs"] == 18 and {r["key"]: r["expected_id"] for r in jd["jobs"]} == exp_ids
   and all(r["source_job"] and r["variant"] and r["stage"] and r["tag"] and r["queue"] == "absent" for r in jd["jobs"]) and tree_hash(DRY) == h0)
SUMMARY0 = "D13 selection: F13 3, F14 8, P3 10 (0 on neither F13 nor F14), 10 distinct designs"
ok("dry run lists F13 / F14 / P3 / already bonded / earlier D13 / stale / picks / dropped / sit-to-stand / mesh sections and the summary line",
   all(s_ in out_d for s_ in ("F13 = ", "F14 = ", "P3 = ", "already bonded", "covered by an earlier D13 submission", "stale D13 bond keys",
                              "bond_only picks", "dropped by the cap", "sit-to-stand: 3 contrasting designs", "mesh noise", SUMMARY0)), out_d[-400:])
vrow = {r["key"]: r["variant"] for r in jd["jobs"]}
ok("variant column, bond_only (source fric_only): diff vs the source spec.json only",
   vrow[D.D13_BOND_PREFIX + JOB["A13"]] == f"bond_only absent -> True, fric_only True -> absent, intact_job absent -> {INTACT}",
   vrow[D.D13_BOND_PREFIX + JOB["A13"]])
ok("variant column, mesh (source fric_only): 'h_int 2.0 -> 1.94' only", vrow[f"D13_mesh_h1.94_{JOB['P9']}"] == "h_int 2.0 -> 1.94",
   vrow[f"D13_mesh_h1.94_{JOB['P9']}"])
ok("variant column, mesh on a bonded source (C13): fric_only added, intact_job removed, h_int changed",
   vrow[f"D13_mesh_h2.06_{JOB['C13']}"] == f"fric_only absent -> True, h_int 2.0 -> 2.06, intact_job {INTACT} -> absent", vrow[f"D13_mesh_h2.06_{JOB['C13']}"])
ok("variant column, sit-to-stand: the cfg.load keys and load_case only",
   vrow[f"D13_sts_F1714_{JOB['P9']}"] == ("cfg.load.alpha_front_deg absent -> 24.0, cfg.load.alpha_sagit_deg absent -> 8.0, "
                                          "cfg.load.resultant_N absent -> 1714.0, load_case absent -> sit_to_stand"), vrow[f"D13_sts_F1714_{JOB['P9']}"])
ok("variant column ignores created / stage / tag / kind / gate / source_job", not any(w in v for v in vrow.values()
                                                                                   for w in ("created", "stage", "tag ", "kind", "gate", "source_job")))


def cli(argv):
    saved = sys.argv, J.QROOT, J.RESULTS
    sys.argv = ["stage_deck.py"] + argv
    try:
        try:
            _, o = captured(runpy.run_path, str(ROOT / "v2" / "stage_deck.py"), run_name="__main__")
            return 0, o
        except SystemExit as e:
            return e.code, ""
    finally:
        sys.argv, J.QROOT, J.RESULTS = saved


error_buf = io.StringIO()
with contextlib.redirect_stderr(error_buf):
    rc, o = cli(["submit", "D13", "--dry-run", "--root", str(DRY)])
    ok("CLI 'submit D13 --dry-run --root <copy>': exit 0, same ids, writes nothing", rc == 0 and {r["key"]: r["expected_id"] for r in dry_json(o)["jobs"]} == exp_ids
       and tree_hash(DRY) == h0, rc)
    ok("after the CLI run J.QROOT is back to the test's own tree (cli() restores what --root changed)", J.QROOT == DRY / "queue")
    rc, _ = cli(["submit", "D13", "--root", str(DRY)])
    ok("CLI --root without --dry-run -> argparse error (exit 2), nothing written", rc == 2 and tree_hash(DRY) == h0, rc)
    rc, _ = cli(["status", "D13", "--dry-run"])
    ok("CLI status --dry-run -> argparse error", rc == 2, rc)
    rc, _ = cli(["submit", "SB", "--allow-unfinished", "--dry-run", "--root", str(DRY)])
    ok("CLI --allow-unfinished on another batch -> argparse error", rc == 2, rc)
    rc, _ = cli(["submit", "D99"])
    ok("CLI unknown batch -> argparse error", rc == 2, rc)
    rc, _ = cli(["submit", "SB", "--reselect", "--dry-run", "--root", str(DRY)])
    ok("CLI --reselect on another batch -> argparse error", rc == 2, rc)
    rc, _ = cli(["status", "D13", "--reselect"])
    ok("CLI status --reselect -> argparse error", rc == 2, rc)

# ================================================================ F. submit on the finished state
SUB = BASE / "submit"
write_tree(SUB, ST13, ST14)
_, out_s = captured(D.submit, "D13")
idsf = json.loads((J.RESULTS / "deck_D13_ids.json").read_text())["jobs"]
ok("submit: deck_D13_ids.json = the dry-run ids; one job directory with spec.json per id", idsf == exp_ids
   and all((J.QROOT / j / "spec.json").exists() for j in idsf.values()))
on_disk = json.loads((J.QROOT / idsf[next(k for k in idsf if k.startswith("D13_bond_"))] / "spec.json").read_text())
ok("submitted spec = built spec + created (J.submit), bond_only and intact_job on disk", on_disk.get("bond_only") is True and on_disk.get("intact_job") == INTACT
   and "created" in on_disk)
h1 = tree_hash(J.QROOT)
_, _ = captured(D.submit, "D13")
ok("re-submit: same ids, no new job directories", json.loads((J.RESULTS / "deck_D13_ids.json").read_text())["jobs"] == exp_ids
   and tree_hash(J.QROOT) == h1)
f_ = J.RESULTS / "deck_D13_ids.json"
bad = json.loads(f_.read_text())
k0 = next(iter(bad["jobs"]))
bad["jobs"][k0] = "d13bond_wrong_00000000"
f_.write_text(json.dumps(bad))
msg = raises(D.submit, "D13")
ok("clash guard: a changed id for an existing key -> refuse", msg and "spec changed for existing keys" in msg, (msg or "")[:120])
_, out_c = captured(D.submit, "D13", dry=True)
ok("dry run shows the clash instead of refusing", "CLASH (submit would refuse)" in out_c and dry_json(out_c)["clash"].get(k0))

# ================================================================ G. real snapshot + earlier batches
SNAP = BASE / "snapshot"
shutil.rmtree(SNAP, ignore_errors=True)
use(SNAP)
for p in ("13", "14"):
    (J.RESULTS / f"neckopt_p{p}.json").write_text(json.dumps(FIX["snapshot_states"][p]))
for j, s in FIX["snapshot_source_specs"].items():
    d = J.QROOT / j
    d.mkdir(parents=True)
    (d / "spec.json").write_text(json.dumps(s))
    (d / FIX["snapshot_source_state"][j]).write_text("snapshot")
ok("fixture code hash = the local code hash (the frozen ids are comparable)", J.code_hash() == FIX["code_hash"], J.code_hash())
sel_r, _ = captured(D.d13_select, FIX["snapshot_states"]["13"], FIX["snapshot_states"]["14"])
P3_NEW = ("sb13_a49_4995a818", "sb13_a52_0879fc1a", "sb13_a53_23a3f031", "sb13_a57_11e6f80c", "sb13_a58_27b8d290", "sb13_a59_d51168f1",
          "sb13_a61_7afcca3a", "sb13_a69_e5f7a0b7")                             # 04:21 phase-13 designs on P3 but on neither F13 nor F14
ok("snapshot 04:21: F13 = a62, a70, a71; F14 17; P3 21 (8 phase-13 designs on P3 alone); 28 distinct; 6 already bonded (sb13 a49, a59, a69 "
   "on P3 alone + sb14 a24, a29, a34)",
   ids_of(sel_r["F13"]) == ["sb13_a62_1e4338ee", "sb13_a70_1a523560", "sb13_a71_bce5f79f"] and len(sel_r["F14"]) == 17 and len(sel_r["P3"]) == 21
   and sel_r["n_p3_only"] == 8 and sorted(e["job_id"] for e in sel_r["P3"] if e["fronts"] == ["P3"]) == list(P3_NEW) and sel_r["n_designs"] == 28
   and sorted(ids_of(sel_r["covered"])) == ["sb13_a49_4995a818", "sb13_a59_d51168f1", "sb13_a69_e5f7a0b7", "sb14_a24_4dd6e4a2",
                                             "sb14_a29_6ad70033", "sb14_a34_7ff4db9a"], (len(sel_r["P3"]), sel_r["n_p3_only"], ids_of(sel_r["covered"])))
sp_r, _ = captured(D.specs, "D13")
got = {k: J.job_id({**v, "created": ""}) for k, v in sp_r.items()}
v1, v2, v3 = FIX["snapshot_expected_ids"], FIX["snapshot_expected_ids_v2"], FIX["snapshot_expected_ids_v3"]
ok("snapshot 04:21, current rules: 22 bond_only (the 17 of segD_fix + the 5 unbonded P3-only designs; default cap 40, none dropped), "
   "sit-to-stand a62 / a29 / sb14_a27 ((c) = P3 median: the 10th by bone of the 19 P3 designs other than a and b; was sb13_a61 under "
   "F14 + P3, sb14_a30 under F14), mesh a62 / sb14_a30 (rule unchanged)",
   len(sel_r["bond"]) == 22 and not sel_r["bond_left_out"]
   and set(ids_of(sel_r["bond"])) == {k[len(D.D13_BOND_PREFIX):] for k in v2 if k.startswith(D.D13_BOND_PREFIX)}
   | {"sb13_a52_0879fc1a", "sb13_a53_23a3f031", "sb13_a57_11e6f80c", "sb13_a58_27b8d290", "sb13_a61_7afcca3a"}
   and ids_of(sel_r["sts"]) == ["sb13_a62_1e4338ee", "sb14_a29_6ad70033", "sb14_a27_acfc4dca"]
   and ids_of(sel_r["mesh"]) == ["sb13_a62_1e4338ee", "sb14_a30_023c7221"], (ids_of(sel_r["sts"]), ids_of(sel_r["mesh"])))
ok("snapshot 04:21, current rules: the 32 jobs and ids of snapshot_expected_ids_v4", got == FIX["snapshot_expected_ids_v4"] and len(got) == 32,
   sorted(set(got.items()) ^ set(FIX["snapshot_expected_ids_v4"].items()))[:3])
ok("id stability vs the P3 rules (v3): the 30 v3 keys still selected keep their ids; the only v3 keys dropped are the sit-to-stand jobs of "
   "sb13_a61 ((c) moved to sb14_a27, whose sit-to-stand keys are the only new ones)",
   len(set(got) & set(v3)) == 30 and all(got[k] == v3[k] for k in set(got) & set(v3))
   and sorted(set(v3) - set(got)) == sorted(f"D13_sts_{ln}_sb13_a61_7afcca3a" for ln in D.D13_STS)
   and sorted(set(got) - set(v3)) == sorted(f"D13_sts_{ln}_sb14_a27_acfc4dca" for ln in D.D13_STS), (sorted(set(v3) - set(got)), sorted(set(got) - set(v3))))
ok("id stability vs segD_fix (v2): the 25 v2 keys the current rules still select keep their ids; the only v2 keys dropped are the sit-to-stand "
   "jobs of sb14_a30 ((c) moved to sb14_a27)",
   len(set(got) & set(v2)) == 25 and all(got[k] == v2[k] for k in set(got) & set(v2))
   and sorted(set(v2) - set(got)) == sorted(f"D13_sts_{ln}_sb14_a30_023c7221" for ln in D.D13_STS), sorted(set(v2) - set(got)))
ok("id stability vs the first 04:21 dry run (v1): every v1 key the current rules still select keeps its id",
   len(set(got) & set(v1)) == 18 and all(got[k] == v1[k] for k in set(got) & set(v1)), len(set(got) & set(v1)))
REG = BASE / "regression"
shutil.rmtree(REG, ignore_errors=True)
use(REG)
for j, s in FIX["regression_source_specs"].items():
    d = J.QROOT / j
    d.mkdir(parents=True)
    (d / "spec.json").write_text(json.dumps(s))
reg_bad = {}
for b, ids in FIX["regression_ids"].items():
    got_b = {k: J.job_id({**v, "created": ""}) for k, v in captured(D.specs, b)[0].items()}
    if got_b != ids:
        reg_bad[b] = sorted(set(got_b.items()) ^ set(ids.items()))[:2]
ok("earlier batches SB / SBb / V3406 / SBdelta / MI: specs() reproduce the ids in their Linux deck_<batch>_ids.json", not reg_bad, reg_bad)
hR = tree_hash(REG)
_, out_mi = captured(D.submit, "MI", dry=True)
ok("dry run works for an earlier batch (MI): its 3 Linux ids, writes nothing", {r["key"]: r["expected_id"] for r in dry_json(out_mi)["jobs"]}
   == FIX["regression_ids"]["MI"] and tree_hash(REG) == hR)
_, _ = captured(D.submit, "MI")
ok("real submit of an earlier batch (MI) in the fake tree writes its ids file exactly as before",
   json.loads((J.RESULTS / "deck_MI_ids.json").read_text())["jobs"] == FIX["regression_ids"]["MI"])

# ================================================================ H. the cap bites: F13 -> 3 lowest-rotation -> farthest point; dropped printed
# (the default cap is 40; D.D13_BOND_CAP is set to 25 for this section so that d13_select's default and the submit path both use it)
BIG13 = [rec("sb13_a1_bg130001", xvec(), 0.030, 2400, 9800, 13), rec("sb13_a2_bg130002", xvec(), 0.035, 2500, 9900, 13)]
BIG14 = [rec(f"sb14_a{i + 1}_bg{i + 1:06d}", xvec(), 0.05 * 1.2 ** i, 2300 - 60 * i, 9000 - 200 * i, 14) for i in range(30)]   # all on F14
BST13, BST14 = state(13, BIG13), state(14, BIG14)
s40, _ = captured(D.d13_select, BST13, BST14)
ok("H: with the default cap 40 all 32 uncovered designs fit (32 picks, nothing dropped)", s40["bond_cap"] == 40 and len(s40["bond"]) == 32
   and not s40["bond_left_out"], (s40["bond_cap"], len(s40["bond"])))
CAP0 = D.D13_BOND_CAP
D.D13_BOND_CAP = 25                                                              # the 'cap bites' path, through the default and submit
sbig, _ = captured(D.d13_select, BST13, BST14)
b_ids = ids_of(sbig["bond"])
f14_by_rot = [r["job_id"] for r in BIG14]                                        # built in rotation order
ok("32 uncovered designs, cap 25 (module constant set to 25, d13_select called without bond_cap): 25 picks, 7 dropped",
   sbig["bond_cap"] == 25 and len(b_ids) == 25 and len(sbig["bond_left_out"]) == 7 and sbig["n_designs"] == 32,
   (len(b_ids), len(sbig["bond_left_out"])))
ok("cap bites: both F13 designs first, then the 3 lowest-rotation F14 designs", b_ids[:5] == ["sb13_a1_bg130001", "sb13_a2_bg130002"] + f14_by_rot[:3],
   b_ids[:5])
ok("farthest point reaches the far end of F14 (highest rotation, least bone) first", b_ids[5] == f14_by_rot[-1], b_ids[5])
dropped = ids_of(sbig["bond_left_out"])
ok("dropped designs lie inside the F14 run (never the 3 lowest-rotation ones or the far end)",
   not (set(dropped) & set(f14_by_rot[:3] + f14_by_rot[-1:])) and set(dropped) <= set(f14_by_rot), dropped)
BIGT = BASE / "big"
write_tree(BIGT, BST13, BST14)
_, out_bd = captured(D.submit, "D13", dry=True)
ok("dry run prints the dropped designs", "dropped by the cap (7):" in out_bd and all(j in out_bd.split("dropped by the cap (7):")[1].split("sit-to-stand")[0]
                                                                                     for j in dropped))
_, out_bs = captured(D.submit, "D13")
ok("real submit prints the summary with the dropped designs; 25 bond_only jobs submitted",
   f"dropped by the cap 7 [{', '.join(dropped)}]" in out_bs
   and sum(k.startswith(D.D13_BOND_PREFIX) for k in json.loads((J.RESULTS / "deck_D13_ids.json").read_text())["jobs"]) == 25)
D.D13_BOND_CAP = CAP0
ok("H: D13_BOND_CAP restored to the default 40 after the section", D.D13_BOND_CAP == 40, D.D13_BOND_CAP)
use(FIN)

# ================================================================ I. cumulative submissions
PA, PP3, PP5 = (D.D13_BOND_PREFIX + JOB[k] for k in ("A13", "P3", "P5"))
sc, _ = captured(D.d13_select, ST13, ST14, bond_cap=5, prior={PA: "d13bond_x", PP5: "d13bond_y"})
ok("earlier D13_bond key of A (on the front) -> kept with its key, not picked again", ids_of(sc["bond_kept"]) == [JOB["A13"]]
   and sc["bond_kept"][0]["d13_key"] == PA and JOB["A13"] not in ids_of(sc["bond"]))
ok("earlier D13_bond key of P5 (dominated, on no front) -> stale", [e["key"] for e in sc["bond_stale"]] == [PP5], sc["bond_stale"])
ok("both earlier keys count against the cap: 5 - 2 = 3 slots -> B (F13), then P7, P1 (F14 by rotation)",
   sc["n_prior_bond"] == 2 and sc["bond_slots"] == 3 and ids_of(sc["bond"]) == [JOB["B13"], JOB["P7"], JOB["P1"]], ids_of(sc["bond"]))
sx, _ = captured(D.d13_select, ST13, ST14, prior={PP3: "d13bond_z"})
ok("matched by x: an earlier key from P3 (= design A solved by the phase-14 arm) covers design A; the kept entry keeps P3 as its source",
   ids_of(sx["bond_kept"]) == [JOB["P3"]] and sx["bond_kept"][0]["fronts"] == ["F13", "F14", "P3"] and JOB["A13"] not in ids_of(sx["bond"])
   and len(sx["bond"]) == 7, ids_of(sx["bond_kept"]))
msg = raises(D.d13_select, ST13, ST14, prior={D.D13_BOND_PREFIX + "sb14_a99_zz000099": "d13bond_q"})
ok("earlier key whose source job is in no state file -> SystemExit", msg and "neither state file" in msg, msg)
s_over, _ = captured(D.d13_select, ST13, ST14, bond_cap=1, prior={PA: "a", PP5: "b"})
ok("more earlier bond keys than the cap: warned, no new bond_only job", s_over["bond"] == [] and any("more than the cap" in w for w in s_over["warnings"]))
CUM = BASE / "cumulative"
s1_14 = copy.deepcopy(ST14)                                                      # state 1: P8 not solved yet
s1_14["records"] = [r for r in s1_14["records"] if r["job_id"] != JOB["P8"]]
s1_14["budget"] = len(s1_14["records"])
write_tree(CUM, ST13, s1_14)
_, _ = captured(D.submit, "D13")
ids1 = json.loads((J.RESULTS / "deck_D13_ids.json").read_text())["jobs"]
ok("state 1: 7 bond_only (A, B, P1, P2, P7, P9, W1), mesh on D (P4) = the F14 median then, sit-to-stand (c) on P1 = the P3 median then "
   "(7 P3 designs other than a and b, B included)",
   sorted(k for k in ids1 if k.startswith(D.D13_BOND_PREFIX)) == sorted(D.D13_BOND_PREFIX + JOB[k] for k in ("A13", "B13", "P1", "P2", "P7", "P9", "W1"))
   and f"D13_mesh_h1.94_{JOB['P4']}" in ids1 and f"D13_sts_F1714_{JOB['P1']}" in ids1, sorted(ids1))
p8 = J.QROOT / JOB["P8"]                                                          # state 2: the arm solved P8 (a new front design)
p8.mkdir()
(p8 / "spec.json").write_text(json.dumps({**P14.spec_of(X["P8"], "a8", bonded=False), "created": "2026-10-25 01:00:00"}))
(p8 / "DONE").write_text("x")
(J.RESULTS / "neckopt_p14.json").write_text(json.dumps(ST14, indent=1))
h_c = tree_hash(BASE / "cumulative")
msg = raises(D.submit, "D13")
new_exp = sorted([D.D13_BOND_PREFIX + JOB["P8"]] + [f"D13_mesh_h{h:g}_{JOB['P9']}" for h in D.D13_MESH_H]
                 + [f"D13_sts_{ln}_{JOB['P9']}" for ln in D.D13_STS])                    # P8 shifts both medians to P9
stale_exp = sorted([f"D13_mesh_h{h:g}_{JOB['P4']}" for h in D.D13_MESH_H] + [f"D13_sts_{ln}_{JOB['P1']}" for ln in D.D13_STS])
ok("state 2: the selection has new keys -> a real submit refuses without --reselect, names new and stale keys, writes nothing",
   msg and "--reselect" in msg and all(k in msg for k in new_exp) and "4 stale keys" in msg and tree_hash(BASE / "cumulative") == h_c, (msg or "")[:300])
_, out_c2 = captured(D.submit, "D13", dry=True)
jc2 = dry_json(out_c2)
ok("dry run on state 2: lists the new and stale keys and says a real submit would refuse without --reselect",
   "would refuse without --reselect" in out_c2 and jc2["new_keys"] == new_exp and jc2["stale_keys"] == stale_exp and tree_hash(BASE / "cumulative") == h_c,
   (jc2["new_keys"], jc2["stale_keys"]))
ok("state 2: the 7 earlier bond designs are kept (same keys), only P8 is new", ids_of(D.d13_select(ST13, ST14, prior=ids1)["bond"]) == [JOB["P8"]])
_, out_r = captured(D.submit, "D13", reselect=True)
ids2 = json.loads((J.RESULTS / "deck_D13_ids.json").read_text())["jobs"]
ok("--reselect: the new keys are submitted, every earlier key (stale ones included) keeps its id", all(ids2.get(k) == v for k, v in ids1.items())
   and set(ids2) - set(ids1) == set(new_exp) and all((J.QROOT / ids2[k] / "spec.json").exists() for k in new_exp) and "--reselect" in out_r)
srcx = [tuple(json.loads((J.QROOT / ids2[k] / "spec.json").read_text())["design"].items()) for k in ids2 if k.startswith(D.D13_BOND_PREFIX)]
ok("no design gets two D13 bond_only jobs: 8 bond keys for the 8 uncovered designs, 8 distinct designs", len(srcx) == 8 and len(set(srcx)) == 8)
h_q = tree_hash(J.QROOT)
_, out_r2 = captured(D.submit, "D13")
ok("re-submit on state 2 without --reselect: no new keys -> goes ahead, prints the stale keys, ids file and queue unchanged",
   "4 stale keys in deck_D13_ids.json" in out_r2 and json.loads((J.RESULTS / "deck_D13_ids.json").read_text())["jobs"] == ids2
   and tree_hash(J.QROOT) == h_q)
use(FIN)

# ================================================================ J. warnings on the real path, warm-start ids, usable bonded records
WN = BASE / "warn_submit"
write_tree(WN, st13_none, ST14)
_, out_w = captured(D.submit, "D13")
ok("real submit prints the selection warnings and the one-line summary",
   f"WARNING: {JOB['B13']}: record has bonded None" in out_w and SUMMARY0 in out_w, out_w[:200])
bad_w = copy.deepcopy(ST14)
bad_w["warm_start_ids"].append("sb13_init_99990009")
msg = raises(D.d13_select, ST13, bad_w)
ok("phase-14 warm-start id missing from the phase-13 records -> SystemExit", msg and "not phase-13 records" in msg and "sb13_init_99990009" in msg, msg)
nv13 = copy.deepcopy(ST13)
next(r for r in nv13["records"] if r["job_id"] == JOB["C13"])["sed_chg_pct"] = None
nv14 = copy.deepcopy(ST14)
next(r for r in nv14["records"] if r["job_id"] == JOB["P4"])["vm_p99"] = None
su, _ = captured(D.d13_select, nv13, nv14)
ok("bonded ok record without sed_chg_pct (C13) or vm_p99 (P4): warned, its design is not covered and gets a bond_only job",
   not su["covered"] and {JOB["C13"], JOB["P4"]} <= set(ids_of(su["bond"]))
   and any(JOB["C13"] in w and "sed_chg_pct" in w for w in su["warnings"]) and any(JOB["P4"] in w and "vm_p99" in w for w in su["warnings"]), su["warnings"])
use(FIN)

# ================================================================ K. one read of the state files and one selection per call
ONCE = BASE / "once"
write_tree(ONCE, ST13, ST14)
calls = {"state": [], "select": 0}
_st_fn, _sel_fn = D._d13_state, D.d13_select


def _count_state(p):
    calls["state"].append(p)
    return _st_fn(p)


def _count_select(*a, **k):
    calls["select"] += 1
    return _sel_fn(*a, **k)


D._d13_state, D.d13_select = _count_state, _count_select
try:
    captured(D.submit, "D13", dry=True)
    c_dry = (sorted(calls["state"]), calls["select"])
    calls["state"], calls["select"] = [], 0
    captured(D.submit, "D13")
    c_sub = (sorted(calls["state"]), calls["select"])
finally:
    D._d13_state, D.d13_select = _st_fn, _sel_fn
ok("one dry run: each state file read once, one selection (report, job table and JSON from the same snapshot)", c_dry == ([13, 14], 1), c_dry)
ok("one real submit: each state file read once, one selection (unfinished check, warnings and specs from the same snapshot)", c_sub == ([13, 14], 1), c_sub)
use(FIN)

# ================================================================ L. queue-order note (--allow-unfinished)
note = " ".join(D.D13_QUEUE_NOTE.split())
ok("the note says D13 jobs (d13*) would be prepped and solved ahead of sb13_ / sb14_ jobs",
   all(w in note for w in ("d13bond_*", "d13sts_*", "d13mesh_*", "sb13_*", "ahead of", "prepped and solved")), note)
ok("--allow-unfinished override warning carries the note", note in " ".join(out_a.split()))
UN2 = BASE / "unfinished2"
write_tree(UN2, u13, ST14)
msg = raises(D.submit, "D13")
ok("the refusal (arms not finished) carries the note", msg and note in " ".join(msg.split()), (msg or "")[:200])
buf_h = io.StringIO()
saved_argv = sys.argv
sys.argv = ["stage_deck.py", "submit", "D13", "-h"]
try:
    with contextlib.redirect_stdout(buf_h):
        try:
            runpy.run_path(str(ROOT / "v2" / "stage_deck.py"), run_name="__main__")
        except SystemExit:
            pass
finally:
    sys.argv = saved_argv
help_txt = " ".join(buf_h.getvalue().split())
ok("--allow-unfinished help carries the note; --reselect is documented", note in help_txt and "--reselect" in help_txt, help_txt[-300:])
use(FIN)

# ================================================================ M. P3: a phase-13 design on P3 but on neither F13 nor F14 must be covered
rngM = random.Random(4321)                                                       # own generator: the x values of sections A-L are unchanged


def xm():
    return [round(rngM.random(), 6) for _ in range(NV)]


JM = "sb13_a8_mmmm0008"                                                          # the sb13_a78 analog of the 2026-10-25 morning checkpoint
m13 = copy.deepcopy(ST13)
m13["records"].append(rec(JM, xm(), 0.07, 2100, 7500, 13))
m13["budget"] = len(m13["records"])
sm, _ = captured(D.d13_select, m13, ST14)
e_m = next((e for e in sm["P3"] if e["job_id"] == JM), None)
ok("M: the phase-13 design (0.07 deg, 2100 mm2, 7500 mm3) is on P3 only: not on F13 (A dominates it in 2 objectives), not on F14 (phase 14 "
   "never saw it), 3-objective non-dominated over both arms", e_m is not None and e_m["fronts"] == ["P3"]
   and JM not in ids_of(sm["F13"]) + ids_of(sm["F14"]) and sm["n_p3_only"] == 1, e_m)
ok("M: it is covered: default cap -> a bond_only pick (F13 first: A, B; then by rotation: it at 0.07 deg, P7, P1, P9, W1, P8, P2); none dropped",
   ids_of(sm["bond"]) == [JOB["A13"], JOB["B13"], JM] + [JOB[k] for k in ("P7", "P1", "P9", "W1", "P8", "P2")] and not sm["bond_left_out"],
   ids_of(sm["bond"]))
ok("M: F13 / F14 / already bonded unchanged; 11 designs; P7 (now 3-obj dominated by the phase-13 design) leaves P3 but stays covered via F14",
   ids_of(sm["F13"]) == ids_of(sel["F13"]) and ids_of(sm["F14"]) == ids_of(sel["F14"]) and ids_of(sm["covered"]) == ids_of(sel["covered"])
   and sm["n_designs"] == 11 and JOB["P7"] not in ids_of(sm["P3"]) and next(e for e in sm["bond"] if e["job_id"] == JOB["P7"])["fronts"] == ["F14"])
ok("M: sit-to-stand (b) still D; (c) = median bone of the 8 P3 designs other than a and b (P2, P8, W1, P9, P1, the P3 design, A, B) = P9 "
   "(5000); P7 (on F14, 3-obj dominated by the P3 design) is not a (c) candidate - with it (the F14 + P3 rule) the median would be P1",
   ids_of(sm["sts"]) == [JOB["C13"], JOB["P4"], JOB["P9"]] and sm["sts"][2]["fronts"] == ["F14", "P3"], ids_of(sm["sts"]))
ok("M: mesh unchanged (rule unchanged: F14 median bone removal) = C13, P9", ids_of(sm["mesh"]) == [JOB["C13"], JOB["P9"]], ids_of(sm["mesh"]))
sm5, _ = captured(D.d13_select, m13, ST14, bond_cap=5)
ok("M, cap 5: F13 (A, B), then the 3 lowest-rotation remaining designs incl. the P3 one: it (0.07), P7 (0.08), P1 (0.10); dropped P9, W1, P8, P2",
   ids_of(sm5["bond"]) == [JOB["A13"], JOB["B13"], JM, JOB["P7"], JOB["P1"]]
   and ids_of(sm5["bond_left_out"]) == [JOB[k] for k in ("P9", "W1", "P8", "P2")], ids_of(sm5["bond"]) + ids_of(sm5["bond_left_out"]))
MT = BASE / "p3_only"
write_tree(MT, m13, ST14)
sp_m, _ = captured(D.specs, "D13")
ids_m = {k: J.job_id({**v, "created": ""}) for k, v in sp_m.items()}
new_m, gone_m = sorted(set(ids_m) - set(exp_ids)), sorted(set(exp_ids) - set(ids_m))
ok("M: specs: every base key keeps its id; the only new key = the P3 design's bond_only job ((c) stays P9); no key gone",
   all(ids_m[k] == exp_ids[k] for k in set(ids_m) & set(exp_ids)) and new_m == [D.D13_BOND_PREFIX + JM] and gone_m == [], (new_m, gone_m))
bm = sp_m[D.D13_BOND_PREFIX + JM]
ok("M: its bond_only spec = its own phase-13 source spec + bond_only + intact_job PHASES[13], stage d13bond, tag p13_a8_mmmm0008, no fric_only",
   bm["source_job"] == JM and bm["bond_only"] is True and bm["intact_job"] == N.PHASES[13]["intact_job"] and bm["stage"] == "d13bond"
   and bm["tag"] == "p13_a8_mmmm0008" and "fric_only" not in bm and bm["design"] == src_of(bm)["design"], {k: bm.get(k) for k in ("stage", "tag")})
hM = tree_hash(MT)
_, out_m = captured(D.submit, "D13", dry=True)
p3_block = out_m.split("P3 = ", 1)[1].split("distinct designs on F13 + F14 + P3", 1)[0]
picks = out_m.split("bond_only picks", 1)[1].split("dropped by the cap", 1)[0]
ok("M: dry run lists it in the P3 section and among the bond_only picks; summary 'P3 10 (1 on neither F13 nor F14), 11 distinct'; writes nothing",
   JM in p3_block and JM in picks and "D13 selection: F13 3, F14 8, P3 10 (1 on neither F13 nor F14), 11 distinct designs" in out_m
   and tree_hash(MT) == hM, p3_block[:300])
_, _ = captured(D.submit, "D13")
ids_ms = json.loads((J.RESULTS / "deck_D13_ids.json").read_text())["jobs"]
ok("M: real submit writes the P3 design's bond_only job (ids = the spec ids)", ids_ms == ids_m
   and (J.QROOT / ids_ms[D.D13_BOND_PREFIX + JM] / "spec.json").exists())
pk = {D.D13_BOND_PREFIX + JM: "d13bond_p13_a8_mmmm0008_x"}
sk, _ = captured(D.d13_select, m13, ST14, prior=pk)
ok("M: an earlier D13_bond key of the P3 design is kept while the design is on P3 (not picked again, counted against the cap: 40 - 1 = 39 slots)",
   ids_of(sk["bond_kept"]) == [JM] and JM not in ids_of(sk["bond"]) and not sk["bond_stale"] and sk["bond_slots"] == 39)
m13c = copy.deepcopy(m13)
m13c["records"].append(rec("sb13_a9_mmmm0009", xm(), 0.065, 2150, 7400, 13))     # dominates JM in all 3 objectives
sk2, _ = captured(D.d13_select, m13c, ST14, prior=pk)
ok("M: once another phase-13 design dominates it in 3 objectives, the earlier key is stale (job stays) and the new P3 design gets the pick",
   [e["key"] for e in sk2["bond_stale"]] == [D.D13_BOND_PREFIX + JM] and "sb13_a9_mmmm0009" in ids_of(sk2["bond"]) and JM not in ids_of(sk2["bond"]),
   ([e["key"] for e in sk2["bond_stale"]], ids_of(sk2["bond"])))
m13d = copy.deepcopy(m13)
next(r for r in m13d["records"] if r["job_id"] == JM).update(bonded=True, fric_only=False, vm_p99=300.0, sed_chg_pct=-10.0)
skd, _ = captured(D.d13_select, m13d, ST14)
ok("M: a P3-only design with a usable bonded record of its own counts as already bonded (no new job)",
   JM in ids_of(skd["covered"]) and JM not in ids_of(skd["bond"]), ids_of(skd["covered"]))
FO13 = state(13, [rec("sb13_a1_ff000001", xm(), 0.01, 3000, 9000, 13), rec("sb13_a2_ff000002", xm(), 0.02, 3100, 5000, 13)])
FO14 = state(14, [rec("sb14_a1_ff000011", xm(), 0.02, 3100, 4800, 14), rec("sb14_a2_ff000012", xm(), 0.5, 1000, 3000, 14),
                  rec("sb14_a3_ff000013", xm(), 1.0, 500, 2000, 14)])
so, _ = captured(D.d13_select, FO13, FO14)
fo2 = next(e for e in so["bond"] if e["job_id"] == "sb13_a2_ff000002")
ok("M: (b) / (c) never come from a design that is only on F13: sb13_a2 (0.02 deg, 5000 mm3; F13 only, 3-obj dominated by sb14_a1) would win "
   "(b) on the rotation tie by job id; (b) = sb14_a1, (c) = sb14_a3 (median of sb14_a2 / a3); sb13_a2 still gets its bond_only job (F13)",
   fo2["fronts"] == ["F13"] and ids_of(so["sts"]) == ["sb13_a1_ff000001", "sb14_a1_ff000011", "sb14_a3_ff000013"], ids_of(so["sts"]))
NC13 = state(13, [rec("sb13_a1_nc000001", xm(), 0.01, 3000, 3000, 13)])                # dominates both phase-14 designs in 3 objectives
NC14 = state(14, [rec("sb14_a1_nc000011", xm(), 0.5, 1000, 5000, 14), rec("sb14_a2_nc000012", xm(), 1.0, 500, 4000, 14)])
snc, _ = captured(D.d13_select, NC13, NC14)
ok("M: no P3 design other than a and b: (c) left out with a warning; sb14_a2 (on F14, 3-obj dominated by sb13_a1) is not taken; "
   "(b) = sb14_a1 (F14, bone <= 6000) as before",
   ids_of(snc["sts"]) == ["sb13_a1_nc000001", "sb14_a1_nc000011"] and [e["role"] for e in snc["sts"]] == ["a", "b"]
   and [e["job_id"] for e in snc["P3"]] == ["sb13_a1_nc000001"] and any(w.startswith("sit-to-stand (c): no P3 design") for w in snc["warnings"]),
   (ids_of(snc["sts"]), snc["warnings"]))
c_all = [s_["sts"][-1] for s_ in (sel, sb_, sn_, s_lo, s7, sm, so, sel_r)]
ok("M: every sit-to-stand (c) selected in this test is on P3 and carries the P3 rule string",
   all(e["role"] == "c" and "P3" in e["fronts"] and e["rule"] == "median bone removal on P3 (excluding a and b)" for e in c_all),
   [(e["job_id"], e["fronts"]) for e in c_all if "P3" not in e["fronts"]])
use(FIN)

# ================================================================ N. the default cap 40 on a fresh read-only copy of the live state
LV = FIX["live_states"]                                                         # 2026-10-25 09:25 GMT, arms still running (2 pending each)
sl, _ = captured(D.d13_select, LV["13"], LV["14"])
MUST = {"sb13_a78_b0f465da", "sb14_a25_69b437e2", "sb14_a46_6c55ace1"}
ok("N: the default D13_BOND_CAP is 40, and on the fresh live copy (09:25) nothing is dropped: 44 designs, 10 already bonded, 34 bond_only "
   "picks incl. sb13_a78_b0f465da (P3 only), sb14_a25_69b437e2 and sb14_a46_6c55ace1 (F14)",
   D.D13_BOND_CAP == 40 and sl["bond_cap"] == 40 and sl["bond_left_out"] == [] and sl["n_designs"] == 44 and len(sl["covered"]) == 10
   and len(sl["bond"]) == 34 and MUST <= set(ids_of(sl["bond"])), (sl["bond_cap"], ids_of(sl["bond_left_out"]), sorted(MUST - set(ids_of(sl["bond"])))))
s25l, _ = captured(D.d13_select, LV["13"], LV["14"], bond_cap=25)
ok("N: the old cap 25 would bite on the same copy: 9 dropped, sb14_a46_6c55ace1 among them",
   len(s25l["bond_left_out"]) == 9 and "sb14_a46_6c55ace1" in ids_of(s25l["bond_left_out"]), ids_of(s25l["bond_left_out"]))
ok("N: live sit-to-stand a sb13_a82 (lowest rotation), b sb14_a29 (bone <= 6000), c sb13_a78_b0f465da (16th by bone of the 32 P3 designs "
   "other than a and b; on P3 only); mesh sb13_a82 + sb14_a27 (F14 median, rule unchanged)",
   ids_of(sl["sts"]) == ["sb13_a82_cd8c77ad", "sb14_a29_6ad70033", "sb13_a78_b0f465da"] and sl["sts"][2]["fronts"] == ["P3"]
   and ids_of(sl["mesh"]) == ["sb13_a82_cd8c77ad", "sb14_a27_acfc4dca"], (ids_of(sl["sts"]), ids_of(sl["mesh"])))

# ================================================================ fixture reset
J.QROOT, J.RESULTS = REAL_Q, REAL_R
ok("fixture reset: J.QROOT / J.RESULTS back to ~/mobo_toy_v2 (never written by this test)", J.QROOT == REAL_Q and J.RESULTS == REAL_R)
bad = [k_ for k_, v in checks if not v]
print(f"\n{len(checks) - len(bad)}/{len(checks)} checks passed in {time.perf_counter() - T_START:.0f} s" + (f"; FAILED: {bad}" if bad else ""))
sys.exit(1 if bad else 0)
