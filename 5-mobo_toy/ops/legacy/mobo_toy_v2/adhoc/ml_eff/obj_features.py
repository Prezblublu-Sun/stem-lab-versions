"""Per-job geometric descriptors (template-time and mesh-time, no FE solve) + alternative FE objective definitions
+ node-level table, for the clean current-code M1 rows of ml_eff/data/metrics_all.csv.

READ-ONLY on queue / results / code. Writes only to ~/mobo_toy_v2/deck/ml_eff/objectives/.

Template-time (prefix g_): from spec design + stored templating (alpha, e, A0) + RealFemur distance fields.
  The stem surface (geom3d section x area-ratio law, shoulder prism and cap) is sampled on a structured grid
  (ds 0.5 mm, 96 points round), quad areas are exact for the grid; only cells below the cut plane and inside the
  periosteal surface count.  t = cancellous-layer thickness = -canal_sdf at the stem surface (>= m by templating).
Mesh-time (prefix mh_): same descriptors on the FE interface node pairs of mesh3d.npz (pair_area, pair_normal),
  available after meshing (about 1 min) but before the Abaqus solve.
Winkler proxy (wk_*): rigid stem on independent springs, normal stiffness E_canc/(t + t0) per unit area,
  tangential beta times that; head load (config load vector) at the head centre -> rigid rotation / subsidence.
FE alternatives (prefix fe_): closed (gap <= 1 um, LOAD2) area split by t, CPRESS-based bearing measures at LOAD2,
  load share through the near-cortex interface (CFORCE LOAD2 - UNLOAD).
"""
from __future__ import annotations

import csv
import json
import math
import pathlib
import sys
import time
import traceback
from multiprocessing import Pool

import numpy as np

HOME = pathlib.Path.home() / 'mobo_toy_v2'
sys.path.insert(0, str(HOME / 'code'))
sys.path.insert(0, str(HOME / 'code' / 'v2'))
import femur_real as FR  # noqa: E402
import geom3d as G  # noqa: E402
import jobs as J  # noqa: E402
import post_m1 as PM  # noqa: E402

OUT = HOME / 'deck' / 'ml_eff' / 'objectives'
TABLE = HOME / 'deck' / 'ml_eff' / 'data' / 'metrics_all.csv'
E_CANC = 400.0
T_LEVELS = (0.75, 1.0, 1.5, 2.0, 3.0, 5.0)
_FM = {}


def femur(h_cut):
    if 'base' not in _FM:
        _FM['base'] = FR.build()
    b = _FM['base']
    return b if h_cut is None else b.with_cut(float(h_cut))


def load_vector(cfg):
    L = cfg['load']
    tx, ty = math.tan(math.radians(L['alpha_front_deg'])), math.tan(math.radians(L['alpha_sagit_deg']))
    fz = L['resultant_N'] / math.sqrt(1 + tx * tx + ty * ty)
    fx_B, fy_B, fz_B = tx * fz, -ty * fz, -fz
    return np.array([-fx_B, -fy_B, fz_B])


def wq(x, w, q):
    if len(x) == 0:
        return float('nan')
    o = np.argsort(x)
    x, w = x[o], w[o]
    c = np.cumsum(w) - 0.5 * w
    c /= w.sum()
    return float(np.interp(q, c, x))


def surface_cells(st, A0, pose, s_top=-25.0, ds=0.5, M=96, ncap=6):
    """Structured surface grid -> cell centroids (world), areas, outward normals, local (s, x, y)."""
    sec = G.unit_section(st.d, M)
    nb = max(int(round(st.L / ds)), 2)
    s = np.r_[np.arange(s_top, 0.0, ds), np.linspace(0.0, st.L, nb + 1)]
    k = np.sqrt(A0 * st.area_ratio(s))
    rings = [np.c_[np.full(M, si), ki * sec] for si, ki in zip(s, k)]
    c = st.cap_length(A0)
    kt = math.sqrt(A0 * st.rho_tip)
    for t in np.linspace(0, 1, ncap + 1)[1:]:
        f = math.sqrt(max(1 - t * t, 0.0))
        rings.append(np.c_[np.full(M, st.L + c * t), f * kt * sec])
    R = np.stack(rings)                         # (nr, M, 3) local
    P0, d, e_ml, e_ap = pose
    W = P0 + R[..., :1] * d + R[..., 1:2] * e_ml + R[..., 2:3] * e_ap
    a, b = W[:-1], np.roll(W[:-1], -1, axis=1)
    cc, dd = np.roll(W[1:], -1, axis=1), W[1:]
    cr = np.cross(cc - a, dd - b)
    area = 0.5 * np.linalg.norm(cr, axis=-1)
    cen = 0.25 * (a + b + cc + dd)
    loc = 0.25 * (R[:-1] + np.roll(R[:-1], -1, axis=1) + np.roll(R[1:], -1, axis=1) + R[1:])
    nrm = cr / np.maximum(np.linalg.norm(cr, axis=-1, keepdims=True), 1e-12)
    sc = loc[..., 0]
    ref = P0 + np.minimum(sc, st.L)[..., None] * d
    sgn = np.sign(((cen - ref) * nrm).sum(-1))
    sgn[sgn == 0] = 1.0
    nrm = nrm * sgn[..., None]
    keep = area.reshape(-1) > 1e-9
    return cen.reshape(-1, 3)[keep], area.reshape(-1)[keep], nrm.reshape(-1, 3)[keep], loc.reshape(-1, 3)[keep]


