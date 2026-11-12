"""Tests of b34's gate G56 before it is frozen. Local, read only on db3406 v0.14; writes a temp dir only.

    PYTHONUTF8=1 ../../.venv-mobo/Scripts/python.exe test_gates_b34.py

A. constants as b33 / b28 (STS curve, the 1.10 limit); the four rows are the better-than-3b rows of b33's proposal that b33 did not pick.
B. v0.14 (none of the 4 rows submitted): NA, batch not finished. b33's three described with the values of b33's own G54.
C. synthetic rows (v0.14 plus made-up 1714 N rows): PASS / FAIL / NA; a failed row, a missing rotation, a force error over the limit,
   a design outside the curve, a missing curve row.
"""
import csv
import importlib.util
import json
import math
import pathlib
import shutil
import sys
import tempfile

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
V14 = pathlib.Path(r"H:/projects/Femoral implant generation/db3406/v0.14")
checks = []


def ok(name, cond, extra=""):
    checks.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""), flush=True)


def load(path, name):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


g = load(HERE / ("gates" + ".py"), "g34")
g33 = load(ROOT / "experiments" / "b33_r2cand" / ("gates" + ".py"), "g33")
g28 = load(ROOT / "experiments" / "b28_fam" / ("gates" + ".py"), "g28")
ok("A: STS curve and the 1.10 limit as b33 and b28", g.STS_CURVE == g33.STS_CURVE == g28.STS_CURVE and g.MAX_STS == g33.MAX_STS == g28.MAX_STS)
man = json.loads((ROOT / "experiments" / "b31_r2" / "feed_manifest.json").read_text(encoding="utf-8"))["rows"]
ok("A: the four main rows are b31's R2_05, R2_06, R2_08, R2_14 as fed", g.MAIN == {"r2_05": man["R2_05"]["id"], "r2_06": man["R2_06"]["id"], "r2_08": man["R2_08"]["id"], "r2_14": man["R2_14"]["id"]})
p33 = (ROOT / "experiments" / "b33_r2cand" / "proposal.md").read_text(encoding="utf-8")
ok("A: they are the four rows b33's proposal lists as better than 3b and not picked", all(f"| {k}（没选" in p33 for k in g.MAIN) and p33.count("（没选") == len(g.MAIN))
ok("A: the described three are b33's candidates", {k: g.tag_of(v) for k, v in g.DESCRIBE.items()} == {k: g33.tag_of(k) for k in g33.CAND})
rin = json.loads((HERE / "rows_in.json").read_text(encoding="utf-8"))
ok("A: rows_in.json has one 1714 N row per design, on the main rows of the gate", [(r["base"], r["cond"]) for r in rin["rows"]] == [(j, {"load": "F1714"}) for j in g.MAIN.values()])
out = g.judge(str(V14))
ok("B: v0.14 (none of the 4 rows submitted) -> NA, batch not finished", out["G56"]["status"] == "NA" and "还没算完" in out["G56"]["note"], out["G56"]["note"][:80])

with open(V14 / "scalars.csv", encoding="utf-8") as fh:
    R14 = list(csv.DictReader(fh))
by_id = {r["job_id"]: r for r in R14}
cols = list(R14[0].keys())
sts_rows = {t: [r for r in R14 if r["tag"] == t and r["status"] == "DONE"][0] for t in g.STS_CURVE}
curve = sorted((float(by_id[b]["bone_total_mm3"]) / 1000, math.log10(float(sts_rows[t]["rot_first_deg"])), math.log10(float(by_id[b]["rot_first_deg"]))) for t, b in g.STS_CURVE.items())
sb, sr, st = (np.array(v) for v in zip(*curve))
KEEP = set(g.STS_CURVE.values()) | {r["job_id"] for r in sts_rows.values()} | set(g.MAIN.values()) | set(g.DESCRIBE.values()) \
    | {r["job_id"] for r in R14 if r["tag"] in {g.tag_of(j) + "_F1714" for j in g.DESCRIBE.values()}}
TMP = pathlib.Path(tempfile.mkdtemp(prefix="gates_b34_"))


def run(spec, edit=None):
    """spec: lab -> (ratio, status, force_err[, load_N]) or None (not submitted); default 0.95, DONE, 1e-6, 1714."""
    rows = []
    for lab, j in g.MAIN.items():
        s = spec.get(lab, (0.95, "DONE", 1e-6))
        if s is None:
            continue
        bone = float(by_id[j]["bone_total_mm3"])
        r = {c: "" for c in cols}
        r.update(tag=g.tag_of(j) + "_F1714", job_id=f"j_sts_{lab}", status=s[1], bone_total_mm3=repr(bone), iface_force_err_load="" if s[2] is None else repr(s[2]),
                 load_R_N=repr(s[3] if len(s) > 3 else 1714.0),
                 rot_first_deg="" if s[0] is None else repr(s[0] * 10 ** float(np.interp(bone / 1000, sb, sr))))
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
    return g.judge(str(d))["G56"]


