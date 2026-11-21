"""V3 报告（短柄、少截骨）：稳定性 vs 骨量损失的前沿、前沿设计在长度/截骨高度/皮质余量上的位置、"能短到哪"的读数。

    python v2/report_v3.py            → v2/reports/V3_short_stem/{figures,tables,acceptance.json}
数据：队列里全部已解设计（stage_v3.dataset：旧数据映射到 9 维，h_cut = 25）+ results/v3_bo_s*.json。
"""
from __future__ import annotations

import json
import math
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import psv2  # noqa: E402,F401
import plotstyle as ps  # noqa: E402
import geom3d as G  # noqa: E402
import jobs as J  # noqa: E402
import stage_v3 as V3  # noqa: E402

plt = ps.plt
ACOL = ps.DORR["A"]
THRESH = (40.0, 150.0)                    # µm：骨长入 / 纤维包裹的常用阈值（Pilliar 1986 等），只作读数线


def _phys(x):
    return {k: V3.SPACE[k][0] + float(v) * (V3.SPACE[k][1] - V3.SPACE[k][0]) for k, v in zip(V3.VARS9, x)}


def collect():
    """全部已解设计 → 行：9 个物理变量、f1、|ΔSED|、vM、骨量损失（拆分）、约束、来源、轮次。"""
    import mobo
    rows = []
    seen = set()
    for d in sorted(J.QROOT.glob("*")):
        sp = d / "spec.json"
        if not sp.exists() or not (d / "DONE").exists():
            continue
        spec = json.loads(sp.read_text())
        if spec.get("kind") != "design" or spec.get("h_int") != V3.S.H_PROD:
            continue
        if (spec.get("delta") is not None or spec.get("mu") is not None or spec.get("torque", True) is False
                or spec.get("E_canc") is not None):
            continue
        dsg = G.design_of_spec(spec)
        h = float(spec.get("h_cut", 25.0))
        key = json.dumps({**dsg, "h_cut": h}, sort_keys=True)
        if key in seen:
            continue
        r = J.result(d.name)
        y, c, ok = V3.objectives(r)
        if not ok:
            continue
        seen.add(key)
        bl = r.get("bone_loss") or {}
        rows.append({"job_id": d.name, "source": "v3" if spec.get("stage") == "v3" else "legacy",
                     "round": int(spec.get("tag", "s0_r0").split("_r")[-1]) if spec.get("stage") == "v3" else 0,
                     "seed": int(spec.get("tag", "s0_r0").split("_r")[0][1:]) if spec.get("stage") == "v3" else -1,
                     **{k: round(v, 4) for k, v in zip(V3.VARS9, [V3.SPACE[k][0] + u * (V3.SPACE[k][1] - V3.SPACE[k][0])
                                                                   for k, u in zip(V3.VARS9, V3.to_unit9(dsg, h))])},
                     "A0_mm2": (r.get("templating") or {}).get("A0"), "f1_um": r["f1_p95_um"], "abs_dsed_pct": abs(r["f2_g7_loss_pct"]),
                     "vm_p99": r["vm_p99"], "resected_mm3": bl.get("resected_mm3", 0.0),
                     "reamed_mm3": bl.get("reamed_mm3", (r.get("templating") or {}).get("volume")),
                     "bone_loss_mm3": y[1], "log_f1": y[0], "constraint": c, "feasible": c <= 0})
    Y = np.array([[r["log_f1"], r["bone_loss_mm3"]] for r in rows if r["feasible"]])
    pm = mobo.pareto_mask(Y) if len(Y) else np.zeros(0, bool)
    k = 0
    for r in rows:
        if r["feasible"]:
            r["front"] = bool(pm[k]); k += 1
        else:
            r["front"] = False
    return rows


