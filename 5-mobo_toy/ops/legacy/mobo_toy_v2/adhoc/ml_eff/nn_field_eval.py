"""ml_eff / nn pilot (b) step 3: evaluate the field predictions at node level and after aggregation to the FE metrics.

For every deck/ml_eff/nn/field/pred_<model>_<split>.npz:
  node level (test nodes, per-job area-normalised weights): R2 of log1p slip, closed accuracy / AUC, R2 of rf comps
  job level (body nodes, the post_m1 / stability definitions):
     f1   = PM._wq(slip, area, 0.95)                    -> compared as log10(max(f1, 2))
     ca2  = sum(area | p_closed > 0.5)  and E[ca2] = sum(area * p_closed)
     rot  = |omega| of ST.rigid_fit(loc, rf * 1e-3, area) in degrees -> compared as log10(max(rot, 1e-3))
  and the direct scalar surrogates of pilot (a) on the SAME test jobs (A <-> cv5_all fold 0 'DT', B <-> neck10_from_rest 'DT').
Output: deck/ml_eff/nn/field/{field_eval.csv, field_jobs.csv, field_eval.json}
"""
from __future__ import annotations

import csv
import json
import pathlib
import sys
import time

HOME = pathlib.Path.home() / 'mobo_toy_v2'
sys.path.insert(0, str(HOME / 'code'))
sys.path.insert(0, str(HOME / 'code' / 'v2'))
import numpy as np  # noqa: E402
from scipy.stats import spearmanr  # noqa: E402
from sklearn.metrics import roc_auc_score  # noqa: E402

import post_m1 as PM  # noqa: E402
import stability as ST  # noqa: E402

FD = HOME / 'deck' / 'ml_eff' / 'nn' / 'field'
SC = HOME / 'deck' / 'ml_eff' / 'nn' / 'scalar' / 'preds.csv'


def r2(y, p, w=None):
    w = np.ones_like(y) if w is None else w
    mu = (w * y).sum() / w.sum()
    return float(1 - (w * (y - p) ** 2).sum() / (w * (y - mu) ** 2).sum())


def jm(y, p):
    return {'r2': r2(y, p), 'spearman': float(spearmanr(y, p).statistic), 'rmse': float(np.sqrt(np.mean((y - p) ** 2)))}


def aggregate(slip, pc, rf, loc, area, body):
    b = body
    f1 = PM._wq(slip[b].astype(np.float64), area[b], 0.95)
    ca = float(area[b][pc[b] > 0.5].sum())
    cae = float((area[b] * pc[b]).sum())
    _, om, _, _ = ST.rigid_fit(loc[b].astype(np.float64), rf[b].astype(np.float64) * 1e-3, area[b])
    return f1, ca, cae, float(np.degrees(np.linalg.norm(om)))


