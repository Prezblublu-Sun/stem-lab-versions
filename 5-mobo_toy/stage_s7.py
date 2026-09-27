"""S7 3D 抽检 → R6 报告。python stage_s7.py [--source front|meshrank] [--n 5] [--test]（.venv-mobo）

* 抽检设计：默认取 R5 各型参考前沿按 f1 等距的 n 个（含两端）；R5 未完成时可用 --source meshrank
  （S2 网格排序检查里的 Sobol 设计），报告里注明来源。
* 每个设计建 3D 摩擦与粘接模型（spot3d/model3d.py），每型一个完整 3D 股骨作 SED 参照；
  每型第一个设计再用细一档网格（界面 1.4 mm）跑一次，检查 3D 网格影响。
* 2D 值取自 runs.csv（同一设计的生产网格结果，缓存命中不重算）。
"""
from __future__ import annotations

import json
import math
import pathlib
import shutil
import sys

import numpy as np
from scipy.stats import spearmanr

import evaluate as EV
import femur2d as F
import plotstyle as ps
import run_abaqus as ra
import stem2d as S

sys.path.insert(0, str(ps.ROOT / "spot3d"))
import model3d as M3  # noqa: E402
import qoi3d as Q3  # noqa: E402

ROOT = ps.ROOT
CFG = F.CFG
RUN3 = ROOT / "runs" / "S7_3d"
OUT = ROOT / "results" / "S7_spot3d.json"
H_COARSE, H_FINE, H_FAR = 2.0, 1.4, 6.0


def pick_designs(source: str, n: int) -> list[dict]:
    rows = EV.read_runs()
    out = []
    for t in "ABC":
        if source == "front":
            s5 = json.loads((ROOT / "results" / "S5_summary.json").read_text())
            import stage_s5 as S5
            import mobo
            import reference_sweep as RS
            g = S5.group_rows()[f"{t}_E{int(CFG['dorr'][t]['E_cancellous'])}"]
            ys, idx, m = S5._front(g)
            fr = [g[i] for i in idx[m]]
            fy = ys[m]
            order = np.argsort(fy[:, 0])
            pick = order[np.linspace(0, len(order) - 1, min(n, len(order))).round().astype(int)]
            cand = [fr[i] for i in pick]
        else:
            cand = [r for r in rows if r.get("campaign") == "S2_meshrank" and r["dorr"] == t and r["status"] == "OK"
                    and abs(EV.as_float(r, "mesh_scale") - 1.0) < 1e-9][:n]
        for r in cand:
            out.append({"dorr": t, "design": {v: EV.as_float(r, v) for v in S.VARS}, "row2d": r})
    return out


def run_3d(items: list[dict], test: bool = False) -> list[dict]:
    res = json.loads(OUT.read_text()) if OUT.exists() else {}
    # 完整 3D 参照
    intact = {}
    for t in sorted({it["dorr"] for it in items}):
        d = RUN3 / f"intact_{t}"
        key = f"intact_{t}"
        if key not in res:
            if d.exists():
                shutil.rmtree(d)
            M3.build_intact(F.build(t), d, "intact", h_roi=H_COARSE, h_far=H_FAR)
            r = ra.run_and_export(d / "intact.inp", cpus=4, timeout=7200)
            if r["status"] != "OK":
                raise RuntimeError(f"3D intact {t}: {r}")
            res[key] = Q3.zone_sed(d, "intact", t, F.build(t).E_cancellous)
            OUT.write_text(json.dumps(res, indent=1))
        intact[t] = res[key]
    jobs = []
    for k, it in enumerate(items):
        for h in ([H_COARSE, H_FINE] if it.get("fine") else [H_COARSE]):
            name = f"{it['dorr']}{k:02d}_h{h:g}".replace(".", "p")
            if name in res:
                continue
            d = RUN3 / name
            if d.exists():
                shutil.rmtree(d)
            st = S.make(it["dorr"], it["design"])
            info = M3.build(st, d, name, h_int=h, h_far=H_FAR)
            jobs.append((name, d, it, h, info))
    for name, d, it, h, info in jobs:
        rr = {}
        for kind in ("fric", "bond"):
            rr[kind] = ra.run_and_export(d / f"{name}_{kind}.inp", cpus=4, timeout=14400)
        entry = {"dorr": it["dorr"], "design": it["design"], "h_int": h, "n_tet": info["n_tet"],
                 "status": "OK" if all(r["status"] == "OK" for r in rr.values()) else "FAIL",
                 "wall_s": {k: r.get("wall_s") for k, r in rr.items()},
                 "reason": "; ".join(f"{k}: {r.get('reason', '')}" for k, r in rr.items() if r["status"] != "OK"),
                 "design_id_2d": it["row2d"].get("design_id")}
        if entry["status"] == "OK":
            mm = Q3.micromotion(d, f"{name}_fric")
            zs = Q3.zone_sed(d, f"{name}_bond", it["dorr"], F.build(it["dorr"]).E_cancellous)
            entry.update(mm)
            entry["f2_g7_loss_pct"] = 100 * (1 - zs["gruen7"] / intact[it["dorr"]]["gruen7"])
            entry["f2_g1_loss_pct"] = 100 * (1 - zs["gruen1"] / intact[it["dorr"]]["gruen1"])
        res[name] = entry
        OUT.write_text(json.dumps(res, indent=1))
        print(name, entry["status"], entry.get("f1_p95_um"), entry.get("f2_g7_loss_pct"), entry["wall_s"], flush=True)
        if test:
            break
    return res


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


