"""How the predicted gap to the A family grows with unit distance from A, over every usable m >= 1 candidate (no distance cut). Local, 0 FE, read only.

    python -X utf8 distance_ladder.py
"""
import json

import numpy as np

import select_b28 as S

R, J, U, X, y, rot, tspec, Fm, fastF, m_ = S.load_training()
mask = rot <= 2.0
info = json.load(open(S.D / "model.json", encoding="utf-8"))
slope, icpt = info["fastF_to_mesh"]
cal = info["calibration"]
cb, cF, cl = (np.array(info["curve"][k]) for k in ("bone", "F", "logf1"))
gp, mu, sd = S.fit_gp(X[mask], y[mask])
C = S.candidates()
uA = np.array(json.load(open(S.D / "inputs.json"))["uA"])
dA = np.linalg.norm(C["U"] - uA, axis=1)
inb = (C["bone"] >= cb[0]) & (C["bone"] <= cb[-1])
Fc = slope * C["F"] + icpt
pm, ps = np.zeros(len(Fc)), np.zeros(len(Fc))
for i0 in range(0, len(Fc), 3000):
    pm[i0:i0 + 3000], ps[i0:i0 + 3000] = gp.predict((C["X"][i0:i0 + 3000] - mu) / sd, return_std=True)
psc = ps * S.factor_of(cal, S.nn_dist(C["U"], U[mask]))
dF = Fc - np.interp(C["bone"], cb, cF)
dl = pm - np.interp(C["bone"], cb, cl)
P = S.p_beat(dF, info["fastF_resid_sd"], dl, psc)
dtrain = S.nn_dist(U[mask], U[mask][None, 0:1].reshape(1, -1)) if False else None
print("training designs by distance from A:", np.histogram(np.linalg.norm(U[mask] - uA, axis=1), bins=[0, 0.25, 0.5, 0.75, 1.0, 3])[0].tolist())
print("band       all  in-bone  bone>9.11  best dl   best dF   max P    n(dl<=0.1)")
for lo, hi in ((0, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 1.0), (1.0, 3.0)):
    k = (dA >= lo) & (dA < hi)
    kb = k & inb
    if not kb.any():
        print(f"{lo:.2f}-{hi:.2f}  {int(k.sum()):5d}  {int(kb.sum()):6d}  {int((k & (C['bone'] > cb[-1])).sum()):8d}   none")
        continue
    print(f"{lo:.2f}-{hi:.2f}  {int(k.sum()):5d}  {int(kb.sum()):6d}  {int((k & (C['bone'] > cb[-1])).sum()):8d}   {dl[kb].min():+.3f}   {dF[kb].max():+.1f}   {P[kb].max():.3f}   {int((kb & (dl <= 0.1)).sum())}")
k = inb & (dA >= 0.25)
o = np.argsort(dl[k])[:8]
ii = np.where(k)[0][o]
print("lowest predicted micromotion gap, distance >= 0.25:")
for i in ii:
    print(f"  {C['src'][i]}#{C['idx'][i]} dist {dA[i]:.2f} e {C['e'][i]:+.1f} bone {C['bone'][i]:.2f} dF {dF[i]:+.1f} dl {dl[i]:+.3f} sd {psc[i]:.3f} P {P[i]:.3f} m {0.5 + 1.5 * C['U'][i][3]:.2f}")
