"""批次 A 附加（0 次 FE，Linux）：峰值载荷（LOAD2）时领面贴合部分的接触压力，按皮质 / 松质拆分。只用积分量：
    贴合     = LOAD2 时间隙 ≤ 1 µm（与 post_m1 的 OPEN_UM 相同）
    法向力   = 骨侧从节点的 CNORMF 矢量模（Abaqus 导出的节点接触力；CNAREA 已知偏大 9.5 %，不用）
    面积     = 几何从属面积 pair_area（建模时由界面三角面分得）
    平均压力 = Σ 法向力 / Σ 面积（该组织的贴合领面节点）；P95 = 节点压力 F_i / A_i 的面积加权 P95；力份额 = 该组织法向力 / 领面法向力
组织：节点挨着皮质单元 = 皮质（pair_cortex），否则 = 松质。范围：主表里现行模型（截骨面统一）的全部带领设计。
输出 ~/mobo_toy_v2/deck/collar_pressure.csv
"""
from __future__ import annotations

import csv
import json
import math
import pathlib
import sys

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "code")); sys.path.insert(0, str(HOME / "code" / "v2"))
import numpy as np  # noqa: E402

import jobs as J  # noqa: E402
import post_m1 as PM1  # noqa: E402
import qoi  # noqa: E402


def one(j: str) -> dict | None:
    d = J.QROOT / j
    f = d / "m_fric_csv" / "LOAD2_CFORCE.csv"
    if not f.exists():
        return None
    p = PM1.pairs(d)
    col = p["pair_collar"]
    if not col.any():
        return None
    pb, ps, nrm, w, di, cort = p["pair_bone"], p["pair_stem"], p["pair_normal"], p["pair_area"], p["pair_interf"], p["pair_cortex"].astype(bool)
    U = PM1._utab(d / "m_fric_csv" / "LOAD2_U.csv", p["n"])
    gap = -(di + ((U[ps] - U[pb]) * nrm).sum(1)) * 1e3
    closed = gap <= PM1.OPEN_UM
    t = qoi._csv(f)
    node = t["node"].astype(int)
    Fn = np.zeros(p["n"] + 1)
    k = (t["field"] == "CNORMF") & (node <= p["n"])
    np.add.at(Fn, node[k], np.linalg.norm(np.c_[t["f1"], t["f2"], t["f3"]][k], axis=1))
    fn = Fn[pb]
    out = {"job_id": j, "collar_area_mm2": float(w[col].sum()), "collar_closed_frac": float(w[col & closed].sum() / w[col].sum()),
           "collar_normal_force_N": float(fn[col].sum()), "collar_normal_force_open_N": float(fn[col & ~closed].sum())}
    tot = fn[col & closed].sum()
    for name, sel in (("cortex", cort), ("cancellous", ~cort)):
        m = col & closed & sel
        A, F = float(w[m].sum()), float(fn[m].sum())
        out[f"{name}_closed_area_mm2"] = A
        out[f"{name}_area_frac_of_collar"] = float(w[col & sel].sum() / w[col].sum())
        out[f"{name}_mean_p_MPa"] = F / A if A > 0 else math.nan
        out[f"{name}_p95_MPa"] = float(qoi.wquantile(fn[m] / w[m], w[m], 0.95)) if m.any() else math.nan
        out[f"{name}_force_share"] = F / tot if tot > 0 else math.nan
    out["all_mean_p_MPa"] = float(tot / w[col & closed].sum()) if (col & closed).any() else math.nan
    return out


if __name__ == "__main__":
    rows = list(csv.DictReader(open(HOME / "deck" / "master_table.csv")))
    sel = [r["job_id"] for r in rows if r["model"] == "m1" and r["cut_plane"] == "unified" and r["collar_w"] not in ("", "0", "0.0")
           and float(r["collar_w"] or 0) > 0]
    sel += [r["job_id"] for r in rows if r["stage"] == "collar" and r["collar_w"] not in ("",) and float(r["collar_w"] or 0) > 0]
    out = []
    for j in sel:
        try:
            r = one(j)
        except Exception as e:                                              # noqa: BLE001
            print(j, "ERR", type(e).__name__, str(e)[:120], flush=True)
            continue
        if r:
            out.append(r)
    keys = list(out[0])
    with open(HOME / "deck" / "collar_pressure.csv", "w", newline="") as fh:
        wr = csv.DictWriter(fh, keys); wr.writeheader(); wr.writerows(out)
    a = np.array([[r["cortex_mean_p_MPa"], r["cancellous_mean_p_MPa"], r["cortex_force_share"], r["collar_closed_frac"]] for r in out])
    print(f"{len(out)} collared designs; medians: cortex mean p {np.nanmedian(a[:, 0]):.1f} MPa, cancellous mean p {np.nanmedian(a[:, 1]):.1f} MPa, "
          f"cortex force share {np.nanmedian(a[:, 2]):.2f}, collar closed {np.nanmedian(a[:, 3]):.2f}")
