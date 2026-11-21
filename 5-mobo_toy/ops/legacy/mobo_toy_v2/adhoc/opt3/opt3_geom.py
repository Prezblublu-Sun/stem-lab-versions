"""Geometry of a stem without a mesh: F, bone removed and the bed quantities, from the same surface sampling and analytic canal distance as pool_area_features. 0 FE, read only.

Linux, from ~/mobo_toy_v2/code:
    ../run.sh <this> jobs <jobs.txt> <out.npz> [workers]         rows that already exist: design, h_cut and templating come from their spec.json and prep.json
    ../run.sh <this> pool <pool.npz> <idx.npy> <out.npz> [w]     pool points at the e and size already templated there
    ../run.sh <this> fixe <u13.npy> <e.npy> <out.npz> [w]        unit-cube points at a given entry offset; the size is templated at that offset by the production rule

F = sum A / max(t, 0.25) over zeta <= 15 mm, |theta| <= 45 deg, t = -canal_sdf (data/zfe_fit_metric.jsonl z15_S_med is the mesh version). The other columns are inputs for the micromotion model.
"""
import json
import math
import pathlib
import sys
import time
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, "v2")
import collar_rule as CR  # noqa: E402
import geom3d as G  # noqa: E402
import jobs as J  # noqa: E402
import stage_neckopt as SN  # noqa: E402
import tpl_record as TR  # noqa: E402

N3 = np.array([0.381, 0.025, -0.924])
U_NECK = np.array([0.9138995811072274, 0.06263424660728525, 0.4010791777242645])
CREF = np.array([37.65271204198696, 0.8509371708090849, 41.89415555538172])
T0 = 0.25
E_F, G_F = 155.0, 155.0 / (2 * 1.3)
HEAD = np.array([52.409, 1.833, 48.0])
Q = J.QROOT
COLS = ("geo_area", "near_area", "mean_wall", "F", "F_A", "F_z10", "F_z20", "F_m30", "F_m60", "S_all", "S_z15", "t_min", "t_mean", "Kt_all", "R_fnd", "R_spin", "R_tilt", "Kr_axis", "Kr_min", "resid")
PH = None
LOAD = None


def rings_of(st, A0, ns=70, m=64, ncap=6):
    """Same rings as pool_area_features.surface_quads, kept as corners so that areas and normals are taken in the world frame."""
    sec = G.unit_section(st.d, m)
    s = np.r_[np.linspace(G.S_TOP, 0, 8, endpoint=False), np.linspace(0, st.L, ns)]
    k = np.sqrt(A0 * st.area_ratio(s))
    rings = [np.c_[np.full(m, si), ki * sec] for si, ki in zip(s, k)]
    c = st.cap_length(A0)
    kt = math.sqrt(A0 * st.rho_tip)
    for t in np.linspace(0, 1, ncap + 1)[1:-1]:
        f = math.sqrt(max(1 - t * t, 0.0))
        rings.append(np.c_[np.full(m, st.L + c * t), f * kt * sec])
    return np.array(rings), np.array([st.L + c, 0.0, 0.0])


def quads(st, fm, pose, A0):
    R, tip = rings_of(st, A0)
    nr, m, _ = R.shape
    W = fm.to_world(R.reshape(-1, 3), pose).reshape(nr, m, 3)
    a, b = W[:-1], W[1:]
    a2, b2 = np.roll(a, -1, axis=1), np.roll(b, -1, axis=1)
    cr = np.cross(b2 - a, b - a2)
    area = 0.5 * np.linalg.norm(cr, axis=2)
    cen = (a + a2 + b + b2) / 4
    nrm = cr / np.maximum(np.linalg.norm(cr, axis=2, keepdims=True), 1e-12)
    a_, a2_ = W[-1], np.roll(W[-1], -1, axis=0)
    t_ = fm.to_world(tip[None], pose)[0]
    cr2 = np.cross(a2_ - a_, t_ - a_)
    return (np.vstack([cen.reshape(-1, 3), (a_ + a2_ + t_) / 3]), np.r_[area.ravel(), 0.5 * np.linalg.norm(cr2, axis=1)],
            np.vstack([nrm.reshape(-1, 3), cr2 / np.maximum(np.linalg.norm(cr2, axis=1, keepdims=True), 1e-12)]))


