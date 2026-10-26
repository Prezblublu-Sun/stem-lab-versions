"""Run with the repo venv: PYTHONUTF8=1 .venv-mobo/Scripts/python.exe v2/tests/test_stage_db.py
Local only: fake queues / results in the system temp dir (mobo_toy_db_tests) built from fixtures_stage_db.json (read-only copies of the Linux
queue taken 2026-10-25 22:12 UTC (v0) and 23:07 UTC (v1: + the 27 CD-0 seed jobs, the seed file, the noise design's h 2.0 twin));
J.QROOT / J.RESULTS are pointed there for every check. A simulated serve + 3-slot worker advances the fake jobs (NEW -> READY -> CLAIMED ->
SOLVED -> DONE). No gmsh, no FE, no Abaqus, no Linux, nothing under ~/mobo_toy_v2 is read or written.
Trees without the seed jobs opt out of the seed check explicitly (stage_db.SEEDS = {"b1": ()}); a declared seed file that is missing is a
problem (section S).

v2/stage_db.py = the db3406 batch submitter v1.1 (D1 of the database plan, research-log/neck_implant_2026-10-02/3406数据库规划_两天一周一月_2026-10-25.md):
A. spec construction per layer on the fixture queue (no seed jobs): 84 rows (REF 4, CD-0 27, NZ-1 8, FD-0 h2.5 24, FD-0 h1.4 2, BD mesh 7
   = 6 + the v3406 noise design's h 2.0 bond_only, BD h2.0 12), the expected ids of the v1 dry run on the 23:07 UTC copy, every v0 id keeps
   its hash8 (only db_bd_ -> db_bo_ for the bond-only partners), submission order; every spec = source spec.json minus meta / role keys +
   exactly the layer's change; record fields; variant strings; init median rule; never in a phase 10-14 family; jobs.ref_for accepts every
   bonded / bond_only spec.
B. every check rejects a bad case (v0 list; the hash8-hit-without-spec message now says 'no readable spec.json'; feed at 10 GiB is refused
   by the first-start gate).
C. feeder on a fake queue with a simulated serve / worker: REF priority on the first pass, full run to DONE with every gate checked at each
   submission (depth, heavy, reference, h1.4 reference + operator file, exclusive REF_h1.4, REF priority, slow start), restart idempotence,
   STOP file, a FAILED reference blocks its dependents (exit 3), dedup existing at feed time, lock, Linux-only guard.
D. dry run writes nothing; CLI option errors; status.
E. jobs.code_hash() == 6d7af243d0.
F. (A) seed adoption: the 27 CD-0 seed jobs (live states NEW / READY / CLAIMED) are recorded as existing via the physics key, 1:1 onto
   db_seed_CD0.json's ids, 57 new (83 = 27 + 56 without the noise row); key-by-key physics comparison; kind design / variant the same,
   intact not; a physics change, an int-for-float value, an unclassified key, a seed-file / queue spec mismatch, a wrong seed code_hash and a
   foreign femur_model_version are each caught; jobs.prep / post / serve only branch on kind bench / intact; feed with seeds (first pass
   submits nothing at 24 unclaimed, WAIT logged; full run never submits a seed id).
G. (B) exclusive REF_h1.4 (in flight -> nothing else submitted; pending -> waits for an idle queue, then goes alone) and the operator file
   DB_H14_REF_OK for FD0_h1.4_* (missing / older than the reference -> WAIT; fresh -> submitted).
H. (B) per-layer failure gate: layer rule (>= 2 FAILED and rate > 5 %), first-10 rule (>= 3 of the first 10 finished), held rows, ERROR
   with FAILED.json reasons, events, release file (older than the hold ignored), acknowledgement and re-hold; batch-wide release
   DB_RELEASE_ALL / DB_RELEASE_b1 (round 2 item 2); integration run.
I. (C) JSONDecodeError robustness (snapshot, build, hash8 hit, FAILED.json, status) and crash logging into db_feed.log.
J. (C) REF priority: other unclaimed db_* capped at 1 while a REF row is pending / NEW / READY; REF_h1.4 does not trigger it.
K. (C) stage db_bo + vocabulary in the module docstring.
L. (C) periodic WAIT lines (idle pass 1, 11, 21) with reasons and the oldest-READY age.
M. (C) first start refused below 30 GB (27.94 GiB); restart only needs the 15 GiB gate.
N. (C) aux md5 (inp_writer, collar_rule, jobs, stability, femur_3406, odb_export) recorded at the first start, re-checked every pass
   (ERROR + halt event + stop), restart refused on change, an absent file that appears counts.
O. (round 2 item 3) physics-path FAILED existing jobs are problems unless acknowledged (DB_ACK_FAILED_<key>); accepted rows count as
   acknowledged in the layer gate.
Round 2 (review of v1, items 1-7):
P. (1) the first-10 window counts only rows the feeder submitted (manifest dedup 'new'): 10 DONE seeds + 3 new FAILED rows hold every layer;
   seeds stay under the per-layer rule; integration with the live seed states (10 DONE, 3 CLAIMED, 14 READY) and DB_RELEASE_ALL.
Q. (2) DB_RELEASE_ALL / DB_RELEASE_b1 (in sections H and P).
R. (3) a row resolving to a FAILED existing job (hash8 path) is a problem unless DB_ACK_FAILED_<key>; a job adopted at an earlier start that
   FAILS later is not; the same checks at feed time (FAILED twin, foreign femur_model_version) stop the feeder; a REF row resolving at feed
   time to another id stops it with a clear message.
S. (4) a declared seed file that is missing is a problem.
T. (5) per-layer slow start: at most 2 rows in flight per new layer until 2 of its rows are DONE.
U. (6) DB_H14_EXCLUSIVE / the word 'exclusive' in DB_H14_REF_OK makes FD0_h1.4_* exclusive; the mode is logged.
V. (7) HEARTBEAT line every 10 min regardless (fake clock), with in-flight rows, oldest READY age and the last claim.
"""
import contextlib
import copy
import hashlib
import io
import json
import os
import pathlib
import re
import shutil
import sys
import tempfile
import time
import inspect

ROOT = pathlib.Path(r"H:/projects/Femoral implant generation/sandbox/mobo_toy")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "v2"))
BASE = pathlib.Path(tempfile.gettempdir()) / "mobo_toy_db_tests"            # fake trees outside the repo and outside ~/mobo_toy_v2
shutil.rmtree(BASE, ignore_errors=True)
BASE.mkdir(parents=True)
FIX = json.loads((ROOT / "v2" / "tests" / "fixtures_stage_db.json").read_text(encoding="utf-8"))
EXP = FIX["expected"]

import jobs as J  # noqa: E402
import stage_neckopt as SN  # noqa: E402
import stage_deck as D  # noqa: E402
import stage_db as DB  # noqa: E402

T_START = time.perf_counter()
REAL_Q, REAL_R = J.QROOT, J.RESULTS
REAL_SUBMIT, REAL_FREE, REAL_CODE = J.submit, DB.disk_free_gib, J.code_hash
REAL_CODE_ROOT = DB.CODE_ROOT
REAL_SEEDS, REAL_MONO = dict(DB.SEEDS), DB._mono
SEED_IDS = set(FIX["seed_queue"])
checks = []


def ok(name, cond, extra=""):
    checks.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + f"(t={time.perf_counter() - T_START:.0f}s) " + name + (f"  [{extra}]" if extra else ""), flush=True)


def use(root: pathlib.Path):
    J.QROOT, J.RESULTS = root / "queue", root / "results"
    assert not str(J.QROOT).startswith(str(pathlib.Path.home() / "mobo_toy_v2"))


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


MARKS = {"NEW": (), "READY": ("READY",), "CLAIMED": ("CLAIMED",), "SOLVED": ("CLAIMED", "SOLVED"), "DONE": ("CLAIMED", "SOLVED", "DONE")}


def write_tree(root: pathlib.Path, states=None, seed=False, seed_states=None) -> pathlib.Path:
    """Fake queue from the fixture: spec.json + markers (+ reduced result.json for DONE jobs) + the reduced state files.
    seed=True also writes the 27 seed job dirs (spec.json exactly as in the live queue, their live NEW / READY / CLAIMED state, or
    seed_states[id]) and results/db_seed_CD0.json, and keeps the real SEEDS; seed=False opts out of the seed check (SEEDS b1 = ())."""
    shutil.rmtree(root, ignore_errors=True)
    DB._SPEC_CACHE.clear()
    DB.SEEDS = dict(REAL_SEEDS) if seed else {"b1": ()}
    use(root)
    J.QROOT.mkdir(parents=True)
    J.RESULTS.mkdir(parents=True)
    for n, j in FIX["jobs"].items():
        d = J.QROOT / n
        d.mkdir()
        (d / "spec.json").write_text(json.dumps(j["spec"], indent=1))
        st = (states or {}).get(n, j["state"])
        if st == "DONE":
            for m in MARKS["DONE"]:
                (d / m).write_text("x")
            (d / "result.json").write_text(json.dumps({**j["result"], "job_id": n}))
    for p, st in FIX["states"].items():
        (J.RESULTS / f"neckopt_p{p}.json").write_text(json.dumps(st))
    if seed:
        for jid, v in FIX["seed_queue"].items():
            d = J.QROOT / jid
            d.mkdir()
            (d / "spec.json").write_text(json.dumps(v["spec"], indent=1, default=float))
            for m in MARKS[(seed_states or {}).get(jid, v["state"])]:
                (d / m).write_text("x")
        (J.RESULTS / "db_seed_CD0.json").write_text(json.dumps(FIX["seed_file"], indent=1))
    return root


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


def mark_done(jid):
    d = J.QROOT / jid
    for m in MARKS["DONE"]:
        (d / m).write_text("x")
    with contextlib.suppress(FileNotFoundError):
        (d / "READY").unlink()
    (d / "result.json").write_text(json.dumps({"gruen7": 1.0, "gruen1": 1.0, "job_id": jid}))


def phys(job):
    return {k: v for k, v in FIX["jobs"][job]["spec"].items() if k in DB.PHYS_KEYS}


def body(r):
    return {k: v for k, v in r["spec"].items() if k not in ("stage", "tag")}


def logtext(root=None):
    p = (root or J.QROOT.parent) / "logs" / "db_feed.log"
    return p.read_text(encoding="utf-8") if p.exists() else ""


DB._ALLOW_NON_LINUX = True
DB.disk_free_gib = lambda *a: 100.0                                              # deterministic disk gates (sections B / M patch it)

# ================================================================ A. spec construction per layer
FQ = write_tree(BASE / "fq")
b, out = captured(DB.build, "b1")
rows = {r["key"]: r for r in b["rows"]}
ID2LAYER = {r["expected_id"]: r["layer"] for r in b["rows"]}
per = {}
for r in b["rows"]:
    per[r["layer"]] = per.get(r["layer"], 0) + 1
ok("A: 84 rows: REF 4, CD-0 27 (19 delta + 8 sit-to-stand), NZ-1 8, FD-0 h2.5 24, FD-0 h1.4 2, BD mesh 7 (6 + noise h 2.0), BD h2.0 12",
   len(b["rows"]) == 84 == EXP["n_jobs"] and per == EXP["per_layer"] == {"REF": 4, "CD-0": 27, "NZ-1": 8, "FD-0 h2.5": 24, "FD-0 h1.4": 2,
                                                                         "BD mesh": 7, "BD h2.0": 12} and b["n_partner"] == 12, per)
ok("A: expected ids and submission order = the v1 dry run on the 2026-10-25 23:07 UTC read-only copy; all new here (no seed jobs in this "
   "tree, seed check opted out); no problems, no warnings",
   {k: r["expected_id"] for k, r in rows.items()} == EXP["ids"] and [r["key"] for r in b["rows"]] == EXP["order"]
   and all(r["dedup"] == "new" and r["id"] == r["expected_id"] and r["dedup_via"] is None for r in b["rows"]) and b["problems"] == []
   and b["warnings"] == [] and b["seeds"] == [], (b["problems"], b["warnings"]))
v0 = EXP["ids_v0"]
h8_same = all(rows[k]["expected_id"].rsplit("_", 1)[1] == v.rsplit("_", 1)[1] for k, v in v0.items())
pref = all(rows[k]["expected_id"] == (v.replace("db_bd_", "db_bo_", 1) if v.startswith("db_bd_") else v) for k, v in v0.items())
ok("A: every v0 key keeps its hash8 and id; only the 18 bond-only partners change prefix db_bd_ -> db_bo_ (stage is not hashed); one new key",
   h8_same and pref and sum(v.startswith("db_bd_") for v in v0.values()) == 18 and sorted(set(rows) - set(v0)) == ["BD_mesh_v3406_noise_smoke_h16_hint2"])
ok("A: init median = sb13_init_4bb091df (3.579 deg, lower median of the 31 ok round-0 records without init29); pilot16 = the plan's ids",
   b["init_median"]["job_id"] == DB.INIT_MEDIAN == EXP["init_median"] and abs(b["init_median"]["rot_first_deg"] - 3.5793) < 1e-3
   and tuple(b["pilot16"]) == DB.PILOT16_PLAN)
REFID = {1.94: "db_ref_intact_h1.94_0df7c4b7", 2.06: "db_ref_intact_h2.06_f1de5f78", 2.5: "db_ref_intact_h2.5_8ea8a847",
         1.4: "db_ref_intact_h1.4_b7b166b8", 2.0: DB.REF_H2}
ok("A: REF = sb_intact_h2_9c9d7fb5's spec with only h_int changed (kind intact, femur_id, neck_axis isthmus), stage db_ref, heavy; only "
   "REF_h1.4 exclusive",
   all(body(rows[f"REF_h{h:g}"]) == {"kind": "intact", "h_int": h, "femur_id": "sawbone3406", "neck_axis": "isthmus"}
       and rows[f"REF_h{h:g}"]["stage"] == "db_ref" and rows[f"REF_h{h:g}"]["heavy"] and rows[f"REF_h{h:g}"]["id"] == REFID[h]
       for h in DB.REF_H) and [k for k, r in rows.items() if r["exclusive"]] == ["REF_h1.4"], [body(rows[f"REF_h{h:g}"]) for h in DB.REF_H])
SRC = {**DB.CODES, "initmed": DB.INIT_MEDIAN, **dict(zip(DB.PILOT16, DB.PILOT16_PLAN))}
cd_ok = all(body(rows[f"CD0_d{dl:g}_{c}"]) == {**phys(SRC[c]), "delta": dl, "kind": "variant", "fric_only": True}
            for c in DB.CD_PAIR_CODES for dl in (0.025, 0.2)) \
    and all(body(rows[f"CD0_d0.05_{c}"]) == {**phys(SRC[c]), "delta": 0.05, "kind": "variant", "fric_only": True} for c in DB.CD_ALL_CODES)
ok("A: CD-0 delta: A, B, B', C, D, a62 x 0.025 / 0.20 + those and init29 x 0.05 = source spec minus meta / role keys + delta, friction only "
   "(C's intact_job dropped)", cd_ok and sum(k.startswith("CD0_d") for k in rows) == 19)
sts_ok = all(body(rows[f"CD0_sts{ln[1:]}_{c}"]) == {**phys(SRC[c]), "cfg": {"load": D.D13_STS[ln]}, "kind": "variant", "fric_only": True}
             for c in DB.STS_CODES for ln in D.D13_STS)
ok("A: CD-0 sit-to-stand: B, D, a62, init29 x cfg.load = stage_deck.D13_STS (1714 / 3839 N, 24 / 8 deg) exactly, delta 0.10, friction only",
   sts_ok and D.D13_STS == {"F1714": {"resultant_N": 1714.0, "alpha_front_deg": 24.0, "alpha_sagit_deg": 8.0},
                            "F3839": {"resultant_N": 3839.0, "alpha_front_deg": 24.0, "alpha_sagit_deg": 8.0}})
