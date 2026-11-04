"""Read-only: b25 under both depth axes, from the queue. Old = the constant in experiments/b25_opt1 (frozen), new = the femur's own neck axis. Also checks the axis against the femur object.
usage: run.sh <this> (from code/v2)."""
import glob, json, math, pathlib, sys
sys.path[:0] = [".", ".."]
import numpy as np
import jobs as J

Q = J.QROOT
N3 = np.array([0.381, 0.025, -0.924])
U_OLD = np.array([0.9138995811072274, 0.06263424660728525, 0.4010791777242645])
CREF = np.array([37.65271204198696, 0.8509371708090849, 41.89415555538172])
T = "db_ws_p13_a105_91e458e3_"
CURVE = (T + "ow_m1_e+2.5_8a2bd628", T + "ow_m1_e+2_c9ca96c8", T + "ow_m1_e+1.5_52dc478a", T + "ow_m1_e+1_fea69910", T + "ow_m1_e+0.5_c17f7b2a", T + "m1_2a79b613", T + "ow_m1_e-0.5_03b0a7bc")
PRED = {"opt1_01": 22.49, "opt1_02": 25.2, "opt1_03": 15.29, "opt1_04": 9.29, "opt1_05": 11.21, "opt1_06": 7.93, "opt1_07": 6.41, "opt1_08": 5.83}
sp0 = json.load(open(Q / CURVE[5] / "spec.json"))
fm0 = J.femur_for({"femur_id": sp0.get("femur_id"), "neck_axis": sp0.get("neck_axis"), "h_cut": sp0.get("h_cut")})
H = np.asarray(fm0.H, float)
C03 = np.asarray(fm0.C03, float)
print("femur attributes with u or axis:", [a for a in dir(fm0) if a in ("u", "neck_u", "neck_axis", "axis", "u_neck", "u_baked") or "neck" in a.lower()][:12])
U_NEW = None
for a in ("u", "neck_u", "u_neck", "neck_axis"):
    v = getattr(fm0, a, None)
    if v is not None and np.size(v) == 3:
        U_NEW = np.asarray(v, float) / np.linalg.norm(v)
        print("femur", a, U_NEW.tolist())
        break
pr0 = json.load(open(Q / "db_cd_p13_a105_91e458e3_m1_TA10_e31bfa78" / "prep.json")) if (Q / "db_cd_p13_a105_91e458e3_m1_TA10_e31bfa78" / "prep.json").exists() else None
print("H", H.tolist(), "CREF from H - 16 u_old", (H - 16 * U_OLD).round(4).tolist(), "stored CREF", CREF.round(4).tolist())
U_GEO = np.array([0.92228, 0.06137, 0.38162]); U_GEO /= np.linalg.norm(U_GEO)
if U_NEW is None:
    U_NEW = U_GEO
print("CREF from H - 16 u_new", (H - 16 * U_NEW).round(4).tolist(), "angle old vs new deg", round(math.degrees(math.acos(float(U_OLD @ U_NEW))), 3))


def row(job):
    d = Q / job
    spec, prep, res = json.load(open(d / "spec.json")), json.load(open(d / "prep.json")), json.load(open(d / "result.json"))
    z = np.load(d / "mesh3d.npz", allow_pickle=True)
    labs = z["node_labels"].astype(int)
    lut = np.full(labs.max() + 1, -1)
    lut[labs] = np.arange(len(labs))
    body = ~z["pair_collar"].astype(bool)
    X = z["nodes"][lut[z["pair_bone"].astype(int)]][body]
    w = z["pair_area"][body]
    fm = J.femur_for({"femur_id": spec.get("femur_id"), "neck_axis": spec.get("neck_axis"), "h_cut": spec.get("h_cut")})
    t = -np.asarray(fm.canal_sdf(X), float)
    tp = prep["templating"]
    P0, ax = (np.asarray(v, float) for v in fm.pose(tp["alpha"], tp["e"])[:2])
    ax = ax / np.linalg.norm(ax)
    q = X - P0
    rad = q - (q @ ax)[:, None] * ax
    em = N3 - (N3 @ ax) * ax
    em /= np.linalg.norm(em)
    ep = np.array([0.0, 1.0, 0.0]) - ax[1] * ax
    ep /= np.linalg.norm(ep)
    th = np.degrees(np.arctan2(rad @ ep, rad @ em))
    out = {"f1": res["f1_p95_um"], "bone": prep["bone_loss"]["total_mm3"] / 1000}
    for lab, u in (("old", U_OLD), ("new", U_NEW)):
        m = (-(X - CREF) @ u <= 15) & (np.abs(th) <= 45)
        out[lab] = float((w[m] / np.maximum(t[m], 0.25)).sum())
    return out


C = {j: row(j) for j in CURVE}
print("A family F old:", [round(C[j]["old"], 1) for j in CURVE], " new:", [round(C[j]["new"], 1) for j in CURVE])
cb = np.array([C[j]["bone"] for j in CURVE]); cl = np.log10([C[j]["f1"] for j in CURVE])
o = np.argsort(cb)
curves = {lab: np.array([C[j][lab] for j in CURVE])[o] for lab in ("old", "new")}
cb, cl = cb[o], cl[o]
hits = {"old": [], "new": []}
errs = []
for d in sorted(glob.glob(str(Q / "db_al_opt1_*"))):
    job = pathlib.Path(d).name
    tag = "_".join(job.split("_")[2:4])
    if not (Q / job / "DONE").exists():
        print(tag, J.state(Q / job))
        continue
    r = row(job)
    ratio = r["f1"] / 10 ** float(np.interp(r["bone"], cb, cl))
    errs.append(math.log10(PRED[tag]) - math.log10(r["f1"]))
    cells = []
    for lab in ("old", "new"):
        dF = r[lab] - float(np.interp(r["bone"], cb, curves[lab]))
        if dF >= 3.0 and ratio <= 0.96:
            hits[lab].append(tag)
        cells.append(f"{lab} F {r[lab]:.1f} dF {dF:+.1f}")
    print(f"{tag} bone {r['bone']:.2f} f1 {r['f1']:.2f} (pred {PRED[tag]}) x{ratio:.3f} | " + " | ".join(cells))
print("improved, old axis", hits["old"], "new axis", hits["new"], "n", len(errs), "RMSE", round(float(np.sqrt(np.mean(np.square(errs)))), 4), "bias pred-FE", round(float(np.mean(errs)), 4))