def skew_rows(Q):
    S = np.zeros((len(Q), 3, 3))
    S[:, 0, 1], S[:, 0, 2] = -Q[:, 2], Q[:, 1]
    S[:, 1, 0], S[:, 1, 2] = Q[:, 2], -Q[:, 0]
    S[:, 2, 0], S[:, 2, 1] = -Q[:, 1], Q[:, 0]
    return S


def winkler(X, n, a, t, H, F, P0, d, t0=0.5, beta=0.385, tcap=10.0, E=E_CANC):
    tt = np.clip(t, 0.05, tcap)
    k = a * E / (tt + t0)
    c = (X * k[:, None]).sum(0) / k.sum()
    Q = X - c
    I = np.eye(3)
    B = np.concatenate([np.broadcast_to(I, (len(X), 3, 3)), -skew_rows(Q)], axis=2)
    Dn = n[:, :, None] * n[:, None, :]
    Ki = k[:, None, None] * (Dn + beta * (I[None] - Dn))
    K = np.einsum('nji,njk,nkl->il', B, Ki, B)
    rhs = np.r_[F, np.cross(H - c, F)]
    q = np.linalg.solve(K, rhs)
    u, w = q[:3], q[3:]
    t_sh = u + np.cross(w, P0 - c)
    Kuu, Kuw, Kww = K[:3, :3], K[:3, 3:], K[3:, 3:]
    Kr = Kww - Kuw.T @ np.linalg.solve(Kuu, Kuw)       # rotational stiffness with translations free (N mm / rad)
    ev = np.linalg.eigvalsh(Kr)
    ax = d / np.linalg.norm(d)
    return {'rot_deg': float(np.degrees(np.linalg.norm(w))),
            'tilt_deg': float(np.degrees(np.linalg.norm(w - (w @ ax) * ax))),
            'axial_deg': float(np.degrees(abs(w @ ax))),
            'subsid_um': float(t_sh @ ax * 1e3),
            'lateral_um': float(np.linalg.norm(t_sh - (t_sh @ ax) * ax) * 1e3),
            'kr_min_Nm_per_deg': float(ev.min() * math.pi / 180 / 1e3),
            'kr_axial_Nm_per_deg': float((ax @ Kr @ ax) * math.pi / 180 / 1e3),
            'k_total_N_per_um': float(k.sum() / 1e3),
            'lever_mm': float(np.linalg.norm(np.cross(H - c, F / np.linalg.norm(F))))}


