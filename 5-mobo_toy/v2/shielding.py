"""应力屏蔽分析（在 Linux 上跑）：植入后骨内应力 / 应变能密度相对完整股骨的变化。数据全部来自粘接模型（TIE），
与界面压配、摩擦无关；除 1 个带应力导出的完整股骨参照外不新增 FE。

    python v2/shielding.py intact     提交带应力导出的完整股骨参照（生产网格）并等待
    python v2/shielding.py zones      每个已解设计 × 分区 × 骨质：SED 与 von Mises 相对完整股骨同一区域的变化 → zones.csv
    python v2/shielding.py maps       选定设计的颈平面切片三联图：完整 / 植入 / 变化
    python v2/shielding.py stats      统计图与汇总表
    python v2/shielding.py all        zones + maps + stats
输出：~/mobo_toy_v2/results/shielding/{zones.csv, summary.json, figs/*.png, maps/*.png}

分区（Gruen 分区按柄自身坐标定义，短柄也适用）：沿柄轴三等分（s < L/3 近、L/3–2L/3 中、2L/3–L 远），柄轴外侧为 1–3 区、
内侧为 7–5 区，尖端以下 max(L/3, 10 mm) 为 4 区；全部限于截骨面以下。另算 calcar_fixed：现行约束用的固定区
（模型坐标 x ≥ 0、z ≥ −10 mm、截骨面以下）。
完整股骨的对应值取同一几何区域，但去掉被截掉（截骨面以上）和被锉掉（柄体内）的骨，只比较两个模型里都存在的骨。
变化量 = (植入 − 完整) / 完整 × 100%：负 = 应力遮挡（低于完整股骨），正 = 过载。
"""
from __future__ import annotations

import csv
import json
import math
import pathlib
import sys
from multiprocessing import Pool

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import psv2  # noqa: E402,F401
import plotstyle as ps  # noqa: E402
import femur_real as FR  # noqa: E402
import geom3d as G  # noqa: E402
import jobs as J  # noqa: E402
import qoi  # noqa: E402
import stage_v2a as S  # noqa: E402

plt = ps.plt
OUT = J.RESULTS / "shielding"
PRE_FIX = {"af2719da27", "3edd9887e5"}          # 假体颈起点修正之前的代码哈希（61 个参考设计 + 验证作业）
TISSUES = ("cortex", "cancellous")
ZONES = ("G1", "G2", "G3", "G4", "G5", "G6", "G7")
MIN_VOL = 50.0                                  # mm³，区域体积小于此不统计
_CTX = {}


# ------------------------------------------------------------------------------------------------ 读数据
def _table(tab, col, n):
    a = np.full(n + 1, np.nan)
    el = tab["elem"].astype(int)
    k = el <= n
    a[el[k]] = tab[col][k]
    return a


def load_fields(d: pathlib.Path) -> dict:
    m = dict(np.load(d / "mesh3d.npz"))
    lab, X = m["node_labels"], m["nodes"]
    lut = np.full(int(lab.max()) + 1, -1)
    lut[lab] = np.arange(len(lab))
    job = "intact" if (d / "intact_csv").exists() else "m_bond"
    n = max(int(m[f"{r}_elab"].max()) for r in TISSUES)
    en = qoi._csv(d / f"{job}_csv" / "LOAD_ENER.csv")
    E, V = _table(en, "else", n), _table(en, "evol", n)
    sp = d / f"{job}_csv" / "LOAD_S.csv"
    VM = _table(qoi._csv(sp), "mises", n) if sp.exists() else None
    out = {}
    for r in TISSUES:
        el = m[f"{r}_elab"].astype(int)
        cen = X[lut[m[f"{r}_conn"][:, :4]]].mean(1)
        out[r] = {"cen": cen, "e": E[el], "v": V[el], "vm": VM[el] if VM is not None else None}
    return out


