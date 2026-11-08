"""Tests of the gates of b29 (G46), b30 (G48, G51), b31 (G49, G50) before they are frozen. Local, read only on db3406 v0.12; writes a temp dir only.

    PYTHONUTF8=1 ../../.venv-mobo/Scripts/python.exe test_gates_b29_b31.py

A. constants: CURVE, N3, U_NECK, CREF, the G41 routes and mesh_F are the same as b28's gates.py and stage_db; PRED and PRED2 equal the frozen
   row files; (label, entry offset) equal stage_db's rows; bones of the judged rows inside the A family curve; sha256 prefixes in the docstrings.
B. on v0.12 (no new rows yet): every gate NA, no crash; 3b reproduces +9.68 mm, -0.0738 dex and its replicate -0.0661.
C. synthetic rows (scalars.csv = v0.12's curve and 3b rows plus made-up rows; mesh F of made-up rows patched in): PASS, FAIL and NA paths,
   missing, duplicated, failed, zero and negative micromotion, bone outside the curve, 3b drift.
"""
import csv
import hashlib
import importlib.util
import inspect
import json
import math
import pathlib
import shutil
import sys
import tempfile

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EXP = ROOT / "experiments"
V12 = pathlib.Path(r"H:/projects/Femoral implant generation/db3406/v0.12")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "v2"))
import stage_db as DB  # noqa: E402

checks = []


def ok(name, cond, extra=""):
    checks.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""), flush=True)


