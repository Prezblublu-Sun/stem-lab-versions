"""Step 5: multi-fidelity evidence from existing results (no new FE), read-only.

A1  truncated step sequence (PRESSFIT, RELEASE, LOAD only): rotation is LOAD-RELEASE (identical); contact at LOAD vs LOAD2;
    first-load micromotion vs recoverable (2nd cycle) micromotion; constraint classification agreement; phase-10 front identity.
A2  mesh fidelity h_int 1.4 vs 2.0 (verify mesh14 vs production source jobs; m1 base/readout/short)
A3  remesh noise (remesh family dL +-0.002 pairs; m1 h 1.94-2.06 jitter)
A4  solver tolerance slip_tol and cycles=3 (m1)
A5  constraint sources: vM P99 and calcar SED come from the bonded model (~35 s) -> how many phase-9/10 evaluations were infeasible
    on a bonded-model constraint alone (friction solve could have been skipped)
A6  cheap predictors of rotation / contact on the 165 collarless rows: geometry-only (templating, ~0.3 s) and geometry + bonded SED/vM,
    5-fold CV R2 (GP) and Spearman
B   CalculiX vs Abaqus on the v3 quantities: stability() on the ccx trial run folders (read-only) vs the Abaqus originals
writes OUT/fidelity.json
"""
from __future__ import annotations

import json
import math
from collections import defaultdict

import numpy as np

import eff_common as E

f = E.fnum
rows = E.read_table()
clean = [r for r in rows if E.tbool(r["current_code"]) and r["variant_class"] == "none"]
coll = [r for r in clean if r["collar_rule"] == "neck_in_shoulder" and f(r["collar_w"]) == 0.0]
out = {"n_clean": len(clean), "n_collarless": len(coll)}


def sp(a, b):
    return E.spearman(a, b)[0]


def arr(rs, k):
    return np.array([f(r[k]) for r in rs])


# ---------------------------------------------------------------- A1 truncated sequence
a1 = {}
for name, rs in (("collarless_165", coll), ("clean_795", clean),
                 ("collared_627", [r for r in clean if f(r["collar_w"]) > 0])):
    cl, cl2 = arr(rs, "contact_area_load_mm2"), arr(rs, "contact_area_load2_mm2")
    ff, f1 = arr(rs, "f1_first_p95_um"), arr(rs, "f1_p95_um")
    ok = np.isfinite(ff) & np.isfinite(f1) & (ff > 0) & (f1 > 0)
    A = np.c_[np.ones(ok.sum()), np.log10(ff[ok])]
    coef, *_ = np.linalg.lstsq(A, np.log10(f1[ok]), rcond=None)
    res = np.log10(f1[ok]) - A @ coef
    a1[name] = {"n": len(rs), "spearman_contact_load_vs_load2": sp(cl, cl2),
                "contact_load_over_load2_median": float(np.nanmedian(cl / cl2)), "contact_load_over_load2_p5_p95": np.nanpercentile(cl / cl2, [5, 95]).tolist(),
                "spearman_f1first_vs_f1": sp(ff, f1), "loglog_fit_f1_on_f1first": coef.tolist(), "loglog_resid_sd": float(res.std()),
                "spearman_contactfrac_load_vs_load2": sp(arr(rs, "contact_frac_load"), arr(rs, "contact_frac_load2"))}
    # classification of f1 <= 150 with a first-load threshold calibrated to give no false negatives on this subset
    viol = f1 > E.MM_LIMIT
    a1[name]["n_violate_f1_150"] = int(viol.sum())
    if viol.any():
        thr = float(np.nanmin(ff[viol]))
        a1[name]["first_load_threshold_no_false_neg"] = thr
        a1[name]["n_flagged_by_threshold"] = int((ff >= thr).sum())
# phase-10 front with LOAD vs LOAD2 contact
p10 = [r for r in coll if f(r["nk_phase"]) == 10]


def front(Y, feas):
    import mobo
    idx = np.nonzero(feas)[0]
    return set(idx[mobo.pareto_mask(Y[idx])].tolist())


feas10 = np.array([f(r["nk_c"]) <= 0 for r in p10])
Yl2 = np.c_[np.log10(np.maximum(arr(p10, "rot_first_deg"), 1e-3)), -arr(p10, "contact_area_load2_mm2")]
Yl1 = np.c_[Yl2[:, 0], -arr(p10, "contact_area_load_mm2")]
fr2, fr1 = front(Yl2, feas10), front(Yl1, feas10)
a1["p10_front_load2"] = sorted(p10[i]["job"] for i in fr2)
a1["p10_front_load"] = sorted(p10[i]["job"] for i in fr1)
a1["p10_front_same"] = fr1 == fr2
out["A1_truncated_steps"] = a1

# ---------------------------------------------------------------- A2-A4 fidelity pairs
DK = ("L", "alpha", "collar_w", "h_cut", "m", "rho_tip", "q", "lam", "g_ml", "g_ap", "n_a", "n_p", "tau_a", "tau_p", "tip", "collar_rule")


