"""M1 后处理（在 Linux 上跑）：界面节点对的相对位移 → 微动；接触场 → 压配质量；粘接模型 → SED 与柄应力（只报告）。

微动定义
* 每个界面节点对（骨侧节点 i、柄侧孪生节点 i'）的相对位移 r = u_stem − u_bone，分解为法向（沿柄外法向 n）与切向。
* f1（主）= 第二次加载循环的可恢复切向相对位移 |r_t(LOAD2) − r_t(UNLOAD)|，面积加权 P95（µm）。张开的节点同样计入。
* f1_first = 首次加载的切向相对位移 |r_t(LOAD) − r_t(RELEASE)|（含首次就位），与旧定义可比。
* 间隙 g = −(δ_i + r·n)：> 1 µm 记为张开；δ_i 为该节点施加的过盈（皮质相邻节点为 0）。
* f1_cslip = 旧定义（CSLIP 增量，只在接触时累积），留作对照。
* 带领的柄（2026-10-02）：上面各量只统计柄身（不含领节点），与无领设计可比；领另报 collar_* ：
  领面滑移、张开（掀起）比例、法向分离，以及领在加载峰值时承担的接触力占柄传给骨的总接触力的比例。
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import post as P  # noqa: E402
import qoi  # noqa: E402
from spot3d import qoi3d  # noqa: E402

OPEN_UM = 1.0
STEPS = ("RELEASE", "LOAD", "UNLOAD", "LOAD2")


def _utab(path: pathlib.Path, n: int) -> np.ndarray:
    t = qoi._csv(path)
    a = np.full((n + 1, 3), np.nan)
    k = t["node"].astype(int)
    ok = k <= n
    a[k[ok]] = np.c_[t["u1"], t["u2"], t["u3"]][ok]
    return a


def _ctab(path: pathlib.Path, n: int) -> dict:
    t = qoi._csv(path)
    out = {}
    node = t["node"].astype(int)
    for f in np.unique(t["field"]):
        k = (t["field"] == f) & (node <= n)
        a = np.full(n + 1, np.nan)
        a[node[k]] = t["value"][k]
        out[str(f)] = a
    return out


def _wq(x, w, q):
    ok = np.isfinite(x)
    return qoi.wquantile(x[ok], w[ok], q) if ok.any() else float("nan")


def pairs(d: pathlib.Path) -> dict:
    m = dict(np.load(d / "mesh3d.npz"))
    out = {k: m[k] for k in ("pair_bone", "pair_stem", "pair_normal", "pair_area", "pair_interf", "pair_cortex")} | \
          {"n": int(m["node_labels"].max()), "nodes": m["nodes"], "node_labels": m["node_labels"]}
    out["pair_collar"] = m["pair_collar"].astype(bool) if "pair_collar" in m else np.zeros(len(m["pair_bone"]), bool)
    return out


def micromotion(d: pathlib.Path, job: str) -> dict:
    p = pairs(d)
    col = p["pair_collar"]
    pb, ps, nrm, w, di, cort = p["pair_bone"], p["pair_stem"], p["pair_normal"], p["pair_area"], p["pair_interf"], p["pair_cortex"]
    U = {s: _utab(d / f"{job}_csv" / f"{s}_U.csv", p["n"]) for s in STEPS}
    rel = {s: U[s][ps] - U[s][pb] for s in STEPS}
    if not all(np.isfinite(rel[s]).all() for s in STEPS):
        raise ValueError("missing displacement for some interface node pairs")

    def tang(v):
        return v - (v * nrm).sum(1)[:, None] * nrm
    first_all = np.linalg.norm(tang(rel["LOAD"] - rel["RELEASE"]), axis=1) * 1e3
    rev_all = np.linalg.norm(tang(rel["LOAD2"] - rel["UNLOAD"]), axis=1) * 1e3
    gap_all = {s: -(di + (rel[s] * nrm).sum(1)) * 1e3 for s in STEPS}
    extra = {}
    if col.any():
        wc = w[col]
        extra = {"collar_area": float(wc.sum()), "collar_n_pairs": int(col.sum()),
                 "collar_slip_rev_p95_um": _wq(rev_all[col], wc, 0.95), "collar_slip_first_p95_um": _wq(first_all[col], wc, 0.95),
                 "collar_open_frac_load2": float(wc[gap_all["LOAD2"][col] > OPEN_UM].sum() / wc.sum()),
                 "collar_open_frac_unload": float(wc[gap_all["UNLOAD"][col] > OPEN_UM].sum() / wc.sum()),
                 "collar_gap_p95_load2_um": _wq(gap_all["LOAD2"][col], wc, 0.95),
                 "f1_all_p95_um": _wq(rev_all, w, 0.95), "f1_first_all_p95_um": _wq(first_all, w, 0.95)}
    b = ~col                                             # 以下各量只统计柄身
    first, rev, w, cort, nrm = first_all[b], rev_all[b], w[b], cort[b], nrm[b]
    nrev = np.abs(((rel["LOAD2"] - rel["UNLOAD"])[b] * nrm).sum(1)) * 1e3
    gap = {s: v[b] for s, v in gap_all.items()}
    pb = pb[b]
    W = w.sum()
    out = {"f1_p95_um": _wq(rev, w, 0.95), "f1_rev_p50_um": _wq(rev, w, 0.50), "f1_rev_max_um": float(rev.max()),
           "f1_first_p95_um": _wq(first, w, 0.95), "f1_first_p50_um": _wq(first, w, 0.50),
           "normal_rev_p95_um": _wq(nrev, w, 0.95),
           "area_frac_gt40": float(w[rev > 40].sum() / W), "area_frac_gt150": float(w[rev > 150].sum() / W),
           "open_frac_release": float(w[gap["RELEASE"] > OPEN_UM].sum() / W),
           "open_frac_load": float(w[gap["LOAD"] > OPEN_UM].sum() / W),
           "open_frac_load2": float(w[gap["LOAD2"] > OPEN_UM].sum() / W),
           "gap_p95_release_um": _wq(gap["RELEASE"], w, 0.95), "gap_p95_load2_um": _wq(gap["LOAD2"], w, 0.95),
           "n_pairs": int(len(pb)), "interface_area": float(W), "cortex_area_frac": float(w[cort].sum() / W)}
    closed = gap["LOAD2"] <= OPEN_UM
    if closed.any():
        out["f1_closed_p95_um"] = _wq(rev[closed], w[closed], 0.95)
    if (~cort).any():
        out["f1_canc_p95_um"] = _wq(rev[~cort], w[~cort], 0.95)
    out.update(extra)
    return out


def _ftab(path: pathlib.Path, n: int):
    """<STEP>_CFORCE.csv → 节点接触力（CNORMF + CSHEARF，作用在骨侧从节点上）。"""
    F = np.zeros((n + 1, 3))
    t = qoi._csv(path)
    node = t["node"].astype(int)
    k = np.isin(t["field"], ["CNORMF", "CSHEARF"]) & (node <= n)
    np.add.at(F, node[k], np.c_[t["f1"], t["f2"], t["f3"]][k])
    return F


def collar_load(d: pathlib.Path, job: str) -> dict:
    """领承担的接触力：加载峰值时领面节点的接触合力在"柄传给骨的接触合力"方向上的分量占比。"""
    p = pairs(d)
    col = p["pair_collar"]
    if not col.any():
        return {}
    out = {}
    for s in ("LOAD", "LOAD2"):
        f = d / f"{job}_csv" / f"{s}_CFORCE.csv"
        if not f.exists():
            continue
        F = _ftab(f, p["n"])[p["pair_bone"]]
        tot, fc = F.sum(0), F[col].sum(0)
        nt = float(np.linalg.norm(tot))
        out[f"collar_force_share_{s.lower()}"] = float(fc @ tot / (nt * nt)) if nt > 0 else float("nan")
        out[f"collar_force_N_{s.lower()}"] = float(np.linalg.norm(fc))
        out[f"contact_force_total_N_{s.lower()}"] = nt
    return out


def contact_stats(d: pathlib.Path, job: str) -> dict:
    p = pairs(d)
    b = ~p["pair_collar"]                                  # 只统计柄身
    pb, w = p["pair_bone"][b], p["pair_area"][b]
    C = {s: _ctab(d / f"{job}_csv" / f"{s}_CONTACT.csv", p["n"]) for s in ("RELEASE", "UNLOAD", "LOAD2")}
    cp = C["RELEASE"]["CPRESS"][pb]
    ok = np.isfinite(cp) & (cp > 0)
    out = {"cpress_release_p50": _wq(cp[ok], w[ok], 0.5), "cpress_release_p95": _wq(cp[ok], w[ok], 0.95),
           "cpress_release_max": float(np.nanmax(cp)) if np.isfinite(cp).any() else float("nan"),
           "cpress_release_mean_all": float(np.nansum(np.where(np.isfinite(cp), cp, 0.0) * w) / w.sum())}
    st = C["LOAD2"]["CSTATUS"][pb]
    s1 = C["LOAD2"]["CSLIP1"][pb] - C["UNLOAD"]["CSLIP1"][pb]
    s2 = C["LOAD2"].get("CSLIP2", np.zeros(p["n"] + 1))[pb] - C["UNLOAD"].get("CSLIP2", np.zeros(p["n"] + 1))[pb]
    sl = np.hypot(s1, s2) * 1e3
    stick, slide = st > 1.5, (st > 0.5) & (st <= 1.5)                 # 导出值：2 = 粘着，1 = 滑动，其余 = 张开
    W = w.sum()
    out.update({"status_frac_stick": float(w[stick].sum() / W), "status_frac_slip": float(w[slide].sum() / W),
                "status_frac_open": float(w[~(stick | slide)].sum() / W),
                "stick_cslip_p95_um": _wq(sl[stick], w[stick], 0.95) if stick.any() else float("nan"),
                "stick_cslip_max_um": float(np.nanmax(sl[stick])) if stick.any() else float("nan"),
                "slide_cslip_p95_um": _wq(sl[slide], w[slide], 0.95) if slide.any() else float("nan")})
    return out


def evaluate(d: pathlib.Path, name: str, fm, intact: dict) -> dict:
    mm = micromotion(d, f"{name}_fric")
    cs = contact_stats(d, f"{name}_fric")
    cs.update(collar_load(d, f"{name}_fric"))
    old = qoi3d.micromotion(d, f"{name}_fric")
    zs = P.zone_sed(d, f"{name}_bond", fm)
    vm = P.stem_vm(d, f"{name}_bond", fm)
    return {**mm, **cs, **vm, "f1_cslip_p95_um": old["f1_p95_um"], "frac_open": old["frac_open"],
            "sed_gruen7": zs["gruen7"], "sed_gruen1": zs["gruen1"],
            "f2_g7_loss_pct": 100.0 * (1.0 - zs["gruen7"] / intact["gruen7"]),
            "f2_g1_loss_pct": 100.0 * (1.0 - zs["gruen1"] / intact["gruen1"]), "model": "m1"}


def lame(d: pathlib.Path) -> dict:
    info = json.loads((d / "model3d.json").read_text())
    p = pairs(d)
    pb, ps, nrm, w, di = p["pair_bone"], p["pair_stem"], p["pair_normal"], p["pair_area"], p["pair_interf"]
    lut = np.full(p["n"] + 1, -1)
    lut[p["node_labels"]] = np.arange(len(p["node_labels"]))
    z = p["nodes"][lut[pb], 2]
    C = _ctab(d / "lame_fric_csv" / "PRESSFIT_CONTACT.csv", p["n"])
    U = _utab(d / "lame_fric_csv" / "PRESSFIT_U.csv", p["n"])
    cp = C["CPRESS"][pb]
    cp0 = np.where(np.isfinite(cp), cp, 0.0)
    mid = (z >= 0.2 * info["L"]) & (z <= 0.8 * info["L"])
    rel_n = ((U[ps] - U[pb]) * nrm).sum(1)
    gap = -(di + rel_n) * 1e3
    pl = info["p_lame_MPa"]
    pm = float((cp0[mid] * w[mid]).sum() / w[mid].sum())
    # 由套筒外表面的径向膨胀反推压力（平面应力 Lamé）：积分量，不依赖节点 CPRESS 的面积归属
    X, lab = p["nodes"], p["node_labels"]
    rad = np.hypot(X[:, 0], X[:, 1])
    outer = (rad > info["R"] - 0.12) & (X[:, 2] >= 0.2 * info["L"]) & (X[:, 2] <= 0.8 * info["L"])
    ur = (U[lab[outer], 0] * X[outer, 0] + U[lab[outer], 1] * X[outer, 1]) / rad[outer]
    r_, R_ = info["r"], info["R"]
    p_inf = float(np.nanmean(ur) * info["E_h"] * (R_ * R_ - r_ * r_) / (2 * r_ * r_ * R_))
    ub = (U[pb] * nrm).sum(1)
    return {"model": "m1-lame", "p_lame_MPa": pl, "p_fe_mean_mid_MPa": pm, "p_fe_median_mid_MPa": float(np.median(cp0[mid])),
            "p_fe_mean_all_MPa": float((cp0 * w).sum() / w.sum()), "p_fe_min_mid": float(cp0[mid].min()),
            "p_fe_max_mid": float(cp0[mid].max()), "err_cpress_pct": 100.0 * (pm / pl - 1.0), "p_inferred_MPa": p_inf, "err_pct": 100.0 * (p_inf / pl - 1.0),
            "bone_normal_disp_mean_um": float(np.mean(ub[mid]) * 1e3), "bone_normal_disp_sd_um": float(np.std(ub[mid]) * 1e3),
            "open_frac": float(w[gap > OPEN_UM].sum() / w.sum()), "rel_normal_mean_um": float((rel_n * w).sum() / w.sum() * 1e3),
            "interface_area_mm2": float(w.sum()), "interface_area_exact_mm2": info["interface_area_exact_mm2"],
            "n_pairs": int(len(pb)), "settings": {k: info[k] for k in ("h", "delta", "mu", "slip_tol", "lagrange", "interference")}}
