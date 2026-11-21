"""ml_eff / nn: run-to-run spread of the out-of-phase scalar results (MLP ensemble seeds; GBM subsample seeds).

The GP fit is deterministic for fixed data, the MLP ensemble and GBM (subsample 0.8) are not. Splits B (neck10 <- rest)
and C (collared -> collarless), features DT, 5 seeds each. torch default dtype is forced to float32 before every fit
so that the ensemble's validation masks depend only on the seed.
Output: deck/ml_eff/nn/scalar_seeds/results.csv
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

OUT = HOME / 'deck' / 'ml_eff' / 'nn' / 'scalar_seeds'


def main():
    import torch
    torch.set_num_threads(1)
    X, Y, meta, _ = NS.load()
    J = len(meta['job'])
    fam = np.array(meta['family'])
    rule = np.array(meta['rule'])
    te = {'B': np.where(fam == 'neck10')[0], 'C': np.where(rule == 'neck_in_shoulder')[0]}
    tr = {'B': np.setdiff1d(np.arange(J), te['B']), 'C': np.where(meta['collar'])[0]}
    Xf = X['DT']
    res = []
    OUT.mkdir(parents=True, exist_ok=True)
    for sp in ('B', 'C'):
        keep = Xf[tr[sp]].std(0) > 1e-12
        for m in ('mlp', 'gbm'):
            for seed in range(5):
                for tg in NS.TARGETS:
                    torch.set_default_dtype(torch.float32)
                    p, sd = NS.fit_predict(m, Xf[tr[sp]][:, keep], Y[tg][tr[sp]], Xf[te[sp]][:, keep], seed=100 + seed)
                    r = NS.metrics(Y[tg][te[sp]], p, sd)
                    r.update(split=sp, model=m, seed=seed, target=tg)
                    res.append(r)
                    print(sp, m, seed, tg, round(r['r2'], 3), round(r['spearman'], 3), flush=True)
    keys = ['split', 'model', 'seed', 'target', 'r2', 'spearman', 'rmse', 'cov90']
    with open(OUT / 'results.csv', 'w', newline='') as fh:
        w = csv.DictWriter(fh, keys, extrasaction='ignore')
        w.writeheader()
        w.writerows(res)
    for sp in ('B', 'C'):
        for m in ('mlp', 'gbm'):
            for tg in NS.TARGETS:
                v = [r['r2'] for r in res if r['split'] == sp and r['model'] == m and r['target'] == tg]
                s = [r['spearman'] for r in res if r['split'] == sp and r['model'] == m and r['target'] == tg]
                print(f'{sp} {m} {tg:8s} R2 mean {np.mean(v):+.3f} min {np.min(v):+.3f} max {np.max(v):+.3f} | '
                      f'rho mean {np.mean(s):.3f} min {np.min(s):.3f}')
    print('when', time.strftime('%Y-%m-%d %H:%M:%S'))


if __name__ == '__main__':
    main()