def bed(X, nrm, w, t, F):
    """6 x 6 stiffness of the stem on its foam bed, cortex rigid, friction sticking; an index, not a solver (zfe_support.foundation)."""
    te = np.maximum(t, T0)
    kn, kt = E_F / te, G_F / te
    c = (X * w[:, None]).sum(0) / w.sum()
    r = X - c
    D = kt[:, None, None] * np.eye(3)[None] + (kn - kt)[:, None, None] * nrm[:, :, None] * nrm[:, None, :]
    Rx = np.zeros((len(r), 3, 3))
    Rx[:, 0, 1], Rx[:, 0, 2], Rx[:, 1, 0], Rx[:, 1, 2], Rx[:, 2, 0], Rx[:, 2, 1] = -r[:, 2], r[:, 1], r[:, 2], -r[:, 0], -r[:, 1], r[:, 0]
    K = np.zeros((6, 6))
    K[:3, :3] = (w[:, None, None] * D).sum(0)
    DR = D @ Rx
    K[:3, 3:] = -(w[:, None, None] * DR).sum(0)
    K[3:, :3] = K[:3, 3:].T
    K[3:, 3:] = (w[:, None, None] * (np.transpose(Rx, (0, 2, 1)) @ DR)).sum(0)
    q = np.linalg.solve(K, np.r_[F, np.cross(HEAD - c, F)])
    return K, q


def features(st, fm, alpha, e, A0):
    pose = fm.pose(float(alpha), float(e))
    X, w, n = quads(st, fm, pose, float(A0))
    below = fm.below_cut(X)
    X, w, n = X[below], w[below], n[below]
    t = -fm.canal_sdf(X)
    o = fm.to_world(np.zeros((1, 3)), pose)[0]
    ax = fm.to_world(np.array([[1.0, 0, 0]]), pose)[0] - o
    ax /= np.linalg.norm(ax)
    q = X - o
    rad = q - (q @ ax)[:, None] * ax
    rho = np.linalg.norm(rad, axis=1)
    em = N3 - (N3 @ ax) * ax
    em /= np.linalg.norm(em)
    ep = np.array([0.0, 1.0, 0.0]) - ax[1] * ax
    ep /= np.linalg.norm(ep)
    th = np.degrees(np.arctan2(rad @ ep, rad @ em))
    zeta = -(X - CREF) @ U_NECK
    te = np.maximum(t, T0)
    spring = w / te
    med = np.abs(th) <= 45
    z15 = zeta <= 15
    tan_ = np.cross(ax, rad / np.maximum(rho, 1e-9)[:, None])
    ct = np.abs((n * tan_).sum(1))
    kt_loc = (G_F + (E_F - G_F) * ct ** 2) / te
    K, q6 = bed(X, n, w, t, LOAD)
    om = q6[3:]
    ev = np.linalg.eigvalsh(K[3:, 3:])
    out = {"geo_area": w.sum(), "near_area": w[t <= st.m + 1.0].sum(), "mean_wall": (w * t).sum() / w.sum(),
           "F": spring[z15 & med].sum(), "F_A": w[z15 & med].sum(), "F_z10": spring[(zeta <= 10) & med].sum(), "F_z20": spring[(zeta <= 20) & med].sum(),
           "F_m30": spring[z15 & (np.abs(th) <= 30)].sum(), "F_m60": spring[z15 & (np.abs(th) <= 60)].sum(),
           "S_all": spring.sum(), "S_z15": spring[z15].sum(), "t_min": t.min(), "t_mean": (w * t).sum() / w.sum(), "Kt_all": (w * kt_loc * rho ** 2).sum(),
           "R_fnd": math.degrees(np.linalg.norm(om)), "R_spin": math.degrees(abs(om @ ax)), "R_tilt": math.degrees(np.linalg.norm(om - (om @ ax) * ax)), "Kr_axis": ax @ K[3:, 3:] @ ax, "Kr_min": ev[0], "resid": 0.0}
    return {k: float(out[k]) for k in COLS}


def init():
    global PH, LOAD
    PH = SN.Phase(13)
    LOAD = np.array(json.load(open(Q / "db_ws_p13_a105_91e458e3_m1_2a79b613" / "prep.json"))["load_N"], float)


def one_job(job):
    try:
        d = Q / job
        spec, prep = json.load(open(d / "spec.json")), json.load(open(d / "prep.json"))
        t = prep["templating"]
        fm = J.femur_for({"femur_id": spec.get("femur_id"), "neck_axis": spec.get("neck_axis"), "h_cut": spec.get("h_cut")})
        st = G.Stem3D(**spec["design"])
        f = features(st, fm, t["alpha"], t["e"], t["A0"])
        return job, True, {**f, "alpha": t["alpha"], "e": t["e"], "A0": t["A0"], "s_bind": t["s_bind"], "contact": t["contact"], "volume": t["volume"], "bone": prep["bone_loss"]["total_mm3"]}, ""
    except Exception as ex:  # noqa: BLE001
        return job, False, {}, f"{type(ex).__name__}: {str(ex)[:160]}"


def one_pool(a):
    i, u, alpha, e, A0, s_bind, contact, volume, bone = a
    try:
        d, h = PH.design_of(u)
        fm = J.femur_for({"femur_id": PH.femur_id, "neck_axis": PH.neck_axis, "h_cut": h})
        f = features(G.Stem3D(**d), fm, alpha, e, A0)
        return i, True, {**f, "alpha": alpha, "e": e, "A0": A0, "s_bind": s_bind, "contact": contact, "volume": volume, "bone": bone}, ""
    except Exception as ex:  # noqa: BLE001
        return i, False, {}, f"{type(ex).__name__}: {str(ex)[:160]}"


