"""候选池里截骨深度的覆盖（只读）：可行候选在各截骨深度区间的比例（均匀撒点时每区间应约占 1/7）。"""
import json
import pathlib

import numpy as np

P = pathlib.Path.home() / "mobo_toy_v2" / "results" / "pools"
for f in sorted(P.glob("neckopt_p[135]_*.json")):
    meta = json.loads(f.read_text())
    sp = meta.get("space", {})
    if "h_cut" not in sp:
        continue
    if not f.with_suffix(".npz").exists():
        continue
    z = np.load(f.with_suffix(".npz"))
    U = z["U"]
    j = list(sp).index("h_cut")
    lo, hi = sp["h_cut"]
    h = lo + U[:, j] * (hi - lo)
    cnt = np.histogram(h, [25, 26, 27, 28, 29, 30, 31, 32.01])[0]
    print(f.name, f"feasible {meta.get('feasible')}/{meta.get('n')}", "per mm bin:", cnt.tolist(), "share", np.round(cnt / cnt.sum(), 3).tolist())