def descriptors(prefix, X, a, n, t, loc, L, m, H, F, P0, d):
    out = {}
    A = float(a.sum())
    out[f'{prefix}area'] = A
    out[f'{prefix}t_min'] = float(t.min())
    for q in (0.05, 0.10, 0.25, 0.50):
        out[f'{prefix}t_p{int(q * 100):02d}'] = wq(t, a, q)
    out[f'{prefix}t_mean'] = float((t * a).sum() / A)
    for lv in T_LEVELS:
        sel = t <= lv
        out[f'{prefix}A_le{lv:g}'] = float(a[sel].sum())
        out[f'{prefix}f_le{lv:g}'] = float(a[sel].sum() / A)
    sel = t <= m + 0.5
    out[f'{prefix}A_le_m05'] = float(a[sel].sum())
    out[f'{prefix}f_le_m05'] = float(a[sel].sum() / A)
    out[f'{prefix}A_cortex'] = float(a[t < 0].sum())
    s = loc[:, 0]
    out[f'{prefix}s_min'], out[f'{prefix}s_max'] = float(s.min()), float(s.max())
    out[f'{prefix}embed_len'] = float(s.max() - s.min())
    near = t <= 2.0
    if near.any():
        out[f'{prefix}near_s_mean'] = float((s[near] * a[near]).sum() / a[near].sum())
        out[f'{prefix}near_s_span'] = wq(s[near], a[near], 0.9) - wq(s[near], a[near], 0.1)
    else:
        out[f'{prefix}near_s_mean'] = out[f'{prefix}near_s_span'] = float('nan')
    third = np.digitize(s, [L / 3, 2 * L / 3])
    for i, nm in enumerate(('prox', 'mid', 'dist')):
        out[f'{prefix}A_le2_{nm}'] = float(a[near & (third == i)].sum())
        out[f'{prefix}A_{nm}'] = float(a[third == i].sum())
    x, y = loc[:, 1], loc[:, 2]
    quad = np.where(np.abs(x) >= np.abs(y), np.where(x >= 0, 0, 1), np.where(y >= 0, 2, 3))
    for i, nm in enumerate(('med', 'lat', 'ant', 'post')):
        out[f'{prefix}A_le2_{nm}'] = float(a[near & (quad == i)].sum())
        out[f'{prefix}tmin_{nm}'] = float(t[quad == i].min()) if (quad == i).any() else float('nan')
    tip = s >= 0.8 * L
    out[f'{prefix}t_tip_min'] = float(t[tip].min()) if tip.any() else float('nan')
    sh = s <= 0.2 * L
    out[f'{prefix}t_shoulder_min'] = float(t[sh].min()) if sh.any() else float('nan')
    ax = d / np.linalg.norm(d)
    nd = np.abs(n @ ax)
    out[f'{prefix}taper_mean'] = float((nd * a).sum() / A)
    out[f'{prefix}taper_near'] = float((nd[near] * a[near]).sum() / a[near].sum()) if near.any() else float('nan')
    out[f'{prefix}Ataper_le2'] = float((nd[near] * a[near]).sum())     # axially projected near-cortex area
    cen = (X * a[:, None]).sum(0) / A
    out[f'{prefix}lever_area_mm'] = float(np.linalg.norm(np.cross(H - cen, F / np.linalg.norm(F))))
    for tag, t0, beta in (('n05', 0.5, 0.0), ('b05', 0.5, 0.385), ('b20', 2.0, 0.385)):
        wk = winkler(X, n, a, t, H, F, P0, d, t0=t0, beta=beta)
        for k_, v in wk.items():
            out[f'{prefix}wk_{tag}_{k_}'] = v
    return out


