"""ml_eff / nn: per-job interface point-cloud export + mesh/file audit (READ-ONLY on queue/results/code).

For every row of deck/ml_eff/data/metrics_all.csv (1036 DONE M1 jobs) writes
  deck/ml_eff/nn/iface/<job>.npz  (float32 unless noted)
    X        [n,3] bone-side node coordinates (world, mm)
    frame    [4,3] P0 (shoulder centre on cut plane), ax (stem axis, distal), e_ml, e_ap   (fm.pose(alpha, e))
    loc      [n,3] (s, x_ml, x_ap) = (X-P0) in the stem frame (mm)
    nloc     [n,3] outward stem normal in the stem frame
    area, interf(mm), cortex(bool), collar(bool)
    d_canal  [n]  canal_sdf(X) (mm; <0 inside canal = cancellous side), d_outer [n] outer_sdf(X)
    rel      [4,n,3] u_stem - u_bone at RELEASE, LOAD, UNLOAD, LOAD2, in the stem frame (um)
    cstat2, cpress2 [n] CSTATUS / CPRESS at LOAD2 (bone node), cpress0 [n] CPRESS at RELEASE (MPa)
and checks that the stored arrays reproduce f1_p95_um, contact_area_load2_mm2, rot_first_deg of metrics_all.csv.
Also writes deck/ml_eff/nn/audit/{files_by_job.csv, mesh_audit.json, voxel_timing.json, extract_log.json}.

    ~/mobo_toy_v2/run.sh ../adhoc/ml_eff/nn_extract_iface.py [--workers 4] [--limit N]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import pathlib
import resource
import sys
import time
import traceback
from multiprocessing import Pool

HOME = pathlib.Path.home() / 'mobo_toy_v2'
sys.path.insert(0, str(HOME / 'code'))
sys.path.insert(0, str(HOME / 'code' / 'v2'))
import numpy as np  # noqa: E402

import jobs as J  # noqa: E402
import post_m1 as PM  # noqa: E402
import stability as ST  # noqa: E402

OUT = HOME / 'deck' / 'ml_eff' / 'nn'
IF = OUT / 'iface'
AUD = OUT / 'audit'
TAB = HOME / 'deck' / 'ml_eff' / 'data' / 'metrics_all.csv'
STEPS = ('RELEASE', 'LOAD', 'UNLOAD', 'LOAD2')
_BASE = []


def femur(spec):
    """Same as jobs.femur_for for geometry purposes, but builds the (SDF-heavy, ~0.4 GB) base femur ONCE per process and
    uses the shallow with_cut copy (shares the distance fields). A first version cached one full build per distinct
    h_cut and grew to 6 GB per worker. cfg overrides (loads/materials) do not change pose or SDFs; a cfg that touches
    'femur' falls back to jobs.femur_for."""
    cfg = spec.get('cfg') or {}
    if isinstance(cfg, dict) and 'femur' in cfg:
        return J.femur_for(spec)
    if not _BASE:
        import femur_real as FR
        _BASE.append(FR.build())
    fm = _BASE[0]
    if spec.get('h_cut') is not None:
        fm = fm.with_cut(spec['h_cut'])
    return fm


def cat_of(rel: str) -> str:
    n = rel.split('/')[-1]
    if n == 'mesh3d.npz':
        return 'mesh3d_npz'
    if n.endswith('.odb'):
        return 'odb'
    if rel.startswith('m_fric_csv/') or rel.startswith('m_bond_csv/'):
        pre = 'fric' if rel.startswith('m_fric') else 'bond'
        for k in ('_U.csv', '_CONTACT.csv', '_CFORCE.csv', '_RF.csv', '_S.csv', '_E.csv', '_ENER.csv'):
            if n.endswith(k) or n.endswith(k + '.gz'):
                return f'{pre}{k[:-4].lower()}'
        return f'{pre}_other'
    if n.endswith('.json'):
        return 'json'
    return 'other'


def file_sizes(d: pathlib.Path) -> dict:
    out = {}
    for root, _, files in os.walk(d):
        for f in files:
            p = pathlib.Path(root) / f
            rel = str(p.relative_to(d))
            c = cat_of(rel)
            out[c] = out.get(c, 0) + p.stat().st_size
    return out


def one(job: str, want_mesh_audit: bool, want_vox: bool):
    t0 = time.time()
    d = J.QROOT / job
    spec = json.loads((d / 'spec.json').read_text())
    res = json.loads((d / 'result.json').read_text())
    tpl = res.get('templating') or json.loads((d / 'prep.json').read_text()).get('templating')
    fm = femur(spec)
    P0, ax, e_ml, e_ap = fm.pose(tpl['alpha'], tpl['e'])
    ax = ax / np.linalg.norm(ax)
    e_ml = e_ml / np.linalg.norm(e_ml)
    e_ap = e_ap / np.linalg.norm(e_ap)
    B = np.stack([ax, e_ml, e_ap])                      # rows = local basis
    p = PM.pairs(d)
    lut = np.full(p['n'] + 1, -1, dtype=np.int64)
    lut[p['node_labels']] = np.arange(len(p['node_labels']))
    X = p['nodes'][lut[p['pair_bone']]]
    U = {s: PM._utab(d / 'm_fric_csv' / f'{s}_U.csv', p['n']) for s in STEPS}
    rel = np.stack([U[s][p['pair_stem']] - U[s][p['pair_bone']] for s in STEPS])        # [4,n,3] mm world
    C2 = PM._ctab(d / 'm_fric_csv' / 'LOAD2_CONTACT.csv', p['n'])
    C0 = PM._ctab(d / 'm_fric_csv' / 'RELEASE_CONTACT.csv', p['n'])
    pb = p['pair_bone']
    q = X - P0
    nrm = p['pair_normal']
    arr = {
        'X': X.astype(np.float32), 'frame': np.stack([P0, ax, e_ml, e_ap]).astype(np.float64),
        'loc': (q @ B.T).astype(np.float32), 'nloc': (nrm @ B.T).astype(np.float32),
        'area': p['pair_area'].astype(np.float32), 'interf': p['pair_interf'].astype(np.float32),
        'cortex': p['pair_cortex'].astype(bool), 'collar': p['pair_collar'].astype(bool),
        'd_canal': np.asarray(fm.canal_sdf(X), dtype=np.float32), 'd_outer': np.asarray(fm.outer_sdf(X), dtype=np.float32),
        'rel': (np.einsum('snk,jk->snj', rel, B) * 1e3).astype(np.float32),
        'cstat2': C2.get('CSTATUS', np.full(p['n'] + 1, np.nan))[pb].astype(np.float32),
        'cpress2': C2.get('CPRESS', np.full(p['n'] + 1, np.nan))[pb].astype(np.float32),
        'cpress0': C0.get('CPRESS', np.full(p['n'] + 1, np.nan))[pb].astype(np.float32),
    }
    IF.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(IF / f'{job}.npz', **arr)
    # ---- reproduce the scalar metrics from the stored (float32) arrays
    body = ~arr['collar']
    R = arr['rel'].astype(np.float64) * 1e-3                                         # mm, stem frame
    nl = arr['nloc'].astype(np.float64)
    w = arr['area'].astype(np.float64)
    rv = R[3] - R[2]
    tang = rv - (rv * nl).sum(1)[:, None] * nl
    slip = np.linalg.norm(tang, axis=1) * 1e3
    f1 = PM._wq(slip[body], w[body], 0.95)
    gap2 = -(arr['interf'] + (R[3] * nl).sum(1)) * 1e3
    ca2 = float(w[body][gap2[body] <= PM.OPEN_UM].sum())
    rf = R[1] - R[0]
    _, om, _, _ = ST.rigid_fit(arr['loc'][body].astype(np.float64), rf[body], w[body])
    rot = float(np.degrees(np.linalg.norm(om)))
    out = {'job': job, 'n_pairs': int(len(X)), 'n_body': int(body.sum()), 'f1_chk': f1, 'ca2_chk': ca2, 'rot_chk': rot,
           'nan_rel': int((~np.isfinite(arr['rel'])).sum()), 'nan_cpress2': int((~np.isfinite(arr['cpress2'])).sum()),
           'cstat2_vals': sorted({float(v) for v in np.unique(arr['cstat2'][np.isfinite(arr['cstat2'])])})[:6],
           'npz_bytes': (IF / f'{job}.npz').stat().st_size, 'files': file_sizes(d)}
    if want_mesh_audit:
        m = np.load(d / 'mesh3d.npz')
        conns = {k: m[k] for k in ('cortex_conn', 'cancellous_conn', 'stem_conn') if k in m}
        allc = np.concatenate(list(conns.values()))
        # tet10 node order (Abaqus C3D10): 0-3 corners, 4:(0,1) 5:(1,2) 6:(2,0) 7:(0,3) 8:(1,3) 9:(2,3)
        sub = [(0, 4), (4, 1), (1, 5), (5, 2), (2, 6), (6, 0), (0, 7), (7, 3), (1, 8), (8, 3), (2, 9), (9, 3)]
        e = np.concatenate([allc[:, [a, b]] for a, b in sub])
        e = np.sort(e, 1)
        n_edge_sub = len(np.unique(e[:, 0].astype(np.int64) * 10_000_000 + e[:, 1]))
        ii, jj = np.triu_indices(10, 1)
        e2 = np.sort(np.stack([allc[:, ii].ravel(), allc[:, jj].ravel()], 1), 1)
        n_edge_clq = len(np.unique(e2[:, 0].astype(np.int64) * 10_000_000 + e2[:, 1]))
        nodes = m['nodes']
        out['mesh'] = {'n_nodes': int(len(nodes)), 'n_tet': {k: int(len(v)) for k, v in conns.items()},
                       'n_edges_tet10_subedges': int(n_edge_sub), 'n_edges_element_clique': int(n_edge_clq),
                       'bbox_min': nodes.min(0).tolist(), 'bbox_max': nodes.max(0).tolist(),
                       'npz_keys': {k: list(m[k].shape) for k in m.files}}
        if want_vox:
            out['vox'] = voxel_timing(m, conns, P0, ax)
    out['t_s'] = time.time() - t0
    out['rss_mb'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    return out


def voxel_timing(m, conns, P0, ax):
    """Point-in-tet voxelisation of the FE mesh (labels 1 cortex, 2 cancellous, 3 stem) at 1.0 and 0.5 mm, over the
    box of the stem nodes + 10 mm (the region a 3D CNN would see). Times only; labels are not stored."""
    from scipy.spatial import cKDTree
    lab_nodes = m['node_labels']
    lut = np.full(int(lab_nodes.max()) + 1, -1, dtype=np.int64)
    lut[lab_nodes] = np.arange(len(lab_nodes))
    nodes = m['nodes']
    tets, labs = [], []
    for li, k in enumerate(('cortex_conn', 'cancellous_conn', 'stem_conn')):
        c = conns[k][:, :4]
        tets.append(lut[c])
        labs.append(np.full(len(c), li + 1))
    T = np.concatenate(tets)
    L = np.concatenate(labs)
    V = nodes[T]                                                 # [ne,4,3]
    A = np.stack([V[:, 1] - V[:, 0], V[:, 2] - V[:, 0], V[:, 3] - V[:, 0]], 2)
    Ainv = np.linalg.inv(A)
    cen = V.mean(1)
    tree = cKDTree(cen)
    sn = lut[np.unique(conns['stem_conn'])]
    lo, hi = nodes[sn].min(0) - 10, nodes[sn].max(0) + 10
    res = {}
    for h in (1.0, 0.5):
        t0 = time.time()
        axs = [np.arange(lo[i], hi[i] + 1e-9, h) for i in range(3)]
        G = np.stack(np.meshgrid(*axs, indexing='ij'), -1).reshape(-1, 3)
        lab = np.zeros(len(G), np.int8)
        for i0 in range(0, len(G), 200_000):
            g = G[i0:i0 + 200_000]
            _, idx = tree.query(g, k=16)
            r = g[:, None, :] - V[idx, 0]                           # [b,16,3]
            bc = np.einsum('bkij,bkj->bki', Ainv[idx], r)
            inside = (bc >= -1e-6).all(-1) & (bc.sum(-1) <= 1 + 1e-6)
            hit = inside.any(1)
            first = inside.argmax(1)
            lab[i0:i0 + 200_000][hit] = L[idx[np.arange(len(g)), first]][hit]
        res[f'h{h}'] = {'shape': [len(a) for a in axs], 'n_vox': int(len(G)), 't_s': time.time() - t0,
                        'frac': {str(k): float((lab == k).mean()) for k in range(4)}}
    return res


def safe(args):
    job, ma, vx = args
    try:
        return one(job, ma, vx)
    except Exception as e:  # noqa: BLE001
        return {'job': job, 'error': f'{type(e).__name__}: {e}', 'tb': traceback.format_exc()[-1500:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()
    rows = list(csv.DictReader(open(TAB, newline='')))
    if a.limit:
        rows = rows[:a.limit]
    AUD.mkdir(parents=True, exist_ok=True)
    ref = {r['job']: r for r in rows}
    jobs = [r['job'] for r in rows]
    # mesh audit for every 25th job; voxel timing for 4 of them (2 collarless, 2 collared)
    clean = [r for r in rows if r['current_code'] == 'True' and r['variant_class'] == 'none']
    vox = {r['job'] for r in clean if r['collar'] == 'False'}
    vox = sorted(vox)[:2] + sorted({r['job'] for r in clean if r['collar'] == 'True'})[:2]
    tasks = [(j, (i % 25 == 0) or j in vox, j in vox) for i, j in enumerate(jobs)]
    t0 = time.time()
    outs = []
    with Pool(a.workers, maxtasksperchild=200) as pool:
        for k, o in enumerate(pool.imap_unordered(safe, tasks, chunksize=2)):
            outs.append(o)
            if k % 50 == 0:
                print(f'{k}/{len(tasks)} {time.time() - t0:.0f}s', flush=True)
    errs = [o for o in outs if 'error' in o]
    ok = [o for o in outs if 'error' not in o]
    # consistency vs metrics_all
    dif = {'f1': [], 'ca2': [], 'rot': []}
    for o in ok:
        r = ref[o['job']]
        dif['f1'].append(abs(o['f1_chk'] - float(r['f1_p95_um'])) / max(float(r['f1_p95_um']), 1e-9))
        dif['ca2'].append(abs(o['ca2_chk'] - float(r['contact_area_load2_mm2'])) / max(float(r['contact_area_load2_mm2']), 1e-9))
        dif['rot'].append(abs(o['rot_chk'] - float(r['rot_first_deg'])) / max(float(r['rot_first_deg']), 1e-12))
    cats = sorted({c for o in ok for c in o['files']})
    with open(AUD / 'files_by_job.csv', 'w', newline='') as fh:
        wr = csv.writer(fh)
        wr.writerow(['job', 'n_pairs', 'n_body', 'npz_bytes'] + cats)
        for o in sorted(ok, key=lambda o: o['job']):
            wr.writerow([o['job'], o['n_pairs'], o['n_body'], o['npz_bytes']] + [o['files'].get(c, 0) for c in cats])
    json.dump([{k: o[k] for k in ('job', 'mesh', 'vox') if k in o} for o in ok if 'mesh' in o],
              open(AUD / 'mesh_audit.json', 'w'), indent=1)
    log = {'n_tasks': len(tasks), 'n_ok': len(ok), 'n_err': len(errs), 'errors': errs[:10], 'wall_s': time.time() - t0,
           'max_rel_err': {k: float(np.max(v)) if v else None for k, v in dif.items()},
           'p99_rel_err': {k: float(np.percentile(v, 99)) if v else None for k, v in dif.items()},
           'nan_rel_jobs': sum(o['nan_rel'] > 0 for o in ok), 'nan_cpress2_jobs': sum(o['nan_cpress2'] > 0 for o in ok),
           'cstat2_vals_seen': sorted({v for o in ok for v in o['cstat2_vals']}),
           'iface_total_MB': sum(o['npz_bytes'] for o in ok) / 1e6,
           'max_rss_mb': max(o['rss_mb'] for o in ok) if ok else None,
           'median_t_s': float(np.median([o['t_s'] for o in ok])) if ok else None}
    json.dump(log, open(AUD / 'extract_log.json', 'w'), indent=1)
    print(json.dumps({k: v for k, v in log.items() if k != 'errors'}, indent=1))
    for e in errs[:5]:
        print(e['job'], e['error'], e['tb'][-600:])
    print('when', time.strftime('%Y-%m-%d %H:%M:%S'))


if __name__ == '__main__':
    main()