try:
    v = run({})
    ok("C: four rows at 0.95 x A -> PASS, value 0.95, four rows named", v["status"] == "PASS" and abs(v["value"] - 0.95) < 1e-3 and v["rows"] == ["j_sts_r2_05", "j_sts_r2_06", "j_sts_r2_08", "j_sts_r2_14"], str((v["status"], v["value"])))
    ok("C: b33's three are described with the ratios b33's own G54 gave (0.895, 0.825, 0.839)",
       all(s in v["note"] for s in ("'r2_01': {'sts': 0.895", "'r2_03': {'sts': 0.825", "'r2_12': {'sts': 0.839")), v["note"][-260:])
    ok("C: the stair ratio and the difference are in the note", "'stair': 0.939" in v["note"] and "'stair': 0.989" in v["note"] and "'sts_minus_stair': 0.011" in v["note"], v["note"][:200])
    v = run({"r2_08": (1.10, "DONE", 1e-6)})
    ok("C: exactly 1.10 x A -> PASS (the limit is <=)", v["status"] == "PASS" and abs(v["value"] - 1.10) < 1e-3)
    v = run({"r2_08": (1.12, "DONE", 1e-6)})
    ok("C: one design at 1.12 x A -> FAIL, the design is named", v["status"] == "FAIL" and abs(v["value"] - 1.12) < 1e-3 and "['r2_08']" in v["note"])
    v = run({"r2_08": (1.1004, "DONE", 1e-6)})
    ok("C: 1.1004 x A -> FAIL: the comparison uses the unrounded ratio (review R2)", v["status"] == "FAIL" and v["value"] == 1.1004, str((v["status"], v["value"])))
    v = run({"r2_06": (0.95, "DONE", 1e-6, 2391.0)})
    ok("C: a row with the right tag but another load -> NA, not PASS (review R3)", v["status"] == "NA" and "不是 1714 N" in v["note"])
    ok("C: the pass direction says what the gate does not show (review R1)", "没有 h 1.94 复核" in g.GATES["G56"] and "一样可以进后面的比较" not in g.GATES["G56"])
    rj = HERE / "rows.json"
    if rj.exists():
        fz = {r["label"]: r["job_id"] for r in json.loads(rj.read_text(encoding="utf-8"))["rows"]}
        ok("A: the frozen rows.json holds one job per design, with the tag the gate looks for", sorted(g.tag_of(j) for j in fz.values()) == sorted(g.tag_of(j) + "_F1714" for j in g.MAIN.values())
           and all(j.startswith("db_cd_") for j in fz.values()), str(fz))
    v = run({"r2_08": (1.12, "DONE", 1e-6), "r2_05": (0.9, "FAILED", None)})
    ok("C: one over the limit and one failed row -> still FAIL", v["status"] == "FAIL" and "算失败" in v["note"])
    v = run({"r2_05": (None, "FAILED", None)})
    ok("C: none over, one row failed -> NA, not PASS", v["status"] == "NA" and "算失败" in v["note"] and v["rows"] == ["j_sts_r2_06", "j_sts_r2_08", "j_sts_r2_14"])
    v = run({"r2_06": None})
    ok("C: one row not submitted -> NA, batch not finished", v["status"] == "NA" and "还没算完" in v["note"])
    v = run({"r2_06": (0.95, "CLAIMED", 1e-6)})
    ok("C: one row still running -> NA, batch not finished", v["status"] == "NA" and "还没算完" in v["note"])
    v = run({"r2_06": (None, "DONE", 1e-6)})
    ok("C: a DONE row without a rotation -> NA", v["status"] == "NA" and "缺转动" in v["note"])
    v = run({"r2_06": (0.95, "DONE", 2e-3)})
    ok("C: a force error over 1e-3 -> the row is not used by value -> NA", v["status"] == "NA" and "界面合力误差" in v["note"])
    v = run({"r2_06": (0.95, "DONE", None)})
    ok("C: a missing force error -> NA", v["status"] == "NA" and "界面合力误差" in v["note"])

    def out_of_curve(base):
        for r in base:
            if r["job_id"] == g.MAIN["r2_08"]:
                r["bone_total_mm3"] = "4000.0"
    v = run({}, out_of_curve)
    ok("C: a design with less bone removed than the curve covers -> NA", v["status"] == "NA" and "在坐起曲线外" in v["note"])

    def drop_curve(base):
        base[:] = [r for r in base if r["tag"] != "p13_a105_91e458e3_ow_m1_e+2_F1714"]
    v = run({}, drop_curve)
    ok("C: a missing row of the A curve -> NA", v["status"] == "NA" and "A 族曲线缺行" in v["note"])
finally:
    shutil.rmtree(TMP, ignore_errors=True)

n_fail = sum(not c for _, c in checks)
print(f"{len(checks) - n_fail}/{len(checks)} passed, {n_fail} failed")
sys.exit(1 if n_fail else 0)