def run_job(row):
    job = row['job']
    d = J.QROOT / job
    t0 = time.time()
    try:
        spec = json.loads((d / 'spec.json').read_text())
        res = json.loads((d / 'result.json').read_text())
        tpl = res.get('templating') or json.loads((d / 'prep.json').read_text()).get('templating')
        fm = femur(spec.get('h_cut'))
        st = G.Stem3D(**spec['design'])
        A0 = float(tpl['A0'])
        m = float(tpl.get('margin', st.m))
        pose = fm.pose(float(tpl['alpha']), float(tpl['e']))
        P0, dax, e_ml, e_ap = pose
        dax = dax / np.linalg.norm(dax)
        H = np.asarray(fm.H, float)
        F = load_vector(fm.cfg)
        out = {'job': job}
        # ---------------- template-time surface
        cen, area, nrm, loc = surface_cells(st, A0, pose)
        inside = fm.below_cut(cen) & (fm.outer_sdf(cen) <= 0)
        cen, area, nrm, loc = cen[inside], area[inside], nrm[inside], loc[inside]
        t = -fm.canal_sdf(cen)
        out.update(descriptors('g_', cen, area, nrm, t, loc, st.L, m, H, F, P0, dax))
        out['g_depth_below_cut'] = float((-(cen - fm.C03) @ fm.u3).max())
        out['g_tip_z'] = float(cen[:, 2].min())
        # ---------------- mesh-time
        p = PM.pairs(d)
        lut = np.full(int(p['node_labels'].max()) + 1, -1)
        lut[p['node_labels'].astype(int)] = np.arange(len(p['node_labels']))
        X = p['nodes'][lut[p['pair_bone'].astype(int)]]
        body = ~p['pair_collar']
        w, nm_, di, cort = p['pair_area'], p['pair_normal'], p['pair_interf'], p['pair_cortex'].astype(bool)
        tn = -fm.canal_sdf(X)
        to = -fm.outer_sdf(X)
        Q = X - P0
        locn = np.c_[Q @ dax, Q @ e_ml, Q @ e_ap]
        out.update(descriptors('mh_', X[body], w[body], nm_[body], tn[body], locn[body], st.L, m, H, F, P0, dax))
        out['mh_n_pairs_body'] = int(body.sum())
        out['mh_cortex_frac_flag'] = float(w[body & cort].sum() / w[body].sum())
        if (~body).any():
            out['mh_collar_area'] = float(w[~body].sum())
            # Winkler with the collar pairs added (collar bears on the cut surface: thickness to cortex is not defined there,
            # use t = max(t, 0.05) as for the body)
            wk = winkler(X, nm_, w, tn, H, F, P0, dax, t0=0.5, beta=0.385)
            for k_, v in wk.items():
                out[f'mh_wk_collar_b05_{k_}'] = v
        # ---------------- FE alternatives
        n = p['n']
        U = {s: PM._utab(d / 'm_fric_csv' / f'{s}_U.csv', n) for s in ('RELEASE', 'LOAD', 'UNLOAD', 'LOAD2')}
        rel = {s: U[s][p['pair_stem']] - U[s][p['pair_bone']] for s in U}
        gap = {s: -(di + (rel[s] * nm_).sum(1)) * 1e3 for s in rel}
        cl2 = (gap['LOAD2'] <= PM.OPEN_UM) & body
        cl1 = (gap['LOAD'] <= PM.OPEN_UM) & body
        out['fe_A_closed_load2'] = float(w[cl2].sum())
        out['fe_A_closed_load'] = float(w[cl1].sum())
        out['fe_A_closed_both'] = float(w[cl1 & cl2].sum())
        for lv in (1.0, 1.5, 2.0, 3.0):
            out[f'fe_A_closed_t_le{lv:g}'] = float(w[cl2 & (tn <= lv)].sum())
        out['fe_A_closed_t_le_m05'] = float(w[cl2 & (tn <= m + 0.5)].sum())
        out['fe_A_closed_cortexflag'] = float(w[cl2 & cort].sum())
        C2 = PM._ctab(d / 'm_fric_csv' / 'LOAD2_CONTACT.csv', n)
        C0 = PM._ctab(d / 'm_fric_csv' / 'RELEASE_CONTACT.csv', n)
        for tag, C in (('load2', C2), ('release', C0)):
            pr = C['CPRESS'][p['pair_bone']]
            pr = np.where(np.isfinite(pr), np.maximum(pr, 0.0), 0.0)
            pb_, wb_ = pr[body], w[body]
            Fn = float((wb_ * pb_).sum())
            out[f'fe_Fn_{tag}_N'] = Fn
            out[f'fe_Aeff_{tag}'] = float(Fn ** 2 / max((wb_ * pb_ ** 2).sum(), 1e-12))
            for lv in (0.5, 1.0, 2.0):
                out[f'fe_A_p_gt{lv:g}_{tag}'] = float(wb_[pb_ > lv].sum())
            out[f'fe_p_p50_{tag}'] = wq(pb_[pb_ > 0], wb_[pb_ > 0], 0.5) if (pb_ > 0).any() else float('nan')
            out[f'fe_p_p95_{tag}'] = wq(pb_[pb_ > 0], wb_[pb_ > 0], 0.95) if (pb_ > 0).any() else float('nan')
            out[f'fe_Fn_t_le1_{tag}_N'] = float((w * pr)[body & (tn <= 1.0)].sum())
            out[f'fe_Fn_t_le2_{tag}_N'] = float((w * pr)[body & (tn <= 2.0)].sum())
        # load transfer through the interface (LOAD2 - UNLOAD nodal contact forces on the bone side)
        try:
            F2 = PM._ftab(d / 'm_fric_csv' / 'LOAD2_CFORCE.csv', n)[p['pair_bone']]
            FU = PM._ftab(d / 'm_fric_csv' / 'UNLOAD_CFORCE.csv', n)[p['pair_bone']]
            dF = F2 - FU
            tot = dF[body].sum(0)
            nt = float(np.linalg.norm(tot))
            out['fe_dF_total_N'] = nt
            for lv in (1.0, 2.0):
                out[f'fe_loadshare_t_le{lv:g}'] = float(dF[body & (tn <= lv)].sum(0) @ tot / (nt * nt)) if nt > 0 else float('nan')
            if (~body).any():
                out['fe_loadshare_collar'] = float(dF[~body].sum(0) @ dF.sum(0) / max(np.linalg.norm(dF.sum(0)) ** 2, 1e-12))
        except Exception as e:  # noqa: BLE001
            out['fe_cforce_err'] = f'{type(e).__name__}: {e}'[:120]
        # rotation-normalised quantities need FE rotation: computed later from the table (rot / lever etc.)
        out['_t_s'] = time.time() - t0
        # ---------------- node table (body pairs)
        sL = locn[:, 0] / st.L
        th = np.arctan2(locn[:, 2], locn[:, 1])
        rr = np.hypot(locn[:, 1], locn[:, 2])
        depth = -(X - fm.C03) @ fm.u3
        pr2 = C2['CPRESS'][p['pair_bone']]
        node = np.c_[sL, np.cos(th), np.sin(th), rr, tn, to, np.abs(nm_ @ dax), depth, di, cort.astype(float),
                     np.full(len(X), st.L), np.full(len(X), m), w,
                     cl2.astype(float), cl1.astype(float), np.where(np.isfinite(pr2), pr2, 0.0),
                     np.linalg.norm((rel['LOAD2'] - rel['UNLOAD']) - ((rel['LOAD2'] - rel['UNLOAD']) * nm_).sum(1)[:, None] * nm_,
                                    axis=1) * 1e3][body].astype(np.float32)
        return out, node, None
    except Exception as e:  # noqa: BLE001
        return {'job': job, 'err': f'{type(e).__name__}: {e}'}, None, traceback.format_exc()[-800:]


