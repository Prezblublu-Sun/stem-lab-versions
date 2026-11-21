"""骨吸收质量分数、股骨坐标系分区、柄强度统计（在 Linux 上跑，零求解）。

对照 Naghavi 2023 博士论文第 5.2.8 节的口径，用已解的粘接模型结果重新统计：

* 公共采样网格：骨内每 HG mm 一个点，按距离场判定骨质；每个点取同一骨质里最近单元质心的值。完整股骨与植入股骨
  用同一组点，所以两套不同的网格可以逐点比较。每个点代表相同的体积 HG³，骨质内密度均匀，体积分数即质量分数。
* 逐点应变能密度比 r = S_植入 / S_完整。r < 1 − s 判为吸收，r > 1 + s 判为增生，s 为死区（论文式 5-13 至 5-16）。
* 应力屏蔽 SSI = 1 − <σ_植入> / <σ_完整>，σ 为 von Mises，<> 为区内平均（论文式 5-10 至 5-12）。
* 三套分区：
    stem    柄坐标系（本项目原有口径，shielding.zone_masks）
    femur   股骨坐标系水平带，位置由柄决定（论文图 5-9 的口径）：柄入口到柄尖的竖直范围三等分，内外侧按柄轴线分
    fixed   股骨坐标系固定带，不随设计变化：z ≥ −10、−40…−10、−70…−40、−100…−70（小转子为 0），内外侧按 x = 0 分
* 总值：7 个区按体积分数加权（论文第 237 页的口径）。
* 空白对照：完整股骨 1.4 mm 网格对 2.0 mm 网格，两者本应相同，算出的吸收 / 增生比例就是网格与映射造成的本底。
* 柄应力：柄体（截骨面以下）与假体颈（截骨面以上、头球以外）的 von Mises 最大值与体积加权 P99。
* 股骨（2026-10-23）：进程内上下文 _CTX 按 femur_id 分键（None = CT 股骨，"sawbone3406" = femur_3406）——采样网格、完整股骨
  参照（shielding.intact_job(femur_id=…)）都取同一股骨的；design_rows 的股骨按该设计 spec 的 femur_id / neck_axis 取（jobs.femur_for），
  指定的参照 iname 必须与设计同一股骨。run --femur sawbone3406 只统计 3406 的设计；默认 CT，与从前相同。

    python v2/resorption.py run [--workers 8] [--k 1] [--femur sawbone3406]
    python v2/resorption.py null
    python v2/resorption.py figs
输出：~/mobo_toy_v2/results/resorption/{zones.csv, stem.csv, null.json, summary.json, figs/*.png}
"""
from __future__ import annotations

import csv
import json
import math
import pathlib
import sys
from multiprocessing import Pool

import numpy as np
from scipy.spatial import cKDTree

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import shielding as SH  # noqa: E402
import femur_real as FR  # noqa: E402
import geom3d as G  # noqa: E402
import jobs as J  # noqa: E402
import qoi  # noqa: E402

OUT = J.RESULTS / "resorption"
HG = 1.5                                   # mm，采样网格间距
REACH = 8.0                                # mm，找最近单元质心的上限
S_LIST = (0.4, 0.6, 0.75)                  # 死区
SCHEMES = ("stem", "femur", "fixed")
ZONES = ("G1", "G2", "G3", "G4", "G5", "G6", "G7")
FIXED_Z = (-10.0, -40.0, -70.0, -100.0)    # mm，固定带的边界（模型坐标，小转子为 0）
MIN_VOL = 50.0                             # mm³
HEAD_EXCL = 1.0                            # mm，头球半径之外再留的余量
JUNC = 3.0                                 # mm，截骨面两侧各这么宽算作颈与柄体的交界
STRESS_THR = (187.5, 375.0)                # MPa，论文的疲劳极限除以 2，与疲劳极限本身
_CTX = {}


