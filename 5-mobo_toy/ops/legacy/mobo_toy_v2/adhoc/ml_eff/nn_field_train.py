"""ml_eff / nn pilot (b) step 2: field-level networks on the interface point clouds (plain torch, GPU env).

Models (shared outputs per interface node: log1p recoverable slip, closed-at-LOAD2 logit, first-load relative
displacement rf (3 comps, stem frame)):
  pw : pointwise MLP on [node features, job design G]                                   (no neighbourhood)
  pn : PointNet-style: per-point MLP -> per-job max+mean pool -> concat back -> per-point head
  mp : k-NN (k=16) message passing, 4 layers, + per-job mean-pool "virtual node" context in every layer
Splits: A = nn_scalar cv5_all fold 0 as test (same jobs as pilot (a)); B = neck10 test, everything else train.
10 % of the training jobs are held out for early stopping (best validation loss).
Loss  : per-job area-weighted (each job weight 1) MSE(log1p slip) + BCE(closed) + MSE(rf / sd_rf).
Output: deck/ml_eff/nn/field/pred_<model>_<split>.npz (test-job per-node predictions) + train_<model>_<split>.json

    /home/linux-user/lit-system/.venv/bin/python ../adhoc/ml_eff/nn_field_train.py --split A --models pw,pn,mp
"""
from __future__ import annotations

import argparse
import json
import pathlib
import time

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as Fn

HOME = pathlib.Path.home() / 'mobo_toy_v2'
FD = HOME / 'deck' / 'ml_eff' / 'nn' / 'field'
DEV = torch.device('cuda' if torch.cuda.is_available() else 'cpu')


def mlp(dims, last_act=False):
    L = []
    for i, (a, b) in enumerate(zip(dims[:-1], dims[1:])):
        L.append(nn.Linear(a, b))
        if i < len(dims) - 2 or last_act:
            L.append(nn.SiLU())
    return nn.Sequential(*L)


def seg_mean(h, bidx, B):
    s = torch.zeros(B, h.shape[1], device=h.device, dtype=h.dtype).index_add_(0, bidx, h)
    c = torch.zeros(B, device=h.device, dtype=h.dtype).index_add_(0, bidx, torch.ones_like(bidx, dtype=h.dtype))
    return s / c.clamp_min(1)[:, None]


def seg_max(h, bidx, B):
    out = torch.full((B, h.shape[1]), -1e30, device=h.device, dtype=h.dtype)
    return out.scatter_reduce(0, bidx[:, None].expand_as(h), h, reduce='amax', include_self=True)


class PW(nn.Module):
    def __init__(self, fi, gi, H=128):
        super().__init__()
        self.net = mlp([fi + gi, H, H, H, H, 5])

    def forward(self, f, g, bidx, B, x=None, nbr=None):
        return self.net(torch.cat([f, g[bidx]], 1))


class PN(nn.Module):
    def __init__(self, fi, gi, H=128):
        super().__init__()
        self.enc = mlp([fi + gi, H, H, H], last_act=True)
        self.glob = mlp([2 * H + gi, H, H], last_act=True)
        self.head = mlp([H + H + fi + gi, H, H, 5])

    def forward(self, f, g, bidx, B, x=None, nbr=None):
        z = torch.cat([f, g[bidx]], 1)
        h = self.enc(z)
        G = self.glob(torch.cat([seg_max(h, bidx, B), seg_mean(h, bidx, B), g], 1))
        return self.head(torch.cat([h, G[bidx], z], 1))