def fig_f01(rows):
    feas = [r for r in rows if r["feasible"]]
    front = sorted([r for r in feas if r["front"]], key=lambda r: r["f1_um"])
    read = {}
    for t in THRESH:
        ok = [r for r in feas if r["f1_um"] <= t]
        read[t] = min(ok, key=lambda r: r["bone_loss_mm3"]) if ok else None
    n_v3 = sum(r["source"] == "v3" for r in rows)
    parts = []
    for t in THRESH:
        rr = read[t]
        parts.append(f"≤ {t:.0f} µm: {rr['bone_loss_mm3'] / 1000:.1f} cm³ (L {rr['L']:.0f}, cut {rr['h_cut']:.0f})" if rr else f"≤ {t:.0f} µm: none")
    ps.publish_figure("V3-F01", rows, plot_f01,
                      title=f"Stability vs bone loss: least bone loss with micromotion " + "; ".join(parts) +
                            f" ({len(front)} front points, {n_v3} V3 evaluations so far)",
                      caption="横轴骨量损失 = 截骨面以上（到头颈交界）的颈部骨 + 锉掉的髓腔骨；纵轴微动 P95（对数）。灰点为旧数据（截骨在头颈交界，"
                              "h_cut = 25 mm），彩色为 V3 的定向评估（按轮次），叉号为不满足约束（|ΔSED| > 30% 或柄应力 > 440 MPa）者。"
                              "黑圈为可行点的非支配前沿；虚线为 40 与 150 µm 读数线。",
                      units={"bone_loss_mm3": "mm3", "f1_um": "um"})
    return read


def plot_f01(csv_path):
    d = ps.read_csv(csv_path)
    fig, ax = ps.new_figure("onehalf", 80)
    bl = np.array(d["bone_loss_mm3"], float) / 1000.0; f1 = np.array(d["f1_um"], float)
    src = np.array(d["source"]); feas = np.array([str(v) == "True" for v in d["feasible"]]); fr = np.array([str(v) == "True" for v in d["front"]])
    rnd = np.array(d["round"], float)
    m = (src == "legacy") & feas
    ax.scatter(bl[m], f1[m], s=9, color=ps.LIGHT, lw=0, label="existing (cut 25 mm)")
    m = (src == "v3") & feas
    if m.any():
        sc = ax.scatter(bl[m], f1[m], s=14, c=rnd[m], cmap="viridis", lw=0, label="V3 evaluations (colour = round)")
        fig.colorbar(sc, ax=ax, shrink=0.7, pad=0.02).set_label("BO round", fontsize=6)
    ax.scatter(bl[~feas], f1[~feas], s=12, marker="x", color=ps.GREY, lw=0.6, label="constraint violated")
    ax.scatter(bl[fr], f1[fr], s=30, facecolors="none", edgecolors="black", lw=0.8, label="front")
    for t in THRESH:
        ax.axhline(t, color="black", lw=0.5, ls="--")
        ax.text(ax.get_xlim()[1] if False else bl.max() * 1.02, t, f"{t:.0f} µm", fontsize=6, va="bottom", ha="right")
    ax.set_yscale("log"); ps.plain_log(ax, "y")
    ax.set_xlabel("bone loss: resected neck + reamed canal (cm³)"); ax.set_ylabel("micromotion P95 (µm)")
    ax.legend(fontsize=6, loc="center right")
    return fig


def fig_f02(rows):
    feas = [r for r in rows if r["feasible"]]
    fr = [r for r in feas if r["front"]]
    Ls = [r["L"] for r in fr]; hs = [r["h_cut"] for r in fr]; ms = [r["m"] for r in fr]
    ps.publish_figure("V3-F02", rows, plot_f02,
                      title=f"Front designs span L {min(Ls):.0f}–{max(Ls):.0f} mm, cut {min(hs):.0f}–{max(hs):.0f} mm from head centre, "
                            f"cortical margin {min(ms):+.2f}–{max(ms):+.2f} mm" if fr else "No feasible front yet",
                      caption="可行设计在（长度，截骨高度）与（长度，皮质余量）平面上的分布，颜色为微动 P95（对数）；黑圈为前沿点。"
                              "旧数据全部在截骨高度 25 mm 这条线上。")


def plot_f02(csv_path):
    d = ps.read_csv(csv_path)
    feas = np.array([str(v) == "True" for v in d["feasible"]]); fr = np.array([str(v) == "True" for v in d["front"]])
    L = np.array(d["L"], float); h = np.array(d["h_cut"], float); m = np.array(d["m"], float); f1 = np.array(d["f1_um"], float)
    fig, axes = ps.new_figure("double", 62, 1, 2)
    from matplotlib.colors import LogNorm
    for ax, y, lab in ((axes[0], h, "cut distance from head centre (mm)"), (axes[1], m, "cortical margin m (mm)")):
        sc = ax.scatter(L[feas], y[feas], c=f1[feas], s=12, cmap="plasma", norm=LogNorm(vmin=5, vmax=150), lw=0)
        ax.scatter(L[fr], y[fr], s=34, facecolors="none", edgecolors="black", lw=0.8)
        ax.set_xlabel("stem length L (mm)"); ax.set_ylabel(lab)
    fig.colorbar(sc, ax=axes, shrink=0.8, pad=0.02).set_label("micromotion P95 (µm)", fontsize=6)
    return fig


