"""0 FE inputs for the next three batches of the five-day plan (user "整份批准", 2026-11-08). Local, writes data/ only.

    python -X utf8 make_inputs.py

R2   ball of unit radius <= 0.15 around b28's 3b (u13), inside the box with m >= 1, random directions, radius ~ U(0, 0.15) (seed 56201); each at e +1, +1.5, +2.
OF-1 A at m 1.0 (A with u_m = 1/3), one factor at a time, entry offset 0 as A m 1.0: h_cut 18, 20, 22 mm; rho_tip, q, n_a, g_ap, tau_a each at two
     levels, +-0.15 in unit coordinates, or two steps inward (0.15, 0.30) when the variable sits on a bound.
Writes data/r2_u13.npy, r2_e.npy, of1_u13.npy, of1_e.npy, of1_labels.json, inputs.json.
"""
import json
import pathlib

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
D = HERE / "data"
D.mkdir(exist_ok=True)
B28 = HERE.parent / "b28_fam" / "prep" / "data"
U_COLS = ["u_L", "u_alpha", "u_h_cut", "u_m", "u_rho_tip", "u_q", "u_lam", "u_g_ml", "u_g_ap", "u_n_a", "u_n_p", "u_tau_a", "u_tau_p"]
UM1 = 1.0 / 3.0
rows = {r["label"]: r for r in json.load(open(B28 / "fam1_rows.json", encoding="utf-8"))}
u3b = np.array(rows["3b"]["u13"])
uA = np.array(json.load(open(B28 / "inputs.json"))["uA"])
uAm1 = uA.copy()
uAm1[3] = UM1
rng = np.random.default_rng(56201)
kept = []
while len(kept) < 1500:
    v = rng.standard_normal((4000, 13))
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    p = u3b + rng.uniform(0.0, 0.15, 4000)[:, None] * v
    ok = np.all((p >= 0) & (p <= 1), axis=1) & (p[:, 3] >= UM1)
    kept += list(p[ok])
P = np.array(kept[:1500])
E2 = (1.0, 1.5, 2.0)
np.save(D / "r2_u13.npy", np.repeat(P, len(E2), axis=0))
np.save(D / "r2_e.npy", np.tile(np.array(E2), len(P)))
of, labels = [], []
for h in (18.0, 20.0, 22.0):
    u = uAm1.copy()
    u[2] = (h - 16.0) / 16.0
    of.append(u)
    labels.append(f"h_cut{h:g}")
for name in ("u_rho_tip", "u_q", "u_n_a", "u_g_ap", "u_tau_a"):
    i = U_COLS.index(name)
    x0 = uAm1[i]
    if x0 + 0.15 > 1.0:
        steps = (-0.15, -0.30)
    elif x0 - 0.15 < 0.0:
        steps = (0.15, 0.30)
    else:
        steps = (-0.15, 0.15)
    for s in steps:
        u = uAm1.copy()
        u[i] = x0 + s
        of.append(u)
        labels.append(f"{name[2:]}{s:+.2f}")
np.save(D / "of1_u13.npy", np.array(of))
np.save(D / "of1_e.npy", np.zeros(len(of)))
json.dump(labels, open(D / "of1_labels.json", "w", encoding="utf-8"), indent=1)
json.dump({"u3b": u3b.tolist(), "uAm1": uAm1.tolist(), "r2_points": len(P), "r2_e": E2, "of1": labels}, open(D / "inputs.json", "w", encoding="utf-8"), indent=1)
print("R2", len(P), "points x", len(E2), "e; OF-1", len(of), "rows:", labels)
print("A m1 unit coordinates of the varied factors:", {n: round(float(uAm1[U_COLS.index(n)]), 3) for n in ("u_h_cut", "u_rho_tip", "u_q", "u_n_a", "u_g_ap", "u_tau_a")})