NODE_COLS = ['s_over_L', 'cos_th', 'sin_th', 'r_axis', 't_canc', 't_outer', 'n_axial', 'depth_below_cut', 'interf', 'cortex',
             'L', 'm', 'area', 'closed_load2', 'closed_load', 'cpress_load2', 'slip_rev_um']


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader(open(TABLE, newline='')))
    sel = [r for r in rows if r['current_code'] == 'True' and r['variant_class'] == 'none']
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else None
    if lim:
        sel = [r for r in sel if r['collar_rule'] == 'neck_in_shoulder'][:lim // 2] + \
              [r for r in sel if r['collar_rule'] != 'neck_in_shoulder'][:lim - lim // 2]
    print(f'{len(sel)} jobs', flush=True)
    t0 = time.time()
    feats, nodes, jidx, errs = [], [], [], []
    with Pool(4) as pool:
        for i, (out, node, tb) in enumerate(pool.imap_unordered(run_job, sel, chunksize=4)):
            if 'err' in out:
                errs.append(out)
                print('ERR', out, tb, flush=True)
                continue
            feats.append(out)
            nodes.append(node)
            jidx.append(np.full(len(node), len(feats) - 1, np.int32))
            if (i + 1) % 100 == 0:
                print(f'{i + 1}/{len(sel)} {time.time() - t0:.0f}s', flush=True)
    keys = []
    for f in feats:
        for k in f:
            if k not in keys:
                keys.append(k)
    suffix = '' if not lim else f'_test{lim}'
    with open(OUT / f'job_features{suffix}.csv', 'w', newline='') as fh:
        wr = csv.DictWriter(fh, fieldnames=keys)
        wr.writeheader()
        for f in feats:
            wr.writerow(f)
    np.savez_compressed(OUT / f'node_table{suffix}.npz', X=np.vstack(nodes), job_idx=np.concatenate(jidx),
                        jobs=np.array([f['job'] for f in feats]), cols=np.array(NODE_COLS))
    import resource
    meta = {'n_jobs': len(sel), 'n_ok': len(feats), 'n_err': len(errs), 'errs': errs[:20], 'elapsed_s': time.time() - t0,
            'maxrss_mb_self': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
            'maxrss_mb_children': resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024,
            'node_rows': int(sum(len(x) for x in nodes)), 'node_cols': NODE_COLS}
    (OUT / f'features_meta{suffix}.json').write_text(json.dumps(meta, indent=1))
    print(json.dumps({k: v for k, v in meta.items() if k != 'errs'}), flush=True)


if __name__ == '__main__':
    main()