def _sens_rows():
    p = J.RESULTS / "v3_sens.json"
    if not p.exists():
        return None, []
    S3 = json.loads(p.read_text())
    rows = []
    for d in S3["designs"]:
        for var in ("base", "Ecanc200", "delta005"):
            v = d.get(var) or {}
            if "f1_um" not in v:
                continue
            rows.append({"job_id": d["job_id"], "source": d["source"], "front": d["front"], "L": round(d["L"], 2),
                         "h_cut": round(d["h_cut"], 2), "m": round(d["m"], 3), "alpha": round(d["alpha"], 2), "variant": var,
                         "f1_um": v["f1_um"], "abs_dsed_pct": v["abs_dsed_pct"], "vm_p99": v["vm_p99"],
                         "feasible": bool(v["abs_dsed_pct"] <= V3.SED_LIMIT and v["vm_p99"] <= V3.VM_LIMIT)})
    return S3, rows


def fig_f03():
    """敏感性：同一批设计在松质骨模量减半 / 过盈减半下的微动与 |ΔSED| 对基线。"""
    S3, rows = _sens_rows()
    if S3 is None:
        return None
    rc = S3["rank_correlation"]
    n = len({r["job_id"] for r in rows})
    ps.publish_figure("V3-F03", rows, plot_f03,
                      title=f"Halving cancellous modulus or interference raises micromotion ×{rc['Ecanc200']['median_ratio_f1']:.1f} / "
                            f"×{rc['delta005']['median_ratio_f1']:.1f} (median) with Spearman {rc['Ecanc200']['spearman_f1']:.2f} / "
                            f"{rc['delta005']['spearman_f1']:.2f} over {n} designs",
                      caption="左：变体下的微动 P95 对基线（400 MPa、0.10 mm），虚线为 y = x 与 y = 2x；右：Gruen 7 |ΔSED| 对基线，"
                              "虚线为 30% 约束。设计 = 前沿 4 个（黑圈）+ V3 内部前沿 4 个。圆 = E_canc 200 MPa，三角 = δ 0.05 mm。",
                      units={"f1_um": "um", "abs_dsed_pct": "%", "vm_p99": "MPa"})
    by = {}
    for r in rows:
        by.setdefault(r["job_id"], {"job_id": r["job_id"], "source": r["source"], "front": r["front"], "L": r["L"],
                                    "h_cut": r["h_cut"], "m": r["m"]})
        by[r["job_id"]].update({f"f1_{r['variant']}": round(r["f1_um"], 2), f"dsed_{r['variant']}": round(r["abs_dsed_pct"], 1),
                                f"vm_{r['variant']}": round(r["vm_p99"], 1), f"ok_{r['variant']}": r["feasible"]})
    cols = ["job_id", "front", "L", "h_cut", "m", "f1_base", "f1_Ecanc200", "f1_delta005", "dsed_base", "dsed_Ecanc200",
            "dsed_delta005", "vm_base", "vm_Ecanc200", "ok_Ecanc200", "ok_delta005"]      # 基线 8 个都可行，ok_base 省略
    ps.publish_table("V3-T02", sorted(by.values(), key=lambda r: r["f1_base"]),
                     title="Sensitivity of the eight re-run designs to cancellous modulus (200 MPa) and interference (0.05 mm)",
                     caption="f1 = 微动 P95（µm），dsed = Gruen 7 |ΔSED|（%），vm = 柄 von Mises P99（MPa），ok = 满足两条约束。", columns=cols)
    return rc