# ------------------------------------------------------------------------------------------------ 采样网格
def build_grid(fm):
    (x0, x1), (y0, y1), (z0, z1) = fm.cfg["femur"]["box_mm"]
    z0 = max(z0, fm.z_trunc)
    ax = [np.arange(a + HG / 2, b, HG) for a, b in ((x0, x1), (y0, y1), (z0, z1))]
    X, Y, Z = np.meshgrid(*ax, indexing="ij")
    P = np.c_[X.ravel(), Y.ravel(), Z.ravel()]
    P = P[fm.outer_sdf(P) <= 0]
    return P, fm.canal_sdf(P) <= 0


def to_grid(fields, P, canc, k=1):
    """每个采样点取同一骨质里最近 k 个单元的体积加权平均（k = 1 即最近单元）。"""
    out = {"sed": np.full(len(P), np.nan), "vm": np.full(len(P), np.nan)}
    for t, sel in (("cancellous", canc), ("cortex", ~canc)):
        a = fields[t]
        ok = np.isfinite(a["e"]) & np.isfinite(a["v"]) & (a["v"] > 0)
        if not ok.any() or not sel.any():
            continue
        cen, e, v = a["cen"][ok], a["e"][ok], a["v"][ok]
        vm = a["vm"][ok] if a["vm"] is not None else None
        dist, idx = cKDTree(cen).query(P[sel], k=k, distance_upper_bound=REACH)
        if k == 1:
            dist, idx = dist[:, None], idx[:, None]
        found = np.isfinite(dist)
        idx = np.where(found, idx, 0)
        w = np.where(found, v[idx], 0.0)
        ws = w.sum(1)
        good = ws > 0
        sed = np.full(len(ws), np.nan)
        sed[good] = np.where(found, e[idx], 0.0).sum(1)[good] / ws[good]
        out["sed"][sel] = sed
        if vm is not None:
            g = np.full(len(ws), np.nan)
            g[good] = (np.where(found, vm[idx], 0.0) * w).sum(1)[good] / ws[good]
            out["vm"][sel] = g
    return out


# ------------------------------------------------------------------------------------------------ 分区
def zones_femur(P, pose, Ltot, e_med):
    P0, d = pose[0], pose[1]
    z_top, z_tip = P0[2], (P0 + Ltot * d)[2]
    H = z_top - z_tip
    z = P[:, 2]
    axis = P0 + ((z - P0[2]) / d[2])[:, None] * d            # 柄轴线在同一高度上的点
    med = ((P - axis) @ e_med) >= 0
    prox = z >= z_tip + 2 * H / 3
    mid = (z >= z_tip + H / 3) & (z < z_tip + 2 * H / 3)
    dist = (z >= z_tip) & (z < z_tip + H / 3)
    tip = (z < z_tip) & (z >= z_tip - max(H / 3, 10.0))
    return {"G1": prox & ~med, "G2": mid & ~med, "G3": dist & ~med, "G4": tip, "G5": dist & med, "G6": mid & med, "G7": prox & med}


def zones_fixed(P):
    x, z = P[:, 0], P[:, 2]
    a, b, c, e = FIXED_Z
    med = x >= 0
    prox, mid, dist, tip = z >= a, (z < a) & (z >= b), (z < b) & (z >= c), (z < c) & (z >= e)
    return {"G1": prox & ~med, "G2": mid & ~med, "G3": dist & ~med, "G4": tip, "G5": dist & med, "G6": mid & med, "G7": prox & med}


def zstat(m, ga, gb):
    n = int(m.sum())
    out = {"vol": n * HG ** 3}
    if out["vol"] < MIN_VOL:
        return out
    sa, sb = ga["sed"][m], gb["sed"][m]
    r = sa / sb
    out["sed_chg_pct"] = 100.0 * (sa.mean() / sb.mean() - 1.0)
    va, vb = ga["vm"][m], gb["vm"][m]
    if np.isfinite(va).all() and np.isfinite(vb).all():
        out["ssi_pct"] = 100.0 * (1.0 - va.mean() / vb.mean())
    for s in S_LIST:
        out[f"res_{s}"] = 100.0 * float(np.mean(r < 1.0 - s))
        out[f"gain_{s}"] = 100.0 * float(np.mean(r > 1.0 + s))
    return out


