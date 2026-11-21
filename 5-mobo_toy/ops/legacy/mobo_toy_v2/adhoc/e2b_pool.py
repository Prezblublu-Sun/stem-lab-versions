"""E2b 去骨侧（Linux，0 次 FE）：阶段 8 候选池里全部可行设计（Sobol 均匀采样 14 维设计空间，按 wrap_fit 选号后可行的 10158 个）
逐个重新模板化，记录 号 A0、入口偏移 e、柄体积（= 锉腔）、截骨体积、形状因子 = 柄体积 / (A0 · L)，以及池里存的去骨量作核对。
输出 ~/mobo_toy_v2/deck/E2b/pool_templated.csv。
    ~/mobo_toy_v2/run.sh e2b_pool.py [--workers 4] [--n 0=全部]
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import math
import os
import pathlib
import sys
import time
from multiprocessing import Pool

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "code")); sys.path.insert(0, str(HOME / "code" / "v2"))
import numpy as np  # noqa: E402

OUT = HOME / "deck" / "E2b"
_C: dict = {}


def one(args):
    i, u = args
    import collar_rule as CR
    import femur_real as FR
    import geom3d as G
    import stage_neckopt as N
    import stage_v2a as S
    if "ph" not in _C:
        _C["ph"] = N.Phase(8, None, "abs")
        _C["fm"] = FR.build()
    ph = _C["ph"]
    d, h = ph.design_of(np.asarray(u, float))
    if h not in _C:
        _C[h] = _C["fm"].with_cut(h)
    fm = _C[h]
    st = G.Stem3D(**d)
    r = CR.template_wrap_fit(st, fm, min_A0=S.MIN_A0)
    row = {"pool_idx": i, **{k: d.get(k) for k in ph.vars if k != "h_cut"}, "h_cut": h, "has_collar": bool(d.get("collar_w", 0) > 0)}
    if not r.get("fit") or r["A0"] < S.MIN_A0:
        row.update(fit=False, reason=(r.get("reason") or "")[:120])
        return row
    vol = float(r["volume"])
    res = float(fm.resected_volume())
    row.update(fit=True, A0=float(r["A0"]), A0_cortex_rule=float(r.get("A0_cortex_rule", r["A0"])), e=float(r["e"]), stem_volume_mm3=vol,
               resected_mm3=res, bone_removed_mm3=vol + res, shape_factor=vol / (float(r["A0"]) * float(d["L"])),
               templ_contact_frac=float(r.get("contact", math.nan)), w_eq_mm=float(r.get("w_eq", math.nan)))
    return row


if __name__ == "__main__":
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--n", type=int, default=0)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    f = sorted(glob.glob(str(HOME / "results" / "pools" / "neckopt_p8_n16384_s0_*.npz")))[-1]
    z = np.load(f)
    U, loss = z["U"], z["loss"]
    idx = np.arange(len(U)) if a.n <= 0 else np.random.default_rng(0).choice(len(U), a.n, replace=False)
    print(f"E2b: pool {pathlib.Path(f).name}, {len(U)} feasible, templating {len(idx)} with {a.workers} workers", flush=True)
    t0 = time.time()
    rows = []
    with Pool(a.workers) as pool:
        for k, r in enumerate(pool.imap_unordered(one, [(int(i), U[i]) for i in idx], chunksize=16), 1):
            r["pool_loss_mm3"] = float(loss[r["pool_idx"]])
            rows.append(r)
            if k % 1000 == 0 or k == len(idx):
                print(f"  {k}/{len(idx)}  {time.time() - t0:.0f} s", flush=True)
    rows.sort(key=lambda r: r["pool_idx"])
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(OUT / "pool_templated.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, keys); w.writeheader()
        for r in rows:
            w.writerow({k: ("" if v is None or (isinstance(v, float) and not math.isfinite(v)) else v) for k, v in r.items()})
    ok = [r for r in rows if r.get("fit")]
    dev = [abs(r["bone_removed_mm3"] - r["pool_loss_mm3"]) for r in ok]
    (OUT / "pool_meta.json").write_text(json.dumps({"pool_file": pathlib.Path(f).name, "n_pool_feasible": int(len(U)), "n_templated": len(rows), "n_fit": len(ok),
                                                   "max_abs_dev_vs_pool_loss_mm3": max(dev) if dev else None, "space": json.load(open(f[:-4] + ".json"))["space"],
                                                   "seconds": time.time() - t0}, indent=1))
    print(f"wrote {len(rows)} rows ({len(ok)} fit); max |bone_removed − pool loss| = {max(dev) if dev else float('nan'):.3f} mm³; {time.time() - t0:.0f} s", flush=True)
