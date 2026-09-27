"""S7 3D 抽检 → R6 报告。python stage_s7.py [--source front|meshrank] [--n 5]（.venv-mobo）

* 抽检设计：默认取 R4/R5 各型参考前沿（可行非支配集）按 f1 等距的 n 个（含两端）；与侧板校准用的设计（S2 Sobol）不重叠，
  所以本检验独立于校准。--source meshrank 用 S2 网格排序检查的设计（仅调试用）。
* 3D 由 spot3d/eval3d 计算（缓存、两路并行）；每型第一个设计另用细一档网格（界面 1.4 mm）检查 3D 网格影响。
* 2D 值取自 runs.csv 中同一设计的生产结果。
"""
from __future__ import annotations

import json
import math
import sys

import numpy as np
from scipy.stats import spearmanr

import evaluate as EV
import femur2d as F
import plotstyle as ps
import stem2d as S

sys.path.insert(0, str(ps.ROOT / "spot3d"))
import eval3d as E3  # noqa: E402

ROOT = ps.ROOT
CFG = F.CFG
H_COARSE, H_FINE = 2.0, 1.4


def pick_designs(source: str, n: int) -> list[dict]:
    out = []
    rows = EV.read_runs()
    for t in "ABC":
        if source == "front":
            import stage_s5 as S5
            g = S5.group_rows()[f"{t}_E{int(CFG['dorr'][t]['E_cancellous'])}"]
            s5 = json.loads((ROOT / "results" / "S5_runs.json").read_text()) if (ROOT / "results" / "S5_runs.json").exists() else {}
            by = {r["design_id"]: r for r in rows}
            extra = [by[row["design_id"]] for run in s5.get(t, {}).get("runs", {}).values() for row in run["rows"]
                     if row["design_id"] in by]
            ys, idx, m = S5._front(g + extra)
            allrows = g + extra
            fr = [allrows[i] for i in idx[m]]
            fy = ys[m]
            order = np.argsort(fy[:, 0])
            pick = order[np.linspace(0, len(order) - 1, min(n, len(order))).round().astype(int)]
            cand = [fr[i] for i in pick]
        else:
            cand = [r for r in rows if r.get("campaign") == "S2_meshrank" and r["dorr"] == t and r["status"] == "OK"
                    and abs(EV.as_float(r, "mesh_scale") - 1.0) < 1e-9][:n]
        out += [{"dorr": t, "design": {v: EV.as_float(r, v) for v in S.VARS}, "design_id_2d": r["design_id"], "tag": "S7"}
                for r in cand]
    return out


# ------------------------------------------------------------------ plots（只读 CSV）
def plot_r6_f01(csv_path):
    d = ps.read_csv(csv_path)
    fig, axes = ps.new_figure("double", 80, 1, 3)
    cols = {"cortex": "#9A9A9A", "cancellous": "#E6C98F", "stem": "#4A7FB5"}
    for ax, t in zip(axes, "ABC"):
        for part, c in cols.items():
            jj = [i for i in range(len(d["dorr"])) if d["dorr"][i] == t and d["part"][i] == part]
            ax.scatter([d["x"][i] for i in jj], [d["z"][i] for i in jj], s=0.6, color=c, label=part, edgecolors="none")
        ax.set_aspect("equal"); ax.set_xlim(-40, 70); ax.set_ylim(-152, 80); ax.set_title(f"Dorr {t}: mid-coronal slice")
        ax.set_xlabel("x (mm)")
    axes[0].set_ylabel("z (mm)"); axes[0].legend(loc="lower right", markerscale=8, fontsize=6)
    return fig


def plot_r6_f02(csv_path):
    d = ps.read_csv(csv_path)
    fig, axes = ps.new_figure("onehalf", 66, 1, 2)
    for ax, (q, lab) in zip(axes, (("f1", ps.LABEL["f1"]), ("f2", ps.LABEL["f2"]))):
        for t in "ABC":
            jj = [i for i in range(len(d["dorr"])) if d["dorr"][i] == t]
            ax.scatter([d[f"{q}_2d"][i] for i in jj], [d[f"{q}_3d"][i] for i in jj], s=16, color=ps.DORR[t],
                       marker=ps.DORR_MARKER[t], label=f"Dorr {t}")
        rho = d[f"rho_{q}"][0]
        ax.set_title(f"pooled Spearman ρ = {rho:.2f}", fontsize=7)
        ax.set_xlabel(f"2D {lab}", fontsize=7); ax.set_ylabel(f"3D {lab}", fontsize=7)
        if q == "f1":
            ax.set_xscale("log"); ax.set_yscale("log")
    axes[0].legend(loc="upper left", fontsize=6)
    ps.panel_labels(axes)
    return fig