nz_ok = all(body(rows[f"NZ1_h{h:g}_{c}"]) == {**phys(SRC[c]), "h_int": h, "kind": "variant", "intact_job": REFID[h]}
            for c in DB.NZ_CODES for h in DB.NZ_H)
ok("A: NZ-1: B, B', C, D x h_int 1.94 / 2.06, bonded (no fric_only), intact_job = the db_ref of the same h", nz_ok)
fd_ok = all(body(rows[f"FD0_h2.5_{c}"]) == {**phys(SRC[c]), "h_int": 2.5, "kind": "variant", "intact_job": REFID[2.5]}
            for c in list(DB.FD25_CODES) + list(DB.PILOT16)) \
    and all(body(rows[f"FD0_h1.4_{c}"]) == {**phys(SRC[c]), "h_int": 1.4, "slip_tol": D.M_SLIP14, "kind": "variant", "intact_job": REFID[1.4]}
            for c in DB.FD14_CODES)
ok("A: FD-0: the 24 pilot designs x h 2.5 bonded with db_ref h2.5; A, init29 x h 1.4 bonded with db_ref h1.4, slip_tol = stage_deck.M_SLIP14 "
   "(0.000357143), heavy", fd_ok and D.M_SLIP14 == 0.000357143 and rows["FD0_h1.4_A"]["heavy"] and not rows["FD0_h2.5_A"]["heavy"])
mesh_ok = True
for j in DB.MESH_SOURCES:
    r = rows[f"BD_mesh_{DB._tag_of(j)}"]
    h = FIX["jobs"][j]["spec"]["h_int"]
    mesh_ok &= body(r) == {**phys(j), "kind": "variant", "bond_only": True, "intact_job": REFID[h]} and r["partner_of"] == j and r["stage"] == "db_bo"
ok("A: BD mesh: the 6 fric_only mesh variants (d13mesh 4, v3406 noise 2) -> same-mesh bond_only with the db_ref of that h, stage db_bo; "
   "v3406 keeps delta 0.025",
   mesh_ok and rows["BD_mesh_v3406_noise_smoke_h16_hint1.94"]["spec"]["delta"] == 0.025
   and rows["BD_mesh_d13mesh_p13_a105_91e458e3_h1.94"]["spec"]["delta"] == 0.1)
TW = DB.NOISE_H2_SOURCE
rn = rows["BD_mesh_v3406_noise_smoke_h16_hint2"]
ok("A/C: the v3406 noise design's h 2.0 bond_only row: source = its h 2.0 friction-only twin sb11_smoke_f_h16_898709ba (= both noise mesh "
   "sources with h_int 2.0), bond_only, intact_job sb_intact_h2_9c9d7fb5, delta 0.025, stage db_bo",
   body(rn) == {**phys(TW), "kind": "variant", "bond_only": True, "intact_job": DB.REF_H2} and rn["spec"]["h_int"] == 2.0
   and rn["spec"]["delta"] == 0.025 and rn["stage"] == "db_bo" and rn["source_job"] == TW and rn["partner_of"] == TW
   and all(phys(TW) == {**phys(j), "h_int": 2.0} for j in DB.NOISE_MESH) and rn["expected_id"] == "db_bo_v3406_noise_smoke_h16_hint2_683b8f33",
   rn["expected_id"])
need = [c for c, have in b["partners"].items() if not have]
ok("A: BD h2.0: a bond_only partner (ref sb_intact_h2_9c9d7fb5, stage db_bo) exactly for the 12 pilot designs without a usable bonded h 2.0 "
   "result; the 12 covered ones by D13 bond_only jobs (9) or their own bonded source (C, sb14_a74, sb13_a44)",
   sorted(k[len("BD_h2_"):] for k in rows if k.startswith("BD_h2_")) == sorted(need) and len(need) == 12
   and all(body(rows[f"BD_h2_{c}"]) == {**phys(SRC[c]), "kind": "variant", "bond_only": True, "intact_job": DB.REF_H2}
           and rows[f"BD_h2_{c}"]["stage"] == "db_bo" for c in need)
   and b["partners"] == EXP["partners"] and b["partners"]["C"] == ["sb14_a29_6ad70033"]
   and sum(bool(v) and v[0].startswith("d13bond_") for v in b["partners"].values()) == 9, need)
ok("A: no meta key (created / gate / source_job / load_case / db_layer ...) in any spec; every stage in DB_STAGES; tags derived from the source",
   all(not (set(r["spec"]) & (DB.META_KEYS - {"stage", "tag"})) and r["stage"] in DB.DB_STAGES and r["spec"]["tag"] for r in b["rows"])
   and rows["CD0_d0.025_A"]["spec"]["tag"] == "p13_a105_91e458e3_d0.025" and rows["CD0_sts3839_B"]["spec"]["tag"] == "p13_a78_b0f465da_F3839")
REC = ("source", "selection", "layer", "condition_id", "bonded", "model_set", "intact_job", "femur_model_version", "hollow_core", "source_job")
ok("A: per-job record fields (source, selection, layer, condition id, bonded flag, intact_job, femur_model_version 3406R_v1_hollowcore, source_job)",
   all(all(k in r for k in REC) and r["femur_model_version"] == "3406R_v1_hollowcore" and r["hollow_core"] is True for r in b["rows"])
   and rows["CD0_sts3839_B"]["condition_id"] == "d0.1|R3839_af24_as8|h2|slip0.00025"
   and rows["FD0_h1.4_A"]["condition_id"] == "d0.1|stair|h1.4|slip0.000357143" and rows["REF_h1.94"]["condition_id"] == "intact|stair|h1.94"
   and rows["CD0_d0.025_A"]["condition_id"] == "d0.025|stair|h2|slip0.00025"
   and [rows[k]["model_set"] for k in ("REF_h2.5", "CD0_d0.2_B", "NZ1_h1.94_B", "FD0_h2.5_A", "BD_h2_a62")] == ["intact", "fric", "fric+bond",
                                                                                                                 "fric+bond", "bond"]
   and [rows[k]["bonded"] for k in ("REF_h2.5", "CD0_d0.2_B", "NZ1_h1.94_B", "BD_h2_a62")] == [False, False, True, True]
   and {r["source"] for r in b["rows"]} == {"intact_ref", "cond_anchor", "noise", "fid_h25", "fid_h14", "bond_partner"}
   and {r["selection"] for r in b["rows"]} == {"reference", "stratum"}
   and rows["FD0_h2.5_sb14_a70"]["pool_idx"] == 6683 and abs(rows["FD0_h2.5_sb14_a70"]["rot_first_deg_h2"] - 0.7616) < 1e-4)
ok("A: variant strings (diff vs the source spec.json, 'key old -> new')",
   DB.variant_diff(rows["CD0_d0.025_C"]["source_spec"], rows["CD0_d0.025_C"]["spec"])
   == "delta 0.1 -> 0.025, fric_only absent -> True, intact_job sb_intact_h2_9c9d7fb5 -> absent, kind design -> variant"
   and DB.variant_diff(rows["REF_h1.4"]["source_spec"], rows["REF_h1.4"]["spec"]) == "h_int 2.0 -> 1.4"
   and DB.variant_diff(rows["FD0_h1.4_A"]["source_spec"], rows["FD0_h1.4_A"]["spec"])
   == "fric_only True -> absent, h_int 2.0 -> 1.4, intact_job absent -> db_ref_intact_h1.4_b7b166b8, kind design -> variant, slip_tol 0.00025 -> 0.000357143",
   DB.variant_diff(rows["CD0_d0.025_C"]["source_spec"], rows["CD0_d0.025_C"]["spec"]))
ok("A: no row is in the optimisation family of phases 10-14; job ids do not start with sb13_ / sb14_",
   not any(SN.Phase(p).in_family(r["spec"]) for r in b["rows"] for p in (10, 11, 12, 13, 14))
   and not any(r["id"].startswith(("sb13_", "sb14_")) for r in b["rows"]))
ok("A: the six delta-0.025 CD rows would match phase 11 only with legacy=True (stage prefix ignored), which phases 11-14 never use",
   sorted(k for k, r in rows.items() if any(SN.Phase(p).in_family(r["spec"], legacy=True) for p in (11, 12, 13, 14)))
   == sorted(f"CD0_d0.025_{c}" for c in DB.CD_PAIR_CODES))
FQA = write_tree(BASE / "fqa")                                               # jobs.ref_for (what post uses) accepts every bonded / bond_only spec
for h in DB.REF_H:
    add_job(REFID[h], rows[f"REF_h{h:g}"]["spec"], "DONE")
rf = [k for k, r in rows.items() if DB.needs_ref(r["spec"]) and J.ref_for(r["spec"])["intact_job"] != r["spec"]["intact_job"]]
ok("A: jobs.ref_for (explicit_ref) accepts all 53 bonded / bond_only specs against fake DONE references of the same femur",
   rf == [] and sum(DB.needs_ref(r["spec"]) for r in b["rows"]) == 53, rf)

# ================================================================ B. checks reject bad cases
use(FQ)
rsof = lambda j: DB._spec_of(j)                                                  # noqa: E731


def mk(spec, key="X"):
    r = {"key": key, "spec": spec}
    r["expected_id"] = r["id"] = DB.expected_id(spec)
    return r


base = {**phys(DB.CODES["A"]), "kind": "variant", "fric_only": True, "stage": "db_cd", "tag": "base"}   # a baseline-condition db row
ok("B: a baseline-condition db_cd row passes (in no family thanks to the db_ stage)", DB.row_problems(mk(base), rsof, "x") == [])
p_sbdb = DB.row_problems(mk({**base, "stage": "sbdb_cd"}), rsof, "x")
ok("B: the plan's first naming sbdb_cd is refused (not a db_ stage, starts with sb)",
   any("stage 'sbdb_cd' is not a database stage" in x for x in p_sbdb) and any("starts with sb" in x for x in p_sbdb), p_sbdb)
p_sb13 = DB.row_problems(mk({**base, "stage": "sb13"}), rsof, "x")
ok("B: stage sb13 -> refused for the stage, the sb13_ job id, and membership of the phase 13 / 14 family",
   any("job id sb13_base_" in x for x in p_sb13) and any("family of phase(s) [13, 14]" in x for x in p_sb13), p_sb13)
SN.PHASES[13]["warm_stages"] = ("db_cd",)                                        # in memory only: phase 13 would warm-start from db_cd
try:
    p_fam = DB.row_problems(mk(base), rsof, "x")
finally:
    del SN.PHASES[13]["warm_stages"]
ok("B: an in-family db spec (phase 13 patched to accept stage db_cd) is refused", p_fam == ["in the optimisation family of phase(s) [13]"], p_fam)
bad_nz = copy.deepcopy(rows["NZ1_h1.94_B"])
bad_nz["spec"]["intact_job"] = DB.REF_H2
p_nz = DB.row_problems(mk(bad_nz["spec"]), rsof, "x")
ok("B: a bonded h1.94 job pointing at the h 2.0 reference is refused (h_int mismatch, not a db_ref of its own mesh)",
   any("h_int: job 1.94 != reference 2.0" in x for x in p_nz) and any("not a db_ref of its own mesh" in x for x in p_nz), p_nz)
sts_b = {**phys(DB.CODES["B"]), "kind": "variant", "cfg": {"load": dict(D.D13_STS["F3839"])}, "intact_job": DB.REF_H2, "stage": "db_cd", "tag": "x"}
p_sts = DB.row_problems(mk(sts_b), rsof, "x")
ok("B: a stair reference for a 3839 N bonded job is refused (cfg.load mismatch)",
   len(p_sts) == 1 and "cfg.load: job {'resultant_N': 3839.0" in p_sts[0] and "!= reference stair (no cfg)" in p_sts[0], p_sts)
rspec = rows["REF_h2.5"]["spec"]
nz25 = rows["FD0_h2.5_A"]["spec"]
mm = {k: DB.ref_mismatch(nz25, {**rspec, **v}) for k, v in {"E_canc": {"E_canc": 400.0}, "h_far": {"h_far": 8.0}, "neck_axis": {"neck_axis": "readme"},
                                                            "femur_id": {"femur_id": None}, "kind": {"kind": "variant"},
                                                            "cfg_mat": {"cfg": {"materials": {"x": 1}}}}.items()}
ok("B: reference mismatches in E_canc / h_far / neck_axis / femur_id / kind / a cfg key besides load are each reported; a matching ref passes",
   all(len(v) == 1 for v in mm.values()) and DB.ref_mismatch(nz25, rspec) == [] and DB.ref_mismatch(nz25, None) == ["intact reference spec not found"],
   mm)
fo = copy.deepcopy(rows["NZ1_h1.94_B"]["spec"])
fo.pop("intact_job")
fo["fric_only"] = True
p_fo = DB.row_problems(mk(fo), rsof, "x")
ok("B: a friction-only mesh variant (h 1.94) is refused (10-23 rule)", any("10-23 rule" in x for x in p_fo), p_fo)
p_role = DB.row_problems(mk({**base, "bond_only": True}), rsof, "x") + DB.row_problems(mk({**base, "kind": "design"}), rsof, "x")
ok("B: fric_only + bond_only, and kind design, are refused", any("fric_only and bond_only" in x for x in p_role) and any("kind 'design'" in x for x in p_role))
p_h14 = DB.row_problems(mk(rows["FD0_h1.4_A"]["spec"]), lambda j: rows["REF_h1.4"]["spec"], None)
ok("B: an h 1.4 row without an h 1.4 reference in the batch is refused", any("h 1.4 row without" in x for x in p_h14), p_h14)
eid = rows["CD0_d0.05_A"]["expected_id"]
h8 = eid.rsplit("_", 1)[1]
write_tree(BASE / "fqc")
add_job(f"zz_collide_{h8}", {**rows["CD0_d0.05_A"]["spec"], "delta": 0.07, "stage": "zz", "tag": "collide"})
e_col = raises(DB.build, "b1")
ok("B: hash8 collision (same hash8, different spec) -> build refuses", e_col is not None and "hash8 collision" in e_col and f"zz_collide_{h8}" in e_col,
   e_col)
write_tree(BASE / "fqm")
(J.QROOT / f"zz_nospec_{h8}").mkdir()
e_ns = raises(DB.build, "b1")
ok("B: a hash8 hit directory without spec.json -> refuses (cannot compare)", e_ns is not None and "has no readable spec.json" in e_ns, e_ns)
FQE = write_tree(BASE / "fqe")
add_job(f"other_cd_{h8}", {**rows["CD0_d0.05_A"]["spec"], "stage": "other", "tag": "cd"}, "DONE")
be, _ = captured(DB.build, "b1")
re_ = {r["key"]: r for r in be["rows"]}["CD0_d0.05_A"]
ok("B: the same spec (minus stage / tag) under another stage -> recorded as that existing job (dedup existing via hash8), id != expected id",
   re_["dedup"] == "existing" and re_["dedup_via"] == "hash8" and re_["id"] == f"other_cd_{h8}" and re_["expected_id"] == eid and be["problems"] == [])
ok("B: disk gate: 14.9 GiB refused, 15.0 accepted, NaN refused", raises(DB.check_disk, 14.9) is not None and "disk gate" in raises(DB.check_disk, 14.9)
   and raises(DB.check_disk, 15.0) is None and raises(DB.check_disk, float("nan")) is not None)
write_tree(BASE / "fqd")
DB.disk_free_gib = lambda *a: 10.0
e_disk = raises(DB.feed, "b1", poll=0, once=True)
DB.disk_free_gib = lambda *a: 100.0
ok("B: feed with 10 GiB free (no manifest yet) is refused by the first-start gate and submits nothing, writes no manifest",
   e_disk is not None and "first start: 10.0 GiB free" in e_disk and not any(p.name.startswith("db_") for p in J.QROOT.iterdir())
   and not DB.manifest_path("b1").exists(), e_disk)
