"""Tests of b33's gates G53-G55 before they are frozen. Local, read only on db3406 v0.13; writes a temp dir only.

    PYTHONUTF8=1 ../../.venv-mobo/Scripts/python.exe test_gates_b33.py

A. constants as b31 (curve, 3b, the better-than-3b routes, mesh_F) and b28 (STS curve, G44 / G45 limits); CAND = stage_db.R2C_WINNERS with R2's offsets.
B. v0.13 (no conditional rows yet): every gate NA; 3b reproduced.
C. synthetic rows (v0.13 plus made-up h 1.94, h 1.4 and 1714 N rows; their mesh F patched in): G53 PASS / FAIL / NA, G54 and G55 PASS / FAIL / NA,
   unconfirmed candidates only described, 3b drift.
"""
import csv
import importlib.util
import inspect
import math
import pathlib
import shutil
import sys
import tempfile

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
V13 = pathlib.Path(r"H:/projects/Femoral implant generation/db3406/v0.13")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "v2"))
import stage_db as DB  # noqa: E402

checks = []


def ok(name, cond, extra=""):
    checks.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""), flush=True)


def load(path, name):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


g = load(HERE / "gates.py", "g33")
g31 = load(ROOT / "experiments" / "b31_r2" / "gates.py", "g31")
g28 = load(ROOT / "experiments" / "b28_fam" / "gates.py", "g28")
REAL = g.mesh_F
ok("A: curve, 3b, routes, mesh_F as b31", g.CURVE == g31.CURVE and (g.JOB_3B, g.DF3, g.DL3, g.TOL_F, g.TOL_L) == (g31.JOB_3B, g31.DF3, g31.DL3, g31.TOL_F, g31.TOL_L)
   and (g.IMP_F, g.IMP_L, g.IMP_L2, g.IMP_F2, g.DF1, g.R1, g.R2, g.DF2) == (g31.IMP_F, g31.IMP_L, g31.IMP_L2, g31.IMP_F2, g31.DF1, g31.R1, g31.R2, g31.DF2)
   and inspect.getsource(g.mesh_F) == inspect.getsource(g31.mesh_F))
ok("A: STS curve and limits as b28", g.STS_CURVE == g28.STS_CURVE and (g.MAX_STS, g.MAX_H14) == (g28.MAX_STS, g28.MAX_H14))
ok("A: CAND = stage_db.R2C_WINNERS with R2's offsets", list(g.CAND) == list(DB.R2C_WINNERS) and all(g.CAND[k] == g31.PRED[k][0] for k in g.CAND)
   and all(g.tag_of(k) == g31.tag_of(k) for k in g.CAND))
out = g.judge(str(V13))
ok("B: v0.13 (none of the 9 rows submitted) -> every gate NA, batch not finished", all(v["status"] == "NA" for v in out.values()) and "还没算完" in out["G53"]["note"],
   str({k: v["status"] for k, v in out.items()}))

with open(V13 / "scalars.csv", encoding="utf-8") as fh:
    R13 = list(csv.DictReader(fh))
by_id = {r["job_id"]: r for r in R13}
by_tag = {r["tag"]: r for r in R13}
cols = list(R13[0].keys())
KEEP = set(g.CURVE) | {g.JOB_3B, g.JOB_3B_REP} | set(g.STS_CURVE.values()) | {by_tag[t]["job_id"] for t in g.STS_CURVE} | {by_tag[g.tag_of(k)]["job_id"] for k in g.CAND}
REAL_F = REAL(str(V13), KEEP)
cb = np.array([float(by_id[j]["bone_total_mm3"]) / 1000 for j in g.CURVE])
o = np.argsort(cb)
cb, cF, cl = cb[o], np.array([REAL_F[j] for j in g.CURVE])[o], np.log10([float(by_id[j]["f1_p95_um"]) for j in g.CURVE])[o]
sts = sorted((float(by_id[b]["bone_total_mm3"]) / 1000, math.log10(float(by_tag[t]["rot_first_deg"]))) for t, b in g.STS_CURVE.items())
sb, sr = (np.array(v) for v in zip(*sts))
TMP = pathlib.Path(tempfile.mkdtemp(prefix="gates_b33_"))