def plot_r6_f03(csv_path):
    d = ps.read_csv(csv_path)
    fig, axes = ps.new_figure("onehalf", 60, 1, 2)
    for ax, (q, lab) in zip(axes, (("f1", ps.LABEL["f1"]), ("f2", ps.LABEL["f2"]))):
        for t in "ABC":
            jj = sorted([i for i in range(len(d["dorr"])) if d["dorr"][i] == t], key=lambda i: -d["h"][i])
            ax.plot([d["h"][i] for i in jj], [d[q][i] for i in jj], "o-", color=ps.DORR[t], label=f"Dorr {t}")
        ax.invert_xaxis(); ax.set_xlabel("3D interface element size (mm)"); ax.set_ylabel(lab, fontsize=7)
    axes[0].legend(loc="best", fontsize=6)
    ps.panel_labels(axes)
    return fig


def publish(items, res, fine_items, fine_res, source):
    f01 = []
    for t in "ABC":
        r = next((v for it, v in zip(items, res) if it["dorr"] == t and v.get("status") == "OK"), None)
        if r is None:
            continue
        m = dict(np.load(ROOT / r["dir"] / "mesh3d.npz"))
        lab, X = m["node_labels"], m["nodes"]
        lut = np.full(int(lab.max()) + 1, -1); lut[lab] = np.arange(len(lab))
        for part in ("cortex", "cancellous", "stem"):
            cen = X[lut[m[f"{part}_conn"][:, :4]]].mean(1)
            for c in cen[np.abs(cen[:, 1]) < 1.0]:
                f01.append(dict(dorr=t, part=part, x=c[0], z=c[2]))
    ps.publish_figure("R6-F01", f01, plot_r6_f01, sources={"runs3d": "results/runs3d.jsonl (tag S7)"},
                      title="The idealised 3D femora share the outer contour and Dorr canal of the 2D models",
                      caption=("3D 模型中冠面（|y| < 1 mm）的单元形心：灰为皮质、黄为松质、蓝为柄。股骨由 2D 轮廓的椭圆截面放样，"
                               "柄沿与 2D 相同的圆弧放样超椭圆截面。C3D10，界面 2 mm、远场 6 mm。"))
    by = {r["design_id"]: r for r in EV.read_runs()}
    pairs = []
    for it, v in zip(items, res):
        r2 = by.get(it["design_id_2d"])
        if v.get("status") != "OK" or r2 is None or r2["status"] != "OK":
            continue
        pairs.append(dict(dorr=it["dorr"], design_id_2d=it["design_id_2d"], f1_2d=EV.as_float(r2, "f1_p95_um"),
                          f1_3d=v["f1_p95_um"], f2_2d=EV.as_float(r2, "f2_g7_loss_pct"), f2_3d=v["f2_g7_loss_pct"]))
    rho1 = float(spearmanr([p["f1_2d"] for p in pairs], [p["f1_3d"] for p in pairs])[0]) if len(pairs) > 2 else float("nan")
    rho2 = float(spearmanr([p["f2_2d"] for p in pairs], [p["f2_3d"] for p in pairs])[0]) if len(pairs) > 2 else float("nan")
    per = {}
    for t in "ABC":
        pp = [p for p in pairs if p["dorr"] == t]
        if len(pp) > 2:
            per[t] = (float(spearmanr([p["f1_2d"] for p in pp], [p["f1_3d"] for p in pp])[0]),
                      float(spearmanr([p["f2_2d"] for p in pp], [p["f2_3d"] for p in pp])[0]))
    for p in pairs:
        p["rho_f1"], p["rho_f2"] = rho1, rho2
    ps.publish_figure("R6-F02", pairs, plot_r6_f02, sources={"runs3d": "results/runs3d.jsonl (tag S7)"},
                      title=f"2D vs 3D ranking of front designs: ρ = {rho1:.2f} for f1 and {rho2:.2f} for f2",
                      caption=(f"抽检设计（来源：{'各型参考前沿按 f1 等距' if source == 'front' else 'S2 网格排序检查的 Sobol 设计'}）"
                               "的 2D 与 3D 目标值；ρ 为三型合并的 Spearman 秩相关；各型内的 ρ 见 R6-T01 与摘要。"))
    conv, ch = [], {}
    for it, v in zip(fine_items, fine_res):
        c = next((w for i2, w in zip(items, res) if i2["design_id_2d"] == it["design_id_2d"]), None)
        if v.get("status") == "OK" and c and c.get("status") == "OK":
            conv += [dict(dorr=it["dorr"], h=H_COARSE, f1=c["f1_p95_um"], f2=c["f2_g7_loss_pct"]),
                     dict(dorr=it["dorr"], h=H_FINE, f1=v["f1_p95_um"], f2=v["f2_g7_loss_pct"])]
            ch[it["dorr"]] = max(abs(v["f1_p95_um"] - c["f1_p95_um"]) / abs(v["f1_p95_um"]),
                                 abs(v["f2_g7_loss_pct"] - c["f2_g7_loss_pct"]) / max(abs(v["f2_g7_loss_pct"]), 1e-9))
    if conv:
        ps.publish_figure("R6-F03", conv, plot_r6_f03,
                          title=f"Refining the 3D interface mesh from 2.0 to 1.4 mm changes f1 or f2 by up to {max(ch.values()) * 100:.0f} %",
                          caption="每型第一个抽检设计用两档 3D 网格计算；相对变化以细网格值为分母。")
    ps.publish_table("R6-T01", [dict(p, rho_type_f1=per.get(p["dorr"], (float("nan"),) * 2)[0],
                                     rho_type_f2=per.get(p["dorr"], (float("nan"),) * 2)[1]) for p in pairs],
                     title="抽检设计清单与 2D、3D 两套目标值", caption="rho_type 为该型 5 个设计内的 Spearman ρ（样本小，仅供参考）。")
    ok1 = (not math.isnan(rho1)) and rho1 >= 0.7 and rho2 >= 0.7
    ps.publish_acceptance("R6", [
        {"id": "R6-A1", "measured": f"f1 ρ = {rho1:.2f}，f2 ρ = {rho2:.2f}（n = {len(pairs)}，三型合并）", "status": "PASS" if ok1 else "FAIL",
         "note": "" if ok1 else "2D 排序在 3D 中不完全保持：2D 的前沿与分型结论只限 2D 模型，迁移到真实股骨前需用 3D 或真实模型复核"},
        {"id": "R6-A2", "measured": "；".join(f"{t} {v * 100:.1f} %" for t, v in ch.items()) or "未算",
         "status": "PASS" if ch and max(ch.values()) < 0.10 else "FAIL",
         "note": "" if ch and max(ch.values()) < 0.10 else "3D 网格在 2 mm 时未收敛，3D 绝对值不作结论；排序比较仍可参考"},
    ])
    ps.publish_inputs("R6", source=source, n_per_type=len(items) // 3, h_int=[H_COARSE, H_FINE],
                      side_plate_2d_mm=CFG["side_plate"]["thickness"])
    write_text(res, source, rho1, rho2, ch, per)