write_tree(BASE / "fqh")
J.code_hash = lambda: "0000000000"
try:
    e_code = raises(DB.feed, "b1", poll=0, once=True)
    bh, _ = captured(DB.build, "b1")
finally:
    J.code_hash = REAL_CODE
ok("B: a changed code hash -> feed refuses before building, nothing submitted; build lists it as a problem (dry run exit 1)",
   e_code is not None and "code_hash 0000000000 != 6d7af243d0" in e_code and not any(p.name.startswith("db_") for p in J.QROOT.iterdir())
   and any("code_hash 0000000000" in x for x in bh["problems"]), e_code)
write_tree(BASE / "fqk")
sp = json.loads((J.QROOT / DB.CODES["a62"] / "spec.json").read_text())
(J.QROOT / DB.CODES["a62"] / "spec.json").write_text(json.dumps({**sp, "lref05": True}))
e_key = raises(DB.build, "b1")
ok("B: an unclassified key in a source spec (lref05) -> refuses (never dropped silently)", e_key is not None and "not classified" in e_key, e_key)
write_tree(BASE / "fqn", states={DB.CODES["D"]: "NEW"})
e_nd = raises(DB.build, "b1")
ok("B: a source job that is not DONE -> refuses", e_nd is not None and f"source {DB.CODES['D']} is NEW, not DONE" in e_nd, e_nd)
write_tree(BASE / "fqt", states={TW: "NEW"})
e_tw = raises(DB.build, "b1")
ok("B: the noise h 2.0 twin not DONE -> refuses", e_tw is not None and f"source {TW} is NEW, not DONE" in e_tw, e_tw)
write_tree(BASE / "fqi")
st = json.loads((J.RESULTS / "neckopt_p13.json").read_text())
for r in st["records"]:
    if r["job_id"] == DB.INIT_MEDIAN:
        r["rot_first_deg"] = 99.0
(J.RESULTS / "neckopt_p13.json").write_text(json.dumps(st))
e_med = raises(DB.build, "b1")
ok("B: the init-median rule picking another design (state file changed) -> refuses", e_med is not None and "init median" in e_med, e_med)
write_tree(BASE / "fqp")
add_job("sb13_a82_00000000", FIX["jobs"]["sb13_a82_cd8c77ad"]["spec"], "DONE")
e_p16 = raises(DB.build, "b1")
ok("B: an ambiguous pilot short name (two sb13_a82_* jobs) -> refuses", e_p16 is not None and "need exactly one" in e_p16, e_p16)
use(FQ)
DB.CD_DELTA_PAIR = (0.025, 0.025)
try:
    e_dup = raises(DB.build, "b1")
finally:
    DB.CD_DELTA_PAIR = (0.025, 0.20)
ok("B: two keys with the same physical spec (same job id) -> refuses", e_dup is not None and "give the same job id" in e_dup, e_dup)


# ================================================================ C. feeder
OKF = lambda: J.QROOT.parent / DB.H14_OK_NAME                                    # noqa: E731
OKX = lambda: J.QROOT.parent / DB.H14_EXCL_NAME                                  # noqa: E731
PRIO_REFS = (REFID[1.94], REFID[2.06], REFID[2.5])
REF_IDS = set(REFID[h] for h in DB.REF_H)
FD14_IDS = (EXP["ids"]["FD0_h1.4_A"], EXP["ids"]["FD0_h1.4_init29"])


class World:
    """Simulated serve (NEW -> READY, FAILED for names in fail_prep or the first fail_first non-REF, non-seed db jobs), slot-limited worker
    (READY -> CLAIMED -> SOLVED) and post (SOLVED -> DONE, bonded jobs only after their reference is DONE). submit() wraps jobs.submit and checks
    every gate at the moment of submission (incl. the per-layer slow start and the exclusive set: REF_h1.4 + excl_extra).
    ok_file: write DB_H14_REF_OK once REF_h1.4 is DONE (the operator). release: layer slugs (or True = all) whose release file is touched once
    the manifest shows them held for their own failures only (not the first-10 reason). release_all: a batch-wide release file name
    (DB_RELEASE_ALL / DB_RELEASE_b1) touched once a layer is held for the first-10 reason. mutate(step): a hook run at every step.
    max_steps: safety stop (writes STOP, sets timed_out)."""

    def __init__(self, slots=3, fail_prep=(), stop_after=None, ok_file=True, release=None, mutate=None, prio_check=True, max_steps=3000,
                 depth=None, stop_when=None, release_all=None, fail_first=0, excl_extra=()):
        self.slots, self.fail_prep, self.stop_after = slots, set(fail_prep), stop_after
        self.ok_file, self.release, self.mutate, self.prio_check, self.max_steps = ok_file, release, mutate, prio_check, max_steps
        self.depth = DB.MAX_UNCLAIMED if depth is None else depth
        self.stop_when, self.release_all, self.fail_first = stop_when, release_all, fail_first
        self.excl = {REFID[1.4]} | set(excl_extra)
        self.calls, self.viol, self.steps, self.released, self.failed = [], [], 0, {}, []
        self.max_unclaimed = self.max_heavy = self.max_at_submit = self.max_slow = 0
        self.timed_out = False

    def _dirs(self):
        return [d for d in sorted(J.QROOT.iterdir()) if d.is_dir()]

    @staticmethod
    def _spec(d):
        try:
            return json.loads((d / "spec.json").read_text())
        except (OSError, ValueError):
            return None                                                          # truncated / missing spec (section I): serve leaves it alone

    def counts(self):
        unc = heavy = 0
        busy = []
        for d in self._dirs():
            s = J.state(d)
            sp = self._spec(d)
            if d.name.startswith("db_") and s in ("NEW", "READY"):
                unc += 1
            if s in ("NEW", "READY", "CLAIMED") and DB.is_heavy(sp):
                heavy += 1
            if s in ("NEW", "READY", "CLAIMED"):
                busy.append(d.name)
        return unc, heavy, busy

    def submit(self, spec):
        unc, heavy, busy = self.counts()
        jid = DB.expected_id(spec)
        if jid.startswith("db_"):
            self.max_at_submit = max(self.max_at_submit, unc + 1)
        if unc >= self.depth:
            self.viol.append(f"{jid}: submitted with {unc} unclaimed db jobs")
        if DB.is_heavy(spec) and heavy >= 1:
            self.viol.append(f"{jid}: heavy submitted with {heavy} heavy in flight")
        if DB.needs_ref(spec) and J.state(J.QROOT / spec["intact_job"]) != "DONE":
            self.viol.append(f"{jid}: submitted before its reference {spec['intact_job']} is DONE")
        if spec.get("kind") != "intact" and spec["h_int"] <= 1.4:
            if J.state(J.QROOT / REFID[1.4]) != "DONE":
                self.viol.append(f"{jid}: h1.4 row before the h1.4 reference is DONE")
            if not OKF().exists():
                self.viol.append(f"{jid}: h1.4 row without the operator file")
        if jid in self.excl and busy:
            self.viol.append(f"{jid}: exclusive submitted with {len(busy)} jobs NEW / READY / CLAIMED")
        fly_ex = [e for e in self.excl if J.state(J.QROOT / e) in ("NEW", "READY", "CLAIMED")]
        if fly_ex:
            self.viol.append(f"{jid}: submitted while the exclusive {fly_ex} is in flight")
        L = ID2LAYER.get(jid)
        if L in DB.SLOW_START_LAYERS:
            sts = [J.state(J.QROOT / i) for i, l_ in ID2LAYER.items() if l_ == L]
            done, fly = sts.count("DONE"), sum(s in ("NEW", "READY", "CLAIMED", "SOLVED") for s in sts)
            if done < DB.SLOW_START_DONE:
                self.max_slow = max(self.max_slow, fly + 1)
                if fly >= DB.SLOW_START_CAP:
                    self.viol.append(f"{jid}: slow start {L}: submitted with {fly} in flight and {done} DONE")
        if self.prio_check and jid not in REF_IDS:
            active = [r for r in PRIO_REFS if J.state(J.QROOT / r) in ("MISSING", "NEW", "READY")]
            other = [d.name for d in self._dirs() if d.name.startswith("db_") and d.name not in REF_IDS and J.state(d) in ("NEW", "READY")]
            if active and len(other) >= DB.REF_PRIORITY_CAP:
                self.viol.append(f"{jid}: submitted with REF {active} pending / NEW / READY and {len(other)} other unclaimed db jobs")
        self.calls.append(jid)
        return REAL_SUBMIT(spec)

    def step(self, _poll=0):
        self.steps += 1
        if self.mutate:
            self.mutate(self.steps)
        for d in self._dirs():                                                   # post
            if J.state(d) == "SOLVED":
                sp = self._spec(d)
                if sp.get("kind") in ("design", "variant") and not sp.get("fric_only") and J.state(J.QROOT / sp["intact_job"]) != "DONE":
                    continue
                (d / "result.json").write_text(json.dumps({"gruen7": 1.0, "gruen1": 1.0, "job_id": d.name}))
                (d / "DONE").write_text("x")
        for d in self._dirs():                                                   # solve finished
            if J.state(d) == "CLAIMED":
                (d / "SOLVED").write_text("x")
        busy = sum(J.state(d) == "CLAIMED" for d in self._dirs())
        for d in self._dirs():                                                   # claim (mv READY CLAIMED)
            if J.state(d) == "READY" and busy < self.slots:
                (d / "READY").rename(d / "CLAIMED")
                busy += 1
        for d in self._dirs():                                                   # prep
            if J.state(d) == "NEW" and self._spec(d) is not None:
                ff = (self.fail_first and len(self.failed) < self.fail_first and d.name.startswith("db_") and d.name not in REF_IDS
                      and d.name not in SEED_IDS)
                if d.name in self.fail_prep or ff:
                    (d / "FAILED.json").write_text(json.dumps({"level": "L3", "stage": "prep", "reason": f"simulated failure of {d.name}"}))
                    self.failed.append(d.name)
                else:
                    (d / "READY").write_text("x")
        unc, heavy, _ = self.counts()
        self.max_unclaimed, self.max_heavy = max(self.max_unclaimed, unc), max(self.max_heavy, heavy)
        if self.ok_file and J.state(J.QROOT / REFID[1.4]) == "DONE" and not OKF().exists():
            OKF().write_text("operator read the .dat estimate")
        if (self.release or self.release_all) and DB.manifest_path("b1").exists():
            man = json.loads(DB.manifest_path("b1").read_text())
            for slug, g in (man.get("gates") or {}).items():
                if not g.get("held"):
                    continue
                kinds = g.get("kinds") or []
                if self.release and (self.release is True or slug in self.release) and "first10" not in kinds \
                        and g["held_utc"] not in self.released.get(slug, {}):
                    (J.QROOT.parent / f"{DB.RELEASE_PREFIX}{slug}").write_text("checked")
                    self.released.setdefault(slug, {})[g["held_utc"]] = len(self.calls)
                if self.release_all and "first10" in kinds and g["held_utc"] not in self.released.get("*", {}):
                    (J.QROOT.parent / self.release_all).write_text("checked")
                    self.released.setdefault("*", {})[g["held_utc"]] = len(self.calls)
        if (self.stop_after is not None and self.steps >= self.stop_after) or self.steps >= self.max_steps \
                or (self.stop_when is not None and self.stop_when()):
            self.timed_out = self.steps >= self.max_steps
            (J.QROOT.parent / DB.STOP_NAME).write_text("stop")


def run_feed(world, **kw):
    J.submit = world.submit
    try:
        return captured(DB.feed, "b1", poll=0, sleep=world.step, **kw)
    finally:
        J.submit = REAL_SUBMIT


def run_feed_raises(world, **kw):
    J.submit = world.submit
    try:
        return raises(DB.feed, "b1", poll=0, sleep=world.step, **kw)
    finally:
        J.submit = REAL_SUBMIT


def manifest():
    return json.loads(DB.manifest_path("b1").read_text())


# C1. first pass with no progress: REF_h1.94 + exactly one other row (REF priority); a second pass submits nothing
write_tree(BASE / "fc1")
add_job("zz_other_x_bbbbbbbb", {**phys(DB.CODES["A"]), "kind": "design", "fric_only": True, "stage": "zz", "tag": "x"})      # non-db NEW job: not counted
w1 = World()
r1, o1 = run_feed(w1, once=True)
m1 = manifest()
sub1 = [k for k in m1["order"] if m1["rows"][k]["status"] == "submitted"]
r1b, _ = run_feed(w1, once=True)
m1b = manifest()
ok("C/J: first pass, no progress: REF_h1.94 + exactly one other row (REF priority caps other unclaimed db_* at 1; other references wait for "
   "the heavy gate); a second pass submits nothing; the non-db NEW job is not counted",
   r1 == 0 and sub1 == ["REF_h1.94", "CD0_d0.025_A"] and len(w1.calls) == 2
   and sum(m["status"] == "submitted" for m in m1b["rows"].values()) == 2 and w1.viol == [], (sub1, w1.viol))
ok("C: manifest rows carry key / id / expected id / dedup / dedup_via / state / submitted_utc / UTC marker times / record fields; aux md5 and "
   "gates recorded",
   all(set(("key", "id", "expected_id", "dedup", "dedup_via", "seed", "status", "state", "submitted_utc", "times_utc", "source", "selection",
            "layer", "condition_id", "bonded", "intact_job", "femur_model_version", "source_job", "exclusive", "ack_failed")) <= set(m)
       for m in m1["rows"].values())
   and m1["rows"]["REF_h1.94"]["state"] == "NEW" and m1["rows"]["REF_h1.94"]["submitted_utc"].endswith("Z")
   and m1["rows"]["REF_h1.94"]["times_utc"]["spec"].endswith("Z") and m1["code_hash"] == "6d7af243d0"
   and m1["femur_model_version"] == "3406R_v1_hollowcore" and len(m1["rows"]) == 84 and set(m1["aux_md5"]) == set(DB.AUX_FILES)
   and set(m1["gates"]) == {DB.layer_slug(L) for L in EXP["per_layer"]})

# C2. full run with a pre-existing non-db heavy job in flight: all gates hold at every submission; everything DONE; each row submitted once
write_tree(BASE / "fc2")
add_job("mg_ref_intact_h1.4_aaaaaaaa", {"kind": "intact", "h_int": 1.4, "stage": "mg_ref", "tag": "intact_h1.4"})   # CT intact, heavy, NEW
add_job("zz_other_x_bbbbbbbb", {**phys(DB.CODES["A"]), "kind": "design", "fric_only": True, "stage": "zz", "tag": "x"})
w2 = World()
r2, o2 = run_feed(w2)
m2 = manifest()
logt = logtext()
ok("C: full run: exit 0, all 84 rows DONE, every expected id submitted exactly once, no gate violated at any submission (depth, heavy, "
   "reference, h1.4 reference + operator file, exclusive REF_h1.4, REF priority, slow start)",
   r2 == 0 and all(m["state"] == "DONE" and m["status"] == "submitted" for m in m2["rows"].values()) and len(w2.calls) == 84 == len(set(w2.calls))
   and set(w2.calls) == set(EXP["ids"].values()) and w2.viol == [] and not w2.timed_out, (r2, w2.viol[:3], len(w2.calls)))
ok("C: the depth cap binds (a submission brought the unclaimed db jobs to exactly 6, never beyond: World check), at most 1 heavy job "
   "was ever in flight (incl. the non-db CT intact job), and the slow-start cap binds (a new layer reached 2 in flight before 2 DONE, never 3)",
   w2.max_at_submit == 6 and w2.max_heavy == 1 and w2.max_slow == 2, (w2.max_at_submit, w2.max_unclaimed, w2.max_heavy, w2.max_slow))
