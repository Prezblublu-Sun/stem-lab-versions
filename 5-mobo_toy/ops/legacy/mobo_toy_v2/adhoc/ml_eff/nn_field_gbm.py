"""ml_eff / nn pilot (b) baseline: per-node gradient boosting (sklearn HistGradientBoosting, CPU, mobo venv).

Same inputs as the networks (15 node features with log area + 23 job features), same splits (A, B) and the same
prediction file format: deck/ml_eff/nn/field/pred_gbm_<split>.npz. Trained on 300 random nodes per training job
(train + the networks' validation jobs), sample weight = per-job normalised node area.

    ~/mobo_toy_v2/run.sh ../adhoc/ml_eff/nn_field_gbm.py --split A
"""
from __future__ import annotations

import argparse
import json
import pathlib
import time

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

HOME = pathlib.Path.home() / 'mobo_toy_v2'
FD = HOME / 'deck' / 'ml_eff' / 'nn' / 'field'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--split', default='A')
    ap.add_argument('--per_job', type=int, default=300)
    a = ap.parse_args()
    t0 = time.time()
    P = np.load(FD / 'pack.npz')
    off = P['off']
    J = len(off) - 1
    if a.split == 'A':
        test = np.where(P['foldA'] == 0)[0]
    elif a.split == 'B':
        test = np.where(P['family'] == 'neck10')[0]
    else:                                                           # C: collared -> collarless (neck_in_shoulder)
        test = np.where(P['rule'] == 'neck_in_shoulder')[0]
    train = np.where(P['collar'])[0] if a.split == 'C' else np.setdiff1d(np.arange(J), test)
    F = P['F'].astype(np.float32).copy()
    F[:, 14] = np.log(F[:, 14])
    G = P['G'].astype(np.float32)
    area = P['area'].astype(np.float64)
    rng = np.random.default_rng(0)
    sel, jid = [], []
    for j in train:
        n = off[j + 1] - off[j]
        k = min(a.per_job, n)
        sel.append(off[j] + rng.choice(n, k, replace=False))
        jid.append(np.full(k, j))
    sel = np.concatenate(sel)
    jid = np.concatenate(jid)
    jsum = np.array([area[off[j]:off[j + 1]].sum() for j in range(J)])
    Xtr = np.concatenate([F[sel], G[jid]], 1)
    wtr = area[sel] / jsum[jid] * (off[jid + 1] - off[jid])
    ys = np.log1p(P['slip'][sel])
    yc = (P['gap2'][sel] <= 1.0).astype(int)
    yr = P['rf'][sel]
    kw = dict(max_iter=400, learning_rate=0.1, max_leaf_nodes=63, min_samples_leaf=40, l2_regularization=1.0,
              random_state=0)
    models = {'slip': HistGradientBoostingRegressor(**kw).fit(Xtr, ys, sample_weight=wtr),
              'closed': HistGradientBoostingClassifier(**kw).fit(Xtr, yc, sample_weight=wtr)}
    for i in range(3):
        models[f'rf{i}'] = HistGradientBoostingRegressor(**kw).fit(Xtr, yr[:, i], sample_weight=wtr)
    t_fit = time.time() - t0
    tidx = np.concatenate([np.arange(off[j], off[j + 1]) for j in test])
    tj = np.concatenate([np.full(off[j + 1] - off[j], j) for j in test])
    Xte = np.concatenate([F[tidx], G[tj]], 1)
    t1 = time.time()
    ps = np.expm1(models['slip'].predict(Xte))
    pc = models['closed'].predict_proba(Xte)[:, 1]
    pr = np.stack([models[f'rf{i}'].predict(Xte) for i in range(3)], 1)
    t_inf = time.time() - t1
    toff = np.zeros(len(test) + 1, np.int64)
    toff[1:] = np.cumsum([off[j + 1] - off[j] for j in test])
    np.savez(FD / f'pred_gbm_{a.split}.npz', test=test, toff=toff, slip=ps.astype(np.float32),
             pclosed=pc.astype(np.float32), rf=pr.astype(np.float32))
    rep = {'model': 'gbm', 'split': a.split, 'n_train_jobs': int(len(train)), 'n_train_rows': int(len(sel)),
           'n_test_jobs': int(len(test)), 'fit_s': t_fit, 'infer_s_per_job': t_inf / len(test),
           'n_iter': {k: int(m.n_iter_) for k, m in models.items()}}
    json.dump(rep, open(FD / f'train_gbm_{a.split}.json', 'w'), indent=1)
    print(json.dumps(rep), 'when', time.strftime('%Y-%m-%d %H:%M:%S'))


if __name__ == '__main__':
    main()