def dkey(r):
    d = tuple((k, round(f(r[k]), 4) if k not in ("tip", "collar_rule") else r[k]) for k in DK)
    model = (r["current_code"], r["prep_delta"] or r["spec_delta"], r["spec_mu"], r["spec_E_canc"], r["load_override"], r["cfg_desc"], r["spec_torque"])
    return d, model


grp = defaultdict(list)
for r in rows:
    grp[dkey(r)].append(r)
Q = ("rot_first_deg", "contact_area_load2_mm2", "f1_p95_um", "f1_first_p95_um", "vm_p99", "sed_chg_pct", "fric_wall_s")


def fid(r):
    return (round(f(r["h_int"]), 2), f(r["prep_slip_tol"]), f(r["prep_cycles"]) if r["prep_cycles"] else 2.0)


pairs = defaultdict(list)
for (d, model), rs in grp.items():
    byf = defaultdict(list)
    for r in rs:
        byf[fid(r)].append(r)
    prod = [k for k in byf if k[0] == 2.0 and abs(k[1] - 2.5e-4) < 1e-9 and k[2] == 2.0]
    if not prod:
        continue
    base = byf[prod[0]][0]
    for k, rr in byf.items():
        if k == prod[0]:
            if len(rr) > 1:
                for r2 in rr[1:]:
                    pairs["replicate"].append((base, r2))
            continue
        lab = ("h1.4" if k[0] == 1.4 else "h_jitter" if abs(k[0] - 2.0) < 0.1 else f"h{k[0]}") if k[0] != 2.0 else \
              (f"slip_tol={k[1]:.4g}" if abs(k[1] - 2.5e-4) > 1e-9 else f"cycles={k[2]:.0f}")
        if k[0] != 2.0 and abs(k[1] - 2.5e-4) > 1e-9 and k[0] == 1.4:
            lab = "h1.4(tol scaled)"
        for r2 in rr:
            pairs[lab].append((base, r2))
# remesh family: pairs L+-0.002
rem = [r for r in rows if r["family_root"] == "remesh"]
byb = defaultdict(list)
for r in rem:
    byb[r["tag"].split("_")[0]].append(r)
for k, rr in byb.items():
    if len(rr) == 2:
        pairs["remesh_dL0.002"].append((rr[0], rr[1]))
a2 = {}
for lab, pr in pairs.items():
    d = {"n_pairs": len(pr), "families": sorted({b["family_root"] for _, b in pr})}
    for qk in Q:
        a = np.array([f(x[qk]) for x, _ in pr]); b = np.array([f(y[qk]) for _, y in pr])
        ok = np.isfinite(a) & np.isfinite(b) & (np.abs(a) > 1e-12)
        if ok.sum() == 0:
            continue
        rel = (b[ok] - a[ok]) / np.abs(a[ok])
        d[qk] = {"median_rel_change": float(np.median(rel)), "max_abs_rel_change": float(np.max(np.abs(rel))),
                 "spearman": sp(a[ok], b[ok]) if ok.sum() >= 4 else None}
    a2[lab] = d
out["A2_A4_fidelity_pairs"] = a2
out["A2_A4_pair_list"] = {lab: [(x["job"], y["job"]) for x, y in pr] for lab, pr in pairs.items()}

# ---------------------------------------------------------------- A5 which constraint made p9/p10 designs infeasible
a5 = {}
for ph in (9, 10):
    rs = [r for r in coll if f(r["nk_phase"]) == ph]
    f1 = arr(rs, "f1_p95_um"); vm = arr(rs, "vm_p99"); sed = arr(rs, "sed_chg_pct")
    v_mm, v_vm, v_sed = f1 > E.MM_LIMIT, vm > E.VM_LIMIT, np.abs(sed) > E.SED_LIMIT
    a5[f"p{ph}"] = {"n": len(rs), "viol_mm": int(v_mm.sum()), "viol_vm": int(v_vm.sum()), "viol_sed": int(v_sed.sum()),
                    "viol_any": int((v_mm | v_vm | v_sed).sum()), "viol_bond_only(vm|sed)": int((v_vm | v_sed).sum()),
                    "viol_bond_only_and_not_mm": int(((v_vm | v_sed) & ~v_mm).sum()),
                    "sed_range": [float(np.nanmin(sed)), float(np.nanmax(sed))], "vm_max": float(np.nanmax(vm)), "f1_max": float(np.nanmax(f1))}
# phase-10 BO records (new evaluations only, in neckopt_p10.json order)
st = json.loads((E.HOME / "results" / "neckopt_p10.json").read_text())
recs = st["records"]
okr = [r for r in recs if r["ok"]]
a5["p10_records"] = {"n": len(recs), "ok": len(okr), "failed": len(recs) - len(okr),
                     "infeasible": sum(r["c"][0] > 0 for r in okr),
                     "infeasible_sed": sum(abs(r["sed_chg_pct"]) > E.SED_LIMIT for r in okr if r.get("sed_chg_pct") is not None),
                     "infeasible_vm": sum((r.get("vm_p99") or 0) > E.VM_LIMIT for r in okr),
                     "infeasible_mm": sum((r.get("f1_body_p95_um") or 0) > E.MM_LIMIT for r in okr)}
