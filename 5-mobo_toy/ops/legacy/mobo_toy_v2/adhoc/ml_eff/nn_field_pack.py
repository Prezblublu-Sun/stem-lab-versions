"""ml_eff / nn pilot (b) step 1: pack the per-job interface point clouds of the clean unique jobs into one file.

Input : deck/ml_eff/nn/iface/<job>.npz (from nn_extract_iface.py), the job list + folds of nn_scalar.load()/kfold()
Output: deck/ml_eff/nn/field/pack.npz
  off [J+1]            node offsets per job
  F   [N,15] float32   node features: s, r, cos(th), sin(th), x_ml, x_ap, n_s, n_ml, n_ap, cortex, collar,
                       interf_um, d_canal, d_outer, area   (stem frame, mm; th = atan2(x_ap, x_ml))
  slip [N]  um         recoverable tangential slip |t(LOAD2 - UNLOAD)|  (post_m1 f1 definition)
  gap2 [N]  um         gap at LOAD2 = -(interf + n . u_rel(LOAD2)); closed <=> gap2 <= 1 um (stability contact)
  rf   [N,3] um        first-load relative displacement LOAD - RELEASE, stem frame (stability rigid-fit input)
  loc  [N,3] mm        (s, x_ml, x_ap) for the rigid fit
  area [N], body [N] (= not collar)
  knn  [N,16] int32    local (per-job) indices of the 16 nearest other interface nodes (Euclidean, stem frame)
  G    [J,23]          job design + template features (nn_scalar 'DT'), G_names
  jobs, family, rule, collar, foldA (0..4 = nn_scalar cv5_all folds), y_f1, y_ca2, y_rot, y_sed (metrics_all)
  chk_f1, chk_ca2, chk_rot (recomputed from the packed arrays)
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

HOME = pathlib.Path.home() / 'mobo_toy_v2'
sys.path.insert(0, str(HOME / 'code'))
sys.path.insert(0, str(HOME / 'code' / 'v2'))
import numpy as np  # noqa: E402
from scipy.spatial import cKDTree  # noqa: E402

import nn_scalar as NS  # noqa: E402  (same folder)
import post_m1 as PM  # noqa: E402
import stability as ST  # noqa: E402

IF = HOME / 'deck' / 'ml_eff' / 'nn' / 'iface'
OUT = HOME / 'deck' / 'ml_eff' / 'nn' / 'field'
K = 16


def one(job):
    a = np.load(IF / f'{job}.npz')
    loc = a['loc'].astype(np.float64)
    nl = a['nloc'].astype(np.float64)
    rel = a['rel'].astype(np.float64)                     # [4,n,3] um, stem frame
    th = np.arctan2(loc[:, 2], loc[:, 1])
    r = np.hypot(loc[:, 1], loc[:, 2])
    F = np.stack([loc[:, 0], r, np.cos(th), np.sin(th), loc[:, 1], loc[:, 2], nl[:, 0], nl[:, 1], nl[:, 2],
                  a['cortex'].astype(float), a['collar'].astype(float), a['interf'] * 1e3, a['d_canal'], a['d_outer'],
                  a['area']], 1)
    rv = rel[3] - rel[2]
    tang = rv - (rv * nl).sum(1)[:, None] * nl
    slip = np.linalg.norm(tang, axis=1)
    gap2 = -(a['interf'].astype(np.float64) * 1e3 + (rel[3] * nl).sum(1))
    rf = rel[1] - rel[0]
    tree = cKDTree(loc)
    _, idx = tree.query(loc, k=K + 1)
    knn = idx[:, 1:].astype(np.int32)
    body = ~a['collar'].astype(bool)
    w = a['area'].astype(np.float64)
    f1 = PM._wq(slip[body], w[body], 0.95)
    ca2 = float(w[body][gap2[body] <= PM.OPEN_UM].sum())
    _, om, _, _ = ST.rigid_fit(loc[body], rf[body] * 1e-3, w[body])
    return dict(F=F.astype(np.float32), slip=slip.astype(np.float32), gap2=gap2.astype(np.float32),
                rf=rf.astype(np.float32), loc=loc.astype(np.float32), area=w.astype(np.float32), body=body, knn=knn,
                chk=(f1, ca2, float(np.degrees(np.linalg.norm(om)))))


def main():
    t0 = time.time()
    X, Y, meta, n_rows = NS.load()
    jobs = meta['job']
    J = len(jobs)
    folds = NS.kfold(np.arange(J), 5, 0)
    foldA = np.zeros(J, np.int8)
    for i, f in enumerate(folds):
        foldA[f] = i
    import csv
    ref = {r['job']: r for r in csv.DictReader(open(NS.TAB, newline=''))}
    parts = []
    for k, j in enumerate(jobs):
        parts.append(one(j))
        if k % 100 == 0:
            print(k, J, f'{time.time() - t0:.0f}s', flush=True)
    off = np.zeros(J + 1, np.int64)
    off[1:] = np.cumsum([len(p['slip']) for p in parts])
    cat = lambda k: np.concatenate([p[k] for p in parts])  # noqa: E731
    y = lambda k: np.array([float(ref[j][k]) for j in jobs])  # noqa: E731
    chk = np.array([p['chk'] for p in parts])
    OUT.mkdir(parents=True, exist_ok=True)
    arr = dict(off=off, F=cat('F'), slip=cat('slip'), gap2=cat('gap2'), rf=cat('rf'), loc=cat('loc'), area=cat('area'),
               body=cat('body'), knn=cat('knn'), G=X['DT'].astype(np.float32),
               G_names=np.array(NS.DES + ['rule_' + q for q in NS.RULES] + NS.TPL),
               F_names=np.array(['s', 'r', 'cos_th', 'sin_th', 'x_ml', 'x_ap', 'n_s', 'n_ml', 'n_ap', 'cortex', 'collar',
                                 'interf_um', 'd_canal', 'd_outer', 'area']),
               jobs=np.array(jobs), family=np.array(meta['family']), rule=np.array(meta['rule']),
               collar=meta['collar'], foldA=foldA,
               y_f1=y('f1_p95_um'), y_ca2=y('contact_area_load2_mm2'), y_rot=y('rot_first_deg'), y_sed=y('sed_chg_pct'),
               chk_f1=chk[:, 0], chk_ca2=chk[:, 1], chk_rot=chk[:, 2])
    np.savez(OUT / 'pack.npz', **arr)
    rel = lambda a, b: float(np.max(np.abs(a - b) / np.maximum(np.abs(b), 1e-12)))  # noqa: E731
    info = {'n_jobs': J, 'n_nodes': int(off[-1]), 'nodes_per_job': [int(np.min(np.diff(off))), float(np.median(np.diff(off))),
                                                                     int(np.max(np.diff(off)))],
            'max_rel_err': {'f1': rel(chk[:, 0], arr['y_f1']), 'ca2': rel(chk[:, 1], arr['y_ca2']),
                            'rot': rel(chk[:, 2], arr['y_rot'])},
            'pack_MB': (OUT / 'pack.npz').stat().st_size / 1e6,
            'slip_quantiles_um': np.quantile(arr['slip'], [0.05, 0.25, 0.5, 0.75, 0.95, 0.99]).tolist(),
            'closed_frac_nodes': float((arr['gap2'] <= 1.0).mean()),
            'rf_sd_um': arr['rf'].std(0).tolist(), 'wall_s': time.time() - t0}
    json.dump(info, open(OUT / 'pack_info.json', 'w'), indent=1)
    print(json.dumps(info, indent=1))


if __name__ == '__main__':
    main()