first_ref = min(i for i, j in enumerate(w2.calls) if j.startswith("db_ref"))
H2P = {r["expected_id"] for r in b["rows"] if r["layer"] == "BD h2.0"}
ok("C: the references waited for the pre-existing heavy job; rows that need no db_ref went in meanwhile, one at a time (REF priority)",
   first_ref > 0 and all(j.startswith("db_cd") or j in H2P for j in w2.calls[:first_ref]), w2.calls[:first_ref + 1])
i14 = w2.calls.index(REFID[1.4])
ok("C/G: REF_h1.4 went after the other three references (only on an idle queue: World check), and both FD h1.4 rows after it",
   i14 > max(w2.calls.index(REFID[h]) for h in (1.94, 2.06, 2.5))
   and all(w2.calls.index(EXP["ids"][k]) > i14 for k in ("FD0_h1.4_A", "FD0_h1.4_init29")), (i14, len(w2.calls)))
ok("C: log (UTC lines) has 84 'submit' lines, the exclusive note and the finished summary; the manifest's times are UTC",
   logt.count(" submit ") == 84 and "batch b1 finished" in logt and "REF_h1.4 is exclusive: no other db submission" in logt
   and all(line[:2] == "20" for line in logt.splitlines()) and all(v.endswith("Z") for m in m2["rows"].values() for v in m["times_utc"].values()))

# C3. restart idempotence: STOP after 12 steps, restart, finish; a submitted row lost from the manifest is found in the queue
write_tree(BASE / "fc3")
w3 = World(stop_after=12)
r3a, o3a = run_feed(w3)
m3a = manifest()
n_sub_a = sum(m["status"] == "submitted" for m in m3a["rows"].values())
e_stop = raises(DB.feed, "b1", poll=0, once=True)
ok("C: STOP file mid-run -> clean exit 0 with the manifest written ('stop file' event); STOP present at start -> refused",
   r3a == 0 and 0 < n_sub_a < 84 and any(e["event"] == "stop file" for e in m3a["events"]) and e_stop is not None and "remove it to start" in e_stop,
   (n_sub_a, e_stop))
lost = next(k for k in m3a["order"] if m3a["rows"][k]["status"] == "submitted" and k.startswith("CD0"))
m3a["rows"][lost].update(status="pending", submitted_utc=None)                 # as if the manifest write after submit had been lost
DB.manifest_path("b1").write_text(json.dumps(m3a))
(J.QROOT.parent / DB.STOP_NAME).unlink()
w3.stop_after = None
calls_a = list(w3.calls)
r3b, o3b = run_feed(w3)
m3b = manifest()
ok("C: restart finishes the batch; no expected id submitted twice across both runs; the row lost from the manifest is recovered from the "
   "queue (not resubmitted)", r3b == 0 and all(m["state"] == "DONE" for m in m3b["rows"].values()) and len(w3.calls) == 84 == len(set(w3.calls))
   and w3.calls[:len(calls_a)] == calls_a and f"{lost}: was pending, now queued" in o3b and w3.viol == [], (lost, len(w3.calls)))
DB.CD_DELTA_ALL = 0.06
try:
    e_chg = raises(DB.feed, "b1", poll=0, once=True)
finally:
    DB.CD_DELTA_ALL = 0.05
ok("C: a changed batch definition against an existing manifest -> refused (keys / expected ids differ)",
   e_chg is not None and "the batch changed since the manifest was written" in e_chg and "CD0_d0.06_A" in e_chg, (e_chg or "")[:300])

# C4. a FAILED reference blocks its dependents (exit 3), the rest finishes
write_tree(BASE / "fc4")
w4 = World(fail_prep={REFID[2.5]})
r4, o4 = run_feed(w4)
m4 = manifest()
blocked = sorted(k for k, m in m4["rows"].items() if m["status"] == "blocked")
ok("C: REF_h2.5 FAILED -> its 24 FD h2.5 dependents blocked (never submitted, ERROR logged), everything else DONE, exit 3; one FAILED "
   "reference is below the layer gate (no hold)",
   r4 == 3 and blocked == sorted(k for k in rows if k.startswith("FD0_h2.5_")) and m4["rows"]["REF_h2.5"]["state"] == "FAILED"
   and all(m["state"] == "DONE" for k, m in m4["rows"].items() if k not in blocked and k != "REF_h2.5")
   and "intact reference db_ref_intact_h2.5_8ea8a847 FAILED; row blocked" in o4 and w4.viol == []
   and f"FAILED REF_h2.5 {REFID[2.5]} (REF): L3 prep: 'simulated failure" in o4 and not any(g["held"] for g in m4["gates"].values()),
   (r4, len(blocked)))

# C5. dedup existing at feed time; lock; Linux-only guard
FQE2 = write_tree(BASE / "fc5")
add_job(f"other_cd_{h8}", {**rows["CD0_d0.05_A"]["spec"], "stage": "other", "tag": "cd"}, "DONE")
w5 = World()
r5, _ = run_feed(w5)
m5 = manifest()
ok("C: a row whose spec already exists under another stage is recorded as that job and never submitted",
   r5 == 0 and m5["rows"]["CD0_d0.05_A"]["status"] == "existing" and m5["rows"]["CD0_d0.05_A"]["id"] == f"other_cd_{h8}"
   and eid not in w5.calls and len(w5.calls) == 83 and w5.viol == [])
lk = BASE / "lock" / "db_feed.lock"
with DB.feed_lock(lk):
    e_lock = raises(lambda: DB.feed_lock(lk).__enter__())
ok("C: a second feeder cannot take the lock while the first holds it", e_lock is not None and "another db feeder" in e_lock, e_lock)
DB._ALLOW_NON_LINUX = False
e_lin = raises(DB.feed, "b1", poll=0, once=True)
DB._ALLOW_NON_LINUX = True
ok("C: feed refuses to run off Linux unless the test hook is set", e_lin is not None and "Linux queue host only" in e_lin)

# ================================================================ D. dry run writes nothing; CLI
FQD = write_tree(BASE / "fdry")
h0 = tree_hash(FQD)
rc, od = captured(DB.main, ["dry-run", "b1", "--root", str(FQD)])
h1 = tree_hash(FQD)
dj = json.loads(od.split("DRY-RUN-JSON", 1)[1])
ok("D: CLI dry-run --root: exit 0, the file tree is byte-identical afterwards (no job dirs, manifest, log or lock)",
   rc == 0 and h0 == h1 and not (FQD / "logs").exists() and not (FQD / "results" / "db_manifest_b1.json").exists())
ok("D: dry-run JSON lists the 84 jobs with expected ids = build's, dedup new, the record fields and the variant strings",
   dj["n_jobs"] == 84 and {j["key"]: j["expected_id"] for j in dj["jobs"]} == EXP["ids"] and all(j["dedup"] == "new" for j in dj["jobs"])
   and dj["n_partner"] == 12 and dj["problems"] == [] and dj["n_new"] == 84 and dj["n_existing"] == 0
   and all("variant" in j and "condition_id" in j and "dedup_via" in j and "ack_failed" in j for j in dj["jobs"])
   and set(dj["aux_md5"]) == set(DB.AUX_FILES) and dj["h14_mode"] == "heavy" and dj["slow_start"]["cap"] == 2)
ok("D: dry-run text prints the per-layer counts, the partner rule, the init-median rule, the legacy-family note, the seed-file status (opted "
   "out here), the exclusive row, the operator files (DB_H14_REF_OK, DB_H14_EXCLUSIVE, DB_RELEASE_ALL / _b1, DB_ACK_FAILED_<key>), the "
   "FD-0 h1.4 mode and the slow start",
   "per layer:" in od and "h 2.0 bond_only partners 12 (of at most 24)" in od and "lower median" in od and "NOTE: 6 rows" in od
   and "seed files declared for batch b1: none" in od and "exclusive (idle queue only" in od and "DB_H14_REF_OK" in od
   and "DB_H14_EXCLUSIVE or the word 'exclusive'" in od and "DB_RELEASE_ALL or DB_RELEASE_b1" in od and "DB_ACK_FAILED_<key>" in od
   and "FD-0 h1.4 mode now: heavy" in od and "slow start: layers ['NZ-1', 'FD-0 h2.5', 'FD-0 h1.4', 'BD mesh', 'BD h2.0'] keep at most 2" in od)
use(FQD)
e_cli = [raises(DB.main, a) for a in (["feed", "b1", "--root", str(FQD)], ["dry-run", "b1", "--once"], ["status", "b1", "--poll", "5"])]
ok("D: CLI option errors: feed --root, dry-run --once, status --poll", all(e == "2" for e in e_cli), e_cli)
use(BASE / "fc2")
_, ost = captured(DB.status, "b1")
ok("D: status prints the finished manifest", '"DONE": 84' in ost and "REF_h1.94" in ost and "FD-0 h1.4 mode:" in ost, ost[:200])

# ================================================================ E. code hash
ok("E: jobs.code_hash() == 6d7af243d0 (the 8 hashed files untouched)", J.code_hash() == "6d7af243d0" == DB.DB_CODE_HASH == FIX["code_hash"])

# ================================================================ F. (A) seed adoption via the physics key
SEEDMAP = {DB.seed_row_key(k): v for k, v in FIX["seed_file"]["jobs"].items()}
FS = write_tree(BASE / "fs", seed=True)
bs, ods = captured(DB.build, "b1")
rs = {r["key"]: r for r in bs["rows"]}
ex = {k: r["id"] for k, r in rs.items() if r["dedup"] == "existing"}
ok("F: with the 27 seed jobs in the queue (17 NEW, 7 READY, 3 CLAIMED): 84 rows = 27 existing via the physics key + 57 new; every CD-0 row "
   "maps 1:1 onto its db_seed_CD0.json id (= the pinned map of the 23:07 UTC dry run); no problems, no warnings",
   len(bs["rows"]) == 84 and ex == SEEDMAP == EXP["seed_map"] and len(set(ex.values())) == 27
   and all(rs[k]["dedup_via"] == "physics" and rs[k]["seed"] == "db_seed_CD0.json" and rs[k]["layer"] == "CD-0" for k in ex)
   and sum(r["dedup"] == "new" for r in bs["rows"]) == 57 and bs["problems"] == [] and bs["warnings"] == []
   and bs["seeds"][0]["adopted"] == SEEDMAP and bs["seeds"][0]["n_jobs"] == 27
   and {v["state"] for v in FIX["seed_queue"].values()} == {"NEW", "READY", "CLAIMED"}, (bs["problems"], bs["warnings"], len(ex)))
ok("F: nothing else changes: the 57 new rows have the same expected ids as without the seeds",
   all(rs[k]["expected_id"] == rows[k]["expected_id"] and rs[k]["id"] == rows[k]["expected_id"] for k in rs if k not in ex))
DB.NOISE_H2_PARTNER = False
try:
    bs83, _ = captured(DB.build, "b1")
finally:
    DB.NOISE_H2_PARTNER = True
ok("F: without the noise h 2.0 row (item A alone) the batch is 83 = 27 existing + 56 new",
   len(bs83["rows"]) == 83 and sum(r["dedup"] == "existing" for r in bs83["rows"]) == 27 and sum(r["dedup"] == "new" for r in bs83["rows"]) == 56)
pair_ok, meta_only = True, True
for k, sid in SEEDMAP.items():
    qsp = json.loads((J.QROOT / sid / "spec.json").read_text())
    pair_ok &= DB.phys_diff(rs[k]["spec"], qsp) == []
    meta_only &= set(qsp) - set(rs[k]["spec"]) <= (DB.META_KEYS | {"created"}) and set(rs[k]["spec"]) - set(qsp) == set() \
        and {x for x in set(qsp) & set(rs[k]["spec"]) if qsp[x] != rs[k]["spec"][x]} <= {"tag"}
ok("F: key by key minus META keys every adopted pair is the same physics (delta, cfg.load, fric_only, design, h_cut, femur_id, neck_axis, "
   "h_int, slip_tol ...); the specs differ only in META keys (db_layer, db_cond, femur_model_version, source_job, load_case, created) and tag",
   pair_ok and meta_only and {"db_layer", "db_cond", "femur_model_version", "source_job", "load_case"} <= DB.META_KEYS
   and set(DB._phys_view(rs["CD0_sts3839_init29"]["spec"])) >= {"delta", "cfg", "fric_only", "design", "h_cut", "femur_id", "neck_axis", "h_int",
                                                                   "slip_tol", "kind", "model", "collar_rule", "min_A0", "margin_check"})
pv = {**rows["CD0_d0.05_A"]["spec"]}
ok("F: physics key: kind design == variant; intact / bench differ; META keys and stage / tag / created ignored; 2 vs 2.0 differ (conservative)",
   DB.phys_key({**pv, "kind": "design", "gate": "g", "source_job": "s", "stage": "zz", "tag": "t", "created": "c"}) == DB.phys_key(pv)
   and DB.phys_key({**pv, "kind": "intact"}) != DB.phys_key(pv) and DB.phys_key({**pv, "kind": "bench"}) != DB.phys_key(pv)
   and DB.phys_key({**pv, "h_int": 2}) != DB.phys_key(pv) and DB.phys_diff(pv, {**pv, "h_int": 2}) == ["h_int 2.0 -> 2"]
   and DB.phys_diff(pv, {**pv, "lref05": True}) == ["lref05 absent -> True"])
# F4. a physics change in one seed (spec.json and seed file both) -> that row stays new, the seed check lists it
FS2 = write_tree(BASE / "fs2", seed=True)
sid = SEEDMAP["CD0_d0.2_B"]
sk_ = next(k for k, v in FIX["seed_file"]["jobs"].items() if v == sid)
qsp = json.loads((J.QROOT / sid / "spec.json").read_text())
(J.QROOT / sid / "spec.json").write_text(json.dumps({**qsp, "delta": 0.2001}))
sf = json.loads((J.RESULTS / "db_seed_CD0.json").read_text())
sf["specs"][sk_]["delta"] = 0.2001
(J.RESULTS / "db_seed_CD0.json").write_text(json.dumps(sf))
DB._SPEC_CACHE.clear()
bf4, _ = captured(DB.build, "b1")
r4_ = {r["key"]: r for r in bf4["rows"]}["CD0_d0.2_B"]
ok("F: a seed whose physics differs (delta 0.2001) is not adopted: the row stays new and the seed check is a problem naming the diff",
   r4_["dedup"] == "new" and any("CD0_delta0.2_B" in p and "not adopted" in p and "delta 0.2 -> 0.2001" in p for p in bf4["problems"])
   and sum(r["dedup"] == "existing" for r in bf4["rows"]) == 26, bf4["problems"])
FS3 = write_tree(BASE / "fs3", seed=True)
sid = SEEDMAP["CD0_d0.05_init29"]
qsp = json.loads((J.QROOT / sid / "spec.json").read_text())
(J.QROOT / sid / "spec.json").write_text(json.dumps({**qsp, "h_int": 2}))       # int for float: different representation
sf = json.loads((J.RESULTS / "db_seed_CD0.json").read_text())
sf["specs"]["CD0_delta0.05_init29"]["h_int"] = 2
(J.RESULTS / "db_seed_CD0.json").write_text(json.dumps(sf))
DB._SPEC_CACHE.clear()
bf5, _ = captured(DB.build, "b1")
ok("F: a seed with h_int 2 (int) instead of 2.0 is not adopted (number representation must match too) -> problem",
   {r["key"]: r for r in bf5["rows"]}["CD0_d0.05_init29"]["dedup"] == "new"
   and any("CD0_delta0.05_init29" in p and "h_int 2.0 -> 2" in p for p in bf5["problems"]), bf5["problems"])
