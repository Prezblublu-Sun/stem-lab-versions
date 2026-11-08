"""RS-1, after the second-model review (29-6): the micromotion prediction of the model R2 used (b28's GP refitted with the 14 b28 rows, as in select_r2.py)
for the 48 RS-1 rows, frozen before any result. Descriptive only: G46 judges b28's frozen model. Local, 0 FE.

    python -X utf8 pred2_rs1.py      writes data/rs1_pred2.json: label -> [predicted log10 micromotion, calibrated sd]
"""
import csv
import json
import math
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
B28P = HERE.parent / "b28_fam" / "prep"
sys.path.insert(0, str(B28P))
import select_b28 as S  # noqa: E402

V12 = pathlib.Path(r"H:/projects/Femoral implant generation/db3406/v0.12")
R, J, U, X, y, rot, tspec, Fm, fastF, m_ = S.load_training()
mask = rot <= 2.0
info = json.load(open(S.D / "model.json", encoding="utf-8"))
sc = {r["tag"]: r for r in csv.DictReader(open(V12 / "scalars.csv", encoding="utf-8"))}
geo = {"ring": np.load(S.D / "geom_ring_v11.npz"), "egrid": np.load(S.D / "geom_egrid_v11.npz")}
Xb, yb, Ub = [], [], []
for r in json.load(open(S.D / "fam1_rows.json", encoding="utf-8")):        # same 14 rows as select_r2.py
    t = sc.get(f"fam1_{r['label']}_e{r['e']:+g}")
    if t is None or t["status"] != "DONE":
        continue
    g = geo[r["src"]]
    ok = np.zeros(len(g["ok"]), bool)
    ok[r["src_idx"]] = True
    Xb.append(S.feat(g, g["u13"][ok], ok)[0])
    yb.append(math.log10(float(t["f1_p95_um"])))
    Ub.append(g["u13"][r["src_idx"]])
Xt, yt, Ut = np.vstack([X[mask], np.array(Xb)]), np.r_[y[mask], yb], np.vstack([U[mask], np.array(Ub)])
gp, mu, sd = S.fit_gp(Xt, yt)
rows = json.load(open(HERE / "data" / "rs1_rows.json", encoding="utf-8"))
g = geo["ring"]
ii = np.array([r["ring_idx"] for r in rows])
ok = np.zeros(len(g["ok"]), bool)
ok[ii] = True
Xc = S.feat(g, g["u13"][ok], ok)                       # rows of Xc follow the order of np.flatnonzero(ok)
order = {k: n for n, k in enumerate(np.flatnonzero(ok))}
Xc = Xc[[order[k] for k in ii]]
pm, ps = gp.predict((Xc - mu) / sd, return_std=True)
psc = ps * S.factor_of(info["calibration"], S.nn_dist(g["u13"][ii], Ut))
out = {r["label"]: [round(float(a), 5), round(float(b), 5)] for r, a, b in zip(rows, pm, psc)}
assert all(np.allclose(g["u13"][r["ring_idx"]], r["u13"]) for r in rows)
json.dump(out, open(HERE / "data" / "rs1_pred2.json", "w", encoding="utf-8"), indent=1)
d = pm - np.array([r["pred_log_f1"] for r in rows])
print(f"training rows {len(yt)} (b28 {len(yb)}); refitted minus b28 model: mean {d.mean():+.3f}, sd {d.std():.3f}, max |d| {np.abs(d).max():.3f} dex")
