"""ml_eff / nn pilot (a): scalar surrogates design (+ template features) -> v2/v3 metrics.

Models : GP  = mobo.fit_gp (the BO surrogate: SingleTaskGP, ARD Matern-5/2, Normalize/Standardize)
         GBM = sklearn GradientBoostingRegressor (600 trees, depth 3, lr 0.03, subsample 0.8)
         MLP = deep ensemble of 5 MLPs (2 x 64, SiLU), batched in one torch module, AdamW, per-member 15 % early-stop split
Targets: log_rot = log10(max(rot_first_deg, 1e-3)); contact = contact_area_load2_mm2; log_f1 = log10(max(f1_p95_um, 2));
         sed = sed_chg_pct (standard intact reference)
Data   : metrics_all.csv rows with current_code & variant_class none (795) -> exact-duplicate designs dropped (keep first).
Splits : cv5_all, cv5_collarless (neck_in_shoulder), neck10_from_rest, neck10_from_neck9, collared_to_collarless,
         lc (learning curve on fold-0 test of cv5_all: N_train 100/200/400 x 3 reps + all).
Output : deck/ml_eff/nn/scalar/{results.csv, preds.csv, meta.json}

    ~/mobo_toy_v2/run.sh ../adhoc/ml_eff/nn_scalar.py [--workers 4] [--quick]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import pathlib
import sys
import time
import traceback
from multiprocessing import get_context

HOME = pathlib.Path.home() / 'mobo_toy_v2'
sys.path.insert(0, str(HOME / 'code'))
sys.path.insert(0, str(HOME / 'code' / 'v2'))
os.environ['OMP_NUM_THREADS'] = '1'
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['MKL_NUM_THREADS'] = '1'
import numpy as np  # noqa: E402

TAB = HOME / 'deck' / 'ml_eff' / 'data' / 'metrics_all.csv'
OUT = HOME / 'deck' / 'ml_eff' / 'nn' / 'scalar'
DES = ['L', 'alpha', 'collar_w', 'h_cut', 'm', 'rho_tip', 'q', 'lam', 'g_ml', 'g_ap', 'n_a', 'n_p', 'tau_a', 'tau_p']
RULES = ['None', 'wrap_fit', 'neck_in_shoulder']
TPL = ['tpl_e', 'tpl_A0', 'tpl_contact', 'tpl_s_bind', 'tpl_volume', 'bone_total_mm3']
TARGETS = ['log_rot', 'contact', 'log_f1', 'sed']


def load():
    rows = [r for r in csv.DictReader(open(TAB, newline=''))
            if r['current_code'] == 'True' and r['variant_class'] == 'none']
    seen, keep = set(), []
    for r in rows:
        key = (r['collar_rule'],) + tuple(round(float(r[k]), 9) for k in DES)
        if key in seen:
            continue
        seen.add(key)
        keep.append(r)
    f = lambda k: np.array([float(r[k]) for r in keep])  # noqa: E731
    D = np.stack([f(k) for k in DES], 1)
    oh = np.array([[r['collar_rule'] == q for q in RULES] for r in keep], float)
    T = np.stack([f(k) for k in TPL], 1)
    Y = {'log_rot': np.log10(np.maximum(f('rot_first_deg'), 1e-3)), 'contact': f('contact_area_load2_mm2'),
         'log_f1': np.log10(np.maximum(f('f1_p95_um'), 2.0)), 'sed': f('sed_chg_pct')}
    meta = {'job': [r['job'] for r in keep], 'family': [r['family'] for r in keep],
            'rule': [r['collar_rule'] for r in keep], 'collar': np.array([r['collar'] == 'True' for r in keep])}
    X = {'D': np.concatenate([D, oh], 1), 'DT': np.concatenate([D, oh, T], 1)}
    return X, Y, meta, len(rows)


def kfold(idx, k, seed):
    rng = np.random.default_rng(seed)
    p = rng.permutation(idx)
    return [p[i::k] for i in range(k)]


def build_tasks(meta, quick=False):
    n = len(meta['job'])
    allidx = np.arange(n)
    fam = np.array(meta['family'])
    rule = np.array(meta['rule'])
    nis = np.where(rule == 'neck_in_shoulder')[0]
    T = []
    models = ['gp', 'gbm', 'mlp']
    for fs in ('D', 'DT'):
        folds = kfold(allidx, 5, 0)
        for i, te in enumerate(folds):
            tr = np.setdiff1d(allidx, te)
            T += [dict(split='cv5_all', fold=i, fs=fs, tr=tr, te=te, model=m, save=(fs == 'DT')) for m in models]
        folds = kfold(nis, 5, 1)
        for i, te in enumerate(folds):
            tr = np.setdiff1d(nis, te)
            T += [dict(split='cv5_collarless', fold=i, fs=fs, tr=tr, te=te, model=m, save=(fs == 'DT')) for m in models]
    te10 = np.where(fam == 'neck10')[0]
    col = np.where(meta['collar'])[0]
    for fs in ('D', 'DT'):
        T += [dict(split='neck10_from_rest', fold=0, fs=fs, tr=np.setdiff1d(allidx, te10), te=te10, model=m, save=True)
              for m in models]
        T += [dict(split='neck10_from_neck9', fold=0, fs=fs, tr=np.where(fam == 'neck9')[0], te=te10, model=m,
                   save=True) for m in models]
        T += [dict(split='collared_to_collarless', fold=0, fs=fs, tr=col, te=nis, model=m, save=True) for m in models]
    folds = kfold(allidx, 5, 0)
    te0 = folds[0]
    pool = np.setdiff1d(allidx, te0)
    for N in (100, 200, 400):
        for rep in range(3):
            tr = np.sort(np.random.default_rng(100 + rep).choice(pool, N, replace=False))
            T += [dict(split='lc', fold=rep, fs='DT', tr=tr, te=te0, model=m, save=False, N=N) for m in models]
    if quick:
        T = [t for t in T if t['split'] == 'neck10_from_neck9' and t['fs'] == 'DT']
    return T


# ----------------------------------------------------------------------------------------------- models
def fit_predict(model, Xtr, ytr, Xte, seed):
    """returns mean, sd (sd may be None) on Xte."""
    if model == 'gbm':
        from sklearn.ensemble import GradientBoostingRegressor
        g = GradientBoostingRegressor(n_estimators=600, max_depth=3, learning_rate=0.03, subsample=0.8,
                                      min_samples_leaf=5, random_state=seed)
        g.fit(Xtr, ytr)
        return g.predict(Xte), None
    if model == 'gp':
        import torch
        import mobo
        gp = mobo.fit_gp(torch.as_tensor(Xtr, dtype=torch.double), torch.as_tensor(ytr, dtype=torch.double))
        gp.eval()
        with torch.no_grad():
            post = gp.posterior(torch.as_tensor(Xte, dtype=torch.double), observation_noise=True)
            mu = post.mean.squeeze(-1).numpy()
            sd = post.variance.clamp_min(0).sqrt().squeeze(-1).numpy()
        return mu, sd
    if model == 'mlp':
        return mlp_ens(Xtr, ytr, Xte, seed)
    raise ValueError(model)


def mlp_ens(Xtr, ytr, Xte, seed, E=5, h=64, depth=2, epochs=2000, lr=3e-3, wd=1e-3):
    import torch
    import torch.nn.functional as F
    torch.manual_seed(seed)
    f32 = torch.float32
    mu_x, sd_x = Xtr.mean(0), Xtr.std(0) + 1e-9
    mu_y, sd_y = ytr.mean(), ytr.std() + 1e-12
    xt = torch.as_tensor((Xtr - mu_x) / sd_x, dtype=f32)
    yt = torch.as_tensor((ytr - mu_y) / sd_y, dtype=f32)
    xe = torch.as_tensor((Xte - mu_x) / sd_x, dtype=f32)
    n, d = xt.shape
    g = torch.Generator().manual_seed(seed)
    va = torch.rand(E, n, generator=g) < 0.15
    trm = (~va).to(f32)
    vam = va.to(f32)
    dims = [d] + [h] * depth + [1]
    W, B = [], []
    for a, b in zip(dims[:-1], dims[1:]):
        W.append(torch.nn.Parameter(torch.randn(E, a, b, generator=g, dtype=f32) * (2.0 / a) ** 0.5 * (0.5 if b == 1 else 1)))
        B.append(torch.nn.Parameter(torch.zeros(E, 1, b, dtype=f32)))
    params = W + B
    opt = torch.optim.AdamW(params, lr=lr, weight_decay=wd)
    sch = torch.optim.lr_scheduler.CosineAnnealingLR(opt, epochs)

    def fwd(x):
        z = x.unsqueeze(0).expand(E, -1, -1)
        for i, (w, b) in enumerate(zip(W, B)):
            z = torch.baddbmm(b, z, w)
            if i < len(W) - 1:
                z = F.silu(z)
        return z.squeeze(-1)

    best = torch.full((E,), float('inf'))
    snap = [p.detach().clone() for p in params]
    for ep in range(epochs):
        opt.zero_grad()
        err = (fwd(xt) - yt) ** 2
        loss = ((err * trm).sum(1) / trm.sum(1)).sum()
        loss.backward()
        opt.step()
        sch.step()
        if ep % 25 == 24:
            with torch.no_grad():
                v = (((fwd(xt) - yt) ** 2) * vam).sum(1) / vam.sum(1).clamp_min(1)
                imp = v < best
                best = torch.where(imp, v, best)
                for s, p in zip(snap, params):
                    s[imp] = p.detach()[imp]
    with torch.no_grad():
        for s, p in zip(snap, params):
            p.copy_(s)
        P = fwd(xe).numpy() * sd_y + mu_y
    return P.mean(0), P.std(0)


def metrics(y, p, sd):
    from scipy.stats import spearmanr
    ss = ((y - y.mean()) ** 2).sum()
    out = {'r2': float(1 - ((y - p) ** 2).sum() / ss) if ss > 0 else float('nan'),
           'spearman': float(spearmanr(y, p).statistic) if len(y) > 2 else float('nan'),
           'rmse': float(np.sqrt(((y - p) ** 2).mean())), 'mae': float(np.abs(y - p).mean()),
           'y_sd': float(y.std()), 'n_test': int(len(y))}
    if sd is not None:
        z = np.abs(y - p) / np.maximum(sd, 1e-12)
        out['cov90'] = float((z <= 1.645).mean())
        out['sd_mean'] = float(np.mean(sd))
    return out


_G = {}


def init(X, Y):
    import torch
    torch.set_num_threads(1)
    _G['X'], _G['Y'] = X, Y


def run(t):
    t0 = time.time()
    try:
        X = _G['X'][t['fs']]
        tr, te = t['tr'], t['te']
        keep = X[tr].std(0) > 1e-12                       # drop constant columns (collarless-only splits)
        Xtr, Xte = X[tr][:, keep], X[te][:, keep]
        res = []
        preds = []
        for tg in TARGETS:
            y = _G['Y'][tg]
            p, sd = fit_predict(t['model'], Xtr, y[tr], Xte, seed=17 + t['fold'])
            m = metrics(y[te], p, sd)
            m.update(split=t['split'], fold=t['fold'], fs=t['fs'], model=t['model'], target=tg,
                     n_train=int(len(tr)), n_feat=int(keep.sum()), t_s=time.time() - t0)
            res.append(m)
            if t['save']:
                preds.append((tg, te, y[te], p, sd))
        return {'res': res, 'preds': preds, 'split': t['split'], 'fold': t['fold'], 'fs': t['fs'], 'model': t['model']}
    except Exception as e:  # noqa: BLE001
        return {'error': f'{type(e).__name__}: {e}', 'tb': traceback.format_exc()[-1500:], 'split': t['split'],
                'model': t['model']}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--quick', action='store_true')
    ap.add_argument('--probe', action='store_true')
    a = ap.parse_args()
    X, Y, meta, n_rows = load()
    tasks = build_tasks(meta, a.quick)
    if a.probe:
        tasks = [t for t in tasks if t['split'] == 'cv5_all' and t['fold'] == 0 and t['fs'] == 'DT']
    # heavy tasks first
    order = {'mlp': 0, 'gp': 1, 'gbm': 2}
    tasks.sort(key=lambda t: (order[t['model']], -len(t['tr'])))
    OUT.mkdir(parents=True, exist_ok=True)
    print(f'rows clean {n_rows} unique {len(meta["job"])} tasks {len(tasks)}', flush=True)
    t0 = time.time()
    outs = []
    ctx = get_context('fork')
    with ctx.Pool(a.workers, initializer=init, initargs=(X, Y)) as pool:
        for k, o in enumerate(pool.imap_unordered(run, tasks)):
            outs.append(o)
            if 'error' in o:
                print('ERR', o['split'], o['model'], o['error'], o['tb'][-500:], flush=True)
            if 'res' in o:
                print(f"{k}/{len(tasks)} {time.time() - t0:.0f}s {o['split']} {o['fs']} {o['model']} "
                      f"N={o['res'][0]['n_train']} task {o['res'][-1]['t_s']:.0f}s", flush=True)
    res = [r for o in outs if 'res' in o for r in o['res']]
    keys = ['split', 'fold', 'fs', 'model', 'target', 'n_train', 'n_test', 'n_feat', 'r2', 'spearman', 'rmse', 'mae',
            'y_sd', 'cov90', 'sd_mean', 't_s']
    with open(OUT / 'results.csv', 'w', newline='') as fh:
        w = csv.DictWriter(fh, keys)
        w.writeheader()
        for r in sorted(res, key=lambda r: (r['split'], r['fs'], r['target'], r['model'], r['n_train'], r['fold'])):
            w.writerow({k: r.get(k, '') for k in keys})
    with open(OUT / 'preds.csv', 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['split', 'fold', 'fs', 'model', 'target', 'job', 'family', 'rule', 'y', 'pred', 'sd'])
        for o in outs:
            for tg, te, yt, p, sd in o.get('preds', []):
                for j, i in enumerate(te):
                    w.writerow([o['split'], o['fold'], o['fs'], o['model'], tg, meta['job'][i], meta['family'][i],
                                meta['rule'][i], yt[j], p[j], '' if sd is None else sd[j]])
    # summary: mean over folds / reps
    summ = {}
    for r in res:
        k = (r['split'], r['fs'], r['target'], r['model'], r['n_train'] if r['split'] == 'lc' else 0)
        summ.setdefault(k, []).append(r)
    S = []
    for k, v in sorted(summ.items()):
        if k[0] in ('cv5_all', 'cv5_collarless'):
            # pooled over folds would differ; report mean of fold metrics
            pass
        S.append({'split': k[0], 'fs': k[1], 'target': k[2], 'model': k[3], 'n_train': k[4] or int(np.mean([x['n_train'] for x in v])),
                  'n_runs': len(v), 'r2': float(np.mean([x['r2'] for x in v])), 'r2_sd': float(np.std([x['r2'] for x in v])),
                  'spearman': float(np.mean([x['spearman'] for x in v])), 'rmse': float(np.mean([x['rmse'] for x in v])),
                  'cov90': float(np.mean([x['cov90'] for x in v])) if 'cov90' in v[0] else None,
                  'y_sd_test': float(np.mean([x['y_sd'] for x in v]))})
    with open(OUT / 'summary.csv', 'w', newline='') as fh:
        w = csv.DictWriter(fh, list(S[0].keys()))
        w.writeheader()
        w.writerows(S)
    json.dump({'n_clean_rows': n_rows, 'n_unique': len(meta['job']), 'n_tasks': len(tasks),
               'n_err': sum('error' in o for o in outs), 'errors': [o for o in outs if 'error' in o][:5],
               'wall_s': time.time() - t0, 'features': {'D': DES + ['rule_' + q for q in RULES],
                                                        'DT': DES + ['rule_' + q for q in RULES] + TPL},
               'targets': TARGETS, 'when': time.strftime('%Y-%m-%d %H:%M:%S')}, open(OUT / 'meta.json', 'w'), indent=1)
    for s in S:
        if s['split'] != 'lc' or True:
            print(f"{s['split']:24s} {s['fs']:3s} {s['target']:8s} {s['model']:4s} N={s['n_train']:4d} "
                  f"R2={s['r2']:+.3f}±{s['r2_sd']:.3f} rho={s['spearman']:+.3f} rmse={s['rmse']:.4g} "
                  f"cov90={s['cov90'] if s['cov90'] is None else round(s['cov90'], 2)} ysd={s['y_sd_test']:.4g}")
    print('wall', time.time() - t0, 'when', time.strftime('%Y-%m-%d %H:%M:%S'))


if __name__ == '__main__':
    main()