out["A5_constraint_sources"] = a5

# ---------------------------------------------------------------- A6 cheap predictors (collarless 165)
import torch  # noqa: E402
import stage_v2a as S  # noqa: E402

torch.set_default_dtype(torch.double)
z = np.load(E.OUT / "collarless_dataset.npz", allow_pickle=True)
geo_keys = ["px_geo_area_mm2", "px_near_area_mm2", "px_mean_wall_mm", "px_tpl_volume", "px_tpl_A0", "px_tpl_e", "px_tpl_s_bind", "px_tpl_contact"]
G = np.column_stack([z[k].astype(float) for k in geo_keys])
keepc = np.all(np.isfinite(G), 0)
out["A6_geometry_features_used"] = [k for k, kk in zip(geo_keys, keepc) if kk]
G = G[:, keepc]
G = (G - G.min(0)) / np.maximum(G.max(0) - G.min(0), 1e-12)
Xd = z["X9"]
sedb = z["c_sed"]; vmb = z["c_vm"]
B = np.c_[(sedb - sedb.min()) / np.ptp(sedb), (vmb - vmb.min()) / np.ptp(vmb)]
feats = {"design13": Xd, "geometry8": G, "design13+geometry8": np.c_[Xd, G], "design13+geometry8+bond(sed,vm)": np.c_[Xd, G, B]}
a6 = {}
rng = np.random.default_rng(1)
perm = rng.permutation(len(Xd))
for yk in ("y_rot", "y_con", "c_mm"):
    y = z[yk]
    a6[yk] = {}
    for fn, F in feats.items():
        ok = np.all(np.isfinite(F), 1)
        pred = np.full(len(y), np.nan)
        for k in range(5):
            te = perm[k::5]; te = te[ok[te]]
            tr = np.setdiff1d(perm, perm[k::5]); tr = tr[ok[tr]]
            gp = S._fit_gp_unit(torch.as_tensor(F[tr]), torch.as_tensor(y[tr]))
            with torch.no_grad():
                pred[te] = gp.posterior(torch.as_tensor(F[te])).mean.numpy().ravel()
        m = np.isfinite(pred)
        a6[yk][fn] = {"cv5_R2": float(1 - ((y[m] - pred[m]) ** 2).sum() / ((y[m] - y[m].mean()) ** 2).sum()), "cv5_spearman": sp(y[m], pred[m]),
                      "n": int(m.sum())}
    print(yk, {k: round(v["cv5_R2"], 3) for k, v in a6[yk].items()}, flush=True)
out["A6_cheap_predictors_cv"] = a6
out["A6_note"] = ("geometry8 = template/geometric quantities computable in ~0.3 s without FE; bond(sed, vm) = outputs of the bonded "
                  "model (~35 s Abaqus); y_rot = log10 rotation, y_con = closed contact area LOAD2, c_mm = log10 stem micromotion")

# ---------------------------------------------------------------- B CalculiX vs Abaqus on stability quantities
import stability as ST  # noqa: E402
import jobs as J  # noqa: E402

b = []
for qd in sorted((E.HOME / "ccx").glob("queue*")):
    for d in sorted(qd.glob("neck*")):
        if not (d / "DONE").exists() or not (d / "m_fric_csv" / "LOAD2_U.csv").exists():
            continue
        try:
            sc = ST.stability(d)
            sa = ST.stability(J.QROOT / d.name)
        except Exception as e:  # noqa: BLE001
            b.append({"job": d.name, "queue": qd.name, "error": f"{type(e).__name__}: {str(e)[:100]}"})
            continue
        b.append({"job": d.name, "queue": qd.name, **{f"abq_{k}": sa[k] for k in ("rot_first_deg", "contact_area_load2_mm2", "contact_frac_load2", "rot_tilt_first_deg")},
                  **{f"ccx_{k}": sc[k] for k in ("rot_first_deg", "contact_area_load2_mm2", "contact_frac_load2", "rot_tilt_first_deg")}})
out["B_ccx_vs_abaqus_stability"] = b
if b:
    g = [x for x in b if "error" not in x]
    for k in ("rot_first_deg", "contact_area_load2_mm2", "contact_frac_load2"):
        a = np.array([x[f"abq_{k}"] for x in g]); c = np.array([x[f"ccx_{k}"] for x in g])
        out.setdefault("B_summary", {})[k] = {"n": len(g), "median_ratio_ccx_over_abq": float(np.median(c / a)),
                                             "min_ratio": float(np.min(c / a)), "max_ratio": float(np.max(c / a)),
                                             "spearman": sp(a, c) if len(g) >= 4 else None}
E.dump("fidelity.json", out)
print(json.dumps({k: v for k, v in out.items() if k not in ("A2_A4_pair_list",)}, indent=1, default=float)[:12000])
