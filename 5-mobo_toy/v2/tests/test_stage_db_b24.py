"""Run with the repo venv: PYTHONUTF8=1 .venv-mobo/Scripts/python.exe v2/tests/test_stage_db_b24.py
Local only: a fake queue in the system temp dir (mobo_toy_db_b24_tests); J.QROOT points there. No gmsh, no FE, no Linux, nothing under
~/mobo_toy_v2 is read or written. Source specs come read-only from db3406/raw; the femur cache is read only.

v2/torsion_load.py, v2/pose_fixed.py and v2/stage_db.py v1.18, batch b24 (TQ-1 and PF-1 smoke):
A. torsion_load: exact moment, zero net force, the plan's formula would add a bending moment, unload blocks and all other lines unchanged, every loaded step rewritten, refusals.
B. torsion_load against the real femur: definition A preload is along the stem axis; both senses agree with the stair head force.
C. pose_fixed: A0 unchanged, the pose moves as written, orthonormal frame, the record, refusals.
D. stage_db: constants; 10 rows; each row differs from its baseline only by cfg.load and torsion, or by pose_fixed; friction only; job ids and condition ids.
E. fail closed: a baseline not DONE, a bad torsion or pose key refuses. Dedup: the same physics under another name -> existing. Earlier job ids did not move.
F. dry_run: exit 0, writes nothing.
G. exporter: the torsion and pose columns are optional, filled from the spec; stage_al and train_scalar drop those rows.
"""
import contextlib
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
sys.path.insert(0, str(ROOT / "tools"))
BASE = pathlib.Path(tempfile.gettempdir()) / "mobo_toy_db_b24_tests"
shutil.rmtree(BASE, ignore_errors=True)
BASE.mkdir(parents=True)

import numpy as np  # noqa: E402

import geom3d as G  # noqa: E402
import jobs as J  # noqa: E402
import model3d_v2 as M  # noqa: E402
import pose_fixed as PF  # noqa: E402
import stage_db as DB  # noqa: E402
import torsion_load as TL  # noqa: E402
import tpl_record as TR  # noqa: E402

T_START = time.perf_counter()
REAL_Q, REAL_R = J.QROOT, J.RESULTS
checks = []
A, REF = DB.CODES["A"], DB.REF_H2
TAG = "p13_a105_91e458e3"
WS = "db_ws_p13_a105_91e458e3_m1_2a79b613"
JOBS = {A, REF, WS}
KEYS = [f"TQ1S_{d}_{e}" for e in ("e0", "e+1.5", "e+2.5") for d in ("A", "B")] + ["PF1S_e0_de-1", "PF1S_e0_de+1", "PF1S_e+1.5_de-1", "PF1S_e+1.5_de+1"]


def ok(name, cond, extra=""):
    checks.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + f"(t={time.perf_counter() - T_START:.0f}s) " + name + (f"  [{extra}]" if extra else ""), flush=True)


def raises(fn, *a):
    try:
        fn(*a)
    except ValueError:
        return True
    return False


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
SRC = json.loads((CACHE / A / "spec.json").read_text())


def queue(name):
    root = BASE / name
    J.QROOT, J.RESULTS = root / "queue", root / "results"
    assert not str(J.QROOT).startswith(str(pathlib.Path.home() / "mobo_toy_v2"))
    J.QROOT.mkdir(parents=True)
    J.RESULTS.mkdir(parents=True)
    for j in JOBS:
        shutil.copytree(CACHE / j, J.QROOT / j)
    ids = {"e0": WS}
    for e in (1.5, 2.5):
        p_ = DB._phys(SRC, A)
        p_["design"] = {**p_["design"], "m": 1.0}
        p_["entry_offset"] = e
        s = DB._variant(p_, "db_ws", f"{TAG}_ow_m1_e{e:+g}", "full", intact_job=REF)
        i = DB.expected_id(s)
        d = J.QROOT / i
        d.mkdir()
        (d / "spec.json").write_text(json.dumps({**s, "created": "x"}, indent=1, default=float))
        (d / "DONE").write_text("")
        ids[f"e{e:+g}"] = i
    return root, ids


