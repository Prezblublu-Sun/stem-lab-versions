"""Existing FE rows only, no model: how close to the A family curve do computed designs get, by unit distance from A. Local, 0 FE, read only.

    python -X utf8 fe_by_distance.py
"""
import json

import numpy as np

import select_b28 as S

R, J, U, X, y, rot, tspec, Fm, fastF, m_ = S.load_training()
info = json.load(open(S.D / "model.json", encoding="utf-8"))
cb, cF, cl = (np.array(info["curve"][k]) for k in ("bone", "F", "logf1"))
uA = np.array(json.load(open(S.D / "inputs.json"))["uA"])
box = np.array([R[j]["in_bounds_v1"] == "true" for j in J])
bone = np.array([S.num(R[j]["bone_total_mm3"]) / 1000 for j in J])
Fv = np.array([Fm.get(j, np.nan) for j in J])
d = np.linalg.norm(U - uA, axis=1)
ok = box & (m_ >= 0.999) & np.isfinite(Fv) & (bone >= cb[0]) & (bone <= cb[-1])
dl = y - np.interp(bone, cb, cl)
dF = Fv - np.interp(bone, cb, cF)
print("FE rows, m >= 1, in box, bone within the A curve range; gaps against the A family curve at the same bone")
print("band        rows  best dl (x)       best dF   rows within 0.1 dex   rows dl<=0.1 and dF>=-5")
for lo, hi in ((0, 0.1), (0.1, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 1.0), (1.0, 3.0)):
    k = ok & (d >= lo) & (d < hi)
    if not k.any():
        print(f"{lo:.2f}-{hi:.2f}     0"); continue
    print(f"{lo:.2f}-{hi:.2f}  {int(k.sum()):5d}  {dl[k].min():+.3f} (x{10 ** dl[k].min():.2f})   {dF[k].max():+6.1f}   {int((k & (dl <= 0.1)).sum()):5d}               {int((k & (dl <= 0.1) & (dF >= -5)).sum())}")
k = ok & (d >= 0.25)
o = np.argsort(dl[k])[:8]
print("closest FE rows to the A curve with distance >= 0.25:")
for i in np.where(k)[0][o]:
    print(f"  {J[i][:46]:46s} dist {d[i]:.2f} bone {bone[i]:.2f} F {Fv[i]:.1f} dF {dF[i]:+.1f} f1 {10 ** y[i]:.1f} dl {dl[i]:+.3f} m {m_[i]:.2f} layer {R[J[i]]['layer']}")