def load(d):
    s = importlib.util.spec_from_file_location(d.replace("/", "_"), EXP / d / "gates.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


g28, g29, g30, g31 = load("b28_fam"), load("b29_rs1"), load("b30_of1"), load("b31_r2")
REAL_MESH_F = g31.mesh_F
D = HERE / "data"
# ---------------------------------------------------------------- A
ok("A: CURVE the same in b28, b29, b30, b31 and stage_db.UROW_CURVE", g28.CURVE == g29.CURVE == g30.CURVE == g31.CURVE == DB.UROW_CURVE)
ok("A: N3, U_NECK, CREF the same as b28", all(np.array_equal(getattr(g28, k), getattr(g, k)) for g in (g29, g30, g31) for k in ("N3", "U_NECK", "CREF")))
facts = json.load(open(ROOT / "ops" / "facts.json", encoding="utf-8"))
ok("A: U_NECK = facts.json neck_axis_u normalised", np.allclose(g31.U_NECK, np.array(facts["neck_axis_u"]) / np.linalg.norm(facts["neck_axis_u"]), atol=0))
ok("A: G41 routes DF1, R1, R2, DF2 the same as b28", all((g.DF1, g.R1, g.R2, g.DF2) == (g28.DF1, g28.R1, g28.R2, g28.DF2) for g in (g29, g31)))
ok("A: mesh_F source identical to b28's", all(inspect.getsource(g.mesh_F) == inspect.getsource(g28.mesh_F) for g in (g29, g30, g31)))
rs = {r["label"]: r for r in json.load(open(D / "rs1_rows.json", encoding="utf-8"))}
ok("A: b29 PRED = rs1_rows.json to 5 decimals", set(rs) == set(g29.PRED) and all(g29.PRED[k] == (rs[k]["e"], round(rs[k]["pred_log_f1"], 5), round(rs[k]["pred_sd_cal"], 5)) for k in rs))
p2 = json.load(open(D / "rs1_pred2.json", encoding="utf-8"))
ok("A: b29 PRED2 = rs1_pred2.json", {k: tuple(v) for k, v in p2.items()} == g29.PRED2)
r2 = {r["label"]: r for r in json.load(open(D / "r2_rows.json", encoding="utf-8"))}
ok("A: b31 PRED = r2_rows.json to 5 decimals", set(r2) == set(g31.PRED) and all(g31.PRED[k] == (r2[k]["e"], round(r2[k]["pred_log_f1"], 5), round(r2[k]["pred_sd_cal"], 5)) for k in r2))
ok("A: (label, entry offset) = stage_db rows", {k: v[0] for k, v in g29.PRED.items()} == {x[0]: x[1] for x in DB.RS1_ROWS}
   and dict(g30.E) == {x[0]: x[1] for x in DB.OF1_ROWS} and {k: v[0] for k, v in g31.PRED.items()} == {x[0]: x[1] for x in DB.R2_ROWS})
sha = {n: hashlib.sha256((D / n).read_bytes()).hexdigest() for n in ("rs1_rows.json", "r2_rows.json")}
ok("A: sha256 prefixes in the docstrings", sha["rs1_rows.json"][:8] in g29.__doc__ and sha["r2_rows.json"][:8] in g31.__doc__, str({k: v[:8] for k, v in sha.items()}))
with open(V12 / "scalars.csv", encoding="utf-8") as fh:
    R12 = list(csv.DictReader(fh))
by_id = {r["job_id"]: r for r in R12}
cb0 = sorted(float(by_id[j]["bone_total_mm3"]) for j in g31.CURVE)
of_bone = {x[0]: x[3] for x in DB.OF1_ROWS}
ok("A: bones of the judged rows (b30 key and back rows, all b31 rows) inside the curve", all(cb0[0] <= of_bone[k] <= cb0[-1] for k in (*g30.KEY_ROWS, *g30.BACK_ROWS))
   and all(cb0[0] <= x[3] <= cb0[-1] for x in DB.R2_ROWS), f"curve {cb0[0]:.0f} to {cb0[-1]:.0f} mm3")

# ---------------------------------------------------------------- B
out = {**g29.judge(str(V12)), **g30.judge(str(V12)), **g31.judge(str(V12))}
ok("B: v0.12, every gate NA", all(v["status"] == "NA" for v in out.values()), str({k: v["status"] for k, v in out.items()}))
ok("B: 3b reproduced in b31 (+9.68, -0.0738) and b30 (two runs, mean -0.0700)", "复核 (+9.68 mm, -0.0738 dex)" in out["G49"]["note"] and "-0.0700" in out["G51"]["note"] and "-0.0661" in out["G51"]["note"])

# ---------------------------------------------------------------- C
KEEP = set(g31.CURVE) | set(g30.REF_3B) | {g31.JOB_3B}
REAL_F = REAL_MESH_F(str(V12), KEEP)
cols = list(R12[0].keys())
cb = np.array([float(by_id[j]["bone_total_mm3"]) / 1000 for j in g31.CURVE])
o = np.argsort(cb)
cb, cF, cl = cb[o], np.array([REAL_F[j] for j in g31.CURVE])[o], np.log10([float(by_id[j]["f1_p95_um"]) for j in g31.CURVE])[o]
TMP = pathlib.Path(tempfile.mkdtemp(prefix="gates_b29_b31_"))


def row(tag, jid, bone_mm3, dF=0.0, dl=0.0, status="DONE", f1=None, fake=None):
    r = {c: "" for c in cols}
    b = bone_mm3 / 1000
    r.update(tag=tag, job_id=jid, status=status, bone_total_mm3=repr(bone_mm3), rot_first_deg="0.5",
             f1_p95_um=repr(10 ** (float(np.interp(b, cb, cl)) + dl)) if f1 is None else str(f1))
    fake[jid] = float(np.interp(b, cb, cF)) + dF
    return r


def run(g, rows, fake, edit=None, drop_rot=False):
    base = [dict(by_id[j]) for j in sorted(KEEP)]
    if edit:
        edit(base)
    d = TMP / f"db{len(list(TMP.iterdir()))}"
    d.mkdir()
    cc = [c for c in cols if not (drop_rot and c == "rot_first_deg")]
    with open(d / "scalars.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cc, extrasaction="ignore")
        w.writeheader()
        w.writerows(base + rows)
    g.mesh_F = lambda db_dir, want: {k: v for k, v in {**REAL_F, **fake}.items() if k in want}
    try:
        return g.judge(str(d))
    finally:
        g.mesh_F = REAL_MESH_F


try:
    # b29
    def rs1(err_of, status_of=lambda lab: "DONE", f1_of=None, extra=()):
        fake, rows = {}, []
        for lab, (e, p, s) in g29.PRED.items():
            f1 = 10 ** (p + err_of(lab, s)) if f1_of is None or f1_of(lab) is None else f1_of(lab)
            rows.append(row(g29.tag_of(lab), f"j_{lab}", rs[lab]["bone_mm3"], status=status_of(lab), f1=f1, fake=fake))
        return run(g29, rows + list(extra), fake)["G46"]
    v = rs1(lambda lab, s: 0.0)
    ok("C29: predictions exact -> PASS, RMSE 0, cover 1", v["status"] == "PASS" and v["value"] == [0.0, 1.0], str(v["value"]))
    v = rs1(lambda lab, s: 2.0 * s)
    ok("C29: every error 2 sigma -> FAIL (cover 0)", v["status"] == "FAIL" and v["value"][1] == 0.0, str(v["value"]))
    v = rs1(lambda lab, s: 0.08 if lab < "rs25" else -0.08)
    ok("C29: RMSE 0.08 -> FAIL", v["status"] == "FAIL" and abs(v["value"][0] - 0.08) < 1e-9, str(v["value"]))
    labs = list(g29.PRED)
    v = rs1(lambda lab, s: 0.0, status_of=lambda lab: "FAILED" if lab in labs[:9] else "DONE")
    ok("C29: 9 rows failed -> NA", v["status"] == "NA" and "算失败" in v["note"], v["note"][:120])
    v = rs1(lambda lab, s: 0.0, status_of=lambda lab: "FAILED" if lab in labs[:8] else "DONE")
    ok("C29: 8 rows failed, rest exact -> PASS with cover 40/48 (missing rows not covered)", v["status"] == "PASS" and v["value"][1] == round(40 / 48, 3) and "RMSE 上界" in v["note"], str(v["value"]))
    v = rs1(lambda lab, s: 0.0, status_of=lambda lab: "FAILED" if lab in labs[:4] else "DONE", f1_of=lambda lab: {labs[4]: 0, labs[5]: -3.0, labs[6]: "nan"}.get(lab))
    ok("C29: f1 0, negative and nan -> missing, no crash; kinds reported apart", v["status"] == "PASS" and "缺微动" in v["note"] and "算失败" in v["note"], v["note"][:160])
    dup = row(g29.tag_of(labs[0]), "j_dup", rs[labs[0]]["bone_mm3"], status="FAILED", fake={})
    v = rs1(lambda lab, s: 0.0, extra=[dup])
    ok("C29: duplicated tag, one DONE -> the DONE row is used", v["status"] == "PASS" and v["value"] == [0.0, 1.0])
    dup2 = row(g29.tag_of(labs[0]), "j_dup2", rs[labs[0]]["bone_mm3"], fake={})
    v = rs1(lambda lab, s: 0.0, extra=[dup2])
    ok("C29: duplicated tag, two DONE -> that row is 'tag 重复'", "tag 重复" in v["note"] and v["value"][1] == round(47 / 48, 3), v["note"][:120])
    v = rs1(lambda lab, s: 0.0)
    ok("C29: descriptive parts present (low subset, PRED2, by offset, A family)", all(x in v["note"] for x in ("预测 ≤ 1.6", "重训版", "按入口偏移", "按 G41 路线")), v["note"][-200:])

    # b30
    of = {x[0]: x for x in DB.OF1_ROWS}
    dl3b = float(np.mean([-0.0738, -0.0661]))

    def of1(spec, edit=None, drop_rot=False):
        fake, rows = {}, []
        for lab in g30.LABELS:
            s = spec.get(lab, (0.0, 0.0, "DONE"))
            if s is None:
                continue
            bone = s[3] if len(s) > 3 else of[lab][3]
            rows.append(row(g30.tag_of(lab), f"j_{lab}", bone, dF=s[0], dl=s[1], status=s[2], fake=fake))
        return run(g30, rows, fake, edit=edit, drop_rot=drop_rot)
    back0 = {k: (0.0, dl3b, "DONE") for k in g30.BACK_ROWS}
    v = of1({"n_a-0.15": (0.0, -0.05, "DONE"), "tau_a+0.15": None, "tau_a+0.30": (0, 0, "FAILED"), **back0})
    ok("C30: one key row -0.05 with F kept -> G48 PASS although the other two are missing", v["G48"]["status"] == "PASS", v["G48"]["note"][:120])
    v = of1({"n_a-0.15": (-3.0, -0.05, "DONE"), **back0})
    ok("C30: key row -0.05 but F -3 mm, others 0 -> G48 FAIL", v["G48"]["status"] == "FAIL", v["G48"]["note"][:120])
    v = of1({"tau_a+0.30": (0, 0, "FAILED"), **back0})
    ok("C30: none pass, a key row failed -> G48 NA", v["G48"]["status"] == "NA")
    v = of1({"n_a-0.15": (0.0, -0.039, "DONE"), **back0})
    ok("C30: -0.039 is not enough -> G48 FAIL", v["G48"]["status"] == "FAIL")
    v = of1({"n_a-0.15": (0.0, -0.05, "DONE", 9500.0), **back0})
    ok("C30: key row bone outside the curve -> unusable, G48 NA", v["G48"]["status"] == "NA" and "曲线外" in v["G48"]["note"])
    v = of1({"3b_back_n_a": (0.0, dl3b + 0.036, "DONE"), "3b_back_tau_a": (0, 0, "FAILED")})
    ok("C30: a back row loses 0.036 of 3b's advantage -> G51 PASS although the other failed", v["G51"]["status"] == "PASS", v["G51"]["note"][:160])
    v = of1({"3b_back_n_a": (0.0, dl3b + 0.034, "DONE"), "3b_back_tau_a": (0.0, dl3b + 0.01, "DONE")})
    ok("C30: back rows lose 0.034 and 0.01 -> G51 FAIL", v["G51"]["status"] == "FAIL")
    v = of1({"3b_back_n_a": (0.0, dl3b + 0.01, "DONE"), "3b_back_tau_a": None})
    ok("C30: one back row 0.01, the other missing -> G51 NA", v["G51"]["status"] == "NA")
    v = of1({**back0}, drop_rot=True)
    ok("C30: no rot_first_deg column -> no crash", v["G48"]["status"] == "FAIL" and "'rot_deg': None" in v["G48"]["note"])

    def drift(base):
        for r in base:
            if r["job_id"] == g31.JOB_3B:
                r["f1_p95_um"] = repr(float(r["f1_p95_um"]) * 1.01)
    v = of1({**back0}, edit=drift)
    ok("C30: 3b drifts by 0.0043 dex -> both gates NA", v["G48"]["status"] == "NA" and v["G51"]["status"] == "NA" and "复核不上" in v["G51"]["note"])

    # b31
    def rr(spec, edit=None):
        fake, rows = {}, []
        for lab in g31.PRED:
            s = spec.get(lab, (0.0, 0.0, "DONE"))
            if s is None:
                continue
            f1 = s[3] if len(s) > 3 else None
            rows.append(row(g31.tag_of(lab), f"j_{lab}", r2[lab]["bone_mm3"], dF=s[0], dl=s[1], status=s[2], f1=f1, fake=fake))
        return run(g31, rows, fake, edit=edit)
    L31 = list(g31.PRED)
    v = rr({L31[0]: (12.7, -0.06, "DONE")})
    ok("C31: one row dF 12.7, dl -0.06 -> G49 PASS (route 1)", v["G49"]["status"] == "PASS")
    v = rr({L31[0]: (7.7, -0.124, "DONE")})
    ok("C31: one row dF 7.7, dl -0.124 -> G49 PASS (route 2)", v["G49"]["status"] == "PASS")
    v = rr({L31[0]: (12.6, -0.06, "DONE"), L31[1]: (0, 0, "FAILED"), L31[2]: None})
    ok("C31: none better, 2 unusable -> G49 FAIL", v["G49"]["status"] == "FAIL", v["G49"]["note"][:80])
    v = rr({L31[1]: (0, 0, "FAILED"), L31[2]: None, L31[3]: (0, 0, "DONE", -1.0)})
    ok("C31: none better, 3 unusable (failed, missing, negative f1) -> G49 NA, no crash", v["G49"]["status"] == "NA", v["G49"]["note"][:80])
    half = {lab: (4.85, -0.0370, "DONE") for lab in L31[:8]}
    v = rr(half)
    ok("C31: 8 rows just inside half of 3b's advantage -> G50 PASS", v["G50"]["status"] == "PASS" and v["G50"]["value"] == 8)
    v = rr({**{lab: (4.85, -0.0370, "DONE") for lab in L31[:7]}, L31[7]: (0, 0, "FAILED")})
    ok("C31: 7 half + 1 unusable -> G50 NA", v["G50"]["status"] == "NA")
    v = rr({lab: (4.85, -0.0370, "DONE") for lab in L31[:7]})
    ok("C31: 7 half, rest usable -> G50 FAIL", v["G50"]["status"] == "FAIL")
    v = rr({lab: (6.0, -0.035, "DONE") for lab in L31})
    ok("C31: dl -0.035 is less than half -> G50 FAIL though all beat A", v["G50"]["status"] == "FAIL" and "超过 A 的 15 行" in v["G49"]["note"])
    v = rr(half, edit=drift)
    ok("C31: 3b drifts by 0.0043 dex -> both NA", v["G49"]["status"] == "NA" and v["G50"]["status"] == "NA" and "复核不上" in v["G50"]["note"])
finally:
    shutil.rmtree(TMP, ignore_errors=True)

n_fail = sum(not c for _, c in checks)
print(f"{len(checks) - n_fail}/{len(checks)} passed, {n_fail} failed")
sys.exit(1 if n_fail else 0)
