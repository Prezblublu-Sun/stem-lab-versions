"""新的外移（单元内线性）是否消除积分点翻转：6 个试算设计（只读）。"""
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path.home() / "mobo_toy_v2" / "code" / "v2"))
import ccx_port as C  # noqa: E402

Q = pathlib.Path.home() / "mobo_toy_v2" / "ccx"
for sub, j in (("queue_lam1e4", "neck3_a81_cb5ce57b"), ("queue", "neck5_r7_5df27b13"), ("queue", "neck3_a40_967145a2"),
               ("queue", "neck5_r1_0730dc8f"), ("queue", "neck3_r3_915160d1"), ("queue_lam1e4", "neck1_r6_20136980")):
    m = dict(np.load(Q / sub / j / "mesh3d.npz"))
    X = {int(a): b.copy() for a, b in zip(m["node_labels"], m["nodes"])}
    off = C.stem_offsets(m)
    for n, v in off.items():
        X[n] = X[n] + v
    bad = C.negative_detj(X, m["stem_conn"])
    mag = np.linalg.norm(np.array(list(off.values())), axis=1)
    print(j, "moved", len(off), "max offset µm", round(float(mag.max()) * 1e3, 2), "negative detJ elements", len(bad))
