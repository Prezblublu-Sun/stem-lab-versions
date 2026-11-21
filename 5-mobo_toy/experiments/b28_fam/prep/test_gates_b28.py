"""Synthetic checks of experiments/b28_fam/gates.py (review R1, R2, R3, R6, R9, R12): build a small fake version directory from v0.11's A family rows and fields,
add fake b28 rows, and see that the verdicts are the intended ones. Local, writes only to the system temp dir.

    python -X utf8 test_gates_b28.py
"""
import csv
import importlib.util
import pathlib
import shutil
import tempfile

import numpy as np

V = pathlib.Path(r"H:/projects/Femoral implant generation/db3406/v0.11")
HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("g", HERE.parent / "gates.py")
G = importlib.util.module_from_spec(spec)
spec.loader.exec_module(G)
TMP = pathlib.Path(tempfile.gettempdir()) / "b28_gates_test"
checks = []


def ok(name, cond, extra=""):
    checks.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))


R = list(csv.DictReader(open(V / "scalars.csv", encoding="utf-8")))
cols = list(R[0])
by_id = {r["job_id"]: r for r in R}
keep = [by_id[j] for j in G.CURVE]
sts = [r for r in R if r["tag"] in G.STS_CURVE and r["status"] == "DONE"]
# fields: reuse each curve row's interface as the fake rows' interface, so mesh F of a fake row = F of the curve row it copies
fields = {}
for p in sorted(V.glob("fields/iface_*.npz")):
    z = np.load(p, allow_pickle=False)
    jobs = [str(j) for j in z["job_id"]]
    for j, job in enumerate(jobs):
        if job in G.CURVE:
            a, b = z["off"][j], z["off"][j + 1]
            fields[job] = {k: z[k][a:b] for k in ("X", "area", "d_canal", "collar")} | {"frame": z["frame"][j]}
Fcur = G.mesh_F(str(V), set(G.CURVE))
mid = G.T + "ow_m1_e+1_fea69910"                     # a curve node in the middle; fake rows copy it, so dF = 0 and dlog = 0 before the changes below