def run(spec, edit=None):
    """spec: lab -> dict(rep=(dF, dl, status) or None, h14=(shift, status) or None, sts=(ratio, status) or None); default all good."""
    rows, fake = [], {}
    for lab in g.CAND:
        m = by_tag[g.tag_of(lab)]
        bone = float(m["bone_total_mm3"])
        s = spec.get(lab, {})
        rep = s.get("rep", (14.0, -0.13, "DONE"))
        if rep is not None:
            r = {c: "" for c in cols}
            jid = f"j_rep_{lab}"
            r.update(tag=g.tag_of(lab) + "_h1.94", job_id=jid, status=rep[2], bone_total_mm3=repr(bone), f1_p95_um=repr(10 ** (float(np.interp(bone / 1000, cb, cl)) + rep[1])))
            fake[jid] = float(np.interp(bone / 1000, cb, cF)) + rep[0]
            rows.append(r)
        h14 = s.get("h14", (0.02, "DONE"))
        if h14 is not None:
            r = {c: "" for c in cols}
            r.update(tag=g.tag_of(lab) + "_h1.4", job_id=f"j_h14_{lab}", status=h14[1], bone_total_mm3=repr(bone), f1_p95_um=repr(float(m["f1_p95_um"]) * 10 ** h14[0]))
            rows.append(r)
        st = s.get("sts", (0.95, "DONE"))
        if st is not None:
            r = {c: "" for c in cols}
            r.update(tag=g.tag_of(lab) + "_F1714", job_id=f"j_sts_{lab}", status=st[1], bone_total_mm3=repr(bone), f1_p95_um="1.0",
                     rot_first_deg=repr(st[0] * 10 ** float(np.interp(bone / 1000, sb, sr))))
            rows.append(r)
    base = [dict(by_id[j]) for j in sorted(KEEP)]
    if edit:
        edit(base)
    d = TMP / f"db{len(list(TMP.iterdir()))}"
    d.mkdir()
    with open(d / "scalars.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(base + rows)
    g.mesh_F = lambda db_dir, want: {k: v for k, v in {**REAL_F, **fake}.items() if k in want}
    try:
        return g.judge(str(d))
    finally:
        g.mesh_F = REAL


try:
    v = run({})
    ok("C: all three replicates better than 3b, STS 0.95, h 1.4 +0.02 -> G53 PASS (3), G54 PASS, G55 PASS",
       v["G53"]["status"] == "PASS" and len(v["G53"]["value"]) == 3 and "3b 复核 (+9.68 mm, -0.0738 dex)" in v["G53"]["note"] and v["G54"]["status"] == "PASS" and abs(v["G54"]["value"] - 0.95) < 1e-3
       and v["G55"]["status"] == "PASS" and abs(v["G55"]["value"] - 0.02) < 1e-4, str({k: (x["status"], x["value"]) for k, x in v.items()}))
    worse = {lab: {"rep": (10.0, -0.06, "DONE")} for lab in g.CAND}
    v = run(worse)
    ok("C: no replicate better than 3b, all usable -> G53 FAIL, G54 / G55 NA", v["G53"]["status"] == "FAIL" and v["G54"]["status"] == "NA" and v["G55"]["status"] == "NA")
    v = run({**worse, "r2_01": {"rep": (0, 0, "FAILED")}})
    ok("C: none confirmed, one replicate failed -> G53 NA", v["G53"]["status"] == "NA" and "算失败" in v["G53"]["note"])
    v = run({**worse, "r2_12": {"rep": None}})
    ok("C: none confirmed, one replicate not submitted -> G53 NA", v["G53"]["status"] == "NA" and "没提交" in v["G53"]["note"])
    one = {**worse, "r2_03": {}}
    v = run(one)
    ok("C: only r2_03 confirmed -> G53 PASS with ['r2_03']", v["G53"]["status"] == "PASS" and v["G53"]["value"] == ["r2_03"])
    v = run({**one, "r2_01": {"rep": (10.0, -0.06, "FAILED")}})
    ok("C: r2_03 confirmed while another replicate failed -> still G53 PASS (monotone)", v["G53"]["status"] == "PASS" and v["G53"]["value"] == ["r2_03"])
    v = run({**one, "r2_03": {"sts": (1.2, "DONE")}})
    ok("C: confirmed r2_03 with STS rotation 1.2 x A -> G54 FAIL", v["G54"]["status"] == "FAIL" and abs(v["G54"]["value"] - 1.2) < 1e-3)
    v = run({**one, "r2_01": {"rep": (10.0, -0.06, "DONE"), "sts": (1.5, "DONE")}})
    ok("C: an unconfirmed candidate's STS 1.5 x A does not count -> G54 PASS", v["G54"]["status"] == "PASS" and "1.5" in v["G54"]["note"])
    v = run({**one, "r2_03": {"sts": None}})
    ok("C: confirmed r2_03 without its STS row -> G54 NA", v["G54"]["status"] == "NA")
    v = run({**one, "r2_03": {"h14": (0.07, "DONE")}})
    ok("C: confirmed r2_03 with h 1.4 +0.07 dex -> G55 FAIL", v["G55"]["status"] == "FAIL" and abs(v["G55"]["value"] - 0.07) < 1e-4)
    v = run({**one, "r2_03": {"h14": (0.0, "CLAIMED")}})
    ok("C: confirmed r2_03 with its h 1.4 row still running -> G55 NA", v["G55"]["status"] == "NA")
    v = run({"r2_01": {"rep": (14.0, -0.13, "DONE"), "h14": (0.02, "DONE"), "sts": (0.95, "DONE")}, "r2_03": {"rep": (12.0, -0.06, "DONE")}, "r2_12": {"rep": (7.0, -0.2, "DONE")}})
    ok("C: route 1 replicate counts, a replicate at dF 12.0 / dl -0.06 does not, dF 7.0 fails route 2 -> only r2_01", v["G53"]["value"] == ["r2_01"], str(v["G53"]["value"]))

    def drift(base):
        for r in base:
            if r["job_id"] == g.JOB_3B:
                r["f1_p95_um"] = repr(float(r["f1_p95_um"]) * 1.01)
    v = run({}, edit=drift)
    ok("C: 3b drifts by 0.0043 dex -> all NA", all(x["status"] == "NA" for x in v.values()) and "复核不上" in v["G53"]["note"])
    v = run({"r2_12": {"sts": (0.95, "CLAIMED")}})
    ok("C: one of the 9 rows still running -> all three NA even though candidates confirm (review N4)", all(x["status"] == "NA" for x in v.values()) and "还没算完" in v["G53"]["note"])
    main01 = by_tag[g.tag_of("r2_01")]["job_id"]

    def main_broken(base):
        for r in base:
            if r["job_id"] == main01:
                r["f1_p95_um"] = ""
    v = run(worse, edit=main_broken)
    ok("C: none confirmed and one main row without micromotion -> G53 NA, not FAIL (review N2)", v["G53"]["status"] == "NA" and "主行" in v["G53"]["note"])
    v = run({"r2_01": {"rep": (12.0, -0.13, "DONE")}})
    ok("C: description: replicate minus main, the 3b replicate comparison and the mean; a 2.35 mm drop is flagged",
       "rep_minus_main" in v["G53"]["note"] and "rep_vs_3b_rep" in v["G53"]["note"] and "mean_main_rep" in v["G53"]["note"] and "'beyond_noise': True" in v["G53"]["note"]
       and "3b 的 h 1.94 复算 (+10.16 mm, -0.0661 dex)" in v["G53"]["note"], v["G53"]["note"][:200])
    v = run({**one, "r2_03": {"sts": (1.2, "DONE")}})
    ok("C: the usable list leaves out a confirmed candidate whose STS rotation fails (review N3)", "可用的候选（确认、坐起和 h 1.4 都不超）[]" in v["G55"]["note"])
    v = run({})
    ok("C: all good -> the usable list has all three", "可用的候选（确认、坐起和 h 1.4 都不超）['r2_01', 'r2_03', 'r2_12']" in v["G55"]["note"])
finally:
    shutil.rmtree(TMP, ignore_errors=True)

n_fail = sum(not c for _, c in checks)
print(f"{len(checks) - n_fail}/{len(checks)} passed, {n_fail} failed")
sys.exit(1 if n_fail else 0)
