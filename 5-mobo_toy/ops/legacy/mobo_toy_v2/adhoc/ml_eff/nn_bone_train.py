"""ml_eff / nn pilot (b2) step 2: learn the bone SED field on the fixed grid and recompute the calcar metric from it.

Data  : deck/ml_eff/nn/bone/pack.npz (nn_bone_extract.py): 779 clean unique jobs, ~30.8k kept grid points per job
        (proximal femur z >= -40 mm, below the design cut, outside the stem), target lr = log(SED_implant / SED_intact).
Inputs per point (all FE-free, built on the fly on the device): grid xyz, tissue (cancellous flag), log intact SED,
        fixed zone one-hot (7), stem-frame coordinates (s, x_ml, x_ap, r) from the job pose, stem_radial_excess,
        distance to the nearest interface node and its cortex flag; plus the job design vector G (nn_scalar 'DT', 23).
Models: pw = pointwise MLP; pn = PointNet-style (per-point MLP -> per-job max+mean pool over a context sample of the
        job's points -> head on every point). The context sample is drawn the same way in training and inference.
Train : each step = 8 jobs x (2048 random kept points + 2048 random G7-cortex points); loss = MSE(lr) on the sampled
        points + aux. MSE of the job-level G7 log ratio of means estimated from the sampled G7-cortex points.
        10 % of the training jobs for early stopping (val = RMSE of the full G7-cortex aggregate, every 5 epochs).
Test  : every kept point of every test job is predicted; calcar sed_chg = 100 (sum_G7c SED_int e^pred / sum SED_int - 1),
        the resorption.py / stage_neckopt._calcar definition (reproduced exactly from the FE grid values).
Splits: A = nn_scalar cv5_all fold 0, B = neck10, C = collared -> collarless (neck_in_shoulder).
Output: deck/ml_eff/nn/bone/train_<model>_<split>.json, bone_jobs_<model>_<split>.csv

    /home/linux-user/lit-system/.venv/bin/python ../adhoc/ml_eff/nn_bone_train.py --split A --models pw,pn
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import time

import numpy as np
import torch
import torch.nn as nn

HOME = pathlib.Path.home() / 'mobo_toy_v2'
BD = HOME / 'deck' / 'ml_eff' / 'nn' / 'bone'


def mlp(dims, last_act=False):
    L = []
    for i, (a, b) in enumerate(zip(dims[:-1], dims[1:])):
        L.append(nn.Linear(a, b))
        if i < len(dims) - 2 or last_act:
            L.append(nn.SiLU())
    return nn.Sequential(*L)


def seg_pool(h, bidx, B):
    mx = torch.full((B, h.shape[1]), -1e30, device=h.device, dtype=h.dtype).scatter_reduce(
        0, bidx[:, None].expand_as(h), h, reduce='amax', include_self=True)
    s = torch.zeros(B, h.shape[1], device=h.device, dtype=h.dtype).index_add_(0, bidx, h)
    c = torch.zeros(B, device=h.device, dtype=h.dtype).index_add_(0, bidx, torch.ones_like(bidx, dtype=h.dtype))
    return torch.cat([mx, s / c.clamp_min(1)[:, None]], 1)


class PW(nn.Module):
    def __init__(self, fi, gi, H=128):
        super().__init__()
        self.net = mlp([fi + gi, H, H, H, H, 1])

    def forward(self, f, g, bidx, B, ctx=None):
        return self.net(torch.cat([f, g[bidx]], 1)).squeeze(1)


class PN(nn.Module):
    def __init__(self, fi, gi, H=128):
        super().__init__()
        self.enc = mlp([fi + gi, H, H, H], last_act=True)
        self.glob = mlp([2 * H + gi, H, H], last_act=True)
        self.head = mlp([H + H + fi + gi, H, H, 1])

    def forward(self, f, g, bidx, B, ctx=None):
        z = torch.cat([f, g[bidx]], 1)
        h = self.enc(z)
        if ctx is None:
            pooled = seg_pool(h, bidx, B)
        else:
            fc, bc = ctx
            pooled = seg_pool(self.enc(torch.cat([fc, g[bc]], 1)), bc, B)
        Gl = self.glob(torch.cat([pooled, g], 1))
        return self.head(torch.cat([h, Gl[bidx], z], 1)).squeeze(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--split', default='A')
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--models', default='pw,pn')
    ap.add_argument('--epochs', type=int, default=150)
    ap.add_argument('--bs', type=int, default=8)
    ap.add_argument('--npts', type=int, default=2048)
    ap.add_argument('--lr', type=float, default=1e-3)
    ap.add_argument('--max_minutes', type=float, default=12.0)
    ap.add_argument('--cpu', action='store_true')
    ap.add_argument('--smoke', action='store_true')
    a = ap.parse_args()
    dev = torch.device('cpu' if (a.cpu or not torch.cuda.is_available()) else 'cuda')
    torch.set_num_threads(2)
    if dev.type == 'cuda':
        torch.cuda.set_per_process_memory_fraction(0.25, 0)            # <= 4 GB of the 16 GB card
    t00 = time.time()
    Pk = np.load(BD / 'pack.npz', allow_pickle=False)
    off, keep = Pk['off'], Pk['keep']
    Jn = len(off) - 1
    fam, rule = Pk['family'], Pk['rule']
    if a.split == 'A':
        test = np.where(Pk['foldA'] == 0)[0]
    elif a.split == 'B':
        test = np.where(fam == 'neck10')[0]
    elif a.split == 'C':
        test = np.where(rule == 'neck_in_shoulder')[0]
    else:
        raise ValueError(a.split)
    rest = np.where(Pk['collar'])[0] if a.split == 'C' else np.setdiff1d(np.arange(Jn), test)
    rng = np.random.default_rng(a.seed)
    val = np.sort(rng.choice(rest, max(8, len(rest) // 10), replace=False))
    train = np.setdiff1d(rest, val)
    if a.smoke:
        train, val, test = train[:24], val[:4], test[:6]
    T = lambda x: torch.as_tensor(x, device=dev)  # noqa: E731
    # ---- compact per-point storage; features are assembled on the device
    gidx = np.concatenate([np.where(keep[j])[0] for j in range(Jn)]).astype(np.int64)
    assert len(gidx) == off[-1]
    jid = np.repeat(np.arange(Jn), np.diff(off))
    code = Pk['code'].astype(np.int64)
    g7c = (Pk['g7'] & ~Pk['canc'])
    isg = g7c[gidx]
    tGI, tJ = T(gidx), T(jid)
    tP = T(Pk['P'].astype(np.float32))
    tCanc = T(Pk['canc'].astype(np.float32))
    gil = Pk['gi_log'].astype(np.float32)
    tGil = T(np.nan_to_num(gil, nan=0.0))
    tOH = T(np.eye(8, dtype=np.float32)[code][:, 1:])
    tPose = T(Pk['pose'].astype(np.float32))
    tRex, tDp, tCp = T(Pk['rex']), T(Pk['dpair']), T(Pk['cpair'])
    tY = T(Pk['lr'].astype(np.float32))
    stats = {'m': None, 's': None}

    def feats(idx):
        g, j = tGI[idx], tJ[idx]
        xyz = tP[g]
        Q = xyz - tPose[j, 0]
        sl = torch.stack([(Q * tPose[j, k]).sum(1) for k in (1, 2, 3)], 1)
        F = torch.cat([xyz, tCanc[g, None], tGil[g, None], tOH[g], sl, torch.hypot(sl[:, 1], sl[:, 2])[:, None],
                       tRex[idx].float()[:, None], tDp[idx].float()[:, None], tCp[idx].float()[:, None]], 1)
        if stats['m'] is not None:
            F = (F - stats['m']) / stats['s']
        return F

    pools_all = [np.arange(off[j], off[j + 1]) for j in range(Jn)]
    pools_g7 = [pools_all[j][isg[off[j]:off[j + 1]]] for j in range(Jn)]
    # normalisation from a sample of training points (flags 3 and 5..11 are left as 0/1)
    smp = T(np.concatenate([rng.choice(pools_all[j], 256, replace=False) for j in train]))
    F0 = feats(smp)
    m_, s_ = F0.mean(0), F0.std(0) + 1e-6
    flag = torch.zeros(F0.shape[1], dtype=torch.bool, device=dev)
    flag[3] = True
    flag[5:12] = True
    flag[-1] = True
    stats['m'] = torch.where(flag, torch.zeros_like(m_), m_)
    stats['s'] = torch.where(flag, torch.ones_like(s_), s_)
    G = Pk['G'].astype(np.float32)
    gm, gs = G[train].mean(0), G[train].std(0)
    gs[gs < 1e-9] = 1.0
    tG = T((G - gm) / gs)
    y_sed = Pk['y_sed']

    def sample(js, r):
        idx, gm_, bl = [], [], []
        for b, j in enumerate(js):
            ia = r.choice(pools_all[j], a.npts, replace=len(pools_all[j]) < a.npts)
            ig = r.choice(pools_g7[j], a.npts, replace=len(pools_g7[j]) < a.npts)
            idx += [ia, ig]
            gm_ += [np.zeros(a.npts, bool), np.ones(a.npts, bool)]
            bl += [np.full(2 * a.npts, b)]
        return T(np.concatenate(idx)), T(np.concatenate(gm_)), T(np.concatenate(bl).astype(np.int64))

    def g7_logratio(pred, idx, g7m, bidx, B):
        w = torch.exp(tGil[tGI[idx]]) * g7m
        num_p = torch.zeros(B, device=dev).index_add_(0, bidx, w * torch.exp(pred.clamp(-12, 12)))
        num_t = torch.zeros(B, device=dev).index_add_(0, bidx, w * torch.exp(tY[idx]))
        return torch.log(num_p.clamp_min(1e-30)), torch.log(num_t.clamp_min(1e-30))

    def predict_job(net, j):
        """full-field prediction for one job -> (pred lr on all its kept points, calcar sed_chg from prediction)."""
        r = np.random.default_rng(1000 + int(j))
        cidx, _, cb = sample([j], r)
        ctx = (feats(cidx), cb)
        ia = torch.arange(int(off[j]), int(off[j + 1]), device=dev)
        out = []
        for c0 in range(0, len(ia), 32768):
            ii = ia[c0:c0 + 32768]
            out.append(net(feats(ii), tG[[j]], torch.zeros(len(ii), dtype=torch.long, device=dev), 1, ctx))
        p = torch.cat(out)
        m = T(isg[off[j]:off[j + 1]])
        w = torch.exp(tGil[tGI[ia]])[m]
        sed = 100.0 * float((w * torch.exp(p[m].clamp(-12, 12))).sum() / w.sum() - 1.0)
        return p, sed

    fi, gi = F0.shape[1], tG.shape[1]
    del F0
    for name in a.models.split(','):
        tag = name if a.seed == 0 else f'{name}s{a.seed}'
        torch.manual_seed(a.seed)
        net = {'pw': PW, 'pn': PN}[name](fi, gi).to(dev)
        npar = sum(p.numel() for p in net.parameters())
        opt = torch.optim.AdamW(net.parameters(), lr=a.lr, weight_decay=1e-4)
        spe = int(np.ceil(len(train) / a.bs))
        sch = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=a.lr, total_steps=a.epochs * spe, pct_start=0.1)
        if dev.type == 'cuda':
            torch.cuda.reset_peak_memory_stats()
        best, best_state, best_ep, hist = float('inf'), None, -1, []
        t0 = time.time()
        ep_done = 0
        for ep in range(a.epochs):
            net.train()
            perm = rng.permutation(train)
            tl = np.zeros(2)
            for b0 in range(0, len(perm), a.bs):
                js = perm[b0:b0 + a.bs]
                idx, g7m, bidx = sample(js, rng)
                pred = net(feats(idx), tG[T(js)], bidx, len(js))
                l_pt = ((pred - tY[idx]) ** 2).mean()
                lp, lt = g7_logratio(pred, idx, g7m.float(), bidx, len(js))
                l_ag = ((lp - lt) ** 2).mean()
                loss = l_pt + l_ag
                opt.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(net.parameters(), 5.0)
                opt.step()
                sch.step()
                tl += [l_pt.item(), l_ag.item()]
            tl /= spe
            ep_done = ep + 1
            stop = (time.time() - t0) / 60 > a.max_minutes
            if ep % 5 == 4 or ep == a.epochs - 1 or stop:
                net.eval()
                with torch.no_grad():
                    ev = np.array([predict_job(net, j)[1] for j in val])
                verr = float(np.sqrt(np.mean((ev - y_sed[val]) ** 2)))
                hist.append([ep, *tl.tolist(), verr])
                if verr < best:
                    best, best_ep = verr, ep
                    best_state = {k: v.detach().clone() for k, v in net.state_dict().items()}
                print(f'{name} ep{ep} train {tl.round(4).tolist()} val_rmse_sed {verr:.3f} {time.time() - t0:.0f}s',
                      flush=True)
            if stop:
                print(f'{name}: time cap after epoch {ep}', flush=True)
                break
        train_s = time.time() - t0
        net.load_state_dict(best_state)
        net.eval()
        rows, se_all, se_g = [], 0.0, 0.0
        yy_all, yy_g = [], []
        t1 = time.time()
        with torch.no_grad():
            for j in test:
                p, sed = predict_job(net, j)
                yt = tY[int(off[j]):int(off[j + 1])]
                m = T(isg[off[j]:off[j + 1]])
                se_all += float(((p - yt) ** 2).sum())
                se_g += float(((p[m] - yt[m]) ** 2).sum())
                yy_all.append(yt.cpu().numpy())
                yy_g.append(yt[m].cpu().numpy())
                rows.append({'job': str(Pk['jobs'][j]), 'family': str(fam[j]), 'rule': str(rule[j]),
                             'sed_true': float(y_sed[j]), 'sed_pred': sed})
        inf_s = (time.time() - t1) / len(test)
        ya, yg = np.concatenate(yy_all), np.concatenate(yy_g)
        st, sp = np.array([r['sed_true'] for r in rows]), np.array([r['sed_pred'] for r in rows])
        from scipy.stats import spearmanr
        rep = {'model': tag, 'seed': a.seed, 'split': a.split, 'n_params': int(npar), 'n_train_jobs': int(len(train)),
               'n_val_jobs': int(len(val)), 'n_test_jobs': int(len(test)), 'epochs_run': ep_done, 'best_epoch': best_ep,
               'train_s': train_s, 'infer_s_per_job': inf_s,
               'peak_gpu_MB': (torch.cuda.max_memory_allocated() / 2 ** 20) if dev.type == 'cuda' else None,
               'point_r2_lr_all': float(1 - se_all / ((ya - ya.mean()) ** 2).sum()),
               'point_r2_lr_g7cortex': float(1 - se_g / ((yg - yg.mean()) ** 2).sum()),
               'sed_r2': float(1 - ((st - sp) ** 2).sum() / ((st - st.mean()) ** 2).sum()),
               'sed_rho': float(spearmanr(st, sp).statistic), 'sed_rmse': float(np.sqrt(np.mean((st - sp) ** 2))),
               'sed_feas_acc': float(np.mean((np.abs(st) <= 30) == (np.abs(sp) <= 30))),
               'sed_false_feasible': int(np.sum((np.abs(sp) <= 30) & (np.abs(st) > 30))),
               'sed_n_infeasible': int(np.sum(np.abs(st) > 30)), 'hist': hist}
        json.dump(rep, open(BD / f'train_{tag}_{a.split}.json', 'w'), indent=1)
        with open(BD / f'bone_jobs_{tag}_{a.split}.csv', 'w', newline='') as fh:
            w = csv.DictWriter(fh, list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(json.dumps({k: v for k, v in rep.items() if k != 'hist'}), flush=True)
        del net, opt, best_state
        if dev.type == 'cuda':
            torch.cuda.empty_cache()
    print('total', time.time() - t00, 'when', time.strftime('%Y-%m-%d %H:%M:%S'))


if __name__ == '__main__':
    main()
