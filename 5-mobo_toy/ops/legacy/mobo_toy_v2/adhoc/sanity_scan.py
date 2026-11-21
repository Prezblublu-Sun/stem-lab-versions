"""优化阶段 p1/p2/p3/p5/p6 全部设计（362）的物理合理性扫描（只读）：分位数 + 越界计数 + 例子。"""
import json
import pathlib

import numpy as np

B = pathlib.Path.home() / "mobo_toy_v2"
rows = []
for k in (1, 2, 3, 5, 6):
    st = json.loads((B / "results" / f"neckopt_p{k}.json").read_text())
    for r in st["records"]:
        p = B / "queue" / r["job_id"] / "result.json"
        if p.exists():
            x = json.loads(p.read_text())
            x["_phase"] = k
            x["_front"] = bool(r.get("front")) if "front" in r else None
            rows.append(x)
print("designs", len(rows))


def col(k):
    return np.array([np.nan if r.get(k) is None else float(r[k]) for r in rows])


def q(k, s=1.0):
    v = col(k) * s
    v = v[np.isfinite(v)]
    return [round(float(x), 3) for x in np.percentile(v, [0, 5, 50, 95, 100])] if len(v) else None


for k in ("f1_p95_um", "f1_all_p95_um", "f1_closed_p95_um", "f1_first_p95_um", "collar_slip_rev_p95_um", "cpress_release_p50",
          "cpress_release_p95", "cpress_release_max", "open_frac_release", "open_frac_load2", "gap_p95_release_um",
          "collar_open_frac_load2", "collar_gap_p95_load2_um", "collar_force_share_load2", "collar_force_N_load2",
          "contact_force_total_N_load2", "status_frac_stick", "status_frac_slip", "stick_cslip_p95_um", "f2_g7_loss_pct",
          "f2_g1_loss_pct", "vm_p99", "vm_max", "area_frac_gt40", "normal_rev_p95_um"):
    print(f"{k:28} min/p5/p50/p95/max", q(k))

f1 = col("f1_p95_um")
print("\nbody micromotion below the 1 µm floor (M1 verification):", int((f1 < 1).sum()), "; below 2 µm:", int((f1 < 2).sum()), "of", len(f1))
cw = np.array([float((r.get("spec") or {}).get("design", {}).get("collar_w", 0) or 0) for r in rows])
sh = col("collar_force_share_load2")
ca = col("collar_area")
print("collarless (collar_w < 0.3):", int((cw < 0.3).sum()), "; their 'collar' share p50/max:",
      np.round(np.nanpercentile(sh[cw < 0.3], [50, 100]), 3).tolist() if (cw < 0.3).any() else None,
      "; 'collar' area p50:", round(float(np.nanmedian(ca[cw < 0.3])), 1) if (cw < 0.3).any() else None,
      "vs collared area p50:", round(float(np.nanmedian(ca[cw >= 0.3])), 1))
# 领面平均接触压力（加载峰值）：领力 / 闭合的领面积
cf, co = col("collar_force_N_load2"), col("collar_open_frac_load2")
pc = cf / (ca * (1 - co))
print("collar mean contact pressure on the closed part at LOAD2 (MPa) min/p5/p50/p95/max:",
      [round(float(x), 2) for x in np.nanpercentile(pc[np.isfinite(pc)], [0, 5, 50, 95, 100])])
tot = col("contact_force_total_N_load2")
print("total contact force at LOAD2 (N; applied joint load 2391 N plus press-fit pairs) p5/p50/p95:",
      [round(float(x)) for x in np.nanpercentile(tot, [5, 50, 95])])
cm = col("cpress_release_max")
print("designs with nodal CPRESS max > 200 MPa after press-fit (cortical crush ~150-200):", int((cm > 200).sum()),
      "; > 1000 MPa:", int((cm > 1000).sum()))
g7 = col("f2_g7_loss_pct")
print("mixed-tissue G7 SED change |x| > 50 %:", int((np.abs(g7) > 50).sum()), "; min", round(float(np.nanmin(g7)), 1))
orl = col("open_frac_release")
print("open after press-fit > 10 % of body interface:", int((orl > 0.10).sum()))
# 例：微动最低的 10 个设计
idx = np.argsort(f1)[:10]
print("\nlowest body micromotion designs:")
for i in idx:
    r = rows[i]
    d = (r.get("spec") or {}).get("design", {})
    print(f"  p{r['_phase']} {r['job_id']:24} f1 {f1[i]:.2f} all {r.get('f1_all_p95_um', 0):.1f} stick {r.get('status_frac_stick', 0):.2f} "
          f"L {d.get('L', 0):.1f} α {d.get('alpha', 0):.1f} m {d.get('m', 0):.2f} collar {d.get('collar_w', 0):.2f}")
