"""Checks for the b28 second-model review (R4, R7, R14). Local, 0 FE, read only.

    python -X utf8 review_checks.py

R4  friction-only rows against full rows with the same physics: is f1_p95_um the same?  And the A family curve: leave-one-node-out interpolation error.
R7  where N3 and CREF come from (geometry.json).
R14 micromotion re-mesh noise as a standard deviation (h 1.94 / 2.06 against h 2.0), and the h 1.4 shift of micromotion.
"""
import collections
import csv
import json
import math
import pathlib

import numpy as np

import select_b28 as S

V = pathlib.Path(r"H:/projects/Femoral implant generation/db3406/v0.11")
R = list(csv.DictReader(open(V / "scalars.csv", encoding="utf-8")))


def num(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else math.nan
    except (TypeError, ValueError):
        return math.nan


KEY = ("design_key", "delta_mm", "load_R_N", "alpha_front_deg", "alpha_sagit_deg", "mu", "cycles", "E_canc_MPa", "entry_offset_forced_mm", "h_int_mm")
print("model_set values:", collections.Counter(r.get("model_set", "") for r in R).most_common(5))
g = collections.defaultdict(list)
for r in R:
    if r["status"] == "DONE" and math.isfinite(num(r["f1_p95_um"])):
        g[tuple(r.get(k, "") for k in KEY)].append(r)
pairs = []
for rs in g.values():
    ms = {r.get("model_set", ""): r for r in rs}
    if "fric" in ms and "fric+bond" in ms:
        pairs.append((ms["fric"], ms["fric+bond"]))
d = [abs(math.log10(num(a["f1_p95_um"]) / num(b["f1_p95_um"]))) for a, b in pairs]
dr = [abs(math.log10(num(a["rot_first_deg"]) / num(b["rot_first_deg"]))) for a, b in pairs]
print(f"R4 friction-only vs full, same physics: {len(pairs)} pairs; |dlog f1| max {max(d) if d else float('nan'):.2e}; |dlog rot| max {max(dr) if dr else float('nan'):.2e}")
for a, b in pairs[:4]:
    print("   ", a["job_id"][:40], b["job_id"][:40], a["f1_p95_um"][:8], b["f1_p95_um"][:8])

info = json.load(open(S.D / "model.json", encoding="utf-8"))
cb, cF, cl = (np.array(info["curve"][k]) for k in ("bone", "F", "logf1"))
loo = []
for i in range(1, len(cb) - 1):
    k = np.arange(len(cb)) != i
    loo.append((cb[i], float(np.interp(cb[i], cb[k], cF[k]) - cF[i]), float(np.interp(cb[i], cb[k], cl[k]) - cl[i])))
print("R4 A curve leave-one-node-out (bone, F error mm, log f1 error dex):", [(round(b, 2), round(x, 2), round(y, 4)) for b, x, y in loo])
print("   max |F| {:.2f} mm, max |log f1| {:.4f} dex (an upper bound: the gap is twice the node spacing)".format(max(abs(x) for _, x, _ in loo), max(abs(y) for _, _, y in loo)))

G = json.load(open(r"H:/projects/application/research-log/neck_implant_2026-10-02/p13_3406/visual_report_2026-10-25/data/geometry.json", encoding="utf-8"))


def walk(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from walk(v, f"{path}.{k}" if path else k)
    elif isinstance(o, list) and len(o) == 3 and all(isinstance(x, (int, float)) for x in o):
        yield path, o


for p, v in walk(G):
    if np.allclose(np.round(v, 3), [0.381, 0.025, -0.924], atol=2e-3) or np.allclose(v, [37.65271204198696, 0.8509371708090849, 41.89415555538172], atol=1e-3):
        print("R7 match:", p, v)
H = np.array(G["head_center"] if "head_center" in G else G.get("head", {}).get("center", [np.nan] * 3), float) if isinstance(G, dict) else None
print("R7 geometry.json top keys:", list(G)[:20] if isinstance(G, dict) else type(G))

groups = collections.defaultdict(dict)
for r in R:
    if r["status"] == "DONE":
        groups[tuple(r.get(k, "") for k in KEY[:-1])].setdefault(r["h_int_mm"], r)
for h in ("1.94", "2.06", "1.4"):
    x = [math.log10(num(gr[h]["f1_p95_um"]) / num(gr["2.0"]["f1_p95_um"])) for gr in groups.values() if "2.0" in gr and h in gr and num(gr[h]["f1_p95_um"]) > 0 and num(gr["2.0"]["f1_p95_um"]) > 0]
    x = np.array(x)
    print(f"R14 h {h} vs 2.0, micromotion: n {len(x)}, mean {x.mean():+.4f}, sd {x.std(ddof=1):.4f}, max |.| {np.abs(x).max():.4f} dex")
