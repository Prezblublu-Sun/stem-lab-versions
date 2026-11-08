"""b28 preliminary winners by the rule written before the results (proposal section 4): FE micromotion of the finished rows and the frozen fast F
(mesh scale) against the A family curve at the frozen bone removed. Local, reads prep/data/fam1_rows.json, model.json and a list of FE micromotion.

    python -X utf8 prelim_winners.py 0b=29.29 1b=28.35 ...
"""
import json
import math
import pathlib
import sys

import numpy as np

D = pathlib.Path(__file__).resolve().parent / "data"
rows = {r["label"]: r for r in json.load(open(D / "fam1_rows.json", encoding="utf-8"))}
cur = json.load(open(D / "model.json", encoding="utf-8"))["curve"]
cb, cF, cl = (np.array(cur[k]) for k in ("bone", "F", "logf1"))
R1L, R2L = math.log10(1.12), math.log10(0.86)
F1L, F2L = 0.7, -6.3
fe = dict(a.split("=") for a in sys.argv[1:])
out = []
for lab, r in rows.items():
    if lab not in fe:
        print(f"{lab}: no FE micromotion")
        continue
    b = r["bone_mm3"] / 1000
    if not (cb[0] <= b <= cb[-1]):
        print(f"{lab}: bone {b:.3f} outside the curve")
        continue
    dF = r["pred_F_mm"] - float(np.interp(b, cb, cF))
    dl = math.log10(float(fe[lab])) - float(np.interp(b, cb, cl))
    r1 = dF >= F1L and dl <= R1L
    r2 = dl <= R2L and dF >= F2L
    margin = max(min((dF - F1L) / 2.16, (R1L - dl) / 0.029) if r1 else -9, min((R2L - dl) / 0.029, (dF - F2L) / 2.16) if r2 else -9)
    out.append((lab, dF, dl, r1, r2, margin))
    print(f"{lab}: bone {b:.3f} fast dF {dF:+.2f} mm, micromotion x{10 ** dl:.3f} ({dl:+.4f} dex); route 1 loose {r1}, route 2 loose {r2}" + (f", margin {margin:.2f}" if r1 or r2 else ""))
win = sorted((o for o in out if o[3] or o[4]), key=lambda o: -o[5])[:5]
print("preliminary winners (largest margin first):", [o[0] for o in win])
