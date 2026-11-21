"""Node-level baseline: predict closed contact (LOAD2, gap <= 1 um) of each interface pair from local geometry only
(no FE solve), then aggregate to per-job closed area.  This is the point-wise baseline a GNN / point-cloud network
would have to beat.  Reads ~/mobo_toy_v2/deck/ml_eff/objectives/node_table.npz (written by obj_features.py).
"""
from __future__ import annotations

import csv
import json
import pathlib
import time

import numpy as np

HOME = pathlib.Path.home() / 'mobo_toy_v2'
OUT = HOME / 'deck' / 'ml_eff' / 'objectives'
META = HOME / 'deck' / 'ml_eff' / 'data' / 'metrics_all.csv'

FEATS = ['s_over_L', 'cos_th', 'sin_th', 'r_axis', 't_canc', 't_outer', 'n_axial', 'depth_below_cut', 'interf', 'cortex', 'L', 'm']


def spearman(a, b):
    from scipy.stats import spearmanr
    return float(spearmanr(a, b).statistic)


def r2(y, p):
    return float(1 - np.sum((y - p) ** 2) / np.sum((y - y.mean()) ** 2))


def main():
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    z = np.load(OUT / 'node_table.npz', allow_pickle=True)
    X, jidx, jobs, cols = z['X'], z['job_idx'], z['jobs'], list(z['cols'])
    meta = {r['job']: r for r in csv.DictReader(open(META, newline=''))}
    fam = np.array([meta[j]['family'] for j in jobs])
    rule = np.array([meta[j]['collar_rule'] for j in jobs])
    ci = {c: cols.index(c) for c in cols}
    F = X[:, [ci[c] for c in FEATS]].astype(np.float32)
    y = X[:, ci['closed_load2']] > 0.5
    w = X[:, ci['area']].astype(np.float64)
    res = {'n_nodes': int(len(X)), 'n_jobs': int(len(jobs)), 'features': FEATS}
    out_rows = []
    job_pred_rows = []

    def phase_group(f):
        if f in ('neck1', 'neck2', 'neck3'):
            return 'neck1-3'
        if f in ('neck5', 'neck6'):
            return 'neck5-6'
        if f in ('neck7', 'neck8'):
            return 'neck7-8'
        if f.startswith('neck'):
            return f
        return 'decks'

    subsets = {
        'collarless': (rule == 'neck_in_shoulder', lambda f: f),
        'collared': (rule != 'neck_in_shoulder', phase_group),
    }
    for sname, (jmask, grp_of) in subsets.items():
        jsel = np.nonzero(jmask)[0]
        nm = np.isin(jidx, jsel)
        groups_job = np.array([grp_of(f) for f in fam])
        gnode = groups_job[jidx]
        ug = sorted(set(groups_job[jsel]))
        for model_name in ('t_canc only (logistic)', 'local geometry (HistGB)'):
            p = np.full(len(X), np.nan)
            t0 = time.time()
            for g in ug:
                te = nm & (gnode == g)
                tr = nm & (gnode != g)
                if model_name.startswith('t_canc'):
                    m = LogisticRegression(max_iter=500)
                    xt = np.c_[np.log(np.clip(F[:, FEATS.index('t_canc')], 0.05, None))]
                    m.fit(xt[tr], y[tr], sample_weight=w[tr])
                    p[te] = m.predict_proba(xt[te])[:, 1]
                else:
                    rng = np.random.default_rng(0)
                    tri = np.nonzero(tr)[0]
                    if len(tri) > 1_200_000:
                        tri = rng.choice(tri, 1_200_000, replace=False)
                    m = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.08, max_leaf_nodes=63, min_samples_leaf=50,
                                                       l2_regularization=1.0, random_state=0)
                    m.fit(F[tri], y[tri], sample_weight=w[tri])
                    p[te] = m.predict_proba(F[te])[:, 1]
            sel = nm
            auc = roc_auc_score(y[sel], p[sel], sample_weight=w[sel])
            acc = float(np.average((p[sel] > 0.5) == y[sel], weights=w[sel]))
            # aggregate to jobs
            A_true = np.bincount(jidx[sel], weights=(w * y)[sel], minlength=len(jobs))[jsel]
            A_pred = np.bincount(jidx[sel], weights=(w * p)[sel], minlength=len(jobs))[jsel]
            A_tot = np.bincount(jidx[sel], weights=w[sel], minlength=len(jobs))[jsel]
            d = {'subset': sname, 'model': model_name, 'cv': 'leave-one-group-out over ' + ','.join(ug), 'n_jobs': int(len(jsel)),
                 'n_nodes': int(sel.sum()), 'node_AUC_area_weighted': round(auc, 4), 'node_accuracy_area_weighted': round(acc, 4),
                 'job_area_R2': round(r2(A_true, A_pred), 3), 'job_area_spearman': round(spearman(A_true, A_pred), 3),
                 'job_frac_R2': round(r2(A_true / A_tot, A_pred / A_tot), 3),
                 'job_frac_spearman': round(spearman(A_true / A_tot, A_pred / A_tot), 3), 'wall_s': round(time.time() - t0, 1)}
            for g in ug:
                jm = groups_job[jsel] == g
                if jm.sum() >= 5:
                    d[f'job_area_spearman[{g}]'] = round(spearman(A_true[jm], A_pred[jm]), 3)
                    d[f'job_frac_spearman[{g}]'] = round(spearman(A_true[jm] / A_tot[jm], A_pred[jm] / A_tot[jm]), 3)
            out_rows.append(d)
            print(json.dumps(d), flush=True)
            for k, j in enumerate(jsel):
                job_pred_rows.append({'job': str(jobs[j]), 'subset': sname, 'model': model_name, 'A_closed_true': float(A_true[k]),
                                      'A_closed_pred': float(A_pred[k]), 'A_body': float(A_tot[k])})
    # feature importance proxy: closed fraction vs t_canc bins (collarless)
    jm = np.isin(jidx, np.nonzero(rule == 'neck_in_shoulder')[0])
    t = F[:, FEATS.index('t_canc')]
    bins = [-1, 0.5, 0.75, 1.0, 1.5, 2, 3, 5, 8, 50]
    tb = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        s = jm & (t > lo) & (t <= hi)
        if s.any():
            tb.append({'t_lo': lo, 't_hi': hi, 'area_mm2_total': float(w[s].sum()), 'closed_frac_area_weighted': float(np.average(y[s], weights=w[s])),
                       'cpress_load2_mean': float(np.average(X[s, ci['cpress_load2']], weights=w[s]))})
    res['collarless closed fraction by cancellous thickness'] = tb
    sL = F[:, FEATS.index('s_over_L')]
    sb = []
    for lo, hi in zip([-1, 0, 0.2, 0.4, 0.6, 0.8, 1.0], [0, 0.2, 0.4, 0.6, 0.8, 1.0, 2]):
        s = jm & (sL > lo) & (sL <= hi)
        if s.any():
            sb.append({'s_over_L_lo': lo, 's_over_L_hi': hi, 'area_mm2_total': float(w[s].sum()),
                       'closed_frac_area_weighted': float(np.average(y[s], weights=w[s]))})
    res['collarless closed fraction by axial position'] = sb
    res['models'] = out_rows
    (OUT / 'node_model.json').write_text(json.dumps(res, indent=1))
    with open(OUT / 'node_model_job_preds.csv', 'w', newline='') as fh:
        wr = csv.DictWriter(fh, fieldnames=list(job_pred_rows[0]))
        wr.writeheader(); wr.writerows(job_pred_rows)
    print(json.dumps({k: v for k, v in res.items() if k != 'models'}, indent=1))


if __name__ == '__main__':
    main()
