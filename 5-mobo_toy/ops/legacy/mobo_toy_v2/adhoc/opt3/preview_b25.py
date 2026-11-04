"""Read-only preview of b25 from the queue, before the export: same F, micromotion and bone as experiments/b25_opt1, same thresholds. The formal verdict is ops/judge.py on the exported version.
usage: run.sh - < this file (from code/v2)."""
import glob, json, math, pathlib, sys
sys.path[:0] = [".", ".."]
import numpy as np
import jobs as J
import stability as S

Q = J.QROOT
N3 = np.array([0.381, 0.025, -0.924])
U_NECK = np.array([0.9138995811072274, 0.06263424660728525, 0.4010791777242645])
CREF = np.array([37.65271204198696, 0.8509371708090849, 41.89415555538172])
T = "db_ws_p13_a105_91e458e3_"
CURVE = (T + "ow_m1_e+2.5_8a2bd628", T + "ow_m1_e+2_c9ca96c8", T + "ow_m1_e+1.5_52dc478a", T + "ow_m1_e+1_fea69910", T + "ow_m1_e+0.5_c17f7b2a", T + "m1_2a79b613", T + "ow_m1_e-0.5_03b0a7bc")
PRED = {"opt1_01": (112.1, 22.49), "opt1_02": (117.3, 25.2), "opt1_03": (126.2, 15.29), "opt1_04": (126.7, 9.29), "opt1_05": (133.1, 11.21), "opt1_06": (134.0, 7.93), "opt1_07": (135.9, 6.41), "opt1_08": (141.2, 5.83)}


def row(job):
    d = Q / job
    spec, prep = json.load(open(d / "spec.json")), json.load(open(d / "prep.json"))
    res = json.load(open(d / "result.json"))
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
    zeta = -(X - CREF) @ U_NECK
    m = (zeta <= 15) & (np.abs(th) <= 45)
    st = S.stability(d)
    return {"F": float((w[m] / np.maximum(t[m], 0.25)).sum()), "f1": res["f1_p95_um"], "bone": prep["bone_loss"]["total_mm3"] / 1000, "rot": st["rot_first_deg"], "rev": st["rot_rev_deg"], "perm": st["rot_perm_deg"], "G7": res.get("f2_g7_loss_pct"), "e": tp["e"], "A0": tp["A0"], "tmin": float(t.min()), "contact": st["contact_area_load2_mm2"]}


C = {j: row(j) for j in CURVE}
print("A family check, F should be 101.7 107.0 114.8 120.6 128.2 136.6 142.5:", [round(C[j]["F"], 1) for j in CURVE])
cb = np.array([C[j]["bone"] for j in CURVE]); cF = np.array([C[j]["F"] for j in CURVE]); cl = np.log10([C[j]["f1"] for j in CURVE])
o = np.argsort(cb); cb, cF, cl = cb[o], cF[o], cl[o]
errs, good = [], []
print("tag e bone F (pred) dF f1 (pred) ratio rot_stair rev perm G7 contact")
for d in sorted(glob.glob(str(Q / "db_al_opt1_*"))):
    job = pathlib.Path(d).name
    tag = "_".join(job.split("_")[2:4])
    if not (Q / job / "DONE").exists():
        print(tag, "state", J.state(Q / job))
        continue
    r = row(job)
    dF = r["F"] - float(np.interp(r["bone"], cb, cF))
    ratio = r["f1"] / 10 ** float(np.interp(r["bone"], cb, cl))
    hit = dF >= 3.0 and ratio <= 0.96
    good += [tag] if hit else []
    errs.append(math.log10(PRED[tag][1]) - math.log10(r["f1"]))
    print(f"{tag} e {r['e']:+.2f} bone {r['bone']:.2f} F {r['F']:.1f} ({PRED[tag][0]}) {dF:+.1f} f1 {r['f1']:.2f} ({PRED[tag][1]}) x{ratio:.3f} rot {r['rot']:.4f} rev {r['rev']:.4f} perm {r['perm']:.4f} G7 {r['G7']} contact {r['contact']:.0f} {'IMPROVED' if hit else ''}")
if errs:
    print("n", len(errs), "improved", good, "RMSE", round(float(np.sqrt(np.mean(np.square(errs)))), 4), "bias pred-FE", round(float(np.mean(errs)), 4))