FS4 = write_tree(BASE / "fs4", seed=True)
sid = SEEDMAP["CD0_sts1714_D"]
qsp = json.loads((J.QROOT / sid / "spec.json").read_text())
(J.QROOT / sid / "spec.json").write_text(json.dumps({**qsp, "lref05": True}))
DB._SPEC_CACHE.clear()
bf6, _ = captured(DB.build, "b1")
ok("F: a seed with an unclassified key is not adopted (unknown keys stay in the physics key); the spec also no longer equals the seed file's",
   {r["key"]: r for r in bf6["rows"]}["CD0_sts1714_D"]["dedup"] == "new"
   and any("CD0_sts_F1714_D" in p and "differs from the queue's spec.json" in p for p in bf6["problems"])
   and any("CD0_sts_F1714_D" in p and "lref05" in p for p in bf6["problems"]), bf6["problems"])
FS5 = write_tree(BASE / "fs5", seed=True)
sf = json.loads((J.RESULTS / "db_seed_CD0.json").read_text())
sf["code_hash"] = "1111111111"
sf["specs"]["CD0_delta0.025_A"]["db_cond"] = "something else"
(J.RESULTS / "db_seed_CD0.json").write_text(json.dumps(sf))
bf7, _ = captured(DB.build, "b1")
ok("F: a seed file with another code_hash, or whose spec differs from the queue's spec.json (even in a META key) -> problems",
   any("code_hash '1111111111'" in p for p in bf7["problems"]) and any("CD0_delta0.025_A" in p and "differs from" in p for p in bf7["problems"])
   and len(bf7["problems"]) == 2, bf7["problems"])
FS6 = write_tree(BASE / "fs6", seed=True)
sid = SEEDMAP["CD0_d0.025_C"]
qsp = json.loads((J.QROOT / sid / "spec.json").read_text())
(J.QROOT / sid / "spec.json").write_text(json.dumps({**qsp, "femur_model_version": "3406R_v2_solid"}))
sf = json.loads((J.RESULTS / "db_seed_CD0.json").read_text())
sf["specs"]["CD0_delta0.025_C"]["femur_model_version"] = "3406R_v2_solid"
(J.RESULTS / "db_seed_CD0.json").write_text(json.dumps(sf))
DB._SPEC_CACHE.clear()
bf8, _ = captured(DB.build, "b1")
ok("F: an adopted job carrying another femur_model_version -> problem (feed refuses)",
   bf8["problems"] == ["CD0_d0.025_C: existing job db_cd_C_d0.025_1466fdf1 carries femur_model_version '3406R_v2_solid' != '3406R_v1_hollowcore'"],
   bf8["problems"])
src_prep, src_post = inspect.getsource(J.prep), inspect.getsource(J.post)
src_serve = (ROOT / "v2" / "stage_v2a.py").read_text(encoding="utf-8")
ok("F: jobs.prep / jobs.post branch on kind only for bench / intact (design and variant take the same build / post path); serve waits for "
   "the reference for kind design and variant alike (so adopting variant seeds for design sources changes no physics)",
   re.findall(r'spec\["kind"\]\s*==\s*"(\w+)"', src_prep) == ["bench", "intact"] and src_prep.count('"kind"') == 2
   and re.findall(r'spec\["kind"\]\s*==\s*"(\w+)"', src_post) == ["bench", "intact"] and src_post.count('"kind"') == 4
   and '"kind": spec["kind"]' in src_post                                         # the other two: the runs_v2a.jsonl record line
   and 'spec["kind"] in ("design", "variant") and not spec.get("fric_only")' in src_serve)
# F9. feed with the seeds
FS9 = write_tree(BASE / "fs9", seed=True)
w9 = World(slots=0)
r9, o9 = run_feed(w9, once=True)
m9 = manifest()
lt9 = logtext()
ok("F: feed with the seeds, first pass: 27 rows recorded existing (states NEW / READY / CLAIMED), nothing submitted (24 unclaimed db_* >= 6), "
   "WAIT line with the depth reason and the oldest READY job",
   r9 == 0 and w9.calls == [] and sum(m["status"] == "existing" for m in m9["rows"].values()) == 27
   and {m9["rows"][k]["id"] for k in SEEDMAP} == set(SEEDMAP.values()) and all(m9["rows"][k]["seed"] == "db_seed_CD0.json" for k in SEEDMAP)
   and "depth cap: 24 unclaimed db_* jobs >= 6" in lt9 and "oldest READY db_cd_" in lt9 and "seed db_seed_CD0.json: 27 of 27 adopted" in lt9, lt9[-600:])
FS10 = write_tree(BASE / "fs10", seed=True)
w10 = World()
r10, o10 = run_feed(w10)
m10 = manifest()
ok("F: feed with the seeds, full run: 57 rows submitted once each, no seed id ever submitted, all 84 DONE, no gate violated",
   r10 == 0 and len(w10.calls) == 57 == len(set(w10.calls)) and not (set(w10.calls) & set(SEEDMAP.values()))
   and all(m["state"] == "DONE" for m in m10["rows"].values()) and w10.viol == [] and not w10.timed_out, (r10, w10.viol[:3], len(w10.calls)))

# ================================================================ G. (B) exclusive REF_h1.4 + operator file
FG1 = write_tree(BASE / "fg1")
for h in (1.94, 2.06, 2.5):
    add_job(REFID[h], rows[f"REF_h{h:g}"]["spec"], "DONE")
add_job(REFID[1.4], rows["REF_h1.4"]["spec"], "CLAIMED")
wg1 = World(slots=0)
rg1, og1 = run_feed(wg1, once=True)
ok("G: REF_h1.4 CLAIMED -> no other db row is submitted (every other db submission held); WAIT logged once with the reason",
   rg1 == 0 and wg1.calls == [] and "exclusive REF_h1.4 (db_ref_intact_h1.4_b7b166b8) is CLAIMED: every other db submission is held" in og1,
   og1[-500:])
FG2 = write_tree(BASE / "fg2")
for h in (1.94, 2.06, 2.5):
    add_job(REFID[h], rows[f"REF_h{h:g}"]["spec"], "DONE")
add_job("zz_busy_cccccccc", {**phys(DB.CODES["A"]), "kind": "design", "fric_only": True, "stage": "zz", "tag": "busy"}, "READY")
wg2 = World(slots=0)
rg2, og2 = run_feed(wg2, once=True)
mg2 = manifest()
ok("G/J: REF_h1.4 pending with a non-db READY job in the queue -> it waits for an idle queue (announced once), and it does not trigger "
   "REF priority: the other rows fill the depth cap (6)",
   rg2 == 0 and mg2["rows"]["REF_h1.4"]["status"] == "pending" and len(wg2.calls) == 6 and REFID[1.4] not in wg2.calls
   and "WAIT REF_h1.4: exclusive REF_h1.4 waits for an idle queue" in og2 and wg2.viol == [], (wg2.calls, og2[-400:]))
FG3 = write_tree(BASE / "fg3")
for h in (1.94, 2.06, 2.5):
    add_job(REFID[h], rows[f"REF_h{h:g}"]["spec"], "DONE")
wg3 = World(slots=0)
rg3, og3 = run_feed(wg3, once=True)
ok("G: REF_h1.4 pending on an idle queue -> submitted alone; the pass stops right after it",
   rg3 == 0 and wg3.calls == [REFID[1.4]] and "REF_h1.4 is exclusive: no other db submission" in og3 and wg3.viol == [], wg3.calls)
FG4 = write_tree(BASE / "fg4")
for h in DB.REF_H:
    add_job(REFID[h], rows[f"REF_h{h:g}"]["spec"], "DONE")
wg4 = World(slots=0, ok_file=False, depth=1000)                                  # the feeder runs with max_unclaimed 1000 here
rg4a, og4a = run_feed(wg4, once=True, max_unclaimed=1000)
mg4a = manifest()
ok("G/T: all references DONE but no DB_H14_REF_OK -> FD0_h1.4_* not submitted, WAIT announced naming the operator file; the other rows go "
   "as far as the slow start allows: 35 = 27 CD-0 + 2 each for NZ-1, FD-0 h2.5, BD mesh, BD h2.0",
   rg4a == 0 and all(mg4a["rows"][k]["status"] == "pending" for k in ("FD0_h1.4_A", "FD0_h1.4_init29")) and len(wg4.calls) == 35
   and "WAIT FD0_h1.4_A, FD0_h1.4_init29: operator file" in og4a and "DB_H14_REF_OK missing" in og4a and wg4.viol == [],
   (len(wg4.calls), og4a[-300:]))
ref14_t = (J.QROOT / REFID[1.4] / "spec.json").stat().st_mtime
OKF().write_text("stale")
os.utime(OKF(), (ref14_t - 3600, ref14_t - 3600))
rg4b, og4b = run_feed(wg4, once=True, max_unclaimed=1000)
mg4b = manifest()
ok("G: a DB_H14_REF_OK older than the h 1.4 reference's submission does not count (still waiting, announced as older)",
   rg4b == 0 and mg4b["rows"]["FD0_h1.4_A"]["status"] == "pending" and "is older than the h 1.4 reference's submission" in og4b, og4b[-300:])
OKF().write_text("operator read the .dat estimate")
rg4c, og4c = run_feed(wg4, once=True, max_unclaimed=1000)
mg4c = manifest()
ok("G: a fresh DB_H14_REF_OK -> FD0_h1.4_A submitted (heavy mode: other jobs in flight beside it); FD0_h1.4_init29 waits for the heavy gate",
   rg4c == 0 and mg4c["rows"]["FD0_h1.4_A"]["status"] == "submitted" and mg4c["rows"]["FD0_h1.4_init29"]["status"] == "pending"
   and wg4.viol == [] and "FD-0 h1.4 mode: heavy" in og4c, [mg4c["rows"][k]["status"] for k in ("FD0_h1.4_A", "FD0_h1.4_init29")])

# ================================================================ H. (B) per-layer failure gate
FH = write_tree(BASE / "fh")
bh_, _ = captured(DB.build, "b1")
L_ = []


def new_man():
    L_.clear()
    return DB.open_manifest("b1", bh_, {"key": "k"}, L_.append, {})


def setf(man, key, state, ts):
    man["rows"][key].update(status="submitted", state=state, finished_ts=ts)


def lay(man, layer, status):
    return [k for k in man["order"] if man["rows"][k]["layer"] == layer and man["rows"][k]["status"] == status]


add_job(EXP["ids"]["FD0_h2.5_A"], rows["FD0_h2.5_A"]["spec"], "FAILED", reason="templating: no fit")
mh = new_man()
for k in [k for k in mh["order"] if mh["rows"][k]["layer"] == "CD-0"][:10]:     # 10 CD rows DONE first (the first-10 rule is not involved)
    setf(mh, k, "DONE", 1.0)
setf(mh, "FD0_h2.5_A", "FAILED", 20.0)
DB.gate_pass(bh_, mh, L_.append)
one = not any(g["held"] for g in mh["gates"].values()) and lay(mh, "FD-0 h2.5", "held") == []
setf(mh, "FD0_h2.5_B", "FAILED", 21.0)
DB.gate_pass(bh_, mh, L_.append)
g25 = mh["gates"]["FD-0_h2.5"]
ok("H: layer rule: 1 FAILED in FD-0 h2.5 -> no hold; 2 FAILED of 2 finished (100 % > 5 %) -> the 22 pending FD-0 h2.5 rows held, other "
   "layers untouched, ERROR HOLD logged with the FAILED.json reasons and the release file (no batch-wide file: not a first-10 hold), hold event",
   one and len(lay(mh, "FD-0 h2.5", "held")) == 22 and lay(mh, "FD-0 h2.5", "pending") == [] and g25["held"] and g25["kinds"] == ["layer"]
   and sum(g["held"] for g in mh["gates"].values()) == 1 and len(lay(mh, "CD-0", "pending")) == 17
   and any(x.startswith("ERROR HOLD layer FD-0 h2.5: layer FD-0 h2.5: 2 FAILED of 2 finished (100.0 % > 5 %") and "templating: no fit" in x
           and "DB_RELEASE_FD-0_h2.5" in x and "DB_RELEASE_ALL" not in x for x in L_)
   and mh["events"][-1]["event"] == "hold" and mh["events"][-1]["failed"] == ["FD0_h2.5_A", "FD0_h2.5_B"], L_[-1:])
rel = FH / "DB_RELEASE_FD-0_h2.5"
rel.write_text("x")
os.utime(rel, (g25["held_ts"] - 100, g25["held_ts"] - 100))
DB.gate_pass(bh_, mh, L_.append)
still = g25["held"] and len(lay(mh, "FD-0 h2.5", "held")) == 22
os.utime(rel, (g25["held_ts"] + 0.01, g25["held_ts"] + 0.01))
DB.gate_pass(bh_, mh, L_.append)
ok("H: a release file older than the hold is ignored; touched after the hold -> the 22 rows pending again, FAILED rows acknowledged, "
   "release event + log line",
   still and not g25["held"] and len(lay(mh, "FD-0 h2.5", "pending")) == 22 and g25["ack_failed"] == ["FD0_h2.5_A", "FD0_h2.5_B"]
   and len(g25["releases"]) == 1 and mh["events"][-1]["event"] == "release" and any(x.startswith("RELEASE layer FD-0 h2.5") for x in L_))
setf(mh, "FD0_h2.5_Bp", "FAILED", 22.0)
DB.gate_pass(bh_, mh, L_.append)
no_rehold = not g25["held"]
time.sleep(0.05)
setf(mh, "FD0_h2.5_C", "FAILED", 23.0)
DB.gate_pass(bh_, mh, L_.append)
ok("H: after a release, 1 new FAILED -> no hold; 2 new FAILED -> held again (20 rows); the earlier release file (older than the new hold) "
   "does not release it",
   no_rehold and g25["held"] and len(lay(mh, "FD-0 h2.5", "held")) == 20 and "2 not released yet" in g25["reasons"][0]
   and rel.stat().st_mtime < g25["held_ts"])
rel.unlink()
DB.GATE_MAX_RATE = 0.10                                                         # b1's layers are <= 27 rows: at 5 % any 2 FAILED trip
try:
    mr = new_man()
    cd = [k for k in mr["order"] if mr["rows"][k]["layer"] == "CD-0"]
    for i, k in enumerate(cd[:24]):
        setf(mr, k, "DONE", 100.0 + i)
    setf(mr, cd[24], "FAILED", 200.0)
    setf(mr, cd[25], "FAILED", 201.0)
    DB.gate_pass(bh_, mr, lambda *_: None)
    rate_lo_held = mr["gates"]["CD-0"]["held"]                                   # 2 / 26 = 7.7 % <= 10 %
    setf(mr, cd[23], "FAILED", 202.0)                                            # 3 / 26 = 11.5 % > 10 %
    DB.gate_pass(bh_, mr, lambda *_: None)
    rate_hi_held = mr["gates"]["CD-0"]["held"]
finally:
    DB.GATE_MAX_RATE = 0.05
ok("H: the rate condition (threshold patched to 10 %): 2 FAILED of 26 finished (7.7 %) -> no hold; 3 of 26 (11.5 %) -> the last pending "
   "CD-0 row held", not rate_lo_held and rate_hi_held and lay(mr, "CD-0", "held") == [cd[26]], (rate_lo_held, rate_hi_held))
