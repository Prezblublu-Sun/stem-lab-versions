"""Run with the repo venv: PYTHONUTF8=1 .venv-mobo/Scripts/python.exe v2/tests/test_stage_deck_d13.py
Local only: fake queues / results in the system temp dir (mobo_toy_d13_tests); J.QROOT / J.RESULTS are pointed there for every check.
No gmsh, no FE, no Abaqus, no Linux, nothing under ~/mobo_toy_v2 is read or written; single process.

Batch D13 of v2/stage_deck.py = segment D of the 50 h plan (front checks after the phase 13 / 14 arms):
A. d13_select on a synthetic finished state (phase 13 2-obj records + phase 14 3-obj records + frozen warm-start rows): F13 / F14 non-dominated
   sets, infeasible / failed / no-bone rows excluded, the same design solved by both arms de-duplicated by x, 'already bonded' = a bonded ok
   record (a FAILED bonded record does not count), F13 first, then greedy farthest-point over bone removal (hand-computed for cap 5), cap 1
   and cap 12, sit-to-stand = top 3 by rotation, mesh = min rotation + F14 median bone removal.
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
G. real snapshot (fixtures_stage_deck_d13.json, read-only copy of the Linux state at 2026-10-25 04:21, arms still running): the selection
   reproduces the 22 jobs and ids of the dry run saved that morning; earlier batches SB / SBb / V3406 / SBdelta / MI reproduce the ids in their
   Linux deck_<batch>_ids.json from the same source specs (the submit / specs refactor did not change any existing id).
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
ok("10 distinct front designs (A on both fronts counted once)", sel["n_designs"] == 10, sel["n_designs"])
ok("already bonded = C (bonded F13 record) and D (its bonded phase-14 twin P4 is on F14); FAILED bonded P10 does not cover B",
   sorted(ids_of(sel["covered"])) == sorted([JOB["C13"], JOB["P4"]]), ids_of(sel["covered"]))
cov_d = next(e for e in sel["covered"] if e["job_id"] == JOB["P4"])
ok("design D: representative = its front row P4 (the 2-obj-dominated D13 is on no front), bonded_jobs = [P4], fronts F14",
   cov_d["bonded_jobs"] == [JOB["P4"]] and cov_d["fronts"] == ["F14"], cov_d)
a_e = next(e for e in sel["bond"] if e["job_id"] == JOB["A13"])
ok("design A (both arms): one entry, representative sb13 job, fronts F13+F14", a_e["fronts"] == ["F13", "F14"]
   and JOB["P3"] not in ids_of(sel["bond"]), a_e)
ok("cap 12: all 8 uncovered front designs get a bond_only job, none left out",
   len(sel["bond"]) == 8 and not sel["bond_left_out"] and not ({JOB["C13"], JOB["D13"], JOB["P4"]} & set(ids_of(sel["bond"]))), ids_of(sel["bond"]))
s5, _ = captured(D.d13_select, ST13, ST14, bond_cap=5)
ok("cap 5: F13 first (A, B by rotation), then farthest-point over bone removal: P2 (2500), P9 (5000), P7 (7800)",
   ids_of(s5["bond"]) == [JOB["A13"], JOB["B13"], JOB["P2"], JOB["P9"], JOB["P7"]], ids_of(s5["bond"]))
ok("cap 5: left out = P8, W1, P1 (sorted by bone removal)", ids_of(s5["bond_left_out"]) == [JOB["P8"], JOB["W1"], JOB["P1"]], ids_of(s5["bond_left_out"]))
s1, _ = captured(D.d13_select, ST13, ST14, bond_cap=1)
ok("cap 1: only the lowest-rotation uncovered F13 design (A); 7 left out", ids_of(s1["bond"]) == [JOB["A13"]] and len(s1["bond_left_out"]) == 7)
ok("sit-to-stand = top 3 by rotation over both fronts, bonded or not: C, A, B", ids_of(sel["sts"]) == [JOB["C13"], JOB["A13"], JOB["B13"]], ids_of(sel["sts"]))
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
ok("dry run lists F13 / F14 / already bonded / picks / left out / sit-to-stand / mesh sections",
   all(s_ in out_d for s_ in ("F13 = ", "F14 = ", "already bonded", "bond_only picks", "left out by the cap", "sit-to-stand", "mesh noise")))


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
ok("snapshot 04:21: F13 = a62, a70, a71; F14 17 designs; 20 distinct; 3 already bonded (sb14 a24, a29, a34)",
   ids_of(sel_r["F13"]) == ["sb13_a62_1e4338ee", "sb13_a70_1a523560", "sb13_a71_bce5f79f"] and len(sel_r["F14"]) == 17 and sel_r["n_designs"] == 20
   and sorted(ids_of(sel_r["covered"])) == ["sb14_a24_4dd6e4a2", "sb14_a29_6ad70033", "sb14_a34_7ff4db9a"])
sp_r, _ = captured(D.specs, "D13")
got = {k: J.job_id({**v, "created": ""}) for k, v in sp_r.items()}
ok("snapshot 04:21: the 22 jobs and ids of the saved dry run are reproduced", got == FIX["snapshot_expected_ids"],
   sorted(set(got.items()) ^ set(FIX["snapshot_expected_ids"].items()))[:3])
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

# ================================================================ fixture reset
J.QROOT, J.RESULTS = REAL_Q, REAL_R
ok("fixture reset: J.QROOT / J.RESULTS back to ~/mobo_toy_v2 (never written by this test)", J.QROOT == REAL_Q and J.RESULTS == REAL_R)
bad = [k_ for k_, v in checks if not v]
print(f"\n{len(checks) - len(bad)}/{len(checks)} checks passed in {time.perf_counter() - T_START:.0f} s" + (f"; FAILED: {bad}" if bad else ""))
sys.exit(1 if bad else 0)
