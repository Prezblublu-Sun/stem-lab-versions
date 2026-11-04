"""Where does the collar's effect on micromotion come from? Read-only decomposition of the press-fit results (Linux).
For each job: recoverable relative motion between UNLOAD and LOAD2 at the interface node pairs →
  (1) rigid-body fit of the relative motion stem vs bone: subsidence (along the stem axis), lateral shift, tilt about the
      medio-lateral axis (AP toggling), tilt about the antero-posterior axis (varus/valgus), twist about the stem axis;
  (2) tangential slip split into axial and circumferential components, P95 and mean, for the proximal / distal halves;
  (3) collar numbers from result.json (load share, lift-off).
    run.sh adhoc/plan/collar_mech.py
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "adhoc" / "plan")); sys.path.insert(0, str(HOME / "adhoc" / "reffig2"))
import plan_figs as PF  # noqa: E402
from plan_figs import R2, G, J  # noqa: E402
import post_m1 as PM  # noqa: E402

JOBS = [("ell L30 w0", "collar_neck_w0_9e92d3e1"), ("ell L30 w3 (first implant)", "collar_neck_w3_36c2bb73"),
        ("asym L30 w0", "collar_neck_asym_L30_w0_7c707534"), ("asym L30 w2", "collar_neck_asym_L30_w2_5a8156fd"), ("asym L30 w3", "collar_neck_asym_w3_4f71e698"),
        ("asym L35 w0", "collar_neck_asym_L35_w0_1adcd5e9"), ("asym L35 w2", "collar_neck_asym_L35_w2_d6eb839e"), ("asym L35 w4", "collar_neck_asym_L35_w4_151aa1a5")]


def rigid_fit(x, u):
    """least-squares rigid motion u ≈ t + ω × (x − c); returns t (at centroid), ω."""
    c = x.mean(0); r = x - c
    # unknowns: t (3), ω (3); u = t + ω × r = t − r × ω  → A = [I, −[r]_x]
    A = np.zeros((3 * len(x), 6)); b = u.reshape(-1)
    for i, ri in enumerate(r):
        A[3 * i:3 * i + 3, 0:3] = np.eye(3)
        A[3 * i:3 * i + 3, 3:6] = -np.array([[0, -ri[2], ri[1]], [ri[2], 0, -ri[0]], [-ri[1], ri[0], 0]])
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    resid = b - A @ sol
    return sol[:3], sol[3:], c, float(np.sqrt(np.mean(resid ** 2)))


def analyse(job):
    d = J.QROOT / job
    spec = json.loads((d / "spec.json").read_text()); res = J.result(job); t = res["templating"]
    g, _ = PF.geo_of(job)
    P0, dvec, e_ml, e_ap = g["pl"]["pose"]
    p = PM.pairs(d)
    U = {s: PM._utab(d / "m_fric_csv" / f"{s}_U.csv", p["n"]) for s in ("UNLOAD", "LOAD2")}
    pos = np.zeros(int(p["node_labels"].max()) + 1, int); pos[p["node_labels"]] = np.arange(len(p["node_labels"]))
    xs = p["nodes"][pos[p["pair_stem"]]]
    rel = {s: U[s][p["pair_stem"]] - U[s][p["pair_bone"]] for s in U}
    v = rel["LOAD2"] - rel["UNLOAD"]                          # recoverable relative motion, mm
    n = p["pair_normal"]; body = ~p["pair_collar"].astype(bool)
    vt = v - (v * n).sum(1)[:, None] * n
    # local frame: axial s along the stem, circumferential about the stem axis
    s_ax = (xs - P0) @ dvec
    rad = (xs - P0) - s_ax[:, None] * dvec; rad /= (np.linalg.norm(rad, axis=1)[:, None] + 1e-12)
    e_th = np.cross(dvec, rad)
    ax_c = vt @ dvec; th_c = (vt * e_th).sum(1); mag = np.linalg.norm(vt, axis=1) * 1e3
    L = g["st"].L; prox = body & (s_ax < L / 2); dist = body & (s_ax >= L / 2)
    out = {"job": job, "L": L, "collar_w": spec["design"].get("collar_w", 0.0),
           "f1_p95_um": res["f1_p95_um"], "f1_all_p95_um": res.get("f1_all_p95_um"),
           "collar_share": res.get("collar_force_share_load2"), "collar_open": res.get("collar_open_frac_load2"),
           "slip_body_p95_um": float(np.percentile(mag[body], 95)), "slip_body_mean_um": float(mag[body].mean()),
           "axial_p95_um": float(np.percentile(np.abs(ax_c[body]) * 1e3, 95)), "circ_p95_um": float(np.percentile(np.abs(th_c[body]) * 1e3, 95)),
           "axial_mean_um": float(np.abs(ax_c[body]).mean() * 1e3), "circ_mean_um": float(np.abs(th_c[body]).mean() * 1e3),
           "prox_p95_um": float(np.percentile(mag[prox], 95)), "dist_p95_um": float(np.percentile(mag[dist], 95)),
           "n_body": int(body.sum())}
    # rigid-body motion of the stem relative to the bone (body nodes), in the stem frame
    tr, om, c, rms = rigid_fit(xs[body], v[body])
    out.update({"rb_subsidence_um": float(tr @ dvec * 1e3), "rb_shift_ml_um": float(tr @ e_ml * 1e3), "rb_shift_ap_um": float(tr @ e_ap * 1e3),
                "rb_twist_mdeg": float(om @ dvec * 1e3 * 180 / np.pi), "rb_tilt_about_ml_mdeg": float(om @ e_ml * 1e3 * 180 / np.pi),
                "rb_tilt_about_ap_mdeg": float(om @ e_ap * 1e3 * 180 / np.pi), "rb_fit_rms_um": rms * 1e3,
                "rb_explained_frac": float(1 - (rms ** 2) / max(np.mean(np.sum(v[body] ** 2, 1)), 1e-30))})
    # what the rigid motion alone would produce at the tip and shoulder (tangential magnitude), to see which term drives slip
    for nm, sel in (("tip", s_ax[body] > 0.9 * L), ("shoulder", s_ax[body] < 0.1 * L)):
        xx = xs[body][sel]; u_rb = tr + np.cross(om, xx - c); u_rb_t = u_rb - ((u_rb * n[body][sel]).sum(1))[:, None] * n[body][sel]
        out[f"rb_tangential_{nm}_mean_um"] = float(np.linalg.norm(u_rb_t, axis=1).mean() * 1e3) if sel.any() else None
    return out


def main():
    rows = [analyse(j) for _, j in JOBS]
    names = [n for n, _ in JOBS]
    keys = ["f1_p95_um", "f1_all_p95_um", "collar_share", "collar_open", "slip_body_p95_um", "axial_p95_um", "circ_p95_um", "axial_mean_um", "circ_mean_um",
            "prox_p95_um", "dist_p95_um", "rb_subsidence_um", "rb_shift_ml_um", "rb_shift_ap_um", "rb_twist_mdeg", "rb_tilt_about_ml_mdeg", "rb_tilt_about_ap_mdeg",
            "rb_fit_rms_um", "rb_explained_frac", "rb_tangential_tip_mean_um", "rb_tangential_shoulder_mean_um"]
    print("metric".ljust(28) + "".join(f"{n[:14]:>15}" for n in names))
    for k in keys:
        print(k.ljust(28) + "".join(f"{(r[k] if r[k] is not None else float('nan')):15.2f}" for r in rows))
    (HOME / "adhoc" / "plan" / "out" / "collar_mech.json").write_text(json.dumps(dict(zip(names, rows)), indent=1, default=float))


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------- collar face: contact pressure and what it sits on
def collar_face(job):
    import qoi
    d = J.QROOT / job
    g, _ = PF.geo_of(job); fm = g["fm"]
    p = PM.pairs(d)
    col = p["pair_collar"].astype(bool)
    if not col.any():
        return None
    pos = np.zeros(int(p["node_labels"].max()) + 1, int); pos[p["node_labels"]] = np.arange(len(p["node_labels"]))
    c = qoi._csv(d / "m_fric_csv" / "LOAD2_CONTACT.csv")
    k = c["field"] == "CPRESS"; pres = dict(zip(c["node"][k].astype(int), c["value"][k]))
    labs = p["pair_bone"][col]; xb = p["nodes"][pos[labs]]
    cp = np.array([pres.get(int(l), 0.0) for l in labs])
    closed = cp > 1e-6
    cortex = fm.canal_sdf(xb) > 0
    w = cp / max(cp.sum(), 1e-12)
    C, e1, e2 = fm.neck_plane(); n3 = np.cross(e1, e2)
    q = xb - fm.C03; med = q @ fm.n3; post = q @ n3 if (n3 @ fm.ant) < 0 else -(q @ n3)
    return {"n_collar_pairs": int(col.sum()), "closed_frac": float(closed.mean()), "cortex_frac_of_ring": float(cortex.mean()),
            "closed_on_cortex_frac": float(cortex[closed].mean()) if closed.any() else None,
            "force_frac_on_cortex": float(w[cortex].sum()), "cpress_mean_closed_MPa": float(cp[closed].mean()) if closed.any() else None,
            "cpress_p95_closed_MPa": float(np.percentile(cp[closed], 95)) if closed.any() else None,
            "cpress_mean_closed_cancellous_MPa": float(cp[closed & ~cortex].mean()) if (closed & ~cortex).any() else None,
            "cpress_mean_closed_cortex_MPa": float(cp[closed & cortex].mean()) if (closed & cortex).any() else None,
            "force_centroid_medial_mm": float((w * med).sum()), "force_centroid_posterior_mm": float((w * post).sum())}


if __name__ == "__main__":
    print()
    print("collar face at peak load (LOAD2)")
    for nm, j in JOBS:
        r = collar_face(j)
        if r:
            print(f"{nm:28} " + "  ".join(f"{k}={v:.2f}" if isinstance(v, float) else f"{k}={v}" for k, v in r.items()))