mf = new_man()
setf(mf, "REF_h1.94", "FAILED", 1.0)
setf(mf, "CD0_d0.025_A", "FAILED", 2.0)
setf(mf, "CD0_d0.2_A", "DONE", 3.0)
setf(mf, "BD_h2_a62", "FAILED", 4.0)
DB.gate_pass(bh_, mf, L_.append)
held_layers = sorted(g["layer"] for g in mf["gates"].values() if g["held"])
ALLF, B1F = FH / "DB_RELEASE_ALL", FH / "DB_RELEASE_b1"
hold_lines = [x for x in L_ if x.startswith("ERROR HOLD layer")]
ok("H: first-10 rule: 3 FAILED among the first 4 finished feeder rows (REF, CD-0, BD h2.0; each layer only 1) -> every layer with pending "
   "rows held (all 7), each with its own ERROR HOLD naming 'batch: 3 of the first 4 finished rows submitted by the feeder FAILED', its "
   "own release file and the batch-wide DB_RELEASE_ALL / DB_RELEASE_b1",
   held_layers == sorted(EXP["per_layer"]) and sum(m["status"] == "pending" for m in mf["rows"].values()) == 0
   and len(hold_lines) == 7 and all("batch: 3 of the first 4 finished rows submitted by the feeder FAILED" in x and str(ALLF) in x
                                    and str(B1F) in x and "every layer held for the first-10 reason" in x for x in hold_lines)
   and all(g["kinds"] == ["first10"] for g in mf["gates"].values()), held_layers)
wl_ = DB.wait_line(mf, {}, {"ready": [], "unclaimed_db": [], "busy_any": []}, 1)
ok("H/Q: the WAIT line names the held layers and, for the first-10 holds, DB_RELEASE_ALL / DB_RELEASE_b1",
   "held layers" in wl_ and f"touch {ALLF} or {B1F} to release them all" in wl_, wl_)
relc = FH / "DB_RELEASE_CD-0"
relc.write_text("x")
os.utime(relc, (mf["gates"]["CD-0"]["held_ts"] + 0.01,) * 2)
DB.gate_pass(bh_, mf, L_.append)
DB.gate_pass(bh_, mf, L_.append)
ok("H: releasing CD-0 alone frees only CD-0 (first-10 acknowledged for that layer: not re-held); the other 6 layers stay held",
   not mf["gates"]["CD-0"]["held"] and mf["gates"]["CD-0"]["first10_ack"] and len(lay(mf, "CD-0", "pending")) == 25
   and sum(g["held"] for g in mf["gates"].values()) == 6)
relc.unlink()
t_hold = max(g["held_ts"] for g in mf["gates"].values() if g["held"])
B1F.write_text("x")
os.utime(B1F, (t_hold - 100,) * 2)                                               # older than the holds: ignored
DB.gate_pass(bh_, mf, L_.append)
stale_b1 = sum(g["held"] for g in mf["gates"].values()) == 6
os.utime(B1F, (t_hold + 0.01,) * 2)
n_ev = len(mf["events"])
DB.gate_pass(bh_, mf, L_.append)
DB.gate_pass(bh_, mf, L_.append)
rel_b1 = [x for x in L_ if x.startswith("RELEASE layer") and str(B1F) in x and "first-10 reason acknowledged" in x]
ok("Q: a DB_RELEASE_b1 older than the holds is ignored; touched after them -> the 6 remaining layers released at once (first-10 acknowledged "
   "on each, not re-held), one RELEASE line and event per layer naming the file",
   stale_b1 and not any(g["held"] for g in mf["gates"].values()) and all(g["first10_ack"] for g in mf["gates"].values())
   and len(rel_b1) == 6 and sum(e["event"] == "release" and e.get("file") == "DB_RELEASE_b1" for e in mf["events"][n_ev:]) == 6
   and sum(m["status"] == "pending" for m in mf["rows"].values()) == 80, (stale_b1, len(rel_b1)))
B1F.unlink()
time.sleep(0.05)
mb = new_man()
bd2 = [k for k in mb["order"] if k.startswith("BD_h2_")]
setf(mb, bd2[0], "FAILED", 1.0)
setf(mb, bd2[1], "FAILED", 2.0)
setf(mb, "NZ1_h1.94_B", "FAILED", 3.0)
DB.gate_pass(bh_, mb, L_.append)
gb = mb["gates"]["BD_h2.0"]
both = gb["held"] and gb["kinds"] == ["layer", "first10"] and sum(g["held"] for g in mb["gates"].values()) == 7
ALLF.write_text("x")
os.utime(ALLF, (max(g["held_ts"] for g in mb["gates"].values() if g["held"]) + 0.01,) * 2)
DB.gate_pass(bh_, mb, L_.append)
partial = (gb["held"] and gb["kinds"] == ["layer"] and gb["first10_ack"] and sum(g["held"] for g in mb["gates"].values()) == 1
           and any("first-10 reason acknowledged for layer BD h2.0; still held for its own failures" in x and "DB_RELEASE_BD_h2.0" in x for x in L_)
           and mb["events"][-1]["event"] == "release_first10")
DB.gate_pass(bh_, mb, L_.append)
still_bd = gb["held"]
relb = FH / "DB_RELEASE_BD_h2.0"
relb.write_text("x")
os.utime(relb, (gb["held_ts"] + 0.01,) * 2)
DB.gate_pass(bh_, mb, L_.append)
ok("Q: a layer held for both reasons (BD h2.0: 2 own FAILED + the first-10 trip): DB_RELEASE_ALL releases the other 6 layers but only "
   "acknowledges the first-10 reason for BD h2.0, which stays held for its own failures until DB_RELEASE_BD_h2.0 is touched",
   both and partial and still_bd and not gb["held"] and len(lay(mb, "BD h2.0", "pending")) == 10 and gb["ack_failed"] == sorted(bd2[:2]),
   (both, partial, still_bd, gb["kinds"]))
ALLF.unlink()
relb.unlink()
m10 = new_man()
order10 = [k for k in m10["order"] if m10["rows"][k]["layer"] == "CD-0"]
for i, k in enumerate(order10[:10]):
    setf(m10, k, "DONE", 10.0 + i)
setf(m10, "REF_h1.94", "FAILED", 50.0)
setf(m10, "NZ1_h1.94_B", "FAILED", 51.0)
setf(m10, "BD_h2_a62", "FAILED", 52.0)
DB.gate_pass(bh_, m10, lambda *_: None)
m2f = new_man()
setf(m2f, "REF_h1.94", "FAILED", 1.0)
setf(m2f, "CD0_d0.025_A", "FAILED", 2.0)
setf(m2f, "CD0_d0.2_A", "DONE", 3.0)
DB.gate_pass(bh_, m2f, lambda *_: None)
ok("H: failures after the first 10 finished feeder rows do not count for the first-10 rule; 2 FAILED of the first 3 is not enough (> 2 needed)",
   not any(g["held"] for g in m10["gates"].values()) and not any(g["held"] for g in m2f["gates"].values()))
# H integration: FD h2.5 failures during a run -> layer held, released by the operator file, finishes
FHI = write_tree(BASE / "fhi")
stale = FHI / "DB_RELEASE_FD-0_h2.5"
stale.write_text("old")
os.utime(stale, (time.time() - 3600,) * 2)
fail2 = {EXP["ids"]["FD0_h2.5_A"], EXP["ids"]["FD0_h2.5_B"]}
wh = World(fail_prep=fail2, release={"FD-0_h2.5"})
rh, oh = run_feed(wh)
mhi = manifest()
gh = mhi["gates"]["FD-0_h2.5"]
hold_ev = [e for e in mhi["events"] if e["event"] == "hold"]
held_keys = [k for k in mhi["order"] if mhi["rows"][k]["layer"] == "FD-0 h2.5" and k not in ("FD0_h2.5_A", "FD0_h2.5_B")]
rel_idx = next(iter(wh.released["FD-0_h2.5"].values()))
late = [k for k in held_keys if EXP["ids"][k] in wh.calls and wh.calls.index(EXP["ids"][k]) < rel_idx]
ok("H: integration: FD0_h2.5_A / _B fail at prep -> FD-0 h2.5 held once (the stale release file from before the hold did not release it), "
   "the operator's release (touched after the hold) frees it, the batch finishes (exit 0, 82 DONE + 2 FAILED), no gate violated",
   rh == 0 and len(hold_ev) == 1 and hold_ev[0]["layer"] == "FD-0 h2.5" and len(gh["releases"]) == 1
   and gh["releases"][0]["file_mtime_utc"] >= gh["held_utc"] and sum(m["state"] == "DONE" for m in mhi["rows"].values()) == 82
   and sorted(k for k, m in mhi["rows"].items() if m["state"] == "FAILED") == ["FD0_h2.5_A", "FD0_h2.5_B"] and wh.viol == [] and not wh.timed_out
   and "ERROR HOLD layer FD-0 h2.5" in oh and "simulated failure of" in oh and "RELEASE layer FD-0 h2.5" in oh, (rh, hold_ev, wh.viol[:2]))
n_held = hold_ev[0]["rows"] if hold_ev else -1
held_at_hold = [k for k in held_keys if EXP["ids"][k] not in wh.calls[:rel_idx]]
ok("H/T: integration: no row of the held layer was submitted between the hold and the release (rows submitted before the hold were already "
   f"in flight: {24 - 2 - n_held}, at most 2 with the slow start)", n_held == len(held_at_hold) and 20 <= n_held <= 22,
   (n_held, len(held_at_hold), late))

# ================================================================ I. (C) JSON robustness + crash logging
FI = write_tree(BASE / "fi")
(J.QROOT / "db_cd_trunc_00000000").mkdir()
(J.QROOT / "db_cd_trunc_00000000" / "spec.json").write_text('{"kind": "vari')
(J.QROOT / "zz_trunc_00000001").mkdir()
(J.QROOT / "zz_trunc_00000001" / "spec.json").write_text("")
snap_i = DB.queue_snapshot()
ok("I: queue_snapshot with a truncated / empty spec.json: no exception; the dirs are unreadable, busy, heavy; the db_ one counts as unclaimed",
   any(u.startswith("db_cd_trunc_00000000 (JSONDecodeError") for u in snap_i["unreadable"]) and any(u.startswith("zz_trunc_00000001") for u in snap_i["unreadable"])
   and {"db_cd_trunc_00000000", "zz_trunc_00000001"} <= set(snap_i["busy_any"]) & set(snap_i["heavy_inflight"])
   and "db_cd_trunc_00000000" in snap_i["unclaimed_db"] and "zz_trunc_00000001" not in snap_i["unclaimed_db"], snap_i["unreadable"])
bi, _ = captured(DB.build, "b1")
ok("I: build with unreadable spec.json dirs that are not hash8 hits: a warning lists them, no crash, no problem",
   any("unreadable spec.json" in w and "db_cd_trunc_00000000" in w for w in bi["warnings"]) and bi["problems"] == [])
wi = World(slots=0)
ri, oi = run_feed(wi, once=True)
lti = logtext()
ok("I: feed with those dirs: no crash; the start WARNING and the per-pass WARNING name them; the unreadable db_ dir and heavy count hold "
   "back the references (heavy gate) and the depth cap counts it",
   ri == 0 and "WARNING queue dirs with an unreadable spec.json" in lti and "WARNING queue dirs without a readable spec.json this pass" in lti
   and "db_cd_trunc_00000000 (JSONDecodeError" in lti and not any(c.startswith("db_ref") for c in wi.calls), lti[-500:])
FI2 = write_tree(BASE / "fi2")
(J.QROOT / f"zz_hit_{h8}").mkdir()
(J.QROOT / f"zz_hit_{h8}" / "spec.json").write_text('{"design": {"L": 4')
e_hit = raises(DB.build, "b1")
ok("I: a truncated spec.json in a hash8-hit dir -> SystemExit (cannot compare)", e_hit is not None and f"zz_hit_{h8}" in e_hit
   and "no readable spec.json" in e_hit, e_hit)
FI3 = write_tree(BASE / "fi3")
J.submit = lambda spec: (_ for _ in ()).throw(RuntimeError("boom in submit"))
try:
    try:
        captured(DB.feed, "b1", poll=0, once=True)
        crashed = None
    except RuntimeError as e:
        crashed = str(e)
finally:
    J.submit = REAL_SUBMIT
lt3 = logtext()
ok("I: an unexpected exception inside the feeder is logged into db_feed.log ('ERROR crashed' + traceback) and re-raised",
   crashed == "boom in submit" and "ERROR crashed: Traceback" in lt3 and "RuntimeError: boom in submit" in lt3, lt3[-300:])
FI4 = write_tree(BASE / "fi4")
wi4 = World(slots=0)
run_feed(wi4, once=True)
jid4 = wi4.calls[1]
(J.QROOT / jid4 / "FAILED.json").write_text('{"level": "L3", "rea')
_, ost4 = captured(DB.status, "b1")
ok("I: a partly written FAILED.json: _fail_reason reports it as unreadable, status does not crash",
   DB._fail_reason(jid4).startswith("FAILED.json unreadable (JSONDecodeError") and "FAILED.json unreadable" in ost4)
(J.RESULTS / "db_manifest_b1.json").write_text('{"batch": "b1", "ro')
e_man = raises(DB.feed, "b1", poll=0, once=True)
bman, _ = captured(DB.build, "b1")
ok("I: a damaged manifest -> feed refuses with a clear message (not a traceback); build only warns about it",
   e_man is not None and "is unreadable (JSONDecodeError" in e_man and any("manifest" in w and "unreadable" in w for w in bman["warnings"]), e_man)

# ================================================================ J. (C) REF priority -- C1 (first pass) and C2 / F10 (World checks at every submission)
FJ = write_tree(BASE / "fj")
refs_done = lambda: all(J.state(J.QROOT / REFID[h]) == "DONE" for h in (1.94, 2.06, 2.5))   # noqa: E731
wj = World(slots=1, stop_when=refs_done)                                         # 1 slot: the references compete with the light rows for it
rj, oj = run_feed(wj)
mj = manifest()
ltj = logtext()
nonref = [c for c in wj.calls if c not in REF_IDS]
ok("J: 1 slot, run until REF_h1.94 / 2.06 / 2.5 are DONE: every non-REF submission while one of them was pending / NEW / READY found 0 other "
   "unclaimed db_* jobs (World check at each submission); light rows still went in meanwhile; the WAIT reason names the REF priority",
   rj == 0 and wj.viol == [] and refs_done() and len(nonref) > 0 and "REF priority (REF_h" in ltj and not wj.timed_out,
   (rj, wj.viol[:2], len(nonref)))

# ================================================================ K. (C) stage db_bo and vocabulary
doc = DB.__doc__
ok("K: bond-only partners use stage db_bo (in DB_STAGES); db_bd stays for the boundary layer; vocabulary intact_ref / bond_partner / "
   "reference / stratum documented in the module docstring",
   "db_bo" in DB.DB_STAGES and "db_bd" in DB.DB_STAGES and all(r["stage"] == "db_bo" and r["expected_id"].startswith("db_bo_")
                                                              for r in b["rows"] if r["layer"].startswith("BD"))
   and sum(r["layer"].startswith("BD") for r in b["rows"]) == 19
   and all(w in doc for w in ("intact_ref", "bond_partner", "reference", "stratum", "cond_anchor", "fid_h25", "db_bo")))

# ================================================================ L. (C) periodic WAIT lines
FL = write_tree(BASE / "fl")
wl = World(slots=0, stop_after=25)
rl_, ol = run_feed(wl)
ltl = logtext()
waits_l = [line for line in ltl.splitlines() if " WAIT idle pass " in line]
ok("L: no progress for 24 passes -> WAIT lines at idle pass 1, 11, 21 only, each with the reasons (heavy gate holder, REF priority, "
   "exclusive, references) and the oldest READY job's age",
   rl_ == 0 and [int(re.search(r"WAIT idle pass (\d+)", x).group(1)) for x in waits_l] == [1, 11, 21]
   and all("heavy gate: db_ref_intact_h1.94_0df7c4b7 in flight" in x and "REF priority" in x and "oldest READY db_" in x and " min;" in x
           and "reference db_ref_intact_h1.94_0df7c4b7 is READY" in x for x in waits_l), waits_l[:1])