def scheme_rows(base, scheme, masks, keep, canc, ga, gb):
    rows = []
    for tis, tsel in (("cortex", ~canc), ("cancellous", canc)):
        parts, union = [], np.zeros(len(keep), bool)
        for z in ZONES:
            m = masks[z] & keep & tsel
            st = zstat(m, ga, gb)
            rows.append({**base, "scheme": scheme, "zone": z, "tissue": tis, **st})
            if "sed_chg_pct" in st:
                parts.append(st)
                union |= m
        if parts:
            tot = zstat(union, ga, gb)
            vs = sum(p["vol"] for p in parts)
            if all("ssi_pct" in p for p in parts):
                tot["ssi_vw_pct"] = sum(p["vol"] / vs * p["ssi_pct"] for p in parts)      # 论文口径：按区体积分数加权
            rows.append({**base, "scheme": scheme, "zone": "total", "tissue": tis, **tot})
    return rows


# ------------------------------------------------------------------------------------------------ 逐设计
def _femur_id_of(name: str) -> str | None:
    sp = J.QROOT / name / "spec.json"
    return (json.loads(sp.read_text()) if sp.exists() else {}).get("femur_id")


def base_femur(femur_id: str | None = None, neck_axis=None):
    """未截骨的股骨对象，按 (femur_id, neck_axis) 在进程内缓存（FR.build / femur_3406.build 每次都读 npz）。CT 股骨忽略 neck_axis。"""
    c = _CTX.setdefault("fm", {})
    key = (femur_id, json.dumps(neck_axis, sort_keys=True) if femur_id else None)
    if key not in c:
        c[key] = J.femur_for({"femur_id": femur_id, "neck_axis": neck_axis})     # 无 femur_id → FR.build()，与从前相同
    return c[key]


def _ctx(femur_id: str | None = None) -> dict:
    """该股骨的采样网格与标准完整股骨参照的采样值；按 femur_id 分键，首次用到时建。"""
    c = _CTX.setdefault("grid", {})
    if femur_id not in c:
        fm = base_femur(femur_id)
        P, canc = build_grid(fm)
        it = SH.load_fields(SH.intact_job(True, femur_id))
        c[femur_id] = {"P": P, "canc": canc, "gi": to_grid(it, P, canc, _CTX.setdefault("k", 1)), "gi_by": {}}
    return c[femur_id]


def _init(k=1, femur_id=None):
    _CTX["k"] = k
    _ctx(femur_id)


def stem_parts(d: pathlib.Path, fm, pose) -> dict:
    """柄体（截骨面以下）、假体颈（截骨面以上、头球以外）的 von Mises：最大值、体积加权 P99 与 P99.9、超过阈值的体积分数、
    最大值所在位置（t = 沿颈轴到截骨面的距离，向头为正；s = 沿柄轴到入口的距离）。单元质心值。"""
    m = dict(np.load(d / "mesh3d.npz"))
    lab, X = m["node_labels"], m["nodes"]
    lut = np.full(int(lab.max()) + 1, -1)
    lut[lab] = np.arange(len(lab))
    cen = X[lut[m["stem_conn"][:, :4]]].mean(1)
    el = m["stem_elab"].astype(int)
    n = int(el.max())
    s = SH._table(qoi._csv(d / "m_bond_csv" / "LOAD_S.csv"), "mises", n)[el]
    v = SH._table(qoi._csv(d / "m_bond_csv" / "LOAD_ENER.csv"), "evol", n)[el]
    t = (cen - fm.C03) @ fm.u3
    sax = (cen - pose[0]) @ pose[1]
    below = t <= 0
    rh = float(fm.cfg["prosthesis"]["head_radius_mm"])
    far = np.linalg.norm(cen - fm.H, axis=1) > rh + HEAD_EXCL
    out = {"neck_len": float(fm.cut_from_head_mm - rh)}
    parts = (("body", below), ("body_deep", t <= -JUNC), ("junction", (t > -JUNC) & (t <= JUNC)), ("neck", ~below & far),
             ("neck_free", (t > JUNC) & far))
    for name, sel in parts:
        k = sel & np.isfinite(s) & np.isfinite(v)
        out[f"n_{name}"] = int(k.sum())
        if k.sum() < 10:
            continue
        i = int(np.argmax(np.where(k, s, -1.0)))
        out[f"vm_max_{name}"] = float(s[i])
        out[f"t_at_max_{name}"] = float(t[i])
        out[f"s_at_max_{name}"] = float(sax[i])
        out[f"vm_p99_{name}"] = float(qoi.wquantile(s[k], v[k], 0.99))
        out[f"vm_p999_{name}"] = float(qoi.wquantile(s[k], v[k], 0.999))
        for thr in STRESS_THR:
            out[f"volfrac_gt{thr:g}_{name}"] = float(v[k][s[k] > thr].sum() / v[k].sum())
    return out


