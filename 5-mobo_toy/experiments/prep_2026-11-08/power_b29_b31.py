"""Power of the revised G46 (b29) and G49 / G50 (b31) under a few true states, 40000 draws each. Local, 0 FE, read only.

    python -X utf8 power_b29_b31.py

G46: error of a row = bias + k * calibrated sigma * N(0,1) + 0.012 dex mesh noise * N(0,1); missing rows count as not covered.
G49 / G50: true dF = predicted + shift + fast-F residual sd * N + 0.6 mm * N; true dl = predicted + shift + calibrated sigma * N + 0.012 * N.
"""
import json
import math
import pathlib

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
D = HERE / "data"
N = 40000
rs = json.load(open(D / "rs1_rows.json", encoding="utf-8"))
s = np.array([x["pred_sd_cal"] for x in rs])
rng = np.random.default_rng(56205)
print("G46 (RMSE <= 0.07 and cover >= 0.70 of 48)")
for k, bias, miss, name in ((1, 0, 0, "model right"), (1, 0, 4, "model right, 4 rows missing"), (1.3, 0, 0, "errors 1.3 x"), (1.5, 0, 0, "errors 1.5 x"),
                            (2, 0, 0, "errors 2 x"), (1, 0.03, 0, "bias +0.03"), (1, 0.05, 0, "bias +0.05")):
    e = bias + k * s * rng.standard_normal((N, 48)) + 0.012 * rng.standard_normal((N, 48))
    use = np.arange(48) >= miss
    rmse = np.sqrt((e[:, use] ** 2).mean(1))
    cov = (np.abs(e[:, use]) <= 1.645 * s[use]).sum(1) / 48
    print(f"  {name:30s} P(PASS) {np.mean((rmse <= 0.07) & (cov >= 0.70)):.3f}")
r2 = json.load(open(D / "r2_rows.json", encoding="utf-8"))
sdF = json.load(open(HERE.parent / "b28_fam" / "prep" / "data" / "model.json", encoding="utf-8"))["fastF_resid_sd"]
dF, dl, sl = (np.array([x[k] for x in r2]) for k in ("pred_dF", "pred_dl", "pred_sd_cal"))
DF3, DL3 = 9.68, -0.0738
rng = np.random.default_rng(56204)
print("G49 (>= 1 better than 3b), G50 (>= 8 keep half of 3b's advantage), rows beating A")
for sl_, sF, name in ((0, 0, "model right"), (0.03, 0, "micromotion +0.03"), (0.05, 0, "micromotion +0.05"), (0.05, -3, "micromotion +0.05, F -3 mm"),
                      (-DL3, -DF3, "every row loses 3b's whole advantage")):
    tF = dF + sF + sdF * rng.standard_normal((N, len(r2))) + 0.6 * rng.standard_normal((N, len(r2)))
    tl = dl + sl_ + sl * rng.standard_normal((N, len(r2))) + 0.012 * rng.standard_normal((N, len(r2)))
    better = ((tF >= DF3 + 3) & (tl <= DL3 + math.log10(1.05))) | ((tl <= DL3 - 0.05) & (tF >= DF3 - 2))
    half = (tF >= DF3 / 2) & (tl <= DL3 / 2)
    beat = ((tF >= 5) & (tl <= math.log10(1.05))) | ((tl <= math.log10(0.8)) & (tF >= -2))
    print(f"  {name:38s} G49 {np.mean(better.any(1)):.3f}  G50 {np.mean(half.sum(1) >= 8):.3f}  E[beat A] {beat.sum(1).mean():.1f}")
