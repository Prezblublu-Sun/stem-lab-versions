"""A7 (added in the resumed run, 2026-10-22 evening): can the BONDED model (~35 s Abaqus) screen rotation / contact?

The bonded model has no relative motion, so rotation and contact cannot be read from it directly.  The question is whether its
load-transfer FIELD (not just the two scalars SED change and stem vM P99 already tested in A6) carries information about the
friction-model rotation / closed contact area that the zero-cost template geometry does not.

Per collarless design (the same 165 rows as A6, from collarless_dataset.npz), from mesh3d.npz + m_bond_csv/LOAD_ENER.csv,
LOAD_S.csv (read-only):
  b_sed_if_canc     log10 volume-weighted mean SED of cancellous elements touching an interface bone node
  b_vm_if_canc_p95  P95 von Mises of those elements
  b_eif_share       energy in interface-adjacent bone elements / total bone energy
  b_cort_share      cortical energy / total bone energy
  b_load_centroid   energy-weighted mean axial position of interface-adjacent bone energy, 0 = proximal end of the interface,
                    1 = distal end (axis = principal axis of the interface nodes, oriented by the head side of the stem mesh)
  b_prox_share      share of interface-adjacent bone energy in the proximal third of the interface
  b_stem_share      stem strain energy / total strain energy
  b_total_energy    log10 total strain energy (= construct compliance under the fixed head load)
Then 5-fold GP CV (same GP, same fold permutation as A6) and a p9 -> p10 extrapolation test for feature sets with / without
these 8 bonded-field features.  Writes OUT/bondfield.json and OUT/bondfield_features.csv.
"""
from __future__ import annotations

import csv
import time

import numpy as np
import torch

import eff_common as E

torch.set_default_dtype(torch.double)
t0 = time.time()
QROOT = E.HOME / "queue"


def read_csv_cols(p, cols):
    with open(p, newline="") as fh:
        rd = csv.reader(fh)
        head = next(rd)
        idx = [head.index(c) for c in cols]
        a = np.array([[float(r[i]) for i in idx] for r in rd])
    return a


def table(arr_elem, arr_val, n):
    out = np.full(n + 1, np.nan)
    el = arr_elem.astype(int)
    k = el <= n
    out[el[k]] = arr_val[k]
    return out


def features(job):
    d = QROOT / job
    m = dict(np.load(d / "mesh3d.npz"))
    lab, X = m["node_labels"], m["nodes"]
    lut = np.full(int(lab.max()) + 1, -1)
    lut[lab] = np.arange(len(lab))
    en = read_csv_cols(d / "m_bond_csv" / "LOAD_ENER.csv", ["elem", "else", "evol"])
    st = read_csv_cols(d / "m_bond_csv" / "LOAD_S.csv", ["elem", "mises"])
    n = int(max(en[:, 0].max(), st[:, 0].max()))
    ELSE, EVOL, VM = table(en[:, 0], en[:, 1], n), table(en[:, 0], en[:, 2], n), table(st[:, 0], st[:, 1], n)
    ifb = np.zeros(int(lab.max()) + 1, bool)
    ifb[m["pair_bone"].astype(int)] = True
    Pif = X[lut[m["pair_bone"].astype(int)]]
    c0 = Pif.mean(0)
    _, _, vt = np.linalg.svd(Pif - c0, full_matrices=False)
    ax = vt[0]
    s_if = (Pif - c0) @ ax
    s_st = (X[lut[np.unique(m["stem_conn"][:, :4].astype(int))]] - c0) @ ax
    if (s_st.max() - s_if.max()) > abs(s_st.min() - s_if.min()):   # +ax points to the head side -> flip so +ax is distal
        ax, s_if = -ax, -s_if
    s_lo, s_hi = s_if.min(), s_if.max()
    reg = {}
    for r in ("cortex", "cancellous", "stem"):
        conn = m[f"{r}_conn"].astype(int)
        el = m[f"{r}_elab"].astype(int)
        touch = ifb[conn].any(1)
        cen = X[lut[conn[:, :4]]].mean(1)
        reg[r] = {"e": ELSE[el], "v": EVOL[el], "vm": VM[el], "touch": touch, "s": ((cen - c0) @ ax - s_lo) / max(s_hi - s_lo, 1e-9)}
    e_bone = np.nansum(reg["cortex"]["e"]) + np.nansum(reg["cancellous"]["e"])
    e_all = e_bone + np.nansum(reg["stem"]["e"])
    ca = reg["cancellous"]
    t = ca["touch"] & np.isfinite(ca["e"]) & np.isfinite(ca["v"]) & (ca["v"] > 0)
    sed_if = ca["e"][t].sum() / ca["v"][t].sum()
    eb_if, sb_if = [], []
    for r in ("cortex", "cancellous"):
        k = reg[r]["touch"] & np.isfinite(reg[r]["e"])
        eb_if.append(reg[r]["e"][k]); sb_if.append(reg[r]["s"][k])
    eb_if, sb_if = np.concatenate(eb_if), np.concatenate(sb_if)
    return {"b_sed_if_canc": float(np.log10(max(sed_if, 1e-12))),
            "b_vm_if_canc_p95": float(np.nanpercentile(ca["vm"][t], 95)),
            "b_eif_share": float(eb_if.sum() / e_bone),
            "b_cort_share": float(np.nansum(reg["cortex"]["e"]) / e_bone),
            "b_load_centroid": float((eb_if * sb_if).sum() / eb_if.sum()),
            "b_prox_share": float(eb_if[sb_if < 1 / 3].sum() / eb_if.sum()),
            "b_stem_share": float(np.nansum(reg["stem"]["e"]) / e_all),
            "b_total_energy": float(np.log10(e_all)),
            "n_if_canc_elems": int(t.sum()), "n_if_cort_elems": int((reg["cortex"]["touch"]).sum())}