def publish(items, res, source):
    f01 = []
    for t in "ABC":
        name = next((k for k, v in res.items() if isinstance(v, dict) and v.get("dorr") == t and abs(v.get("h_int", 0) - H_COARSE) < 1e-9), None)
        if not name:
            continue
        m = dict(np.load(RUN3 / name / "mesh3d.npz"))
        lab, X = m["node_labels"], m["nodes"]
        lut = np.full(int(lab.max()) + 1, -1); lut[lab] = np.arange(len(lab))
        for part in ("cortex", "cancellous", "stem"):
            cen = X[lut[m[f"{part}_conn"][:, :4]]].mean(1)
            sel_ = np.abs(cen[:, 1]) < 1.0
            for c in cen[sel_]:
                f01.append(dict(dorr=t, part=part, x=c[0], z=c[2]))
    ps.publish_figure("R6-F01", f01, plot_r6_f01,
                      title="The idealised 3D femora carry the same outer contour and Dorr canal as the 2D models",
                      caption=("3D 模型中冠面（|y| < 1 mm）的单元形心：灰为皮质、黄为松质、蓝为柄。股骨由 2D 轮廓的椭圆截面放样，"
                               "柄沿与 2D 相同的圆弧放样超椭圆截面。C3D10，界面 2 mm、远场 6 mm。"))
    pairs = []
    for k, v in res.items():
        if not isinstance(v, dict) or v.get("status") != "OK" or abs(v.get("h_int", 0) - H_COARSE) > 1e-9:
            continue
        r2 = next((r for r in EV.read_runs() if r["design_id"] == v["design_id_2d"]), None)
        if r2 is None:
            continue
        pairs.append(dict(dorr=v["dorr"], name=k, f1_2d=EV.as_float(r2, "f1_p95_um"), f1_3d=v["f1_p95_um"],
                          f2_2d=EV.as_float(r2, "f2_g7_loss_pct"), f2_3d=v["f2_g7_loss_pct"]))
    rho1 = float(spearmanr([p["f1_2d"] for p in pairs], [p["f1_3d"] for p in pairs])[0]) if len(pairs) > 2 else float("nan")
    rho2 = float(spearmanr([p["f2_2d"] for p in pairs], [p["f2_3d"] for p in pairs])[0]) if len(pairs) > 2 else float("nan")
    for p in pairs:
        p["rho_f1"], p["rho_f2"] = rho1, rho2
    ps.publish_figure("R6-F02", pairs, plot_r6_f02,
                      title=f"2D and 3D rank the spot-check designs consistently (ρ = {rho1:.2f} for f1, {rho2:.2f} for f2)",
                      caption=f"抽检设计（来源：{'R5 参考前沿' if source == 'front' else 'S2 网格排序检查的 Sobol 设计'}）的 2D 与 3D 目标值；ρ 为三型合并的 Spearman 秩相关。")
    conv = []
    for k, v in res.items():
        if isinstance(v, dict) and v.get("status") == "OK" and "_h" in k:
            base = k.split("_h")[0]
            fine = [w for kk, w in res.items() if kk.startswith(base) and isinstance(w, dict) and abs(w.get("h_int", 0) - H_FINE) < 1e-9]
            if fine:
                conv.append(dict(dorr=v["dorr"], h=v["h_int"], f1=v["f1_p95_um"], f2=v["f2_g7_loss_pct"]))
    ch = {}
    for t in "ABC":
        c = sorted([r for r in conv if r["dorr"] == t], key=lambda r: r["h"])
        if len(c) >= 2:
            ch[t] = max(abs(c[0]["f1"] - c[1]["f1"]) / abs(c[0]["f1"]), abs(c[0]["f2"] - c[1]["f2"]) / abs(c[0]["f2"]))
    if conv:
        ps.publish_figure("R6-F03", conv, plot_r6_f03,
                          title=f"Refining the 3D interface mesh from 2.0 to 1.4 mm changes f1 or f2 by up to {max(ch.values()) * 100:.0f} %",
                          caption="每型第一个抽检设计用两档 3D 网格计算。")
    ps.publish_table("R6-T01", pairs, title="抽检设计清单与 2D、3D 两套目标值")
    ok1 = (not math.isnan(rho1)) and rho1 >= 0.7 and rho2 >= 0.7
    ps.publish_acceptance("R6", [
        {"id": "R6-A1", "measured": f"f1 ρ = {rho1:.2f}，f2 ρ = {rho2:.2f}（n = {len(pairs)}）", "status": "PASS" if ok1 else "FAIL",
         "note": "" if ok1 else "2D 排序在 3D 中不保持，2D 结论只限 2D 模型"},
        {"id": "R6-A2", "measured": "；".join(f"{t} {v * 100:.1f} %" for t, v in ch.items()) or "未算",
         "status": "PASS" if ch and max(ch.values()) < 0.10 else "FAIL", "note": "" if ch and max(ch.values()) < 0.10 else "3D 网格需加密"},
    ])
    write_text(res, source, rho1, rho2, ch)