# ================================================================ M. (C) first-start disk gate
FM = write_tree(BASE / "fm")
DB.disk_free_gib = lambda *a: 27.9
e_m1 = raises(DB.feed, "b1", poll=0, once=True)
DB.disk_free_gib = lambda *a: 28.0
wm = World(slots=0)
rm1, _ = run_feed(wm, once=True)
DB.disk_free_gib = lambda *a: 20.0
rm2, _ = run_feed(wm, once=True)
DB.disk_free_gib = lambda *a: 14.0
e_m3 = run_feed_raises(wm, once=True)
DB.disk_free_gib = lambda *a: 100.0
ok("M: first start at 27.9 GiB (< 30 GB = 27.94 GiB) refused, nothing written; 28.0 GiB starts; a restart at 20 GiB runs (only the 15 GiB "
   "gate applies once a manifest exists); 14 GiB with pending rows -> disk gate refusal",
   e_m1 is not None and "first start: 27.9 GiB free" in e_m1 and "30 GB" in e_m1 and rm1 == 0 and rm2 == 0 and len(wm.calls) == 2
   and e_m3 is not None and "disk gate: 14.0 GiB free" in e_m3 and abs(DB.FIRST_START_MIN_GIB - 27.94) < 0.01, (e_m1, e_m3))

# ================================================================ N. (C) aux md5
AUXR = BASE / "auxroot"
shutil.rmtree(AUXR, ignore_errors=True)
for rel_ in DB.AUX_FILES:
    if rel_ == "abaqus/odb_export.py":
        continue                                                               # as on Linux: the Windows worker's file is absent
    (AUXR / rel_).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / rel_, AUXR / rel_)
DB.CODE_ROOT = AUXR
try:
    FN = write_tree(BASE / "fn")


    def mut_stab(step):
        if step == 2:
            with open(AUXR / "v2" / "stability.py", "a", encoding="utf-8") as fh:
                fh.write("\n# changed\n")


    wn = World(mutate=mut_stab)
    e_n1 = run_feed_raises(wn)
    mn = manifest()
    ltn = logtext()
    e_n2 = raises(DB.feed, "b1", poll=0, once=True)
    shutil.copyfile(ROOT / "v2" / "stability.py", AUXR / "v2" / "stability.py")
    wn2 = World(mutate=lambda s: (AUXR / "abaqus").mkdir(exist_ok=True) or (AUXR / "abaqus" / "odb_export.py").write_text("x") if s == 1 else None)
    e_n3 = run_feed_raises(wn2)
finally:
    DB.CODE_ROOT = REAL_CODE_ROOT
ok("N: the first start records the md5 of the 6 aux files (absent abaqus/odb_export.py -> null); a change between passes -> ERROR + halt "
   "event + manifest written + stop",
   mn["aux_md5"]["abaqus/odb_export.py"] is None and mn["aux_md5"]["v2/jobs.py"] == hashlib.md5((ROOT / "v2" / "jobs.py").read_bytes()).hexdigest()
   and set(mn["aux_md5"]) == set(DB.AUX_FILES) and e_n1 is not None and "aux code files changed while feeding" in e_n1 and "v2/stability.py" in e_n1
   and mn["events"][-1]["event"] == "halt" and "ERROR refused / stopped: aux code files changed" in ltn, e_n1)
ok("N: a restart with the changed file is refused (aux md5 differs from the manifest); an absent file that appears also stops the feeder",
   e_n2 is not None and "aux file md5 changed since the manifest was written: v2/stability.py" in e_n2
   and e_n3 is not None and "abaqus/odb_export.py: absent -> " in e_n3, (e_n2, e_n3))

# ================================================================ O. physics-path FAILED existing jobs: problem unless acknowledged
FO = write_tree(BASE / "fo")
fspec = {**phys(DB.CODES["A"]), "delta": 0.05, "kind": "design", "fric_only": True, "stage": "zz", "tag": "cdesign", "gate": "x", "source_job": "y"}
fid = J.job_id({**fspec, "created": ""})
add_job(fid, fspec, "FAILED", reason="templating: no fit")
fspecB = {**phys(DB.CODES["B"]), "delta": 0.05, "kind": "design", "fric_only": True, "stage": "zz", "tag": "cdesignB", "gate": "x"}
fidB = J.job_id({**fspecB, "created": ""})
add_job(fidB, fspecB, "FAILED", reason="L4 solve: licence lost")
bo, _ = captured(DB.build, "b1")
ro = {r["key"]: r for r in bo["rows"]}["CD0_d0.05_A"]
e_o = raises(DB.feed, "b1", poll=0, once=True)
ok("O/R: physics-equal FAILED jobs of kind design under another stage (gate / source_job META) -> rows existing via the physics key, each a "
   "problem naming the FAILED reason and DB_ACK_FAILED_<key>; feed refuses, submits nothing",
   ro["dedup"] == "existing" and ro["dedup_via"] == "physics" and ro["id"] == fid and len(bo["problems"]) == 2
   and any(p.startswith(f"CD0_d0.05_A: resolves to existing job {fid}, which is FAILED (L3 prep: 'templating: no fit')")
           and "DB_ACK_FAILED_CD0_d0.05_A" in p for p in bo["problems"])
   and any(p.startswith(f"CD0_d0.05_B: resolves to existing job {fidB}, which is FAILED") for p in bo["problems"])
   and e_o is not None and "2 check problem(s)" in e_o and not any(p.name.startswith("db_") for p in J.QROOT.iterdir()), bo["problems"])
for k in ("CD0_d0.05_A", "CD0_d0.05_B"):
    (FO / f"DB_ACK_FAILED_{k}").write_text("accepted: known failure, the hole is recorded")
bo2, _ = captured(DB.build, "b1")
wo = World(slots=0)
ro2, _ = run_feed(wo, once=True)
mo = manifest()
lto = logtext()
ok("O/R: both acknowledged -> no problems; feed logs the WARNING (accepted) and the FAILED lines; the rows are recorded existing with the "
   "ack and never submitted; CD-0 is not held although 2 of its 2 finished rows FAILED (accepted rows count as acknowledged)",
   bo2["problems"] == [] and ro2 == 0 and f"WARNING CD0_d0.05_A: resolves to existing job {fid}, which is FAILED" in lto
   and "accepted by the operator file" in lto and f"FAILED CD0_d0.05_A {fid} (CD-0)" in lto and EXP["ids"]["CD0_d0.05_A"] not in wo.calls
   and not mo["gates"]["CD-0"]["held"] and all(mo["rows"][k]["ack_failed"] and mo["rows"][k]["status"] == "existing" and
                                                mo["rows"][k]["ack_failed"]["file"].endswith(f"DB_ACK_FAILED_{k}") for k in ("CD0_d0.05_A", "CD0_d0.05_B")),
   bo2["problems"])

# ================================================================ P. (1) first-10 window = feeder-submitted rows only
FP = write_tree(BASE / "fp", seed=True)
bp, _ = captured(DB.build, "b1")
LP = []
mp_ = DB.open_manifest("b1", bp, {"key": "k"}, LP.append, {})
seedkeys = [k for k in mp_["order"] if mp_["rows"][k]["status"] == "existing"]
for i, k in enumerate(seedkeys[:10]):
    mp_["rows"][k].update(state="DONE", finished_ts=1.0 + i)
new3 = ["REF_h1.94", "NZ1_h1.94_B", f"BD_h2_{need[0]}"]
for i, k in enumerate(new3):
    setf(mp_, k, "FAILED", 100.0 + i)
DB.gate_pass(bp, mp_, LP.append)
held_p = sorted(g["layer"] for g in mp_["gates"].values() if g["held"])
v1_first = sorted((m["finished_ts"], k, m["state"]) for k, m in mp_["rows"].items() if m["state"] in ("DONE", "FAILED"))[:10]
ok("P: 10 seeds DONE first + 3 new rows FAILED -> the window holds only feeder-submitted rows (3 of 3 FAILED) -> every layer with pending "
   "rows held for the first-10 reason (REF, NZ-1, FD-0 h2.5, FD-0 h1.4, BD mesh, BD h2.0; CD-0 has none: all 27 rows are seeds); the v1 "
   "window (all finished rows) would have been the 10 DONE seeds and never tripped",
   len(seedkeys) == 27 and held_p == sorted(L for L in EXP["per_layer"] if L != "CD-0") and not mp_["gates"]["CD-0"]["held"]
   and all(g["kinds"] == ["first10"] and "batch: 3 of the first 3 finished rows submitted by the feeder FAILED" in g["reasons"][0]
           for g in mp_["gates"].values() if g["held"])
   and [k for _, k, _s in v1_first] == seedkeys[:10] and all(s_ == "DONE" for _, _, s_ in v1_first), (held_p, LP[-1:]))
mq = DB.open_manifest("b1", bp, {"key": "k"}, LP.append, {})
mq["rows"]["CD0_sts3839_init29"].update(status="pending")                       # as if one CD-0 row were not adopted (CD-0 gets a pending row)
fs3 = [k for k in seedkeys if k != "CD0_sts3839_init29"][:3]
for i, k in enumerate(fs3):
    mq["rows"][k].update(state="FAILED", finished_ts=1.0 + i)
DB.gate_pass(bp, mq, LP.append)
ok("P: seeds stay under the per-layer rule: 3 seeds FAILED -> no first-10 hold (seeds are not in the window), but CD-0 (with one pending row "
   "here) is held for its own failures",
   mq["gates"]["CD-0"]["held"] and mq["gates"]["CD-0"]["kinds"] == ["layer"] and sum(g["held"] for g in mq["gates"].values()) == 1
   and "layer CD-0: 3 FAILED of 3 finished" in mq["gates"]["CD-0"]["reasons"][0], mq["gates"]["CD-0"]["reasons"])
# P integration: live seed states (10 DONE, 3 CLAIMED, 14 READY); the first 3 new non-REF rows fail at prep
sq = list(FIX["seed_queue"])
SS_LIVE = {j: ("DONE" if i < 10 else "CLAIMED" if i < 13 else "READY") for i, j in enumerate(sq)}
FPI = write_tree(BASE / "fpi", seed=True, seed_states=SS_LIVE)
wp = World(fail_first=3, release=True, release_all="DB_RELEASE_ALL")
rp, op = run_feed(wp)
mpi = manifest()
ltp = logtext()
f_keys = sorted(k for k, m in mpi["rows"].items() if m["state"] == "FAILED")
hold_p = [e for e in mpi["events"] if e["event"] == "hold"]
f10_layers = sorted(e["layer"] for e in hold_p if "first10" in e["kinds"])
lay_rule = sorted({ID2LAYER[i] for i in wp.failed if sum(ID2LAYER[x] == ID2LAYER[i] for x in wp.failed) >= 2})
ok("P/Q: integration, live seed states: the first 3 new non-REF rows fail at prep -> one first-10 trip holding every layer with pending rows "
   "(the 6 non-seed layers), ERROR HOLD lines and a WAIT line name DB_RELEASE_ALL / DB_RELEASE_b1; the operator's DB_RELEASE_ALL releases "
   "them (a layer that also failed its own rule waits for its own file); the batch finishes: exit 0, 81 DONE + 3 FAILED, no gate violated",
   rp == 0 and len(wp.failed) == 3 and f_keys == sorted(k for k in EXP["ids"] if EXP["ids"][k] in wp.failed)
   and f10_layers == sorted(L for L in EXP["per_layer"] if L != "CD-0") and sum(m["state"] == "DONE" for m in mpi["rows"].values()) == 81
   and wp.viol == [] and not wp.timed_out and "DB_RELEASE_ALL" in "".join(x for x in ltp.splitlines() if "ERROR HOLD" in x)
   and any(" WAIT idle pass " in x and "to release them all" in x for x in ltp.splitlines())
   and sum(x.count("RELEASE layer") for x in ltp.splitlines() if "DB_RELEASE_ALL" in x) == 6 - len(lay_rule)
   and all(f"first-10 reason acknowledged for layer {L}; still held for its own failures" in ltp for L in lay_rule),
   (rp, wp.failed, f10_layers, lay_rule, wp.viol[:2]))
print(f"    (P integration: failed rows {[k for k in EXP['ids'] if EXP['ids'][k] in wp.failed]}; layers also held by their own rule: {lay_rule})")

# ================================================================ R. (3) FAILED existing jobs; feed-time checks; REF at feed time
FR1 = write_tree(BASE / "fr1")
add_job(f"other_cd_{h8}", {**rows["CD0_d0.05_A"]["spec"], "stage": "other", "tag": "cd"}, "FAILED", reason="L4 solve: licence lost")
br1, _ = captured(DB.build, "b1")
rr1 = {r["key"]: r for r in br1["rows"]}["CD0_d0.05_A"]
rc1, od1 = captured(DB.main, ["dry-run", "b1", "--root", str(FR1)])
e_r1 = raises(DB.feed, "b1", poll=0, once=True)
ok("R: a row resolving via hash8 to a FAILED existing job -> a problem (the FAILED reason and DB_ACK_FAILED_CD0_d0.05_A named); dry run "
   "exit 1; feed refuses, submits nothing, writes no manifest",
   rr1["dedup"] == "existing" and rr1["dedup_via"] == "hash8" and len(br1["problems"]) == 1
   and br1["problems"][0].startswith(f"CD0_d0.05_A: resolves to existing job other_cd_{h8}, which is FAILED (L3 prep: 'L4 solve: licence lost')")
   and "DB_ACK_FAILED_CD0_d0.05_A" in br1["problems"][0] and rc1 == 1 and "PROBLEMS (1;" in od1 and e_r1 is not None
   and "1 check problem(s)" in e_r1 and not any(p.name.startswith("db_") for p in J.QROOT.iterdir()) and not DB.manifest_path("b1").exists(),
   br1["problems"])
(FR1 / "DB_ACK_FAILED_CD0_d0.05_A").write_text("accepted: licence loss, recompute in a later batch")
br1b, _ = captured(DB.build, "b1")
rc1b, od1b = captured(DB.main, ["dry-run", "b1", "--root", str(FR1)])
wr1 = World(slots=0)
rr1b, _ = run_feed(wr1, once=True)
mr1 = manifest()
ok("R: with DB_ACK_FAILED_CD0_d0.05_A: no problem (dry run exit 0, the acceptance printed); feed starts, records the row existing with the "
   "ack (file + time), never submits it, logs the FAILED line",
   br1b["problems"] == [] and any("accepted by the operator file" in w and "DB_ACK_FAILED_CD0_d0.05_A" in w for w in br1b["warnings"])
   and rc1b == 0 and "FAILED existing job accepted: CD0_d0.05_A" in od1b and rr1b == 0
   and mr1["rows"]["CD0_d0.05_A"]["status"] == "existing" and mr1["rows"]["CD0_d0.05_A"]["ack_failed"]["file"].endswith("DB_ACK_FAILED_CD0_d0.05_A")
   and mr1["rows"]["CD0_d0.05_A"]["ack_failed"]["mtime_utc"].endswith("Z") and eid not in wr1.calls
   and f"FAILED CD0_d0.05_A other_cd_{h8} (CD-0)" in logtext())
# a seed adopted at the first start that FAILS later is an ordinary FAILED row, not a problem
FR3 = write_tree(BASE / "fr3", seed=True)
wr3 = World(slots=0)
run_feed(wr3, once=True)
sid3 = SEEDMAP["CD0_d0.2_B"]
(J.QROOT / sid3 / "FAILED.json").write_text(json.dumps({"level": "L4", "stage": "solve", "reason": "simulated seed failure"}))
br3, _ = captured(DB.build, "b1")
rc3, _ = captured(DB.main, ["dry-run", "b1", "--root", str(FR3)])
rr3, _ = run_feed(wr3, once=True)
lt3r = logtext()
mpath = DB.manifest_path("b1")
saved = mpath.read_text()
mpath.unlink()
br3n, _ = captured(DB.build, "b1")
mpath.write_text(saved)
ok("R: a seed that FAILS after the first start (the manifest records the row as that job): not a problem (a note), dry run exit 0, the "
   "restart runs and logs the FAILED line; the same queue without a manifest -> a problem (never adopted before)",
   br3["problems"] == [] and any(w.startswith(f"CD0_d0.2_B: job {sid3} is FAILED") and "already records this row" in w for w in br3["warnings"])
   and rc3 == 0 and rr3 == 0 and f"FAILED CD0_d0.2_B {sid3} (CD-0): L4 solve" in lt3r
   and any(p.startswith(f"CD0_d0.2_B: resolves to existing job {sid3}, which is FAILED") for p in br3n["problems"]), (br3["problems"], br3n["problems"]))