INP = """*HEADING
a line that stays
*NSET, NSET=HEADN
5, 6, 7, 8, 9,
10, 11, 12,
*STEP, NAME=PRESSFIT, INC=1000
*BOUNDARY
HEADN, 1, 3
*END STEP
*STEP, NAME=LOAD, INC=1000
*CLOAD, OP=NEW
HEADN, 1, -10.5
HEADN, 2, 3.25
HEADN, 3, -40.
*NODE PRINT
*END STEP
*STEP, NAME=UNLOAD, INC=1000
*CLOAD, OP=NEW
HEADN, 1, 0.
HEADN, 2, 0.
HEADN, 3, 0.
*END STEP
*STEP, NAME=LOAD2, INC=1000
*CLOAD, OP=NEW
HEADN, 1, -10.5
HEADN, 2, 3.25
HEADN, 3, -40.
*END STEP
"""
rng = np.random.default_rng(3)
X0 = rng.normal(size=(8, 3)) * [5.0, 3.0, 1.5] + [50.0, 2.0, 48.0]     # an asymmetric cloud
AX = np.array([-0.7, 0.0, -0.714]); AX = AX / np.linalg.norm(AX)
M0 = 10000.0 * AX

try:
    # ---------------------------------------------------------------- A
    Fc = TL.couple_forces(X0, M0)
    r0 = X0 - X0.mean(0)
    ok("A: couple: zero net force, exact moment", np.linalg.norm(Fc.sum(0)) < 1e-9 and np.linalg.norm(np.cross(r0, Fc).sum(0) - M0) < 1e-6)
    perp = r0 - (r0 @ AX)[:, None] * AX
    plan = 10000.0 * np.cross(AX, r0) / (perp * perp).sum()
    m_plan = np.cross(r0, plan).sum(0)
    ok("A: the plan's formula would add a bending moment on this cloud (why it is not used)", abs(m_plan @ AX - 10000.0) < 1e-6 and np.linalg.norm(m_plan - (m_plan @ AX) * AX) > 100.0, f"{np.linalg.norm(m_plan - (m_plan @ AX) * AX):.0f} N*mm")
    ok("A: head nodes parsed across lines", TL.head_nodes(INP) == [5, 6, 7, 8, 9, 10, 11, 12])
    new, rec = TL.rewrite(INP, TL.head_nodes(INP), X0, M0)
    ok("A: two loaded steps rewritten, unload unchanged", rec["n_load_steps"] == 2 and new.count("HEADN, 1, 0.") == 1 and new.count("HEADN, 1, -10.5") == 0 and new.count("5, 1, ") == 2, json.dumps(rec)[:160])
    a_lines = [l for l in INP.splitlines() if not l.startswith("HEADN, 1, -") and not l.startswith("HEADN, 2, 3") and not l.startswith("HEADN, 3, -40")]
    b_lines = [l for l in new.splitlines() if not (l[0].isdigit() and len(l.split(",")) == 3)]
    ok("A: every other line is unchanged, in order", a_lines == b_lines)
    body = new.split("*STEP, NAME=LOAD, INC=1000")[1].split("*END STEP")[0]
    vals = {}
    for l in body.splitlines():
        if l and l[0].isdigit():
            n_, k_, v_ = l.split(",")
            vals[(int(n_), int(k_))] = float(v_)
    Ft = np.array([[vals[(n_, k_)] for k_ in (1, 2, 3)] for n_ in TL.head_nodes(INP)])
    ok("A: the written forces carry the head force and the couple", len(vals) == 24 and np.allclose(Ft.sum(0), np.array([-10.5, 3.25, -40.0]) * 8, atol=1e-5) and np.linalg.norm(np.cross(r0, Ft).sum(0) - M0) < 1e-3)
    ok("A: no loaded block refuses", raises(TL.rewrite, INP.replace("-10.5", "0.").replace("3.25", "0.").replace("-40.", "0."), [5, 6, 7, 8, 9, 10, 11, 12], X0, M0))
    ok("A: bad keys refuse", all(raises(TL.validate, x) for x in ({"def": "C", "T_Nm": 10}, {"def": "A", "T_Nm": 0}, {"def": "A"}, {"def": "A", "T_Nm": 10, "x": 1}, "A")))
    ok("A: friction only", raises(TL.apply, BASE, {"torsion": {"def": "A", "T_Nm": 10.0}}, None, None))

    # ---------------------------------------------------------------- B
    queue("view")
    sA = json.loads((J.QROOT / WS / "spec.json").read_text())
    rule = TR.spec_rule(sA)
    fm = TR.base_femur(rule.femur_id, rule.neck_axis)
    if sA.get("h_cut") is not None:
        fm = fm.with_cut(float(sA["h_cut"]))
    st = G.Stem3D(**sA["design"])
    pose = fm.pose(sA["design"]["alpha"], 0.0)
    ax = pose[1] / np.linalg.norm(pose[1])
    F = M.load_vector({"load": TL.axial_load(pose[1], 1000.0)})
    ok("B: definition A preload is along the stem axis, pointing distally", np.linalg.norm(F / 1000.0 - ax) < 1e-12, F.round(3).tolist())
    ok("B: the head force of definition A has no torque about the stem axis", abs(np.cross(np.asarray(fm.H, float) - pose[0], F) @ ax) < 1e-6)
    Ma, axa = TL.target_moment({"def": "A", "T_Nm": 10.0}, fm, pose)
    Mb, axb = TL.target_moment({"def": "B", "T_Nm": 10.0}, fm, pose)
    Fst = M.load_vector({"load": TL.STAIR_LOAD})
    T_st = float(np.cross(np.asarray(fm.H, float) - pose[0], Fst) @ ax)
    ok("B: both senses add to the stair torque; magnitudes are right", Ma @ ax * T_st > 0 and Mb @ ax * T_st > 0 and abs(np.linalg.norm(Ma) - 1e4) < 1e-6 and abs(np.linalg.norm(Mb) - 1e4) < 1e-6 and np.allclose(axa, ax), f"T_stair {T_st / 1000:.2f} N*m, Mb.ax {Mb @ ax / 1000:.2f}")
    ok("B: the stair torque matches the exporter's number", abs(abs(T_st) / 1000 - 4.72) < 0.01, f"{abs(T_st) / 1000:.3f}")

    # ---------------------------------------------------------------- C
    pl = G.template(st, fm) if False else None
    v = TR.record_spec(sA)["prep_view"]
    pl = {"alpha": v["alpha"], "e": v["e"], "A0": v["A0"], "margin": 1.0, "pose": pose}
    a1, e1, p1 = PF.moved_pose(fm, pl, {"de": -1.0})
    p_ref = fm.pose(v["alpha"], -1.0)
    ok("C: de moves along the entry offset, nothing else", e1 == -1.0 and a1 == v["alpha"] and all(np.allclose(p1[i], p_ref[i]) for i in range(4)))
    _, _, p2 = PF.moved_pose(fm, pl, {"ds": 1.0})
    ok("C: ds moves along the stem axis", np.allclose(p2[0] - np.asarray(pose[0]), pose[1]) and np.allclose(p2[1], pose[1]))
    _, _, p3 = PF.moved_pose(fm, pl, {"rot_deg": 3.0})
    ok("C: rot keeps the axis and the frame orthonormal, turns by 3 deg", np.allclose(p3[1], pose[1]) and abs(p3[2] @ p3[3]) < 1e-12 and abs(p3[2] @ p3[1]) < 1e-12 and abs(np.degrees(np.arccos(p3[2] @ pose[2])) - 3.0) < 1e-9)
    a4, _, p4 = PF.moved_pose(fm, pl, {"dalpha_deg": 3.0})
    ok("C: dalpha turns the axis by 3 deg", a4 == v["alpha"] + 3.0 and abs(np.degrees(np.arccos(p4[1] @ pose[1] / np.linalg.norm(p4[1]) / np.linalg.norm(pose[1]))) - 3.0) < 1e-9)
    n_ = PF.apply(st, fm, pl, {"de": 1.0})
    r_ = n_["pose_fixed"]
    ok("C: apply keeps A0, updates e, records penetration and overhang", n_["A0"] == v["A0"] and n_["e"] == 1.0 and r_["A0"] == v["A0"] and r_["nominal_e"] == 0.0 and r_["penetration_vs_margin_mm"] > 0.0 and set(r_) >= {"penetration_vs_endosteum_mm", "neck_overhang_mm2"}, json.dumps({k: round(x, 3) for k, x in r_.items()}))
    ok("C: bad keys refuse", all(raises(PF.validate, x) for x in ({}, {"de": 0.0}, {"x": 1.0}, {"de": "1"})))

    # ---------------------------------------------------------------- D
    ok("D: b24 in BATCHES, code_hash unchanged, keys classified", "b24" in DB.BATCHES and J.code_hash() == DB.DB_CODE_HASH and {"torsion", "pose_fixed"} <= DB.PHYS_KEYS)
    ok("D: layers", DB.LAYER_SOURCE["TQ-1 smoke"] == "cond_anchor" and DB.LAYER_SOURCE["PF-1 smoke"] == "cond_anchor" and "TQ-1 smoke" in DB.SLOW_START_LAYERS and "PF-1 smoke" in DB.SLOW_START_LAYERS and "v2/torsion_load.py" in DB.AUX_FILES and "v2/pose_fixed.py" in DB.AUX_FILES)
    _, ids = queue("rows")
    b = DB.build("b24")
    rows = {r["key"]: r for r in b["rows"]}
    ok("D: no problems on a clean queue", not b["problems"], "; ".join(b["problems"])[:600])
    ok("D: 10 rows in order", list(rows) == KEYS, list(rows)[:5])
    fine = True
    F3839 = DB.STS_LOADS["F3839"]
    for k, r in rows.items():
        s = r["spec"]
        lab = k.split("_")[2] if k.startswith("TQ1S") else k.split("_")[1]
        b0 = json.loads((J.QROOT / ids[lab] / "spec.json").read_text())
        same = s["design"] == b0["design"] and s.get("entry_offset") == b0.get("entry_offset") and s["delta"] == b0["delta"] and s["fric_only"] and "intact_job" not in s and s["stage"] == "db_cd" and r["model_set"] == "fric" and not r["heavy"]
        if k.startswith("TQ1S_A"):
            same = same and s["torsion"] == {"def": "A", "T_Nm": 10.0} and s["cfg"]["load"] == TL.axial_load(fm.pose(s["design"]["alpha"], 0.0)[1], 1000.0) and "pose_fixed" not in s
        elif k.startswith("TQ1S_B"):
            same = same and s["torsion"] == {"def": "B", "T_Nm": 10.0} and s["cfg"]["load"] == F3839 and "pose_fixed" not in s
        else:
            same = same and s["pose_fixed"] == {"de": float(k.split("_de")[1])} and "torsion" not in s and "cfg" not in s
        fine = fine and same
    ok("D: each row differs from its baseline only by the written condition", fine)
    ok("D: job ids", rows["TQ1S_A_e0"]["expected_id"].startswith(f"db_cd_{TAG}_m1_TA10_") and rows["TQ1S_B_e+2.5"]["expected_id"].startswith(f"db_cd_{TAG}_ow_m1_e+2.5_TB10_") and rows["PF1S_e0_de-1"]["expected_id"].startswith(f"db_cd_{TAG}_m1_pf_de-1_") and rows["PF1S_e+1.5_de+1"]["expected_id"].startswith(f"db_cd_{TAG}_ow_m1_e+1.5_pf_de+1_"), rows["PF1S_e+1.5_de+1"]["expected_id"])
    ok("D: condition ids carry the hook", rows["TQ1S_A_e0"]["condition_id"].endswith("|TA10") and rows["PF1S_e0_de-1"]["condition_id"].endswith("|posede-1"), rows["PF1S_e0_de-1"]["condition_id"])
    ok("D: all new; the controls are the e rows", all(r["dedup"] == "new" for r in rows.values()) and b["ws_control"] == ids, json.dumps(b["ws_control"])[:200])

    # ---------------------------------------------------------------- E
    _, ids = queue("fail")
    (J.QROOT / ids["e+2.5"] / "DONE").unlink()
    ok("E: a baseline not DONE is a problem", [p for p in DB.build("b24")["problems"] if "the baseline e+2.5" in p])
    (J.QROOT / WS / "DONE").unlink()
    ok("E: WS_m1 not DONE is a problem", [p for p in DB.build("b24")["problems"] if "the baseline e0" in p])
    queue("dedup")
    r0 = {r["key"]: r for r in DB.build("b24")["rows"]}["PF1S_e0_de-1"]
    other = {**r0["spec"], "tag": "somewhere_else", "created": "x"}
    d = J.QROOT / "db_cd_somewhere_else_00000000"
    d.mkdir()
    (d / "spec.json").write_text(json.dumps(other, indent=1, default=float))
    (d / "DONE").write_text("")
    r2 = {r["key"]: r for r in DB.build("b24")["rows"]}["PF1S_e0_de-1"]
    ok("E: the same physics under another name is adopted", r2["dedup"] == "existing" and r2["id"] == d.name, f"{r2['dedup']} {r2['id']}")
    shutil.rmtree(d)
    r14 = {r["key"]: r for r in DB.build("b14")["rows"]}
    ok("E: the b14 job id did not move", r14["WS_m1"]["expected_id"] == WS)

    # ---------------------------------------------------------------- F
    root, _ = queue("dry")
    before = sorted(str(x.relative_to(root)) for x in root.rglob("*"))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = DB.dry_run("b24")
    out = buf.getvalue()
    ok("F: dry run exits 0, lists 10 jobs, writes nothing", rc == 0 and "jobs (10):" in out and before == sorted(str(x.relative_to(root)) for x in root.rglob("*")), out[-300:] if rc else "")

    # ---------------------------------------------------------------- G
    import db_export as DX
    ver = tuple(int(x) for x in DX.EXPORTER_VERSION.split()[1].split("."))          # 11-08: 0.2.5 adds foam_refine
    ok("G: exporter version >= 0.2.4 and the two AUX files", ver >= (0, 2, 4) and "v2/torsion_load.py" in DX.AUX_FILES and "v2/pose_fixed.py" in DX.AUX_FILES)
    src = (ROOT / "tools/db_export.py").read_text(encoding="utf-8")
    ok("G: the columns are optional now and filled from the spec", '_c("torsion", "json", "", req="optional"' in src and '_c("pose", "json", "", req="optional"' in src and 'torsion=spec.get("torsion"), pose=spec.get("pose_fixed"),' in src)
    src = (ROOT / "v2/stage_al.py").read_text(encoding="utf-8")
    ok("G: stage_al drops hook rows", 'no("torsion / pose hook")' in src)
    src = pathlib.Path(r"H:/projects/Femoral implant generation/ml3406/code/train_scalar.py").read_text(encoding="utf-8")
    ok("G: train_scalar drops hook rows", 'if r.get("torsion") or r.get("pose"):' in src)
finally:
    J.QROOT, J.RESULTS = REAL_Q, REAL_R
    shutil.rmtree(BASE, ignore_errors=True)

n_fail = sum(not c for _, c in checks)
print(f"{len(checks) - n_fail}/{len(checks)} passed, {n_fail} failed")
sys.exit(1 if n_fail else 0)
