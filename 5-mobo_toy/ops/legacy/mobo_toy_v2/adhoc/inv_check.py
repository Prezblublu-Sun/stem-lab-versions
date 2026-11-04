"""neck3_a81：柄侧孪生节点外移 δ 后哪些单元体积变负（只读）。也统计 6 个试算设计的最小单元体积与"外移后翻转"的单元数。"""
import json
import pathlib
import sys

import numpy as np

Q = pathlib.Path.home() / "mobo_toy_v2" / "ccx"


def tet_vol(X):
    a, b, c, d = X[:, 0], X[:, 1], X[:, 2], X[:, 3]
    return np.einsum("ij,ij->i", np.cross(b - a, c - a), d - a) / 6.0


def check(d: pathlib.Path):
    m = dict(np.load(d / "mesh3d.npz"))
    lab, X = m["node_labels"], m["nodes"].copy()
    lut = np.full(int(lab.max()) + 1, -1); lut[lab] = np.arange(len(lab))
    X1 = X.copy()
    off = m["pair_interf"] > 0
    X1[lut[m["pair_stem"][off]]] += m["pair_interf"][off, None] * m["pair_normal"][off]
    out = {}
    for r, conn in (("stem", m["stem_conn"]), ("cortex", m["cortex_conn"]), ("cancellous", m["cancellous_conn"])):
        v0 = tet_vol(X[lut[conn[:, :4]]]); v1 = tet_vol(X1[lut[conn[:, :4]]])
        # 二次单元：用 10 节点在 4 个积分点的雅可比
        bad = np.where(v1 <= 0)[0]
        out[r] = {"n": len(conn), "min_vol0": float(v0.min()), "min_vol1": float(v1.min()), "n_inverted_corner": int(len(bad)),
                  "labels_inverted": m[f"{r}_elab"][bad][:10].tolist()}
        # 中节点外移导致的扭曲：比较各积分点 detJ 的符号
        from importlib import util
        sys.path.insert(0, str(pathlib.Path.home() / "mobo_toy_v2" / "code" / "v2"))
        import ccx_port as C
        Xe = X1[lut[conn]]
        neg = np.zeros(len(conn), bool)
        for q in range(4):
            Jm = np.einsum("eai,aj->eij", Xe, C._DN[q])
            neg |= np.linalg.det(Jm) <= 0
        out[r]["n_negative_detJ_ip"] = int(neg.sum())
        out[r]["labels_negative_detJ"] = m[f"{r}_elab"][neg][:10].tolist()
        Xe0 = X[lut[conn]]
        neg0 = np.zeros(len(conn), bool)
        for q in range(4):
            neg0 |= np.linalg.det(np.einsum("eai,aj->eij", Xe0, C._DN[q])) <= 0
        out[r]["n_negative_detJ_ip_before"] = int(neg0.sum())
    return out


for sub, j in (("queue_lam1e4", "neck3_a81_cb5ce57b"), ("queue", "neck5_r7_5df27b13"), ("queue", "neck3_a40_967145a2"),
               ("queue", "neck5_r1_0730dc8f"), ("queue", "neck3_r3_915160d1"), ("queue_lam1e4", "neck1_r6_20136980")):
    d = Q / sub / j
    if (d / "mesh3d.npz").exists():
        print(j, json.dumps(check(d)))