def main():
    t0 = time.time()
    P = np.load(FD / 'pack.npz')
    off = P['off']
    jobs = P['jobs']
    area = P['area'].astype(np.float64)
    body = P['body']
    loc = P['loc']
    slip_t = P['slip']
    closed_t = (P['gap2'] <= 1.0)
    rf_t = P['rf']
    rule = P['rule']
    # direct scalar predictions from pilot (a)
    sc = {}
    if SC.exists():
        for r in csv.DictReader(open(SC, newline='')):
            if r['fs'] != 'DT':
                continue
            key = {'cv5_all': 'A', 'neck10_from_rest': 'B', 'collared_to_collarless': 'C'}.get(r['split'])
            if key is None or (key == 'A' and r['fold'] != '0'):
                continue
            sc.setdefault((key, r['model'], r['target']), {})[r['job']] = float(r['pred'])
    rows, jrows, out = [], [], {}
    for f in sorted(FD.glob('pred_*_*.npz')):
        model, split = f.stem.split('_')[1], f.stem.split('_')[2]
        Q = np.load(f)
        test = Q['test']
        toff = Q['toff']
        tidx = np.concatenate([np.arange(off[j], off[j + 1]) for j in test])
        w = np.concatenate([area[off[j]:off[j + 1]] / area[off[j]:off[j + 1]].sum() for j in test])
        node = {'r2_log1p_slip': r2(np.log1p(slip_t[tidx]).astype(np.float64), np.log1p(Q['slip']).astype(np.float64), w),
                'acc_closed': float((w * ((Q['pclosed'] > 0.5) == closed_t[tidx])).sum() / w.sum()),
                'auc_closed': float(roc_auc_score(closed_t[tidx], Q['pclosed'], sample_weight=w)),
                'r2_rf': [r2(rf_t[tidx, i].astype(np.float64), Q['rf'][:, i].astype(np.float64), w) for i in range(3)]}
        A = []
        for k, j in enumerate(test):
            s = slice(off[j], off[j + 1])
            q = slice(toff[k], toff[k + 1])
            tru = aggregate(slip_t[s], closed_t[s].astype(float), rf_t[s], loc[s], area[s], body[s])
            prd = aggregate(Q['slip'][q], Q['pclosed'][q], Q['rf'][q], loc[s], area[s], body[s])
            A.append((j, tru, prd))
            jrows.append({'model': model, 'split': split, 'job': jobs[j], 'rule': rule[j],
                          'f1_true': tru[0], 'f1_pred': prd[0], 'ca2_true': tru[1], 'ca2_pred': prd[1],
                          'ca2_pred_exp': prd[2], 'rot_true': tru[3], 'rot_pred': prd[3]})
        tr = np.array([a[1] for a in A])
        pr = np.array([a[2] for a in A])
        # sanity: aggregated truth equals the metrics_all values
        chk = float(np.max(np.abs(tr[:, 0] - P['y_f1'][test]) / P['y_f1'][test]))
        lf = lambda x: np.log10(np.maximum(x, 2.0))  # noqa: E731
        lr = lambda x: np.log10(np.maximum(x, 1e-3))  # noqa: E731
        subsets = {'all': np.ones(len(test), bool), 'collarless': rule[test] == 'neck_in_shoulder',
                   'collared': rule[test] != 'neck_in_shoulder'}
        for sname, m in subsets.items():
            if m.sum() < 5:
                continue
            res = {'model': model, 'split': split, 'subset': sname, 'n_test_jobs': int(m.sum()),
                   'f1_log': jm(lf(tr[m, 0]), lf(pr[m, 0])), 'ca2': jm(tr[m, 1], pr[m, 1]),
                   'ca2_exp': jm(tr[m, 1], pr[m, 2]), 'rot_log': jm(lr(tr[m, 3]), lr(pr[m, 3]))}
            if sname == 'all':
                res['node'] = node
                res['truth_check_max_rel_err_f1'] = chk
            rows.append(res)
            # direct scalar surrogates on the same jobs
            if model == 'gbm':                                    # do it once per split/subset
                for sm in ('gp', 'gbm', 'mlp'):
                    d = {}
                    for tg, idx, tf in (('log_f1', 0, lf), ('contact', 1, lambda x: x), ('log_rot', 3, lr)):
                        mp = sc.get((split, sm, tg))
                        if not mp:
                            continue
                        jj = [jobs[j] for j in test[m]]
                        if not all(x in mp for x in jj):
                            d[tg] = 'job set mismatch'
                            continue
                        d[tg] = jm(tf(tr[m, idx]), np.array([mp[x] for x in jj]))
                    rows.append({'model': f'scalar_{sm}', 'split': split, 'subset': sname, 'n_test_jobs': int(m.sum()),
                                 'f1_log': d.get('log_f1'), 'ca2': d.get('contact'), 'rot_log': d.get('log_rot')})
    with open(FD / 'field_jobs.csv', 'w', newline='') as fh:
        wr = csv.DictWriter(fh, list(jrows[0].keys()))
        wr.writeheader()
        wr.writerows(jrows)
    flat = []
    for r in rows:
        d = {'model': r['model'], 'split': r['split'], 'subset': r['subset'], 'n_test_jobs': r['n_test_jobs']}
        for k in ('f1_log', 'ca2', 'ca2_exp', 'rot_log'):
            v = r.get(k)
            if isinstance(v, dict):
                d[f'{k}_r2'], d[f'{k}_rho'], d[f'{k}_rmse'] = v['r2'], v['spearman'], v['rmse']
        if 'node' in r:
            n = r['node']
            d.update(node_r2_log1p_slip=n['r2_log1p_slip'], node_acc_closed=n['acc_closed'], node_auc_closed=n['auc_closed'],
                     node_r2_rf_s=n['r2_rf'][0], node_r2_rf_ml=n['r2_rf'][1], node_r2_rf_ap=n['r2_rf'][2])
        flat.append(d)
    keys = sorted({k for d in flat for k in d}, key=lambda k: (k not in ('model', 'split', 'subset', 'n_test_jobs'), k))
    with open(FD / 'field_eval.csv', 'w', newline='') as fh:
        wr = csv.DictWriter(fh, keys)
        wr.writeheader()
        wr.writerows(flat)
    json.dump({'rows': rows, 'wall_s': time.time() - t0, 'when': time.strftime('%Y-%m-%d %H:%M:%S')},
              open(FD / 'field_eval.json', 'w'), indent=1)
    for d in sorted(flat, key=lambda d: (d['split'], d['subset'], d['model'])):
        print(d['split'], d['subset'], f"{d['model']:11s}", 'n', d['n_test_jobs'],
              'f1 R2/rho', round(d.get('f1_log_r2', np.nan), 3), round(d.get('f1_log_rho', np.nan), 3),
              '| ca2', round(d.get('ca2_r2', np.nan), 3), round(d.get('ca2_rho', np.nan), 3),
              '| rot', round(d.get('rot_log_r2', np.nan), 3), round(d.get('rot_log_rho', np.nan), 3),
              '| node slip/acc/rf', round(d.get('node_r2_log1p_slip', np.nan), 3), round(d.get('node_acc_closed', np.nan), 3),
              round(d.get('node_r2_rf_s', np.nan), 3))
    print('wall', time.time() - t0)


if __name__ == '__main__':
    main()