def intact_grid(iname: str | None, femur_id: str | None = None):
    """指定完整股骨参照的采样值；None = 该股骨的标准参照（生产网格、标准载荷）。按股骨、作业名缓存；参照必须是同一股骨。"""
    c = _ctx(femur_id)
    if iname is None:
        return c["gi"]
    if iname not in c["gi_by"]:
        if _femur_id_of(iname) != femur_id:
            raise ValueError(f"intact reference {iname} is for femur {_femur_id_of(iname) or 'CT'}, design is for {femur_id or 'CT'}")
        c["gi_by"][iname] = to_grid(SH.load_fields(J.QROOT / iname), c["P"], c["canc"], _CTX["k"])
    return c["gi_by"][iname]


def design_rows(dname: str, iname: str | None = None):
    d = J.QROOT / dname
    spec = json.loads((d / "spec.json").read_text())
    fid = spec.get("femur_id")                                     # None = CT；股骨、网格、参照全按它取
    ctx = _ctx(fid)
    res = J.result(dname)
    prep = json.loads((d / "prep.json").read_text()) if (d / "prep.json").exists() else {}
    t = res["templating"]
    dsg = G.design_of_spec(spec)
    stem = G.Stem3D(**spec["design"])
    h = float(spec.get("h_cut", 25.0))
    fm = base_femur(fid, spec.get("neck_axis")).with_cut(h)
    pose = fm.pose(t["alpha"], t["e"])
    P, canc, gi = ctx["P"], ctx["canc"], intact_grid(iname, fid)
    ga = to_grid(SH.load_fields(d), P, canc, _CTX["k"])
    loc = SH.local(P, pose)
    keep = (fm.below_cut(P) & ~G.inside_stem(stem, t["A0"], loc) & np.isfinite(ga["sed"]) & np.isfinite(gi["sed"]) & (gi["sed"] > 0))
    base = {"job_id": dname, "femur_id": fid, "version": "pre-fix" if prep.get("code_hash") in SH.PRE_FIX else "current",
            "L": dsg["L"], "alpha": dsg["alpha"], "m": dsg["m"], "h_cut": h, "A0": t["A0"]}
    Ltot = stem.L + stem.cap_length(t["A0"])
    rows = (scheme_rows(base, "stem", SH.zone_masks(loc, stem.L), keep, canc, ga, gi)
            + scheme_rows(base, "femur", zones_femur(P, pose, Ltot, fm.e_med0), keep, canc, ga, gi)
            + scheme_rows(base, "fixed", zones_fixed(P), keep, canc, ga, gi))
    srow = {**base, "vm_p99_stored": res.get("vm_p99"), "vm_max_stored": res.get("vm_max"), **stem_parts(d, fm, pose)}
    return rows, srow


def _write(path, rows):
    cols = []
    for r in rows:
        cols += [c for c in r if c not in cols]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def run(workers=8, k=1, femur_id=None):
    OUT.mkdir(parents=True, exist_ok=True)
    names = [d.name for d in SH.design_jobs(femur_id)]
    print(f"[resorption] {len(names)} designs, femur {femur_id or 'CT'}, grid {HG} mm, k = {k}", flush=True)
    with Pool(workers, initializer=_init, initargs=(k, femur_id)) as p:
        res = p.map(design_rows, names, chunksize=4)
    rows = [r for c, _ in res for r in c]
    tag = ("" if k == 1 else f"_k{k}") + (f"_{femur_id}" if femur_id else "")
    _write(OUT / f"zones{tag}.csv", rows)
    _write(OUT / f"stem{tag}.csv", [s for _, s in res])
    print(f"[resorption] zones{tag}.csv {len(rows)} rows", flush=True)