def write_text(res, source, rho1, rho2, ch):
    tx = ps.report_dir("R6") / "text"
    tx.joinpath("summary.md").write_text(
        f"理想化 3D 模型（无侧板、自带环向刚度）对抽检设计的排序与 2D 的 Spearman 秩相关：f1 ρ = {rho1:.2f}，f2 ρ = {rho2:.2f}。"
        + ("两者都达到 0.7，2D 的设计排序在 3D 中保持，侧板假设没有改变结论。" if rho1 >= 0.7 and rho2 >= 0.7 else
           "未达到 0.7，2D 的排序在 3D 中不完全保持，2D 结论只限 2D 模型。")
        + (f" 3D 网格加密（2.0 → 1.4 mm）的最大变化 {max(ch.values()) * 100:.0f} %。" if ch else ""), encoding="utf-8")
    tx.joinpath("methods.md").write_text(
        "**3D 模型（`spot3d/model3d.py`）**：股骨外形由 2D 外轮廓在 z = −150…+40 mm 每 5 mm 的椭圆截面放样（冠状半轴 = 2D 半弦长，"
        "矢状半轴 = 深度比 × 冠状半轴，干部 1.0、近端 0.72），并上颈部椭圆柱、头部球与大转子椭球；髓腔同法由 2D 内轮廓放样，"
        "矢状壁厚取冠状面平均壁厚。柄体沿与 2D 相同的圆弧放样 4 次超椭圆截面（冠状半宽 w(s)，矢状半厚 6 mm × w(s)/w_p），"
        "尖端椭球帽；锉刀腔为截面内缩 δ。C3D10，界面 2 mm、远场 6 mm；每型第一个设计另用 1.4 mm。"
        "材料、载荷（Fy = 0）、三步压配、TIE 与 QoI 定义与 2D 相同；f1 用两个切向滑移分量的合成，Gruen ROI 取全部深度。"
        f"抽检设计来源：{'R5 各型参考前沿按 f1 等距' if source == 'front' else 'S2 网格排序检查的 Sobol 设计'}。", encoding="utf-8")
    tx.joinpath("limitations.md").write_text(
        "- 3D 股骨为解析放样的理想化形状，不是真实解剖；与 2D 的比较只检验排序，不是确认。\n"
        "- 3D 网格较粗（受求解时间限制），绝对值不作结论。", encoding="utf-8")


def main():
    source = next((a.split("=")[1] for a in sys.argv if a.startswith("--source=")), "front")
    n = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--n=")), 5))
    test = "--test" in sys.argv
    items = pick_designs(source, 1 if test else n)
    seen = set()
    for it in items:
        if it["dorr"] not in seen:
            it["fine"] = True
            seen.add(it["dorr"])
    res = run_3d(items, test=test)
    if not test:
        publish(items, res, source)


if __name__ == "__main__":
    main()