def one_fixe(a):
    i, u, e = a
    try:
        rule = TR.phase_rule(13)
        d, h = PH.design_of(u)
        fm = J.femur_for({"femur_id": PH.femur_id, "neck_axis": PH.neck_axis, "h_cut": h})
        st = G.Stem3D(**d)
        with J.a_bounds_cap(rule.a_bounds_max):
            r = CR.template_neck_in_shoulder(st, fm, offsets=np.array([float(e)]), margin=rule.margin, min_A0=rule.min_A0, tol_mm2=rule.tol_mm2, margin_check=rule.margin_check)
        if not r.get("fit"):
            return i, False, {}, f"template: {str(r.get('reason'))[:120]}"
        f = features(st, fm, r["alpha"], r["e"], r["A0"])
        bone = float(fm.resected_volume(ref_cut_mm=rule.ref_cut_mm)) + float(r["volume"])
        return i, True, {**f, "alpha": float(r["alpha"]), "e": float(r["e"]), "A0": float(r["A0"]), "s_bind": float(r["s_bind"]), "contact": float(r["contact"]), "volume": float(r["volume"]), "bone": bone}, ""
    except Exception as ex:  # noqa: BLE001
        return i, False, {}, f"{type(ex).__name__}: {str(ex)[:160]}"


def run(fn, tasks, n, out, workers, extra):
    keys = (*COLS, "alpha", "e", "A0", "s_bind", "contact", "volume", "bone")
    A = {k: np.full(n, np.nan) for k in keys}
    ok = np.zeros(n, bool)
    why = {}
    t0 = time.time()
    with Pool(workers, init) as p:
        for k, (i, good, r, w) in enumerate(p.imap_unordered(fn, tasks, chunksize=8)):
            ok[i] = good
            if good:
                for c, v in r.items():
                    A[c][i] = v
            else:
                why[i] = w
            if k % 1000 == 0:
                print(f"{k}/{n} {time.time() - t0:.0f} s", flush=True)
    np.savez_compressed(out, ok=ok, **A, **extra)
    reasons = {}
    for v in why.values():
        reasons[v[:40]] = reasons.get(v[:40], 0) + 1
    print(json.dumps({"n": n, "ok": int(ok.sum()), "wall_s": round(time.time() - t0, 1), "fail": sorted(reasons.items(), key=lambda x: -x[1])[:6]}))


def main():
    mode = sys.argv[1]
    if mode == "jobs":
        jobs = [x.strip() for x in open(sys.argv[2]) if x.strip()]
        idx = {j: i for i, j in enumerate(jobs)}
        workers = int(sys.argv[4]) if len(sys.argv) > 4 else 4

        def gen():
            for j in jobs:
                yield j
        keys = (*COLS, "alpha", "e", "A0", "s_bind", "contact", "volume", "bone")
        A = {k: np.full(len(jobs), np.nan) for k in keys}
        ok = np.zeros(len(jobs), bool)
        bad = {}
        t0 = time.time()
        with Pool(workers, init) as p:
            for k, (j, good, r, w) in enumerate(p.imap_unordered(one_job, gen(), chunksize=4)):
                ok[idx[j]] = good
                if good:
                    for c, v in r.items():
                        A[c][idx[j]] = v
                else:
                    bad[j] = w
                if k % 100 == 0:
                    print(f"{k}/{len(jobs)} {time.time() - t0:.0f} s", flush=True)
        np.savez_compressed(sys.argv[3], ok=ok, job=np.array(jobs), **A)
        print(json.dumps({"n": len(jobs), "ok": int(ok.sum()), "wall_s": round(time.time() - t0, 1), "bad": dict(list(bad.items())[:5])}))
    elif mode == "pool":
        z = np.load(sys.argv[2])
        idx = np.load(sys.argv[3])
        u, al, e, a0, sb, ct, vol, bo = z["u13"][idx], z["alpha_star"][idx], z["e_star"][idx], z["A0_star"][idx], z["s_bind_star"][idx], z["contact_star"][idx], z["volume_star"][idx], z["bone_mm3"][idx]
        tasks = [(i, u[i], float(al[i]), float(e[i]), float(a0[i]), float(sb[i]), float(ct[i]), float(vol[i]), float(bo[i])) for i in range(len(idx))]
        run(one_pool, tasks, len(idx), sys.argv[4], int(sys.argv[5]) if len(sys.argv) > 5 else 4, {"u13": u, "src_idx": idx})
    elif mode == "fixe":
        U, E = np.load(sys.argv[2]), np.load(sys.argv[3])
        tasks = [(i, U[i], float(E[i])) for i in range(len(U))]
        run(one_fixe, tasks, len(U), sys.argv[4], int(sys.argv[5]) if len(sys.argv) > 5 else 4, {"u13": U, "e_req": E})


if __name__ == "__main__":
    main()
