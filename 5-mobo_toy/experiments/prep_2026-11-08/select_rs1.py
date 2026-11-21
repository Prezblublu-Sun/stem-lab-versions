"""RS-1: 48 rows drawn without looking at any score from the ring candidates of b28 (unit distance 0.25 to 0.75 from A, production templating
feasible at e 0, +1 or +2, m >= 1), seed 56202. Rows within unit distance 0.02 of a b28 row at the same offset are dropped first. Local, 0 FE.

    python -X utf8 select_rs1.py

Writes data/rs1_rows.json: label, e, size, bone, u13, and the micromotion prediction of the b28 model (for gate G46; the draw does not use it).
"""
import json
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
B28P = HERE.parent / "b28_fam" / "prep"
sys.path.insert(0, str(B28P))
import select_b28 as S  # noqa: E402

N, SEED = 48, 56202
g = np.load(S.D / "geom_ring_v11.npz")
ok = g["ok"] & np.isfinite(g["F"]) & np.isfinite(g["bone"]) & (g["u13"][:, 3] >= S.UM1 - 1e-9)
U, E = g["u13"][ok], g["e"][ok]
idx = np.flatnonzero(ok)
picks = json.load(open(S.D / "fam1_rows.json", encoding="utf-8"))
near = np.zeros(len(U), bool)
for p in picks:
    near |= (np.linalg.norm(U - np.array(p["u13"]), axis=1) < 0.02) & (np.abs(E - p["e"]) < 0.26)
pool = np.flatnonzero(~near)
rng = np.random.default_rng(SEED)
take = np.sort(rng.choice(pool, size=N, replace=False))
# predictions of the b28 model, recorded for G46 only
R, J, Ut, X, y, rot, tspec, Fm, fastF, m_ = S.load_training()
mask = rot <= 2.0
info = json.load(open(S.D / "model.json", encoding="utf-8"))
gp, mu, sd = S.fit_gp(X[mask], y[mask])
Xc = S.feat(g, g["u13"][ok], ok)
pm, ps = gp.predict((Xc[take] - mu) / sd, return_std=True)
psc = ps * S.factor_of(info["calibration"], S.nn_dist(U[take], Ut[mask]))
uA = np.array(json.load(open(S.D / "inputs.json"))["uA"])
slope, icpt = info["fastF_to_mesh"]
out = []
for n, (k, a, b) in enumerate(zip(take, pm, psc), 1):
    i = idx[k]
    out.append({"label": f"rs{n:02d}", "e": float(g["e"][i]), "A0": float(g["A0"][i]), "bone_mm3": float(g["bone"][i]), "u13": g["u13"][i].tolist(),
                "dist_A": float(np.linalg.norm(g["u13"][i] - uA)), "pred_log_f1": float(a), "pred_sd_cal": float(b), "fast_F_mesh": float(slope * g["F"][i] + icpt), "ring_idx": int(i)})
json.dump(out, open(HERE / "data" / "rs1_rows.json", "w", encoding="utf-8"), indent=1)
d = np.array([o["dist_A"] for o in out])
print(f"RS-1: {len(out)} rows from {len(pool)} feasible ring pairs; distance {d.min():.2f} to {d.max():.2f}, median {np.median(d):.2f}; e counts {dict(zip(*np.unique([o['e'] for o in out], return_counts=True)))}")
print("bone cm3", round(min(o['bone_mm3'] for o in out) / 1000, 2), "to", round(max(o['bone_mm3'] for o in out) / 1000, 2), "; predicted micromotion um", round(10 ** min(o['pred_log_f1'] for o in out), 1), "to", round(10 ** max(o['pred_log_f1'] for o in out), 1))