z = np.load(E.OUT / "collarless_dataset.npz", allow_pickle=True)
jobs = [str(j) for j in z["job"]]
BK = ["b_sed_if_canc", "b_vm_if_canc_p95", "b_eif_share", "b_cort_share", "b_load_centroid", "b_prox_share", "b_stem_share", "b_total_energy"]
rows, errs = [], {}
for i, j in enumerate(jobs):
    try:
        rows.append(features(j))
    except Exception as ex:  # noqa: BLE001
        errs[j] = repr(ex)[:200]
        rows.append({k: float("nan") for k in BK})
    if i % 20 == 0:
        print(f"{i}/{len(jobs)} {j} {time.time() - t0:.0f}s", flush=True)
Bf = np.array([[r[k] for k in BK] for r in rows], float)
with open(E.OUT / "bondfield_features.csv", "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["job", "family"] + BK + ["n_if_canc_elems", "n_if_cort_elems", "y_rot", "y_con", "c_sed", "c_vm"])
    for j, fam, r, yr, yc, cs, cv in zip(jobs, z["family"], rows, z["y_rot"], z["y_con"], z["c_sed"], z["c_vm"]):
        w.writerow([j, fam] + [r.get(k) for k in BK] + [r.get("n_if_canc_elems"), r.get("n_if_cort_elems"), yr, yc, cs, cv])

out = {"n": len(jobs), "n_errors": len(errs), "errors": errs, "features": BK, "spearman": {}}
for k, col in zip(BK, Bf.T):
    out["spearman"][k] = {t: E.spearman(col, z[t])[0] for t in ("y_rot", "y_con", "c_mm", "c_sed", "c_vm")}
    out["spearman"][k]["px_geo_area_mm2"] = E.spearman(col, z["px_geo_area_mm2"])[0]
    out["spearman"][k]["px_L"] = E.spearman(col, z["px_L"])[0]

# ---- same CV protocol as A6
import stage_v2a as S  # noqa: E402

geo_keys = ["px_geo_area_mm2", "px_near_area_mm2", "px_mean_wall_mm", "px_tpl_volume", "px_tpl_A0", "px_tpl_e", "px_tpl_s_bind", "px_tpl_contact"]
G = np.column_stack([z[k].astype(float) for k in geo_keys])
G = G[:, np.all(np.isfinite(G), 0)]


def mm(A):
    A = np.asarray(A, float)
    lo, hi = np.nanmin(A, 0), np.nanmax(A, 0)
    return (A - lo) / np.maximum(hi - lo, 1e-12)


G, Bn, Xd = mm(G), mm(Bf), z["X9"]
sedb, vmb = z["c_sed"], z["c_vm"]
B2 = np.c_[mm(sedb), mm(vmb)]
feats = {"design13": Xd, "bondfield8": Bn, "bondfield8+bond(sed,vm)": np.c_[Bn, B2], "design13+bondfield8": np.c_[Xd, Bn],
         "geometry8": G, "design13+geometry8": np.c_[Xd, G], "design13+geometry8+bondfield8": np.c_[Xd, G, Bn]}
rng = np.random.default_rng(1)
perm = rng.permutation(len(Xd))
fam = np.array([str(f) for f in z["family"]])
tr9, te10 = np.where(fam == "neck9")[0], np.where(fam == "neck10")[0]
cv = {}
for yk in ("y_rot", "y_con"):
    y = z[yk]
    cv[yk] = {}
    for fn, F in feats.items():
        ok = np.all(np.isfinite(F), 1)
        pred = np.full(len(y), np.nan)
        for k in range(5):
            te = perm[k::5]; te = te[ok[te]]
            tr = np.setdiff1d(perm, perm[k::5]); tr = tr[ok[tr]]
            gp = S._fit_gp_unit(torch.as_tensor(F[tr]), torch.as_tensor(y[tr]))
            with torch.no_grad():
                pred[te] = gp.posterior(torch.as_tensor(F[te])).mean.numpy().ravel()
        msk = np.isfinite(pred)
        r2 = float(1 - ((y[msk] - pred[msk]) ** 2).sum() / ((y[msk] - y[msk].mean()) ** 2).sum())
        a, b = tr9[ok[tr9]], te10[ok[te10]]
        gp = S._fit_gp_unit(torch.as_tensor(F[a]), torch.as_tensor(y[a]))
        with torch.no_grad():
            p10 = gp.posterior(torch.as_tensor(F[b])).mean.numpy().ravel()
        cv[yk][fn] = {"cv5_R2": r2, "cv5_spearman": E.spearman(y[msk], pred[msk])[0], "n": int(msk.sum()),
                      "p9_to_p10_spearman": E.spearman(y[b], p10)[0], "n_p10": int(len(b))}
        print(yk, fn, round(r2, 3), round(cv[yk][fn]["p9_to_p10_spearman"], 3), f"{time.time() - t0:.0f}s", flush=True)
out["cv"] = cv
out["note"] = ("bonded-model LOAD-step field features; GP = stage_v2a._fit_gp_unit (Matern 5/2 ARD, as in A6), 5-fold CV with the A6 "
               "fold permutation (default_rng(1)); p9_to_p10 = train on the 99 neck9 rows, Spearman on the 66 neck10 rows")
out["wall_s"] = time.time() - t0
E.dump("bondfield.json", out)
print("DONE", f"{time.time() - t0:.0f}s", "errors", len(errs))
