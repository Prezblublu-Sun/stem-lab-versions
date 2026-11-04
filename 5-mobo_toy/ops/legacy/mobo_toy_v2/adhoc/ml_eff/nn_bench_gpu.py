"""ml_eff / nn (c): cost of a full-mesh MeshGraphNet and a voxel 3D U-Net on the RTX 5060 Ti (no training, timing only).

* MeshGraphNet-style encode-process-decode (edge + node MLPs with residual + LayerNorm, sum aggregation) on the REAL
  tet mesh of one collarless job (mesh3d.npz read-only): graph = C3D10 sub-edges (corner-midside, bidirectional) and,
  for comparison, the full element clique (all 45 node pairs per C3D10).
* 3D U-Net (4 levels, base 16/32 channels, GroupNorm, SiLU) on the voxel box of that job (stem box + 10 mm) at 1.0 mm
  and 0.5 mm (sizes from audit/mesh_audit.json).
Forward + backward + Adam step, fp32 and bf16 autocast; peak memory and time per step. The process is capped at
50 % of the card (8 GB); an OOM is recorded, not fatal.
Output: deck/ml_eff/nn/bench/bench_gpu.json
"""
from __future__ import annotations

import json
import pathlib
import time

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as Fn

HOME = pathlib.Path.home() / 'mobo_toy_v2'
OUT = HOME / 'deck' / 'ml_eff' / 'nn' / 'bench'
JOB = 'neck10_a0_2074bc29'
DEV = torch.device('cuda')


def mlp(a, h, b, ln=True):
    L = [nn.Linear(a, h), nn.SiLU(), nn.Linear(h, b)]
    if ln:
        L.append(nn.LayerNorm(b))
    return nn.Sequential(*L)


class MGN(nn.Module):
    def __init__(self, fin, ein, H=128, L=15, out=9):
        super().__init__()
        self.ne, self.ee = mlp(fin, H, H), mlp(ein, H, H)
        self.em = nn.ModuleList([mlp(3 * H, H, H) for _ in range(L)])
        self.nm = nn.ModuleList([mlp(2 * H, H, H) for _ in range(L)])
        self.dec = mlp(H, H, out, ln=False)

    def forward(self, x, ea, src, dst):
        h, e = self.ne(x), self.ee(ea)
        for em, nm in zip(self.em, self.nm):
            e = e + em(torch.cat([e, h[src], h[dst]], 1))
            agg = torch.zeros_like(h).index_add_(0, dst, e.to(h.dtype))
            h = h + nm(torch.cat([h, agg], 1))
        return self.dec(h)


class Block(nn.Module):
    def __init__(self, a, b):
        super().__init__()
        self.c1, self.c2 = nn.Conv3d(a, b, 3, padding=1), nn.Conv3d(b, b, 3, padding=1)
        self.n1, self.n2 = nn.GroupNorm(8, b), nn.GroupNorm(8, b)

    def forward(self, x):
        return Fn.silu(self.n2(self.c2(Fn.silu(self.n1(self.c1(x))))))


class UNet3D(nn.Module):
    def __init__(self, cin=5, cout=9, base=16, levels=4):
        super().__init__()
        ch = [base * 2 ** i for i in range(levels)]
        self.down = nn.ModuleList()
        a = cin
        for c in ch:
            self.down.append(Block(a, c))
            a = c
        self.up = nn.ModuleList()
        self.upc = nn.ModuleList()
        for c in reversed(ch[:-1]):
            self.upc.append(nn.ConvTranspose3d(a, c, 2, stride=2))
            self.up.append(Block(2 * c, c))
            a = c
        self.head = nn.Conv3d(a, cout, 1)

    def forward(self, x):
        skips = []
        for i, d in enumerate(self.down):
            x = d(x)
            if i < len(self.down) - 1:
                skips.append(x)
                x = Fn.max_pool3d(x, 2)
        for upc, up in zip(self.upc, self.up):
            x = upc(x)
            x = up(torch.cat([x, skips.pop()], 1))
        return self.head(x)


def timed(step, n=5):
    torch.cuda.synchronize()
    torch.cuda.reset_peak_memory_stats()
    step()
    torch.cuda.synchronize()
    t0 = time.time()
    for _ in range(n):
        step()
    torch.cuda.synchronize()
    return (time.time() - t0) / n, torch.cuda.max_memory_allocated() / 2 ** 20