def plot_f03(csv_path):
    d = ps.read_csv(csv_path)
    var = np.array(d["variant"]); jid = np.array(d["job_id"]); fr = np.array([str(v) == "True" for v in d["front"]])
    f1 = np.array(d["f1_um"], float); ds = np.array(d["abs_dsed_pct"], float)
    base = {j: (f, s) for j, v, f, s in zip(jid, var, f1, ds) if v == "base"}
    fig, axes = ps.new_figure("double", 62, 1, 2)
    for v, mk, col, lab in (("Ecanc200", "o", ACOL, "E_canc 200 MPa"), ("delta005", "^", ps.GREY, "δ 0.05 mm")):
        m = var == v
        xb = np.array([base[j][0] for j in jid[m]]); yb = np.array([base[j][1] for j in jid[m]])
        axes[0].scatter(xb, f1[m], s=16, marker=mk, color=col, lw=0, label=lab)
        axes[0].scatter(xb[fr[m]], f1[m][fr[m]], s=40, marker=mk, facecolors="none", edgecolors="black", lw=0.7)
        axes[1].scatter(yb, ds[m], s=16, marker=mk, color=col, lw=0)
        axes[1].scatter(yb[fr[m]], ds[m][fr[m]], s=40, marker=mk, facecolors="none", edgecolors="black", lw=0.7)
    lo, hi = 3.0, 60.0
    axes[0].plot([lo, hi], [lo, hi], color="black", lw=0.5, ls="--"); axes[0].plot([lo, hi], [2 * lo, 2 * hi], color="black", lw=0.5, ls=":")
    axes[0].text(hi, 2 * hi, "2×", fontsize=6, ha="right", va="bottom")
    axes[0].set_xscale("log"); axes[0].set_yscale("log"); ps.plain_log(axes[0], "x"); ps.plain_log(axes[0], "y")
    axes[0].set_xlabel("micromotion P95, baseline (µm)"); axes[0].set_ylabel("micromotion P95, variant (µm)")
    axes[0].legend(fontsize=6, loc="upper left")
    axes[1].plot([0, 50], [0, 50], color="black", lw=0.5, ls="--")
    axes[1].axhline(V3.SED_LIMIT, color="black", lw=0.5, ls="--"); axes[1].axvline(V3.SED_LIMIT, color="black", lw=0.5, ls="--")
    axes[1].set_xlabel("|ΔSED| Gruen 7, baseline (%)"); axes[1].set_ylabel("|ΔSED| Gruen 7, variant (%)")
    return fig


def seed_stats(rows):
    """按 BO 种子汇总 V3 评估：完成数、可行数、最好微动、最少骨量损失。"""
    out = {}
    for p in sorted(J.RESULTS.glob("v3_bo_s*.json")):
        b = json.loads(p.read_text())
        rec = b["records"]
        ok = [r for r in rec if r["ok"]]
        feas = [r for r in ok if r["c"][0] <= 0]
        out[f"s{b['seed']}"] = {"rounds": max((r["round"] for r in rec), default=0), "n_eval": len(rec), "n_ok": len(ok),
                                "n_feasible": len(feas),
                                "min_f1_um": (10 ** min(r["y"][0] for r in feas)) if feas else None,
                                "min_bone_loss_mm3": min((r["y"][1] for r in feas), default=None), "updated": b.get("updated")}
    return out


def table_t01(rows):
    fr = sorted([r for r in rows if r["feasible"] and r["front"]], key=lambda r: r["bone_loss_mm3"])
    cols = ["job_id", "source", "L", "h_cut", "alpha", "m", "lam", "g_ml", "g_ap", "n", "tau", "A0_mm2", "f1_um", "abs_dsed_pct",
            "vm_p99", "resected_mm3", "reamed_mm3", "bone_loss_mm3"]
    t = [{k: (round(r[k], 3) if isinstance(r[k], float) else r[k]) for k in cols} for r in fr]
    ps.publish_table("V3-T01", t, title="Designs on the stability–bone-loss front (least bone loss first)",
                     caption="变量为物理量；bone_loss = resected + reamed。", columns=cols)
    return fr


def main():
    rows = collect()
    read = fig_f01(rows)
    fig_f02(rows)
    fr = table_t01(rows)
    rc = fig_f03()
    n_v3 = sum(r["source"] == "v3" for r in rows)
    summ = {"n_designs": len(rows), "n_feasible": sum(r["feasible"] for r in rows), "n_v3": n_v3, "n_front": len(fr),
            "readout": {f"{t:.0f}um": ({k: read[t][k] for k in ("job_id", "L", "h_cut", "alpha", "m", "A0_mm2", "f1_um", "abs_dsed_pct",
                                                                  "resected_mm3", "reamed_mm3", "bone_loss_mm3")} if read[t] else None)
                        for t in THRESH},
            "n_v3_feasible": sum(r["feasible"] for r in rows if r["source"] == "v3"),
            "seeds": seed_stats(rows), "sensitivity": rc}
    (J.RESULTS / "v3_summary.json").write_text(json.dumps(summ, indent=1, default=float))
    print(json.dumps(summ, indent=1, default=float))


if __name__ == "__main__":
    main()