# ------------------------------------------------------------------------------------------------ 空白对照
def null():
    """完整股骨 1.4 mm 网格对 2.0 mm 网格：同一个模型，差别只来自网格与映射。只有应变能密度，没有应力。"""
    OUT.mkdir(parents=True, exist_ok=True)
    fm = FR.build()
    P, canc = build_grid(fm)
    ref = SH.load_fields(SH.intact_job(True))
    alt = None
    for d in sorted(J.QROOT.glob("ref_intact_h1.4_*")):
        if (d / "DONE").exists() and (d / "intact_csv" / "LOAD_ENER.csv").exists():
            alt = d
    if alt is None:
        raise FileNotFoundError("no intact reference at 1.4 mm")
    out = {"alt": alt.name, "ref": SH.intact_job(True).name, "grid_mm": HG, "n_points": int(len(P)), "k": {}}
    keep0 = fm.below_cut(P)
    for k in (1, 6):
        ga, gb = to_grid(SH.load_fields(alt), P, canc, k), to_grid(ref, P, canc, k)
        keep = keep0 & np.isfinite(ga["sed"]) & np.isfinite(gb["sed"]) & (gb["sed"] > 0)
        rows = scheme_rows({}, "fixed", zones_fixed(P), keep, canc, ga, gb)
        out["k"][str(k)] = [{kk: v for kk, v in r.items() if kk != "scheme"} for r in rows]
    out["shaft_x_centre_mm"] = float(P[(P[:, 2] < -70) & (P[:, 2] > -100)][:, 0].mean())
    (OUT / "null.json").write_text(json.dumps(out, indent=1, default=float))
    for k, rows in out["k"].items():
        for r in rows:
            if r["tissue"] == "cortex":
                print(k, r["zone"], {a: round(b, 2) for a, b in r.items() if isinstance(b, float)}, flush=True)