def run_case(name, make, inputs_fn, amp):
    torch.cuda.empty_cache()
    net = opt = None
    try:
        net = make().to(DEV)
        opt = torch.optim.Adam(net.parameters(), 1e-4)
        args, tgt = inputs_fn()

        def step():
            opt.zero_grad(set_to_none=True)
            with torch.autocast('cuda', dtype=torch.bfloat16, enabled=amp):
                out = net(*args)
            loss = ((out.float() - tgt) ** 2).mean()
            loss.backward()
            opt.step()
        dt, mem = timed(step)
        r = {'case': name, 'amp_bf16': amp, 's_per_step': dt, 'peak_MB': mem,
             'n_params': int(sum(p.numel() for p in net.parameters()))}
    except torch.cuda.OutOfMemoryError as e:
        r = {'case': name, 'amp_bf16': amp, 'oom': str(e)[:200]}
    print(json.dumps(r), flush=True)
    del net, opt
    import gc
    gc.collect()
    torch.cuda.empty_cache()
    return r


def main():
    torch.cuda.set_per_process_memory_fraction(0.5, 0)
    OUT.mkdir(parents=True, exist_ok=True)
    m = np.load(HOME / 'queue' / JOB / 'mesh3d.npz')
    nodes = m['nodes']
    lab = m['node_labels']
    lut = np.full(int(lab.max()) + 1, -1, np.int64)
    lut[lab] = np.arange(len(lab))
    conn = np.concatenate([m[k] for k in ('cortex_conn', 'cancellous_conn', 'stem_conn')])
    conn = lut[conn]
    sub = [(0, 4), (4, 1), (1, 5), (5, 2), (2, 6), (6, 0), (0, 7), (7, 3), (1, 8), (8, 3), (2, 9), (9, 3)]
    e = np.unique(np.sort(np.concatenate([conn[:, [a, b]] for a, b in sub]), 1), axis=0)
    ii, jj = np.triu_indices(10, 1)
    e2 = np.unique(np.sort(np.stack([conn[:, ii].ravel(), conn[:, jj].ravel()], 1), 1), axis=0)
    N = len(nodes)
    info = {'job': JOB, 'n_nodes': int(N), 'n_tet10': int(len(conn)), 'n_undirected_subedges': int(len(e)),
            'n_undirected_clique_edges': int(len(e2))}
    print(json.dumps(info), flush=True)
    X = torch.as_tensor(nodes, dtype=torch.float32, device=DEV)
    res = []

    def graph(E, reps):
        s = np.concatenate([E[:, 0], E[:, 1]])
        d = np.concatenate([E[:, 1], E[:, 0]])
        S = np.concatenate([s + r * N for r in range(reps)])
        D = np.concatenate([d + r * N for r in range(reps)])
        src = torch.as_tensor(S, device=DEV)
        dst = torch.as_tensor(D, device=DEV)
        x = torch.randn(N * reps, 12, device=DEV)
        Xr = X.repeat(reps, 1)
        dx = Xr[dst] - Xr[src]
        ea = torch.cat([dx, dx.norm(dim=1, keepdim=True)], 1)
        tgt = torch.randn(N * reps, 9, device=DEV)
        return (x, ea, src, dst), tgt

    for gname, E in (('subedges', e), ('clique', e2)):
        for H, L in ((128, 15), (64, 8)):
            for reps in (1, 4):
                for amp in (False, True):
                    if gname == 'clique' and (reps == 4 and H == 128):
                        continue
                    r = run_case(f'MGN_{gname}_H{H}_L{L}_graphs{reps}', lambda H=H, L=L: MGN(12, 4, H, L),
                                 lambda E=E, reps=reps: graph(E, reps), amp)
                    r.update(graph=gname, H=H, L=L, graphs_per_batch=reps, nodes=N * reps,
                             directed_edges=2 * len(E) * reps)
                    res.append(r)
    for h, shape in ((1.0, (84, 48, 92)), (0.5, (168, 96, 183))):
        pad = [int(np.ceil(s / 16) * 16) for s in shape]
        for base in (16, 32):
            for bs in ((1, 4) if h == 1.0 else (1, 2)):
                r = run_case(f'UNet3D_h{h}_base{base}_bs{bs}', lambda base=base: UNet3D(5, 9, base),
                             lambda pad=pad, bs=bs: ((torch.randn(bs, 5, *pad, device=DEV),),
                                                     torch.randn(bs, 9, *pad, device=DEV)), True)
                r.update(h_mm=h, grid=pad, base=base, batch=bs)
                res.append(r)
    json.dump({'info': info, 'cases': res, 'gpu': torch.cuda.get_device_name(0), 'torch': torch.__version__,
               'when': time.strftime('%Y-%m-%d %H:%M:%S')}, open(OUT / 'bench_gpu.json', 'w'), indent=1)
    print('done when', time.strftime('%Y-%m-%d %H:%M:%S'))


if __name__ == '__main__':
    main()
