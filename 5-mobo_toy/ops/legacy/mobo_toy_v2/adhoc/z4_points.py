"""Z4 (external review item 2), read-only on the queue, 0 FE. For nominal rows with rot_first < 0.2 deg, and their mesh-noise replicates: rot_perm, rotation in fixed geometric bands, virtual LVDT readings,
the micromotion CDF, closed area near the cortex, friction torque capacity. Definitions follow v2/stability.py and v2/post_m1.py, which are imported and not changed.
usage (from ~/mobo_toy_v2/code/v2): ~/mobo_toy_v2/run.sh z4_points.py <jobs.txt> <out.jsonl> [workers]"""
import json, multiprocessing as mp, pathlib, sys, time
sys.path[:0] = [".", ".."]
import numpy as np
from scipy.spatial import cKDTree
import jobs as J
import post_m1 as PM
import stability as S

SEGS = S.SEGS
BANDS = ((0.0, 15.0), (0.0, 25.0), (15.0, 40.0))
LVDT_H, LVDT_R = 5.0, 12.0     # virtual sensors 5 mm above the cut, 12 mm from the cut centre, in the medial, lateral, anterior and posterior directions; reading along the neck axis
NEAR_MM = (2.0, 3.0, 4.0)


def one(job):
    d = J.QROOT / job
    out = {"job_id": job}
    try:
        st = S.stability(d)
        L = S._load(d)
        p, P0, ax, X, rel, U, lut, fm = L["p"], L["P0"], L["ax"], L["X"], L["rel"], L["U"], L["lut"], L["fm"]
        body = ~p["pair_collar"]
        w, nrm, di = p["pair_area"], p["pair_normal"], p["pair_interf"]
        spec = json.loads((d / "spec.json").read_text())
        for k in ("rot_first_deg", "rot_axial_first_deg", "rot_tilt_first_deg", "rot_rev_deg", "rot_perm_deg", "rot_axial_perm_deg", "rot_tilt_perm_deg", "subsid_perm_um", "subsid_rev_um", "contact_area_load2_mm2", "body_interface_mm2",
                  "bench_cx_rot_perm_deg", "bench_cx_rot_rev_deg", "bench_cx_subsid_perm_um", "bench_cx_rot_axial_perm_deg", "bench_cx_rot_tilt_perm_deg", "slip_axial_p95_um", "slip_circ_p95_um"):
            out[k] = st.get(k)
        # fixed geometric bands along the stem axis, area-weighted rigid fit as in stability()
        s_ax = (X - P0) @ ax
        for lo, hi in BANDS:
            b = body & (s_ax >= lo) & (s_ax <= hi)
            lab = f"band{lo:g}_{hi:g}"
            out[f"{lab}_n"] = int(b.sum())
            if b.sum() < 12:
                continue
            for seg, (a_, b_) in SEGS.items():
                _, om, _, _ = S.rigid_fit(X[b], (rel[b_] - rel[a_])[b], w[b])
                out[f"{lab}_{seg}_deg"] = float(np.degrees(np.linalg.norm(om)))
        # virtual LVDT: the same marker sets and unweighted fits as stability._bench
        m = np.load(d / "mesh3d.npz")
        stem_labs, cort_labs = np.unique(m["stem_conn"]), np.unique(m["cortex_conn"])
        C0, u3, n3 = np.asarray(fm.C03, float), np.asarray(fm.u3, float), np.asarray(fm.n3, float)
        u3 = u3 / np.linalg.norm(u3)
        nodes = p["nodes"]
        xyz = lambda labs: nodes[np.array([lut[int(n)] for n in labs])]    # noqa: E731
        hs, hc = (xyz(stem_labs) - C0) @ u3, (xyz(cort_labs) - C0) @ u3
        SS, BB = stem_labs[(hs > 0) & (hs <= S.BENCH_H_STEM)], cort_labs[(hc >= -S.BENCH_H_BONE) & (hc < 0)]
        XS, XB = xyz(SS), xyz(BB)
        ey = np.array([0.0, 1.0, 0.0])
        sensors = {"M": n3, "L": -n3, "A": ey, "P": -ey}
        for seg, (a_, b_) in SEGS.items():
            dU = U[b_] - U[a_]
            okS, okB = np.isfinite(dU[SS]).all(1), np.isfinite(dU[BB]).all(1)
            tS, oS, cS, _ = S.rigid_fit(XS[okS], dU[SS][okS], None)
            tB, oB, cB, _ = S.rigid_fit(XB[okB], dU[BB][okB], None)
            read = {}
            for k, v in sensors.items():
                P_ = C0 + LVDT_H * u3 + LVDT_R * v
                r = (tS + np.cross(oS, P_ - cS)) - (tB + np.cross(oB, P_ - cB))
                read[k] = float(r @ u3 * 1e3)
            out[f"lvdt_{seg}_um"] = read
            out[f"lvdt_{seg}_max_um"] = max(abs(x) for x in read.values())
            out[f"lvdt_{seg}_ml_diff_um"] = read["M"] - read["L"]
        # micromotion CDF over the body interface, same definition as post_m1.micromotion
        Rv = (rel["LOAD2"] - rel["UNLOAD"])[body]
        nb, wb, Xb = nrm[body], w[body], X[body]
        tang = Rv - (Rv * nb).sum(1)[:, None] * nb
        rev = np.linalg.norm(tang, axis=1) * 1e3
        for q in (0.5, 0.75, 0.9, 0.95, 0.99):
            out[f"f1_p{int(q * 100)}_um"] = PM._wq(rev, wb, q)
        out["f1_mean_um"] = float((rev * wb).sum() / wb.sum())
        # closed area near the cortex
        cort_xyz = xyz(cort_labs)
        dist, _ = cKDTree(cort_xyz).query(Xb)
        gap = -(di[body] + (rel["LOAD2"][body] * nb).sum(1)) * 1e3
        closed = gap <= PM.OPEN_UM
        out["cort_dist_p50_mm"] = PM._wq(dist, wb, 0.5)
        for r in NEAR_MM:
            out[f"near{r:g}_area_mm2"] = float(wb[dist <= r].sum())
            out[f"near{r:g}_closed_mm2"] = float(wb[(dist <= r) & closed].sum())
        # friction torque capacity about the stem axis
        mu = float(spec.get("mu", 0.3) or 0.3)
        q_ = Xb - P0
        rad = np.linalg.norm(q_ - (q_ @ ax)[:, None] * ax, axis=1)
        pb = p["pair_bone"][body]
        for stp in ("RELEASE", "LOAD2"):
            C = PM._ctab(d / "m_fric_csv" / f"{stp}_CONTACT.csv", p["n"])
            cp = np.nan_to_num(C["CPRESS"][pb], nan=0.0)
            cp = np.where(cp > 0, cp, 0.0)
            out[f"normal_N_{stp}"] = float((cp * wb).sum())
            out[f"torque_cap_Nm_{stp}"] = float(mu * (cp * wb * rad).sum() / 1000.0)
            out[f"radial_mean_mm_{stp}"] = float((cp * wb * rad).sum() / max((cp * wb).sum(), 1e-9))
    except Exception as ex:                                     # noqa: BLE001
        out["error"] = f"{type(ex).__name__}: {str(ex)[:300]}"
    return out


if __name__ == "__main__":
    jobs_ = [l.strip() for l in open(sys.argv[1]) if l.strip()]
    out = pathlib.Path(sys.argv[2])
    if out.exists():
        raise SystemExit(f"{out} exists")
    w = int(sys.argv[3]) if len(sys.argv) > 3 else 4
    t0 = time.time()
    with mp.get_context("fork").Pool(w) as pool, open(out, "w") as fo:
        for k, r in enumerate(pool.imap(one, jobs_, chunksize=4)):
            fo.write(json.dumps(r) + "\n")
            if (k + 1) % 50 == 0:
                print(f"{k + 1}/{len(jobs_)} {time.time() - t0:.0f}s", flush=True)
    print(f"done {len(jobs_)} {time.time() - t0:.0f}s", flush=True)
