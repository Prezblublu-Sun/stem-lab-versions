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
        if spec.get("delta") is not None or spec.get("mu") is not None or spec.get("torque", True) is False:
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
    ax.legend(fontsize=6, loc="upper right")
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
    n_v3 = sum(r["source"] == "v3" for r in rows)
    summ = {"n_designs": len(rows), "n_feasible": sum(r["feasible"] for r in rows), "n_v3": n_v3, "n_front": len(fr),
            "readout": {f"{t:.0f}um": ({k: read[t][k] for k in ("job_id", "L", "h_cut", "alpha", "m", "A0_mm2", "f1_um", "abs_dsed_pct",
                                                                  "resected_mm3", "reamed_mm3", "bone_loss_mm3")} if read[t] else None)
                        for t in THRESH}}
    (J.RESULTS / "v3_summary.json").write_text(json.dumps(summ, indent=1, default=float))
    print(json.dumps(summ, indent=1, default=float))


if __name__ == "__main__":
    main()