class MP(nn.Module):
    def __init__(self, fi, gi, H=96, L=4):
        super().__init__()
        self.enc = mlp([fi + gi, H, H], last_act=True)
        self.msg = nn.ModuleList([mlp([2 * H + 4, H, H], last_act=True) for _ in range(L)])
        self.upd = nn.ModuleList([mlp([3 * H, H, H]) for _ in range(L)])
        self.norm = nn.ModuleList([nn.LayerNorm(H) for _ in range(L)])
        self.dec = mlp([H + fi + gi, H, H, 5])

    def forward(self, f, g, bidx, B, x=None, nbr=None):
        z = torch.cat([f, g[bidx]], 1)
        h = self.enc(z)
        k = nbr.shape[1]
        src = nbr.reshape(-1)
        dst = torch.arange(len(h), device=h.device).repeat_interleave(k)
        dx = (x[src] - x[dst]) / 5.0
        e = torch.cat([dx, dx.norm(dim=1, keepdim=True)], 1)
        for msg, upd, nrm in zip(self.msg, self.upd, self.norm):
            m = msg(torch.cat([h[dst], h[src], e], 1)).view(len(h), k, -1).mean(1)
            ctx = seg_mean(h, bidx, B)[bidx]
            h = nrm(h + upd(torch.cat([h, m, ctx], 1)))
        return self.dec(torch.cat([h, z], 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--split', default='A')
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--models', default='pw,pn,mp')
    ap.add_argument('--epochs', type=int, default=80)
    ap.add_argument('--bs', type=int, default=8)
    ap.add_argument('--epochs_mp', type=int, default=100)
    ap.add_argument('--lr', type=float, default=1e-3)
    ap.add_argument('--max_minutes', type=float, default=14.0)
    a = ap.parse_args()
    torch.set_num_threads(2)
    if DEV.type == 'cuda':
        torch.cuda.set_per_process_memory_fraction(0.5, 0)        # <= 8 GB of the 16 GB card
    t00 = time.time()
    P = np.load(FD / 'pack.npz', allow_pickle=False)
    off = P['off']
    J = len(off) - 1
    fam = P['family']
    if a.split == 'A':
        test = np.where(P['foldA'] == 0)[0]
    elif a.split == 'B':
        test = np.where(fam == 'neck10')[0]
    elif a.split == 'C':                                            # collared -> collarless (neck_in_shoulder)
        test = np.where(P['rule'] == 'neck_in_shoulder')[0]
    else:
        raise ValueError(a.split)
    rest = np.where(P['collar'])[0] if a.split == 'C' else np.setdiff1d(np.arange(J), test)
    rng = np.random.default_rng(a.seed)
    val = np.sort(rng.choice(rest, max(8, len(rest) // 10), replace=False))
    train = np.setdiff1d(rest, val)
    # ---- arrays
    F = P['F'].astype(np.float32).copy()
    F[:, 14] = np.log(F[:, 14])                                     # log area
    trn_nodes = np.concatenate([np.arange(off[j], off[j + 1]) for j in train])
    fm, fs = F[trn_nodes].mean(0), F[trn_nodes].std(0) + 1e-6
    F = (F - fm) / fs
    G = P['G'].astype(np.float32)
    gm, gs = G[train].mean(0), G[train].std(0)
    gs[gs < 1e-9] = 1.0
    G = (G - gm) / gs
    slip = np.log1p(P['slip'].astype(np.float32))
    closed = (P['gap2'] <= 1.0).astype(np.float32)
    rf = P['rf'].astype(np.float32)
    rf_sd = rf[trn_nodes].std(0)
    rfn = rf / rf_sd
    area = P['area'].astype(np.float32)
    # per-job normalised weight (each job sums to 1)
    w = np.zeros_like(area)
    for j in range(J):
        s = slice(off[j], off[j + 1])
        w[s] = area[s] / area[s].sum()
    T = lambda x: torch.as_tensor(x, device=DEV)  # noqa: E731
    tF, tG, tS, tC, tR, tW = T(F), T(G), T(slip), T(closed), T(rfn), T(w)
    tX = T(P['loc'].astype(np.float32))
    tK = T(P['knn'].astype(np.int64))
    def batch(js):
        idx = torch.cat([torch.arange(int(off[j]), int(off[j + 1]), device=DEV) for j in js])
        sizes = torch.as_tensor([int(off[j + 1] - off[j]) for j in js], device=DEV)
        starts = torch.cumsum(sizes, 0) - sizes
        bidx = torch.repeat_interleave(torch.arange(len(js), device=DEV), sizes)
        nbr = tK[idx] + starts[bidx][:, None]
        return idx, bidx, nbr

    def lossf(out, idx):
        ww = tW[idx]
        ls = (ww * (out[:, 0] - tS[idx]) ** 2).sum()
        lc = (ww * Fn.binary_cross_entropy_with_logits(out[:, 1], tC[idx], reduction='none')).sum()
        lr = (ww[:, None] * (out[:, 2:5] - tR[idx]) ** 2).sum() / 3
        return ls, lc, lr

    fi, gi = F.shape[1], G.shape[1]
    report = {}
    bs_cli = a.bs
    for name in a.models.split(','):
        a.bs = min(bs_cli, 4) if name == 'mp' else bs_cli
        tag = name if a.seed == 0 else f'{name}s{a.seed}'
        n_ep = a.epochs_mp if name == 'mp' else a.epochs
        torch.manual_seed(a.seed)
        net = {'pw': PW, 'pn': PN, 'mp': MP}[name](fi, gi).to(DEV)
        npar = sum(p.numel() for p in net.parameters())
        opt = torch.optim.AdamW(net.parameters(), lr=a.lr, weight_decay=1e-4)
        steps_per_ep = int(np.ceil(len(train) / a.bs))
        sch = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=a.lr, total_steps=n_ep * steps_per_ep, pct_start=0.1)
        best, best_state, hist = float('inf'), None, []
        t0 = time.time()
        if DEV.type == 'cuda':
            torch.cuda.reset_peak_memory_stats()
        ep_done = 0
        for ep in range(n_ep):
            net.train()
            perm = rng.permutation(train)
            tl = np.zeros(3)
            for b0 in range(0, len(perm), a.bs):
                js = perm[b0:b0 + a.bs]
                idx, bidx, nbr = batch(js)
                out = net(tF[idx], tG[js], bidx, len(js), tX[idx], nbr)
                ls, lc, lr = lossf(out, idx)
                loss = (ls + lc + lr) / len(js)
                opt.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(net.parameters(), 5.0)
                opt.step()
                sch.step()
                tl += np.array([ls.item(), lc.item(), lr.item()])
            net.eval()
            vl = np.zeros(3)
            with torch.no_grad():
                for b0 in range(0, len(val), a.bs):
                    js = val[b0:b0 + a.bs]
                    idx, bidx, nbr = batch(js)
                    out = net(tF[idx], tG[js], bidx, len(js), tX[idx], nbr)
                    vl += np.array([x.item() for x in lossf(out, idx)])
            vl /= len(val)
            tl /= len(train)
            hist.append([ep, *tl.tolist(), *vl.tolist()])
            if vl.sum() < best:
                best = vl.sum()
                best_state = {k: v.detach().clone() for k, v in net.state_dict().items()}
                best_ep = ep
            ep_done = ep + 1
            if ep % 10 == 0 or ep == n_ep - 1:
                print(f'{name} ep{ep} train {tl.round(4).tolist()} val {vl.round(4).tolist()} {time.time() - t0:.0f}s',
                      flush=True)
            if (time.time() - t0) / 60 > a.max_minutes:
                print(f'{name}: time cap after epoch {ep}', flush=True)
                break
        train_s = time.time() - t0
        net.load_state_dict(best_state)
        net.eval()
        # ---- predict test jobs
        ps, pc, pr, tm = [], [], [], []
        t1 = time.time()
        with torch.no_grad():
            for b0 in range(0, len(test), a.bs):
                js = test[b0:b0 + a.bs]
                idx, bidx, nbr = batch(js)
                out = net(tF[idx], tG[js], bidx, len(js), tX[idx], nbr)
                ps.append(torch.expm1(out[:, 0].clamp(max=12)).cpu().numpy())
                pc.append(torch.sigmoid(out[:, 1]).cpu().numpy())
                pr.append((out[:, 2:5].cpu().numpy() * rf_sd))
        inf_s = time.time() - t1
        ps, pc, pr = np.concatenate(ps), np.concatenate(pc), np.concatenate(pr)
        tidx = np.concatenate([np.arange(off[j], off[j + 1]) for j in test])
        toff = np.zeros(len(test) + 1, np.int64)
        toff[1:] = np.cumsum([off[j + 1] - off[j] for j in test])
        np.savez(FD / f'pred_{tag}_{a.split}.npz', test=test, toff=toff, slip=ps.astype(np.float32),
                 pclosed=pc.astype(np.float32), rf=pr.astype(np.float32))
        # node-level quick metrics (all test nodes, area-weighted per job)
        ys = slip[tidx]
        yc = closed[tidx]
        yr = rf[tidx]
        ww = w[tidx]
        r2 = lambda y, p, w_: float(1 - (w_ * (y - p) ** 2).sum() / (w_ * (y - (w_ * y).sum() / w_.sum()) ** 2).sum())  # noqa: E731
        rep = {'model': tag, 'seed': a.seed, 'split': a.split, 'n_params': int(npar), 'n_train_jobs': int(len(train)),
               'n_val_jobs': int(len(val)), 'n_test_jobs': int(len(test)), 'epochs_run': ep_done, 'best_epoch': best_ep,
               'train_s': train_s, 'infer_s_per_job': inf_s / len(test),
               'peak_gpu_MB': (torch.cuda.max_memory_allocated() / 2 ** 20) if DEV.type == 'cuda' else None,
               'node_r2_log1p_slip': r2(ys, np.log1p(ps), ww),
               'node_acc_closed': float((ww * ((pc > 0.5) == (yc > 0.5))).sum() / ww.sum()),
               'node_r2_rf': [r2(yr[:, i], pr[:, i], ww) for i in range(3)],
               'hist': hist}
        json.dump(rep, open(FD / f'train_{tag}_{a.split}.json', 'w'), indent=1)
        print(json.dumps({k: v for k, v in rep.items() if k != 'hist'}), flush=True)
        report[name] = rep
        del net, opt, best_state
        if DEV.type == 'cuda':
            torch.cuda.empty_cache()
    print('total', time.time() - t00, 'when', time.strftime('%Y-%m-%d %H:%M:%S'))


if __name__ == '__main__':
    main()