def write_text(res, source, rho1, rho2, ch, per):
    tx = ps.report_dir("R6") / "text"
    tx.joinpath("summary.md").write_text(
        f"理想化 3D 模型（无侧板、自带环向刚度）对前沿抽检设计的排序与 2D 的 Spearman 秩相关（三型合并）：f1 ρ = {rho1:.2f}，f2 ρ = {rho2:.2f}"
        + ("；各型内：" + "；".join(f"{t} f1 {a:.2f}、f2 {b:.2f}" for t, (a, b) in per.items()) if per else "") + "。"
        + ("两者都达到 0.7，2D 的设计排序在 3D 中基本保持。" if rho1 >= 0.7 and rho2 >= 0.7 else
           "未都达到 0.7，2D 的排序在 3D 中不完全保持，2D 结论只限 2D 模型。")
        + (f"3D 网格加密（2.0 → 1.4 mm）的最大相对变化 {max(ch.values()) * 100:.0f} %。" if ch else ""), encoding="utf-8")
    tx.joinpath("methods.md").write_text(
        "**3D 模型（`spot3d/model3d.py`）**：股骨外形由 2D 外轮廓在 z = −150…+40 mm 每 5 mm 的椭圆截面放样（冠状半轴 = 2D 半弦长，"
        "矢状半轴 = 深度比 × 冠状半轴，干部 1.0、近端 0.72），并上颈部椭圆柱、头部球与大转子椭球；髓腔同法由 2D 内轮廓放样，"
        "矢状壁厚取冠状面平均壁厚。柄体沿与 2D 相同的圆弧放样 4 次超椭圆截面（冠状半宽 w(s)，矢状半厚 6 mm × w(s)/w_p），"
        "尖端椭球帽；锉刀腔为截面内缩 δ。直边二阶四面体 C3D10（gmsh Delaunay + Netgen 优化），界面 2 mm、远场 6 mm；"
        "每型第一个设计另用 1.4 mm。材料、载荷（Fx = −668 N、Fz = −2,296 N，Fy = 0）、三步压配、TIE 与 QoI 定义与 2D 相同；"
        "f1 用两个切向滑移分量的合成，Gruen ROI 取全部深度，SED 参照为同法建的完整 3D 股骨。"
        f"抽检设计：{'各型参考前沿（R4 扫描 + R5 BO 的可行非支配集）按 f1 等距取 5 个' if source == 'front' else 'S2 网格排序检查的 Sobol 设计'}；"
        "它们与侧板校准用的 36 个设计不重叠。", encoding="utf-8")
    tx.joinpath("limitations.md").write_text(
        "- 3D 股骨为解析放样的理想化形状，不是真实解剖；与 2D 的比较只检验排序，不是确认。\n"
        "- 3D 网格较粗（受求解时间限制），绝对值不作结论。\n"
        "- 每型只 5 个设计，型内秩相关的统计力很弱，验收用三型合并值。", encoding="utf-8")


def main():
    source = next((a.split("=")[1] for a in sys.argv if a.startswith("--source=")), "front")
    n = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--n=")), 5))
    items = pick_designs(source, n)
    res = E3.evaluate(items, h=H_COARSE, max_parallel=2)
    fine_items = []
    for t in "ABC":
        it = next((i for i, r in zip(items, res) if i["dorr"] == t and r.get("status") == "OK"), None)
        if it:
            fine_items.append(it)
    fine_res = E3.evaluate(fine_items, h=H_FINE, max_parallel=2)
    publish(items, res, fine_items, fine_res, source)


if __name__ == "__main__":
    main()