# feed time: a foreign-femur_model_version twin and a FAILED twin appear after the build
FR4 = write_tree(BASE / "fr4")
twin_fmv = {**rows["NZ1_h1.94_B"]["spec"], "stage": "zz", "tag": "fmv", "femur_model_version": "3406R_v2_solid"}
twin_fail = {**rows["NZ1_h1.94_Bp"]["spec"], "stage": "zz", "tag": "fail", "gate": "x"}
N_FMV, N_FAIL = J.job_id({**twin_fmv, "created": ""}), J.job_id({**twin_fail, "created": ""})


def mut_r4(s):
    if s == 1:
        add_job(N_FMV, twin_fmv, "DONE")
        add_job(N_FAIL, twin_fail, "FAILED", reason="L4 solve: worker restarted")


wr4 = World(mutate=mut_r4)
e_r4 = run_feed_raises(wr4)
mr4 = manifest()
ok("R: feed time: a same-physics job with another femur_model_version appears after the build -> when that row's turn comes the feeder stops "
   "(_halt: halt event, manifest written); the row is not submitted",
   e_r4 is not None and f"feed-time dedup: NZ1_h1.94_B: existing job {N_FMV} carries femur_model_version '3406R_v2_solid'" in e_r4
   and mr4["events"][-1]["event"] == "halt" and mr4["rows"]["NZ1_h1.94_B"]["status"] == "pending" and EXP["ids"]["NZ1_h1.94_B"] not in wr4.calls
   and wr4.viol == [] and "ERROR refused / stopped: feed-time dedup" in logtext(), e_r4)
e_r4b = raises(DB.feed, "b1", poll=0, once=True)
ok("R: the restart is refused at build, listing both: the foreign femur_model_version (NZ1_h1.94_B) and the FAILED physics twin "
   "(NZ1_h1.94_Bp, not acknowledged)",
   e_r4b is not None and "2 check problem(s)" in e_r4b and f"NZ1_h1.94_B: existing job {N_FMV} carries femur_model_version" in e_r4b
   and f"NZ1_h1.94_Bp: resolves to existing job {N_FAIL}, which is FAILED" in e_r4b, e_r4b)
shutil.rmtree(J.QROOT / N_FMV)
DB._SPEC_CACHE.clear()
(FR4 / "DB_ACK_FAILED_NZ1_h1.94_Bp").write_text("accepted")
wr4.mutate = None
rr4c, _ = run_feed(wr4)
mr4c = manifest()
ok("R: foreign twin removed + DB_ACK_FAILED_NZ1_h1.94_Bp -> the restart finishes: NZ1_h1.94_Bp recorded existing (the FAILED twin, ack "
   "recorded, never submitted), 83 DONE, NZ-1 never held, every other row submitted once, no gate violated",
   rr4c == 0 and mr4c["rows"]["NZ1_h1.94_Bp"]["id"] == N_FAIL and mr4c["rows"]["NZ1_h1.94_Bp"]["ack_failed"]
   and EXP["ids"]["NZ1_h1.94_Bp"] not in wr4.calls and sum(m["state"] == "DONE" for m in mr4c["rows"].values()) == 83
   and not any(e["event"] == "hold" for e in mr4c["events"]) and wr4.viol == [] and len(wr4.calls) == 83 == len(set(wr4.calls)),
   (rr4c, len(wr4.calls), wr4.viol[:2]))
# feed time: an identical intact spec appears under another stage before REF_h2.06's turn
FR6 = write_tree(BASE / "fr6")
N_REF = f"zz_intact_h2.06_{REFID[2.06].rsplit('_', 1)[1]}"
wr6 = World(mutate=lambda s: add_job(N_REF, {**rows["REF_h2.06"]["spec"], "stage": "zz", "tag": "intact_h2.06"}, "DONE") if s == 1 else None)
e_r6 = run_feed_raises(wr6)
mr6 = manifest()
e_r6b = raises(DB.feed, "b1", poll=0, once=True)
ok("R: feed time: REF_h2.06 resolves to another id (an identical intact spec appeared after the build) -> stop with a message naming both "
   "ids, the dependents and the way out (new batch name); halt event; REF_h2.06 never submitted; the restart is refused",
   e_r6 is not None and f"REF_h2.06: at feed time this reference resolves to {N_REF} (existing via hash8), not to {REFID[2.06]}" in e_r6
   and "dependents" in e_r6 and "NZ1_h2.06_B" in e_r6 and "start a new batch name" in e_r6 and mr6["events"][-1]["event"] == "halt"
   and REFID[2.06] not in wr6.calls and e_r6b is not None, (e_r6, (e_r6b or "")[:300]))

# ================================================================ S. (4) declared seed file missing
FSM = write_tree(BASE / "fsm")
DB.SEEDS = dict(REAL_SEEDS)
try:
    bsm, _ = captured(DB.build, "b1")
    rcm, odm = captured(DB.main, ["dry-run", "b1", "--root", str(FSM)])
    e_sm = raises(DB.feed, "b1", poll=0, once=True)
finally:
    DB.SEEDS = {"b1": ()}
ok("S: the declared seed file results/db_seed_CD0.json missing -> a problem (dry run exit 1, MISSING printed); feed refuses; the explicit "
   "opt-out (SEEDS b1 empty, all other sections) has no such problem",
   len(bsm["problems"]) == 1 and bsm["problems"][0].startswith(f"declared seed file {J.RESULTS / 'db_seed_CD0.json'} (SEEDS['b1']) is missing")
   and rcm == 1 and "seed file db_seed_CD0.json: MISSING" in odm and e_sm is not None and "1 check problem(s)" in e_sm
   and not DB.manifest_path("b1").exists(), bsm["problems"])

# ================================================================ T. (5) per-layer slow start
FT = write_tree(BASE / "ft")
for h in DB.REF_H:
    add_job(REFID[h], rows[f"REF_h{h:g}"]["spec"], "DONE")
wt = World(slots=0, ok_file=False, depth=1000)
rt1, ot1 = run_feed(wt, once=True, max_unclaimed=1000)
mt1 = manifest()
rt1b, ot1b = run_feed(wt, once=True, max_unclaimed=1000)                         # nothing more to submit -> the WAIT line


def nsub(man, L):
    return sum(man["rows"][k]["layer"] == L and man["rows"][k]["submitted_utc"] is not None for k in man["order"])


ok("T: slow start: with every reference DONE and no depth cap, each new layer gets exactly 2 rows in flight (NZ-1, FD-0 h2.5, BD mesh, "
   "BD h2.0), CD-0 (seeds' layer, not slow-started) all 27; the next pass submits nothing and its WAIT line gives the slow-start reasons",
   rt1 == 0 and rt1b == 0 and [nsub(mt1, L) for L in ("CD-0", "NZ-1", "FD-0 h2.5", "BD mesh", "BD h2.0")] == [27, 2, 2, 2, 2]
   and len(wt.calls) == 35 and "slow start NZ-1: 2 rows in flight >= 2 until 2 of its rows are DONE (0 DONE)" in ot1b
   and "slow start BD h2.0: 2 rows in flight" in ot1b and wt.viol == [], ot1b[-600:])
nz_s = [k for k in mt1["order"] if mt1["rows"][k]["layer"] == "NZ-1" and mt1["rows"][k]["submitted_utc"]]
fd_s = [k for k in mt1["order"] if mt1["rows"][k]["layer"] == "FD-0 h2.5" and mt1["rows"][k]["submitted_utc"]]
for k in nz_s + fd_s[:1]:
    mark_done(mt1["rows"][k]["id"])
rt2, ot2 = run_feed(wt, once=True, max_unclaimed=1000)
mt2 = manifest()
ok("T: 2 NZ-1 rows DONE -> the cap lifts and the other 6 NZ-1 rows go; FD-0 h2.5 with 1 DONE + 1 in flight gets exactly 1 more (cap 2 until "
   "2 DONE); BD layers unchanged",
   rt2 == 0 and [nsub(mt2, L) for L in ("NZ-1", "FD-0 h2.5", "BD mesh", "BD h2.0")] == [8, 3, 2, 2] and wt.viol == [],
   [nsub(mt2, L) for L in ("NZ-1", "FD-0 h2.5", "BD mesh", "BD h2.0")])

# ================================================================ U. (6) FD0_h1.4_* exclusive mode
FU = write_tree(BASE / "fu")
md = [DB.h14_mode()]
for txt in ("operator read the .dat estimate: 11 GB, run them exclusive", "ok, 4 GB", "nonexclusive", "EXCLUSIVE."):
    OKF().write_text(txt)
    md.append(DB.h14_mode())
OKF().unlink()
OKX().write_text("x")
md.append(DB.h14_mode())
OKX().unlink()
ok("U: FD-0 h1.4 mode: heavy without files; the word 'exclusive' (any case) in DB_H14_REF_OK -> exclusive; no such word ('ok', "
   "'nonexclusive') -> heavy; DB_H14_EXCLUSIVE present -> exclusive; each with its reason",
   [m_[0] for m_ in md] == [False, True, False, False, True, True] and "DB_H14_EXCLUSIVE present" in md[-1][1]
   and "the word 'exclusive'" in md[1][1] and md[0][1].startswith("heavy"), md)
FU2 = write_tree(BASE / "fu2")
for h in DB.REF_H:
    add_job(REFID[h], rows[f"REF_h{h:g}"]["spec"], "DONE")
OKF().write_text("operator read the .dat estimate")
OKX().write_text("x")
wu2 = World(slots=0, depth=1000, excl_extra=FD14_IDS)
ru2, ou2 = run_feed(wu2, once=True, max_unclaimed=1000)
mu2 = manifest()
ok("U: DB_H14_EXCLUSIVE + a fresh DB_H14_REF_OK: FD0_h1.4_A waits for an idle queue (announced) instead of going beside the light rows; the "
   "mode is logged (exclusive, with the file) and recorded as an event",
   ru2 == 0 and mu2["rows"]["FD0_h1.4_A"]["status"] == "pending" and not (set(FD14_IDS) & set(wu2.calls))
   and "WAIT FD0_h1.4_A, FD0_h1.4_init29: exclusive FD0_h1.4_" in ou2 and "waits for an idle queue" in ou2
   and f"FD-0 h1.4 mode: exclusive ({OKX()} present)" in ou2
   and any(e["event"] == "h14_mode" and e["mode"] == "exclusive" for e in mu2["events"]) and wu2.viol == [], ou2[-400:])
FU3 = write_tree(BASE / "fu3")
for h in DB.REF_H:
    add_job(REFID[h], rows[f"REF_h{h:g}"]["spec"], "DONE")
add_job(FD14_IDS[0], rows["FD0_h1.4_A"]["spec"], "CLAIMED")
OKF().write_text("operator read the .dat estimate")
OKX().write_text("x")
wu3 = World(slots=0)
ru3a, ou3a = run_feed(wu3, once=True)
n3a = len(wu3.calls)
OKX().unlink()
ru3b, ou3b = run_feed(wu3, once=True)
ok("U: FD0_h1.4_A CLAIMED in exclusive mode -> every other db submission held (nothing submitted); the file removed -> heavy mode, the "
   "light rows go again beside it (mode logged at the restart)",
   ru3a == 0 and ru3b == 0 and n3a == 0 and "exclusive FD0_h1.4_A (" in ou3a and "is CLAIMED: every other db submission is held" in ou3a
   and len(wu3.calls) > 0 and FD14_IDS[1] not in wu3.calls and "FD-0 h1.4 mode: heavy" in ou3b, (wu3.calls[:3], ou3a[-300:]))

# ================================================================ U/V. full run: exclusive mode switched on mid-run + HEARTBEAT on a fake clock
FU4 = write_tree(BASE / "fu4")
FAKE = [0.0]


def mut_u(s):
    FAKE[0] += 301.0                                                             # one pass = 301 s of the heartbeat clock
    if s == 3:
        OKX().write_text("x")


DB._mono = lambda: FAKE[0]
try:
    wu = World(mutate=mut_u, excl_extra=FD14_IDS)
    ru, ou = run_feed(wu)
finally:
    DB._mono = REAL_MONO
mu = manifest()
ltu = logtext().splitlines()
i_heavy = next((i for i, x in enumerate(ltu) if "FD-0 h1.4 mode: heavy" in x), None)
i_excl = next((i for i, x in enumerate(ltu) if "FD-0 h1.4 mode: exclusive (" in x), None)
ok("U: full run with DB_H14_EXCLUSIVE written at step 3: the mode change is logged (heavy, then exclusive) and recorded; FD0_h1.4_A and "
   "_init29 run alone, each on an idle queue and with nothing submitted while in flight (World check), after REF_h1.4; all 84 DONE",
   ru == 0 and all(m["state"] == "DONE" for m in mu["rows"].values()) and wu.viol == [] and not wu.timed_out
   and i_heavy is not None and i_excl is not None and i_heavy < i_excl
   and [e["mode"] for e in mu["events"] if e["event"] == "h14_mode"] == ["heavy", "exclusive"]
   and wu.calls[-3:] == [REFID[1.4], *FD14_IDS] and len(wu.calls) == 84 == len(set(wu.calls)), (ru, wu.viol[:2], wu.calls[-3:]))
hb = [(i, x) for i, x in enumerate(ltu) if " HEARTBEAT batch b1: " in x]
last_sub = max(i for i, x in enumerate(ltu) if " submit " in x)
passes = wu.steps + 1
ok("V: HEARTBEAT every 10 min of the (fake) clock regardless of pending rows: about one per 2 passes at 301 s per pass, including passes "
   "that submitted and the tail after the last submission (nothing pending); each line gives the batch rows in flight by state, the oldest "
   "READY age, the last claim and its age",
   abs(len(hb) - (passes + 1) // 2) <= 1 and any(i > last_sub for i, _ in hb) and "2 submitted this pass" in hb[0][1]
   and all("batch rows in flight {" in x and ("oldest READY " in x or "no READY job" in x) and "last claim " in x and " min ago)" in x
           for _, x in hb)
   and any(i > last_sub and '"pending"' not in x for i, x in hb), (len(hb), passes, hb[:1]))

# ================================================================ reset
J.QROOT, J.RESULTS = REAL_Q, REAL_R
J.submit, DB.disk_free_gib, J.code_hash = REAL_SUBMIT, REAL_FREE, REAL_CODE
DB.SEEDS, DB._mono = dict(REAL_SEEDS), REAL_MONO
ok("fixture reset: J.QROOT / J.RESULTS back to ~/mobo_toy_v2 (never written by this test); SEEDS / clock restored; code hash unchanged",
   J.QROOT == REAL_Q and J.RESULTS == REAL_R and DB.CODE_ROOT == REAL_CODE_ROOT and J.code_hash() == "6d7af243d0"
   and DB.SEEDS == {"b1": ("db_seed_CD0.json",)} and DB._mono is REAL_MONO)
bad = [k_ for k_, v in checks if not v]
print(f"\n{len(checks) - len(bad)}/{len(checks)} checks passed in {time.perf_counter() - T_START:.0f} s" + (f"; FAILED: {bad}" if bad else ""))
sys.exit(1 if bad else 0)