# ------------------------------------------------------------------------------------------------ 汇总与图
def read(name):
    with open(OUT / name, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        for kk, v in r.items():
            if kk not in ("job_id", "femur_id", "version", "scheme", "zone", "tissue"):
                r[kk] = float(v) if v not in ("", "nan", "None") else math.nan
    return rows


def _q(v):
    v = np.array([x for x in v if np.isfinite(x)])
    if len(v) == 0:
        return {"n": 0}
    return {"n": int(len(v)), "median": float(np.median(v)), "q25": float(np.percentile(v, 25)), "q75": float(np.percentile(v, 75)),
            "min": float(v.min()), "max": float(v.max())}


def figs():
    import plotstyle as ps
    plt = ps.plt
    F = OUT / "figs"
    F.mkdir(parents=True, exist_ok=True)
    rows = [r for r in read("zones.csv") if r["version"] == "current"]
    keys = ["ssi_pct", "ssi_vw_pct", "sed_chg_pct"] + [f"{a}_{s}" for s in S_LIST for a in ("res", "gain")]
    summ = {"n": len({r["job_id"] for r in rows}), "grid_mm": HG, "zones": {}}
    for sc in SCHEMES:
        for tis in ("cortex", "cancellous"):
            for z in ZONES + ("total",):
                rr = [r for r in rows if r["scheme"] == sc and r["tissue"] == tis and r["zone"] == z]
                summ["zones"][f"{sc}:{tis}:{z}"] = {kk: _q([r.get(kk, math.nan) for r in rr]) for kk in keys}
    # 与原有逐单元统计（shielding/zones.csv）的一致性：柄坐标系、皮质、von Mises
    try:
        old = {(r["job_id"], r["zone"]): r["chg_vm_pct"] for r in SH.read_zones() if r["tissue"] == "cortex"}
        dif = [(-r["ssi_pct"]) - old[(r["job_id"], r["zone"])] for r in rows
               if r["scheme"] == "stem" and r["tissue"] == "cortex" and (r["job_id"], r["zone"]) in old and np.isfinite(r.get("ssi_pct", math.nan))
               and np.isfinite(old[(r["job_id"], r["zone"])])]
        summ["grid_vs_element_vm_change_pct_points"] = {"n": len(dif), "median": float(np.median(dif)),
                                                         "p05": float(np.percentile(dif, 5)), "p95": float(np.percentile(dif, 95))}
    except Exception as ex:                                     # 记录，不吞掉
        summ["grid_vs_element_error"] = repr(ex)
    st = [r for r in read("stem.csv") if r["version"] == "current"]
    skeys = sorted({kk for r in st for kk in r if kk.startswith(("vm_", "t_at", "s_at", "volfrac", "neck_len"))})
    summ["stem"] = {kk: _q([r.get(kk, math.nan) for r in st]) for kk in skeys}
    summ["stem_rows"] = [{kk: r.get(kk) for kk in ["job_id", "L", "alpha", "h_cut"] + skeys} for r in st]
    (OUT / "summary.json").write_text(json.dumps(summ, indent=1, default=float))

    def box(ax, data, labels, ylabel):
        ax.boxplot(data, showfliers=False, medianprops={"color": "black"}, widths=0.6)
        ax.set_xticks(range(1, len(labels) + 1))
        ax.set_xticklabels(labels)
        ax.set_ylabel(ylabel)
        ax.axhline(0, color="0.6", lw=0.5)

    def pick(sc, z, key, tis="cortex"):
        return [r[key] for r in rows if r["scheme"] == sc and r["tissue"] == tis and r["zone"] == z and np.isfinite(r.get(key, math.nan))]

    # R1：三套分区下的皮质应力屏蔽
    fig, axes = plt.subplots(1, 3, figsize=(7.2, 2.6), sharey=True)
    for ax, sc, tt in zip(axes, SCHEMES, ("stem frame", "femur frame, set by stem", "femur frame, fixed")):
        box(ax, [pick(sc, z, "ssi_pct") for z in ZONES], [z[1] for z in ZONES], "cortical stress shielding (%)" if sc == "stem" else "")
        ax.set_title(tt, fontsize=7)
        ax.set_xlabel("Gruen zone")
    fig.savefig(F / "R1_ssi_schemes.png", dpi=220, bbox_inches="tight")
    plt.close(fig)
    # R2：骨吸收体积分数，股骨坐标系，三个死区
    fig, axes = plt.subplots(1, 3, figsize=(7.2, 2.6), sharey=True)
    for ax, s in zip(axes, S_LIST):
        box(ax, [pick("femur", z, f"res_{s}") for z in ZONES + ("total",)], [z[1] for z in ZONES] + ["all"],
            "resorbed cortical bone (% of zone)" if s == S_LIST[0] else "")
        ax.set_title(f"dead zone s = {s}", fontsize=7)
        ax.set_xlabel("Gruen zone (femur frame)")
    fig.savefig(F / "R2_resorption_zones.png", dpi=220, bbox_inches="tight")
    plt.close(fig)
    # R3：总值对柄长
    tot = [r for r in rows if r["scheme"] == "femur" and r["tissue"] == "cortex" and r["zone"] == "total"]
    fig, axes = plt.subplots(1, 2, figsize=(6.4, 2.6))
    axes[0].scatter([r["L"] for r in tot], [r.get("ssi_vw_pct", math.nan) for r in tot], s=7, lw=0, color=ps.DORR["A"])
    axes[0].set_xlabel("stem length (mm)")
    axes[0].set_ylabel("total stress shielding, cortex (%)")
    axes[1].scatter([r["L"] for r in tot], [r.get("res_0.6", math.nan) for r in tot], s=7, lw=0, color=ps.DORR["A"])
    axes[1].set_xlabel("stem length (mm)")
    axes[1].set_ylabel("total resorbed cortical bone, s = 0.6 (%)")
    fig.savefig(F / "R3_total_vs_length.png", dpi=220, bbox_inches="tight")
    plt.close(fig)
    print("[resorption] summary.json + 3 figures", flush=True)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "null", "figs"])
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--k", type=int, default=1)
    ap.add_argument("--femur", default=None, help="femur_id（如 sawbone3406）；默认 CT 股骨")
    a = ap.parse_args()
    if a.cmd == "run":
        run(a.workers, a.k, a.femur)
    elif a.cmd == "null":
        null()
    else:
        figs()