def make(rows_extra, name):
    d = TMP / name
    shutil.rmtree(d, ignore_errors=True)
    (d / "fields").mkdir(parents=True)
    out = keep + sts + rows_extra
    with open(d / "scalars.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(strip(out))
    jobs = [r["job_id"] for r in out if r["job_id"] in fields or r.get("_like")]
    src = [r.get("_like", r["job_id"]) for r in out if r["job_id"] in fields or r.get("_like")]
    off = np.cumsum([0] + [len(fields[s]["area"]) for s in src])
    np.savez(d / "fields" / "iface_000.npz", job_id=np.array(jobs), off=off, frame=np.stack([fields[s]["frame"] for s in src]),
             X=np.concatenate([fields[s]["X"] for s in src]), area=np.concatenate([fields[s]["area"] for s in src]),
             d_canal=np.concatenate([fields[s]["d_canal"] for s in src]), collar=np.concatenate([fields[s]["collar"] for s in src]))
    return str(d)


def fake(tag, f1_factor=1.0, status="DONE", like=mid, rot=None):
    r = dict(by_id[like])
    r.update(job_id=f"db_x_{tag}_00000000", tag=tag, status=status, f1_p95_um=repr(float(r["f1_p95_um"]) * f1_factor) if status == "DONE" else "")
    if rot is not None:
        r["rot_first_deg"] = repr(rot)
    r["_like"] = like
    return r


def strip(rows):
    return [{k: v for k, v in r.items() if k != "_like"} for r in rows]


def run(rows):
    d = make(rows, "x")
    # make() needs _like to find the field; the csv must not carry it
    with open(pathlib.Path(d) / "scalars.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(strip(keep + sts + rows))
    return G.judge(d)


ctrl = [fake(t) for t in G.CONTROLS.values()]
base = [fake(G.tag_of(lab)) for lab in G.ROWS]
r = run(ctrl + base)
ok("all 15 rows equal to the curve: G43 PASS, G41 FAIL, G42 computed", r["G43"]["status"] == "PASS" and r["G41"]["status"] == "FAIL" and r["G42"]["status"] in ("PASS", "FAIL"), str({k: v["status"] for k, v in r.items()}))
rows = ctrl + [fake(G.tag_of(lab), status="FAILED") if lab == "3b" else fake(G.tag_of(lab)) for lab in G.ROWS]
r = run(rows)
ok("R1: one row FAILED and no winner -> G41 NA, not FAIL; G42 NA", r["G41"]["status"] == "NA" and r["G42"]["status"] == "NA", r["G41"]["note"][:120])
win = ctrl + [fake(G.tag_of(lab), 0.7) if lab == "3b" else fake(G.tag_of(lab)) for lab in G.ROWS]
r = run(win)
ok("route 2 winner without its replicate -> G41 NA (pending)", r["G41"]["status"] == "NA" and "待复算 ['3b']" in r["G41"]["note"], r["G41"]["note"][:120])
r = run(win + [fake(G.tag_of("3b") + "_h1.94", 0.72)])
ok("winner confirmed by its replicate -> G41 PASS; G44 and G45 NA without their rows", r["G41"]["status"] == "PASS" and r["G44"]["status"] == "NA" and r["G45"]["status"] == "NA", str({k: v["status"] for k, v in r.items()}))
rows = win + [fake(G.tag_of("3b") + "_h1.94", 0.72)]
rows = [x for x in rows if x["tag"] != G.tag_of("4x")] + [fake(G.tag_of("4x"), status="FAILED")]
r = run(rows)
ok("R9: a confirmed winner and another row FAILED -> G41 PASS", r["G41"]["status"] == "PASS", r["G41"]["note"][:100])
rot_mid = float(next(x for x in sts if x["tag"] == "p13_a105_91e458e3_ow_m1_e+1_F1714")["rot_first_deg"])
r = run(win + [fake(G.tag_of("3b") + "_h1.94", 0.72), fake(G.tag_of("3b") + "_F1714", rot=rot_mid * 1.05), fake(G.tag_of("3b") + "_h1.4", 0.7 * 1.1)])
ok("G44 ratio 1.05 PASS; G45 shift log10(1.1) = 0.041 PASS", r["G44"]["status"] == "PASS" and abs(r["G44"]["value"] - 1.05) < 0.01 and r["G45"]["status"] == "PASS", f"{r['G44']['value']} {r['G45']['value']}")
r = run(win + [fake(G.tag_of("3b") + "_h1.94", 0.72), fake(G.tag_of("3b") + "_F1714", rot=rot_mid * 1.3), fake(G.tag_of("3b") + "_h1.4", 0.7 * 1.3)])
ok("G44 ratio 1.3 FAIL; G45 shift 0.114 FAIL", r["G44"]["status"] == "FAIL" and r["G45"]["status"] == "FAIL")
far = G.T + "ow_m1_e-0.5_03b0a7bc"
r = run(win + [fake(G.tag_of("3b") + "_h1.94", 0.72), fake(G.tag_of("3b") + "_F1714", rot=rot_mid, like=far), fake(G.tag_of("3b") + "_h1.4", 0.7)])
ok("R3: winner's sit-to-stand row beyond the sit-to-stand curve -> G44 NA", r["G44"]["status"] == "NA", r["G44"]["note"][:100])
bad = [fake(t, 1.2) for t in G.CONTROLS.values()]
r = run(bad + base)
ok("G43 FAIL when a control is 0.08 dex off -> G41 NA", r["G43"]["status"] == "FAIL" and r["G41"]["status"] == "NA")
r = run(ctrl + [x for x in base if x["tag"] != G.tag_of("2o")])
ok("R2: a row missing from the table -> G41 NA, G42 NA", r["G41"]["status"] == "NA" and r["G42"]["status"] == "NA")
shutil.rmtree(TMP, ignore_errors=True)
print(f"{sum(checks)}/{len(checks)} passed")
