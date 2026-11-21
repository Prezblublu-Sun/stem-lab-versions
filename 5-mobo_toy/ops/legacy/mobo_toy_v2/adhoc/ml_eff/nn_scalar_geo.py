"""ml_eff / nn control experiment: is the field networks' out-of-phase advantage just the extra mesh geometry?

Adds 14 FE-free interface-geometry descriptors (from the prep mesh, no solve) to the scalar 'DT' features and refits
GP / GBM / MLP-ensemble (nn_scalar.fit_predict) on the same splits as the field pilot:
  A = cv5_all fold 0 test, B = neck10 hold-out, C = collared -> collarless (neck_in_shoulder).
Descriptors (body interface nodes, area-weighted): area, cortex area fraction, mean interference, d_canal p10/p50/p90,
area fraction with d_canal > -0.5 mm, mean n_s, mean |n_s|, axial length, mean r, mean r^2, area-weighted s centroid,
area fraction in the distal third.
Output: deck/ml_eff/nn/scalar_geo/{results.csv, preds.csv}
"""
from __future__ import annotations

import csv
import os
import pathlib
import sys
import time

os.environ['OMP_NUM_THREADS'] = '1'
HOME = pathlib.Path.home() / 'mobo_toy_v2'
sys.path.insert(0, str(HOME / 'code'))
sys.path.insert(0, str(HOME / 'code' / 'v2'))
import numpy as np  # noqa: E402

import nn_scalar as NS  # noqa: E402

FD = HOME / 'deck' / 'ml_eff' / 'nn' / 'field'
OUT = HOME / 'deck' / 'ml_eff' / 'nn' / 'scalar_geo'
GEO = ['g_area', 'g_cortex_frac', 'g_interf_um', 'g_dcanal_p10', 'g_dcanal_p50', 'g_dcanal_p90', 'g_near_cortex_frac',
       'g_ns_mean', 'g_absns_mean', 'g_len', 'g_r_mean', 'g_r2_mean', 'g_s_centroid', 'g_distal_frac']


def wq(x, w, q):
    o = np.argsort(x)
    c = np.cumsum(w[o]) / w.sum()
    return float(x[o][np.searchsorted(c, q)])


def geo(P):
    off = P['off']
    F = P['F']
    out = []
    for j in range(len(off) - 1):
        s = slice(off[j], off[j + 1])
        b = P['body'][s]
        f = F[s][b].astype(np.float64)
        w = f[:, 14]
        W = w.sum()
        sx, r, ns, cx, it, dc = f[:, 0], f[:, 1], f[:, 6], f[:, 9], f[:, 11], f[:, 12]
        L = sx.max() - sx.min()
        out.append([W, (w * cx).sum() / W, (w * it).sum() / W, wq(dc, w, 0.1), wq(dc, w, 0.5), wq(dc, w, 0.9),
                    w[dc > -0.5].sum() / W, (w * ns).sum() / W, (w * np.abs(ns)).sum() / W, L, (w * r).sum() / W,
                    (w * r ** 2).sum() / W, (w * sx).sum() / W, w[sx > sx.min() + 2 * L / 3].sum() / W])
    return np.array(out)


def main():
    import torch
    torch.set_num_threads(1)
    t0 = time.time()
    X, Y, meta, _ = NS.load()
    P = np.load(FD / 'pack.npz')
    assert list(P['jobs']) == meta['job']
    Gm = geo(P)
    feats = {'DT': X['DT'], 'DTG': np.concatenate([X['DT'], Gm], 1)}
    J = len(meta['job'])
    rule = np.array(meta['rule'])
    fam = np.array(meta['family'])
    test = {'A': np.where(P['foldA'] == 0)[0], 'B': np.where(fam == 'neck10')[0], 'C': np.where(rule == 'neck_in_shoulder')[0]}
    train = {'A': np.setdiff1d(np.arange(J), test['A']), 'B': np.setdiff1d(np.arange(J), test['B']),
             'C': np.where(meta['collar'])[0]}
    OUT.mkdir(parents=True, exist_ok=True)
    res, preds = [], []
    for sp in ('A', 'B', 'C'):
        for fs in ('DT', 'DTG'):
            Xf = feats[fs]
            tr, te = train[sp], test[sp]
            keep = Xf[tr].std(0) > 1e-12
            for m in ('gp', 'gbm', 'mlp'):
                for tg in NS.TARGETS:
                    t1 = time.time()
                    p, sd = NS.fit_predict(m, Xf[tr][:, keep], Y[tg][tr], Xf[te][:, keep], seed=17)
                    r = NS.metrics(Y[tg][te], p, sd)
                    r.update(split=sp, fs=fs, model=m, target=tg, n_train=len(tr), t_s=time.time() - t1)
                    res.append(r)
                    preds += [(sp, fs, m, tg, meta['job'][i], Y[tg][i], p[k]) for k, i in enumerate(te)]
                    print(f"{sp} {fs:3s} {m:4s} {tg:8s} R2={r['r2']:+.3f} rho={r['spearman']:+.3f} rmse={r['rmse']:.4g}",
                          flush=True)
    keys = ['split', 'fs', 'model', 'target', 'n_train', 'n_test', 'r2', 'spearman', 'rmse', 'mae', 'y_sd', 'cov90', 't_s']
    with open(OUT / 'results.csv', 'w', newline='') as fh:
        w = csv.DictWriter(fh, keys, extrasaction='ignore')
        w.writeheader()
        w.writerows(res)
    with open(OUT / 'preds.csv', 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['split', 'fs', 'model', 'target', 'job', 'y', 'pred'])
        w.writerows(preds)
    np.savez(OUT / 'geo_features.npz', jobs=np.array(meta['job']), G=Gm, names=np.array(GEO))
    print('wall', time.time() - t0, 'when', time.strftime('%Y-%m-%d %H:%M:%S'))


if __name__ == '__main__':
    main()
