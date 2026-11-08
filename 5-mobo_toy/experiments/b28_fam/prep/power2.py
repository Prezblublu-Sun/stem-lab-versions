"""Power of G41 again, with the noise the review (R14) asked for: each observation has re-mesh noise (F 0.6 mm, micromotion 0.012 dex, the pooled sd of
the h 1.94 / 2.06 pairs, 0.011 to 0.014); the A family curve nodes carry the same kind of noise, shared by both observations of a row; and the linear
interpolation between nodes has its own error (leave-one-node-out at doubled spacing: up to 1.4 mm and 0.058 dex, taken as sd 0.7 mm and 0.02 dex at real spacing).
Local, 0 FE.   python -X utf8 power2.py
"""
import json
import math
import pathlib

import numpy as np

D = pathlib.Path(__file__).resolve().parent / "data"
rows = json.load(open(D / "fam1_rows.json", encoding="utf-8"))
info = json.load(open(D / "model.json", encoding="utf-8"))
sdF_pred = info["fastF_resid_sd"]
DF1, R1, R2, DF2 = 5.0, math.log10(1.05), math.log10(0.80), -2.0
SDF_OBS, SDL_OBS, SDF_NODE, SDL_NODE, SDF_INT, SDL_INT = 0.6, 0.012, 0.6, 0.012, 0.7, 0.02
rng = np.random.default_rng(56104)
n = 40000
dF = np.array([r["pred_dF_mm"] for r in rows])
dl = np.array([r["pred_dl"] for r in rows])
sl = np.array([r["pred_sd_cal"] for r in rows])
fam = np.array([r["fam"] for r in rows])


def beats(x, y):
    return ((x >= DF1) & (y <= R1)) | ((y <= R2) & (x >= DF2))


for name, mF, ml, sF, sL in (("predictions right", dF, dl, sdF_pred, sl), ("no improvement", 0 * dF, 0 * dl, 0.0, 0 * sl)):
    tF = mF + sF * rng.standard_normal((n, len(rows)))
    tl = ml + sL * rng.standard_normal((n, len(rows)))
    shF = np.sqrt(SDF_NODE ** 2 + SDF_INT ** 2) * rng.standard_normal((n, len(rows)))      # curve error at the row's bone, shared by the two observations
    shl = np.sqrt(SDL_NODE ** 2 + SDL_INT ** 2) * rng.standard_normal((n, len(rows)))
    o1 = beats(tF - shF + SDF_OBS * rng.standard_normal(tF.shape), tl - shl + SDL_OBS * rng.standard_normal(tl.shape))
    o2 = beats(tF - shF + SDF_OBS * rng.standard_normal(tF.shape), tl - shl + SDL_OBS * rng.standard_normal(tl.shape))
    conf = o1 & o2
    fp = np.stack([conf[:, fam == f].any(1) for f in range(5)], 1)
    print(f"{name}: P(G41 PASS) {fp.any(1).mean():.3f}, families {fp.sum(1).mean():.2f}, per family {fp.mean(0).round(3).tolist()}")