def intact_job(need_s: bool = True) -> pathlib.Path:
    cands = []
    for d in J.QROOT.glob(f"ref_intact_h{S.H_PROD:g}_*"):
        if not (d / "DONE").exists():
            continue
        sp = json.loads((d / "spec.json").read_text())
        if sp.get("E_canc") is not None:
            continue
        has_s = (d / "intact_csv" / "LOAD_S.csv").exists()
        if need_s and not has_s:
            continue
        cands.append((d.stat().st_mtime, d))
    if not cands:
        raise FileNotFoundError("no DONE intact reference" + (" with LOAD_S.csv — run `shielding.py intact` first" if need_s else ""))
    return max(cands)[1]


def submit_intact() -> str:
    jid = J.submit({"kind": "intact", "h_int": S.H_PROD, "stage": "ref", "tag": f"intact_h{S.H_PROD:g}_S", "export": "S"})
    res = S.wait_for([jid], timeout_h=2.0, poll=20.0)
    d = J.QROOT / jid
    print(jid, J.state(d), "LOAD_S:", (d / "intact_csv" / "LOAD_S.csv").exists(), json.dumps(S._brief(res[jid])))
    return jid


def design_jobs() -> list[pathlib.Path]:
    out, seen = [], set()
    for d in sorted(J.QROOT.glob("*")):
        sp = d / "spec.json"
        if not sp.exists() or not (d / "DONE").exists():
            continue
        spec = json.loads(sp.read_text())
        if spec.get("kind") != "design" or spec.get("h_int") != S.H_PROD:
            continue
        if (spec.get("delta") is not None or spec.get("mu") is not None or spec.get("torque", True) is False
                or spec.get("E_canc") is not None or spec.get("rep") is not None):
            continue
        key = json.dumps({**G.design_of_spec(spec), "h_cut": float(spec.get("h_cut", 25.0))}, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out


# ------------------------------------------------------------------------------------------------ 分区统计
def local(P, pose):
    P0, d, e_ml, e_ap = pose
    Q = P - P0
    return np.c_[Q @ d, Q @ e_ml, Q @ e_ap]


def zone_masks(loc, L):
    s, x = loc[:, 0], loc[:, 1]
    prox, mid, dist = s < L / 3, (s >= L / 3) & (s < 2 * L / 3), (s >= 2 * L / 3) & (s <= L)
    tip = (s > L) & (s <= L + max(L / 3, 10.0))
    lat, med = x < 0, x >= 0
    return {"G1": prox & lat, "G2": mid & lat, "G3": dist & lat, "G4": tip, "G5": dist & med, "G6": mid & med, "G7": prox & med}


def _agg(a, m):
    v = a["v"][m]
    vol = float(np.nansum(v))
    if vol < MIN_VOL:
        return vol, math.nan, math.nan
    sed = float(np.nansum(a["e"][m]) / vol)
    vm = float(np.nansum(a["vm"][m] * v) / vol) if a["vm"] is not None else math.nan
    return vol, sed, vm


def _chg(a, b):
    return 100.0 * (a / b - 1.0) if (b and np.isfinite(a) and np.isfinite(b) and b > 0) else math.nan


def _init():
    _CTX["fm"] = FR.build()
    _CTX["intact"] = load_fields(intact_job(True))


def design_rows(dname: str) -> list[dict]:
    if "fm" not in _CTX:
        _init()
    d = J.QROOT / dname
    spec = json.loads((d / "spec.json").read_text())
    res = J.result(dname)
    prep = json.loads((d / "prep.json").read_text()) if (d / "prep.json").exists() else {}
    t = res["templating"]
    dsg = G.design_of_spec(spec)
    stem = G.Stem3D(**spec["design"])
    h = float(spec.get("h_cut", 25.0))
    fm = _CTX["fm"].with_cut(h)
    pose = fm.pose(t["alpha"], t["e"])
    f, it = load_fields(d), _CTX["intact"]
    base = {"job_id": dname, "stage": spec.get("stage"), "code": prep.get("code_hash"),
            "version": "pre-fix" if prep.get("code_hash") in PRE_FIX else "current",
            "L": dsg["L"], "alpha": dsg["alpha"], "m": dsg["m"], "h_cut": h, "A0": t["A0"], "rho_tip": dsg["rho_tip"], "q": dsg["q"],
            "f1_um": res["f1_p95_um"], "f2_loss_pct": res["f2_g7_loss_pct"], "vm_stem_p99": res["vm_p99"]}
    rows, acc = [], {}
    for tis in TISSUES:
        a, b = f[tis], it[tis]
        la, lb = local(a["cen"], pose), local(b["cen"], pose)
        keep_b = fm.below_cut(b["cen"]) & ~G.inside_stem(stem, t["A0"], lb)
        za, zb = zone_masks(la, stem.L), zone_masks(lb, stem.L)
        za["calcar_fixed"] = (a["cen"][:, 0] >= 0) & (a["cen"][:, 2] >= -10.0)
        zb["calcar_fixed"] = (b["cen"][:, 0] >= 0) & (b["cen"][:, 2] >= -10.0)
        for z in ZONES + ("calcar_fixed",):
            ma, mb = za[z], zb[z] & keep_b
            va, sa, ma_vm = _agg(a, ma)
            vb, sb, mb_vm = _agg(b, mb)
            rows.append({**base, "zone": z, "tissue": tis, "vol_impl": va, "vol_intact": vb, "sed_impl": sa, "sed_intact": sb,
                         "chg_sed_pct": _chg(sa, sb), "vm_impl": ma_vm, "vm_intact": mb_vm, "chg_vm_pct": _chg(ma_vm, mb_vm)})
            acc.setdefault(z, []).append((float(np.nansum(a["e"][ma])), va, float(np.nansum(b["e"][mb])), vb))
    for z, parts in acc.items():                       # 皮质 + 松质混合（现行约束的口径）
        ea, va, eb, vb = (sum(p[k] for p in parts) for k in range(4))
        sa, sb = (ea / va if va >= MIN_VOL else math.nan), (eb / vb if vb >= MIN_VOL else math.nan)
        rows.append({**base, "zone": z, "tissue": "mixed", "vol_impl": va, "vol_intact": vb, "sed_impl": sa, "sed_intact": sb,
                     "chg_sed_pct": _chg(sa, sb), "vm_impl": math.nan, "vm_intact": math.nan, "chg_vm_pct": math.nan})
    return rows


def zones(workers: int = 8) -> list[dict]:
    OUT.mkdir(parents=True, exist_ok=True)
    names = [d.name for d in design_jobs()]
    print(f"[shielding] {len(names)} designs; intact reference {intact_job(True).name}", flush=True)
    with Pool(workers, initializer=_init) as p:
        chunks = p.map(design_rows, names, chunksize=4)
    rows = [r for c in chunks for r in c]
    cols = list(rows[0])
    with open(OUT / "zones.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"[shielding] zones.csv: {len(rows)} rows", flush=True)
    return rows


def read_zones() -> list[dict]:
    with open(OUT / "zones.csv", newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        for k, v in r.items():
            if k not in ("job_id", "stage", "code", "version", "zone", "tissue"):
                r[k] = float(v) if v not in ("", "nan") else math.nan
    return rows


def pick(rows, zone, tissue, version="current"):
    return [r for r in rows if r["zone"] == zone and r["tissue"] == tissue and (version is None or r["version"] == version)]


# ------------------------------------------------------------------------------------------------ 切片图
def plane_grid(fields, fm, key, keep_fn, step=1.0, slab=3.0, reach=6.0):
    """颈平面上的规则网格；每个网格点按距离场判定骨质（髓腔内 = 松质，否则皮质），只在同一骨质的单元质心里找最近者，
    这样两套不同网格在皮质—松质交界处不会互相取错骨质。"""
    from scipy.spatial import cKDTree
    C, e1, e2 = _CTX["fm"].neck_plane()
    n = np.cross(e1, e2)
    u, v = np.arange(-55.0, 45.0 + step, step), np.arange(-120.0, 35.0 + step, step)
    U, V = np.meshgrid(u, v)
    UV = np.c_[U.ravel(), V.ravel()]
    P = C + U.reshape(-1, 1) * e1 + V.reshape(-1, 1) * e2
    in_bone = fm.outer_sdf(P) <= 0
    is_canc = fm.canal_sdf(P) <= 0
    g = np.full(U.size, np.nan)
    for t, sel in (("cancellous", in_bone & is_canc), ("cortex", in_bone & ~is_canc)):
        a = fields[t]
        Q = a["cen"] - C
        k = np.abs(Q @ n) < slab
        if not k.any() or not sel.any():
            continue
        val = (a["e"][k] / a["v"][k]) if key == "sed" else a[key][k]
        dist, idx = cKDTree(np.c_[Q[k] @ e1, Q[k] @ e2]).query(UV[sel], distance_upper_bound=reach)
        ok = np.isfinite(dist)
        tmp = np.full(int(sel.sum()), np.nan)
        tmp[ok] = val[idx[ok]]
        g[sel] = tmp
    g[~(in_bone & keep_fn(P))] = np.nan
    return U, V, g.reshape(U.shape), P


def map_figure(dname: str, rows, path: pathlib.Path) -> dict:
    from matplotlib.colors import LogNorm
    if "fm" not in _CTX:
        _init()
    d = J.QROOT / dname
    spec = json.loads((d / "spec.json").read_text())
    res = J.result(dname)
    t = res["templating"]
    stem = G.Stem3D(**spec["design"])
    fm = _CTX["fm"].with_cut(float(spec.get("h_cut", 25.0)))
    pose = fm.pose(t["alpha"], t["e"])

    def kept(P):
        return fm.below_cut(P) & ~G.inside_stem(stem, t["A0"], local(P, pose))
    U, V, gi, P = plane_grid(_CTX["intact"], fm, "vm", lambda P: np.ones(len(P), bool))
    _, _, gk, _ = plane_grid(_CTX["intact"], fm, "vm", kept)
    _, _, gd, _ = plane_grid(load_fields(d), fm, "vm", kept)
    chg = 100.0 * (gd / gk - 1.0)
    in_stem = (G.inside_stem(stem, t["A0"], local(P, pose)) & fm.below_cut(P) & (fm.outer_sdf(P) <= 0)).reshape(U.shape)
    fig, axes = ps.new_figure("double", 95, 1, 3)
    norm = LogNorm(0.3, 60.0)
    for ax, g, ttl in ((axes[0], gi, "intact femur"), (axes[1], gd, "implanted (bonded)")):
        im = ax.pcolormesh(U, V, g, norm=norm, cmap="viridis", shading="nearest", rasterized=True)
        ax.set_title(ttl, fontsize=7)
    fig.colorbar(im, ax=axes[:2], shrink=0.75, pad=0.02).set_label("von Mises stress (MPa)", fontsize=6)
    im2 = axes[2].pcolormesh(U, V, np.clip(chg, -100, 100), vmin=-100, vmax=100, cmap="RdBu_r", shading="nearest", rasterized=True)
    axes[2].set_title("change vs intact", fontsize=7)
    fig.colorbar(im2, ax=axes[2], shrink=0.75, pad=0.02).set_label("change (%): blue = shielded, red = overloaded", fontsize=6)
    for ax in axes[1:]:
        ax.contourf(U, V, np.where(in_stem, 1.0, np.nan), levels=[0.5, 1.5], colors=[ps.LIGHT])
    for ax in axes:
        ax.set_aspect("equal")
        ax.set_xlabel("medial → (mm)")
        ax.set_xlim(-55, 45)
        ax.set_ylim(-120, 35)
    axes[0].set_ylabel("along shaft axis, proximal ↑ (mm)")
    mine = {(r["zone"], r["tissue"]): r for r in rows if r["job_id"] == dname}
    g7, g1 = mine[("G7", "cortex")], mine[("G1", "cortex")]
    dsg = G.design_of_spec(spec)
    fig.suptitle(f"L {dsg['L']:.0f} mm, α {dsg['alpha']:.0f}°, margin {dsg['m']:+.2f} mm, cut {spec.get('h_cut', 25.0):.0f} mm: "
                 f"cortical von Mises {g7['chg_vm_pct']:+.0f}% in zone 7 (calcar), {g1['chg_vm_pct']:+.0f}% in zone 1", fontsize=7.5)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=220)
    plt.close(fig)
    return {"job_id": dname, "L": dsg["L"], "alpha": dsg["alpha"], "m": dsg["m"], "h_cut": float(spec.get("h_cut", 25.0)),
            "A0": t["A0"], "g7_cortex_vm": g7["chg_vm_pct"], "g7_cortex_sed": g7["chg_sed_pct"],
            "g1_cortex_vm": g1["chg_vm_pct"], "file": path.name}


def select_for_maps(rows) -> list[tuple[str, str]]:
    g7 = [r for r in pick(rows, "G7", "cortex") if np.isfinite(r["chg_vm_pct"])]
    g7s = sorted(g7, key=lambda r: r["chg_vm_pct"])
    out = [("most shielded calcar cortex", g7s[0]["job_id"]), ("median", g7s[len(g7s) // 2]["job_id"]),
           ("most overloaded calcar cortex", g7s[-1]["job_id"]),
           ("shortest stem", min(g7, key=lambda r: r["L"])["job_id"]), ("longest stem", max(g7, key=lambda r: r["L"])["job_id"])]
    ro = [r for r in g7 if r["job_id"].startswith("bo_qnehvi_s1_r0_62bbf792")]
    if ro:
        out.append(("former read-out design", ro[0]["job_id"]))
    seen, uniq = set(), []
    for lab, j in out:
        if j not in seen:
            seen.add(j)
            uniq.append((lab, j))
    return uniq


def maps(rows) -> list[dict]:
    out = []
    for k, (lab, j) in enumerate(select_for_maps(rows), 1):
        info = map_figure(j, rows, OUT / "maps" / f"map_{k}_{j}.png")
        info["why"] = lab
        out.append(info)
        print(f"[shielding] map {k}: {lab} {j}", flush=True)
    return out


# ------------------------------------------------------------------------------------------------ 统计
def _q(v):
    v = np.array([x for x in v if np.isfinite(x)])
    if len(v) == 0:
        return {"n": 0}
    return {"n": int(len(v)), "median": float(np.median(v)), "q25": float(np.percentile(v, 25)), "q75": float(np.percentile(v, 75)),
            "min": float(v.min()), "max": float(v.max()),
            "shield_gt30": float(np.mean(v < -30)), "shield_gt50": float(np.mean(v < -50)), "shield_gt75": float(np.mean(v < -75)),
            "over_gt30": float(np.mean(v > 30)), "over_gt50": float(np.mean(v > 50)), "over_gt75": float(np.mean(v > 75))}


def stats(rows) -> dict:
    figs = OUT / "figs"
    figs.mkdir(parents=True, exist_ok=True)
    summ = {"n_designs": {v: len({r["job_id"] for r in rows if r["version"] == v}) for v in ("current", "pre-fix")}, "zones": {}}
    for tis in TISSUES:
        for z in ZONES + ("calcar_fixed",):
            rr = pick(rows, z, tis)
            summ["zones"][f"{z}:{tis}"] = {"vm": _q([r["chg_vm_pct"] for r in rr]), "sed": _q([r["chg_sed_pct"] for r in rr])}
    summ["zones"]["calcar_fixed:mixed"] = {"sed": _q([r["chg_sed_pct"] for r in pick(rows, "calcar_fixed", "mixed")])}

    # S1：各区分布（皮质；von Mises 与 SED）
    fig, axes = ps.new_figure("double", 70, 1, 2)
    for ax, key, lab in ((axes[0], "chg_vm_pct", "cortical von Mises, change vs intact (%)"),
                         (axes[1], "chg_sed_pct", "cortical strain-energy density, change vs intact (%)")):
        data = [[r[key] for r in pick(rows, z, "cortex") if np.isfinite(r[key])] for z in ZONES]
        ax.boxplot(data, showfliers=True, flierprops={"markersize": 2, "marker": "."},
                   medianprops={"color": "black"}, widths=0.6)
        ax.set_xticks(range(1, len(ZONES) + 1))
        ax.set_xticklabels([z[1:] for z in ZONES])
        ax.axhline(0, color="black", lw=0.5)
        for y in (-30, 30):
            ax.axhline(y, color=ps.GREY, lw=0.5, ls="--")
        ax.set_xlabel("Gruen zone (stem frame)")
        ax.set_ylabel(lab)
        ax.set_ylim(-100, min(400, max(60, np.nanpercentile(np.concatenate([np.array(d) for d in data if d]), 99.5) * 1.1)))
    fig.savefig(figs / "S1_zones_box.png", dpi=220)
    plt.close(fig)

    # S2：股骨距皮质的变化对长度、插入角、肩部面积
    g7 = [r for r in pick(rows, "G7", "cortex") if np.isfinite(r["chg_sed_pct"])]
    fig, axes = ps.new_figure("double", 62, 1, 3, sharey=True)
    al = np.array([r["alpha"] for r in g7])
    for ax, k, lab in ((axes[0], "L", "stem length L (mm)"), (axes[1], "alpha", "insertion angle α (°)"), (axes[2], "A0", "shoulder area A0 (mm²)")):
        sc = ax.scatter([r[k] for r in g7], [r["chg_vm_pct"] for r in g7], c=al, s=8, cmap="viridis", lw=0)
        ax.axhline(0, color="black", lw=0.5)
        ax.set_xlabel(lab)
    axes[0].set_ylabel("zone 7 cortical von Mises, change vs intact (%)")
    fig.colorbar(sc, ax=axes, shrink=0.8, pad=0.02).set_label("insertion angle α (°)", fontsize=6)
    fig.savefig(figs / "S2_calcar_vs_design.png", dpi=220)
    plt.close(fig)

    # S3：现行约束的量（固定区、皮质 + 松质混合 SED）对皮质口径
    mix = {r["job_id"]: -r["f2_loss_pct"] for r in pick(rows, "calcar_fixed", "cortex")}     # 优化器实际用的量（存档 f2，换成变化量的符号）
    cor = {r["job_id"]: r for r in pick(rows, "calcar_fixed", "cortex")}
    can = {r["job_id"]: r["chg_sed_pct"] for r in pick(rows, "calcar_fixed", "cancellous")}
    ids = [j for j in mix if j in cor and np.isfinite(mix[j]) and np.isfinite(cor[j]["chg_sed_pct"])]
    fig, axes = ps.new_figure("double", 66, 1, 2)
    axes[0].scatter([mix[j] for j in ids], [cor[j]["chg_sed_pct"] for j in ids], s=8, color=ps.DORR["A"], lw=0, label="cortex only")
    axes[0].scatter([mix[j] for j in ids], [can.get(j, np.nan) for j in ids], s=8, color=ps.DORR["C"], lw=0, marker="^", label="cancellous only")
    lim = [-100, max(100.0, float(np.nanpercentile([mix[j] for j in ids], 99)))]
    axes[0].plot(lim, lim, color="black", lw=0.5, ls="--")
    for v in (-30, 30):
        axes[0].axvline(v, color=ps.GREY, lw=0.5, ls="--")
        axes[0].axhline(v, color=ps.GREY, lw=0.5, ls="--")
    axes[0].set_xlabel("current constraint quantity: mixed-tissue SED change (%)")
    axes[0].set_ylabel("same zone, single tissue: SED change (%)")
    axes[0].set_xlim(lim)
    axes[0].set_ylim(-100, max(150.0, float(np.nanpercentile([can.get(j, np.nan) for j in ids], 97))))
    axes[0].legend(fontsize=6)
    shares = [cor[j]["vol_impl"] for j in ids]
    esh = []
    for j in ids:
        rc = cor[j]
        rn = next(r for r in pick(rows, "calcar_fixed", "cancellous") if r["job_id"] == j)
        ec, en_ = rc["sed_impl"] * rc["vol_impl"], rn["sed_impl"] * rn["vol_impl"]
        esh.append(100.0 * en_ / (ec + en_))
    axes[1].hist(esh, bins=24, color=ps.DORR["C"])
    axes[1].set_xlabel("share of the zone's strain energy stored in cancellous bone (%)")
    axes[1].set_ylabel("designs")
    fig.savefig(figs / "S3_measure_comparison.png", dpi=220)
    plt.close(fig)
    summ["measure"] = {"n": len(ids), "cancellous_energy_share_median_pct": float(np.median(esh)),
                       "cortex_volume_median_mm3": float(np.median(shares)),
                       "violate30_mixed": int(sum(abs(mix[j]) > 30 for j in ids)),
                       "violate30_cortex_abs": int(sum(abs(cor[j]["chg_sed_pct"]) > 30 for j in ids)),
                       "shield30_cortex": int(sum(cor[j]["chg_sed_pct"] < -30 for j in ids)),
                       "over30_cortex": int(sum(cor[j]["chg_sed_pct"] > 30 for j in ids)),
                       "shield30_mixed": int(sum(mix[j] < -30 for j in ids)), "over30_mixed": int(sum(mix[j] > 30 for j in ids)),
                       "sign_disagree": int(sum((mix[j] > 0) != (cor[j]["chg_sed_pct"] > 0) for j in ids))}
    (OUT / "summary.json").write_text(json.dumps(summ, indent=1, default=float))
    print(json.dumps({"n_designs": summ["n_designs"], "measure": summ["measure"]}, indent=1, default=float), flush=True)
    return summ


def check_f2(n: int = 8) -> list:
    """用旧口径（固定区、皮质 + 松质混合、完整股骨参照含后来被锉掉的骨）重算 SED 下降率，应与存档的 f2 一致。"""
    _init()
    fm0, it = _CTX["fm"], _CTX["intact"]
    jobs_ = design_jobs()
    out = []
    for d in jobs_[::max(1, len(jobs_) // n)][:n]:
        spec = json.loads((d / "spec.json").read_text())
        res = J.result(d.name)
        fm = fm0.with_cut(float(spec.get("h_cut", 25.0)))
        f = load_fields(d)
        ea = va = eb = vb = 0.0
        for tis in TISSUES:
            a, b = f[tis], it[tis]
            ma = (a["cen"][:, 0] >= 0) & (a["cen"][:, 2] >= -10.0) & fm.below_cut(a["cen"])
            mb = (b["cen"][:, 0] >= 0) & (b["cen"][:, 2] >= -10.0) & fm.below_cut(b["cen"])
            ea += float(np.nansum(a["e"][ma])); va += float(np.nansum(a["v"][ma]))
            eb += float(np.nansum(b["e"][mb])); vb += float(np.nansum(b["v"][mb]))
        loss = 100.0 * (1.0 - (ea / va) / (eb / vb))
        out.append((d.name, round(loss, 4), round(res["f2_g7_loss_pct"], 4)))
        print(d.name, "recomputed", round(loss, 4), "stored", round(res["f2_g7_loss_pct"], 4), flush=True)
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["intact", "zones", "maps", "stats", "all", "check"])
    a = ap.parse_args()
    if a.cmd == "intact":
        submit_intact()
    elif a.cmd == "check":
        check_f2()
    else:
        rows = zones() if a.cmd in ("zones", "all") else read_zones()
        if a.cmd in ("zones", "all"):
            rows = read_zones()
        if a.cmd in ("maps", "all"):
            _init()
            info = maps(rows)
            (OUT / "maps.json").write_text(json.dumps(info, indent=1, default=float))
        if a.cmd in ("stats", "all"):
            stats(rows)
