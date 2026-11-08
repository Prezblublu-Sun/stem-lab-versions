"""Descriptive numbers for the b28 report, from db3406 v0.12 (not a gate; the verdict is experiments/b28_fam/result.json). Local, read only.

    python -X utf8 describe_b28.py
"""
import csv
import importlib.util
import math
import pathlib

import numpy as np

V = r"H:/projects/Femoral implant generation/db3406/v0.12"
HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("g", HERE.parent / "gates.py")
G = importlib.util.module_from_spec(spec)
spec.loader.exec_module(G)
R = list(csv.DictReader(open(V + "/scalars.csv", encoding="utf-8")))
by_tag = {r["tag"]: r for r in R}
by_id = {r["job_id"]: r for r in R}


def num(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else math.nan
    except (TypeError, ValueError):
        return math.nan


err, cov = [], []
for lab in G.ROWS:
    r = by_tag.get(G.tag_of(lab))
    if r is None or r["status"] != "DONE":
        continue
    e = math.log10(num(r["f1_p95_um"])) - G.PRED[lab][0]
    err.append(e)
    cov.append(abs(e) <= 1.645 * G.PRED[lab][1])
print(f"micromotion model on {len(err)} rows (descriptive, G42 is NA): RMSE {np.sqrt(np.mean(np.square(err))):.4f} dex, mean {np.mean(err):+.4f}, 90 % coverage {np.mean(cov):.2f}")
cb = np.array([num(by_id[j]["bone_total_mm3"]) / 1000 for j in G.CURVE])
cr = np.log10([num(by_id[j]["rot_first_deg"]) for j in G.CURVE])
o = np.argsort(cb)
for lab in ("3b", "1b", "0b"):
    r = by_tag[G.tag_of(lab)]
    b = num(r["bone_total_mm3"]) / 1000
    rot = num(r["rot_first_deg"])
    print(f"{lab}: m {num(r['m']):.2f} e {num(r['tpl_e']):+.2f} bone {b:.3f} stair rotation {rot:.4f} deg, A family at the same bone {10 ** np.interp(b, cb[o], cr[o]):.4f} (x{rot / 10 ** np.interp(b, cb[o], cr[o]):.2f}); f1 {num(r['f1_p95_um']):.2f}")
    s = by_tag.get(G.tag_of(lab) + "_F1714")
    if s is not None:
        print(f"    sit-to-stand 1714 N: rotation {num(s['rot_first_deg']):.4f} deg, f1 {num(s['f1_p95_um']):.2f} um")
