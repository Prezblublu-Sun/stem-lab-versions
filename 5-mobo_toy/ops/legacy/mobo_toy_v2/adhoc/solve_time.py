"""摩擦模型求解时间与模型规模、几何、接触状态的关系（只读；颈部柄各阶段的已解作业）。"""
import json
import pathlib

import numpy as np
from scipy.stats import spearmanr

Q = pathlib.Path.home() / "mobo_toy_v2" / "queue"
rows = []
for d in Q.iterdir():
    if not d.name.startswith(("neck1_", "neck2_", "neck3_", "neck5_")) or not (d / "DONE").exists():
        continue
    try:
        r = json.loads((d / "result.json").read_text())
        p = json.loads((d / "prep.json").read_text())
        s = json.loads((d / "spec.json").read_text())
    except Exception:  # noqa: BLE001
        continue
    w = (r.get("solve") or {}).get("m_fric", {}).get("wall_s")
    if not w:
        continue
    nt = p["n_tet"]
    rows.append({"wall_min": w / 60, "n_tet": sum(nt.values()) if isinstance(nt, dict) else nt, "n_pairs": p.get("n_pairs"),
                 "iface_mm2": p.get("interface_area_mm2"), "L": s["design"]["L"], "A0": p.get("A0"), "collar": s["design"].get("collar_w", 0.0),
                 "f1_um": r.get("f1_all_p95_um"), "slip": r.get("status_frac_slip"), "open": r.get("open_frac_load2"),
                 "stage": d.name[:5]})
print("n", len(rows))
W = np.array([r["wall_min"] for r in rows])
print(f"wall time: median {np.median(W):.1f} min, P10 {np.percentile(W, 10):.1f}, P90 {np.percentile(W, 90):.1f}, max {W.max():.1f}")
for k in ("n_tet", "n_pairs", "iface_mm2", "L", "A0", "collar", "f1_um", "slip", "open"):
    x = np.array([r[k] if r[k] is not None else np.nan for r in rows], float)
    m = np.isfinite(x)
    print(f"  {k:10} Spearman with wall time {spearmanr(x[m], W[m]).correlation:+.2f}   range {np.nanmin(x):.3g}–{np.nanmax(x):.3g}")
# 按柄长分组
for lo, hi in ((20, 30), (30, 40), (40, 50), (50, 60.1)):
    m = np.array([lo <= r["L"] < hi for r in rows])
    if m.any():
        print(f"  L {lo}-{hi:.0f}: n {m.sum():3}  wall median {np.median(W[m]):5.1f} min  n_pairs median {np.median([r['n_pairs'] for r, k in zip(rows, m) if k]):.0f}  "
              f"n_tet median {np.median([r['n_tet'] for r, k in zip(rows, m) if k]):.0f}")
# 线性回归：log(wall) ~ log(n_pairs) + slip
X = np.c_[np.ones(len(rows)), np.log([r["n_pairs"] for r in rows]), [r["slip"] or 0 for r in rows], [r["open"] or 0 for r in rows]]
b, *_ = np.linalg.lstsq(X, np.log(W), rcond=None)
pred = X @ b
print("log(wall) = %.2f + %.2f log(n_pairs) + %.2f slip_frac + %.2f open_frac;  R2 %.2f" % (*b, 1 - np.sum((np.log(W) - pred) ** 2) / np.sum((np.log(W) - np.log(W).mean()) ** 2)))
