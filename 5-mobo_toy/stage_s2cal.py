"""侧板厚度校准（2026-09-27 用户同意）：同一批设计在 2D（不同侧板厚度）与 3D 中计算，选 2D–3D 秩相关最好的厚度。

python stage_s2cal.py   → R2-F11、R2-F12；results/S2_sideplate_calibration.json；把选定厚度写回 config.yaml。
设计：每型 12 个过几何门的打乱 Sobol 设计（种子 321，与 R2-F10 相同）。3D 用 spot3d/eval3d（界面 2 mm）。
选择准则：三型 × 两个目标共 6 个 Spearman ρ 的平均值最大；同时报最小值。
"""
from __future__ import annotations

import json
import re
import sys

import numpy as np
from scipy.stats import qmc, spearmanr

import evaluate as EV
import plotstyle as ps
import stem2d as S

ROOT = ps.ROOT
sys.path.insert(0, str(ROOT / "spot3d"))
import eval3d as E3  # noqa: E402

THICK = [0.0, 0.5, 1.0, 2.0, 3.0, 6.0]
N_PER_TYPE = 12


def designs():
    out = []
    for t in "ABC":
        U = qmc.Sobol(5, scramble=True, seed=321).random(256)
        picked = [u for u in U if S.gate(S.make(t, S.to_physical(u)))["pass"]][:N_PER_TYPE]
        out += [{"dorr": t, "design": S.to_physical(u)} for u in picked]
    return out


def plot_r2_f11(csv_path):
    d = ps.read_csv(csv_path)
    fig, axes = ps.new_figure("onehalf", 64, 1, 2, sharey=True)
    for ax, q in zip(axes, ("f1", "f2")):
        for t in "ABC":
            jj = sorted([i for i in range(len(d["dorr"])) if d["dorr"][i] == t and d["objective"][i] == q],
                        key=lambda i: d["side_plate"][i])
            ax.plot([d["side_plate"][i] for i in jj], [d["rho"][i] for i in jj], marker=ps.DORR_MARKER[t],
                    color=ps.DORR[t], label=f"Dorr {t}")
        best = d["chosen"][0]
        ax.axvline(best, color="black", ls=":", lw=0.9)
        ps.threshold_line(ax, 0.7, "y", "0.7")
        ax.set_xlabel("Side-plate thickness in 2D (mm)"); ax.set_title(f"{q}: 2D vs 3D Spearman ρ")
        ax.set_ylim(-1, 1)
    axes[0].set_ylabel("Spearman ρ (–)"); axes[0].legend(loc="lower right", fontsize=6)
    ps.panel_labels(axes)
    return fig


def plot_r2_f12(csv_path):
    d = ps.read_csv(csv_path)
    fig, axes = ps.new_figure("onehalf", 64, 1, 2)
    for ax, q, lab in ((axes[0], "f1", ps.LABEL["f1"]), (axes[1], "f2", ps.LABEL["f2"])):
        for t in "ABC":
            jj = [i for i in range(len(d["dorr"])) if d["dorr"][i] == t]
            ax.scatter([d[f"{q}_2d"][i] for i in jj], [d[f"{q}_3d"][i] for i in jj], s=14, color=ps.DORR[t],
                       marker=ps.DORR_MARKER[t], label=f"Dorr {t}")
        ax.set_xlabel(f"2D {lab}", fontsize=7); ax.set_ylabel(f"3D {lab}", fontsize=7)
        if q == "f1":
            ax.set_xscale("log"); ax.set_yscale("log")
    axes[0].legend(loc="upper left", fontsize=6)
    ps.panel_labels(axes)
    return fig


def main():
    items = designs()
    # 2D：各侧板厚度
    rows2d = {}
    for tsp in THICK:
        res = EV.evaluate([dict(it, variant={"side_plate": tsp}, note=f"S2cal side plate {tsp}") for it in items],
                          campaign="S2_sideplate_cal", provenance="sampled")
        rows2d[tsp] = res
    # 3D
    res3 = E3.evaluate([dict(it, tag="S2cal") for it in items], h=2.0, max_parallel=2)
    out, rho_rows, table = {}, [], []
    for tsp in THICK:
        rho = {}
        for t in "ABC":
            idx = [i for i, it in enumerate(items) if it["dorr"] == t
                   and rows2d[tsp][i]["status"] == "OK" and res3[i]["status"] == "OK"]
            for q, k2, k3 in (("f1", "f1_p95_um", "f1_p95_um"), ("f2", "f2_g7_loss_pct", "f2_g7_loss_pct")):
                a = [EV.as_float(rows2d[tsp][i], k2) for i in idx]
                b = [float(res3[i][k3]) for i in idx]
                r = float(spearmanr(a, b)[0]) if len(idx) > 2 else float("nan")
                rho[(t, q)] = r
                rho_rows.append(dict(side_plate=tsp, dorr=t, objective=q, rho=r, n=len(idx)))
        vals = [v for v in rho.values() if not np.isnan(v)]
        out[tsp] = {"mean_rho": float(np.mean(vals)), "min_rho": float(np.min(vals)),
                    "rho": {f"{t}_{q}": v for (t, q), v in rho.items()}}
    best = max(out, key=lambda k: out[k]["mean_rho"])
    for r in rho_rows:
        r["chosen"] = best
    json.dump({"thicknesses": THICK, "results": {str(k): v for k, v in out.items()}, "chosen": best,
               "n_per_type": N_PER_TYPE}, open(ROOT / "results" / "S2_sideplate_calibration.json", "w"), indent=1)
    ps.publish_figure("R2-F11", rho_rows, plot_r2_f11,
                      sources={"runs_csv": "campaign S2_sideplate_cal", "runs3d": "results/runs3d.jsonl (tag S2cal)"},
                      title=(f"A {best:g} mm side plate gives the best 2D–3D rank agreement "
                             f"(mean ρ {out[best]['mean_rho']:.2f}, worst {out[best]['min_rho']:.2f})"),
                      caption=("每型 12 个过几何门的 Sobol 设计（与 R2-F10 相同）分别用 2D（侧板 0–6 mm）与理想化 3D（界面 2 mm，无侧板）计算，"
                               "纵轴为 2D 与 3D 同一目标的 Spearman 秩相关。点线为选定厚度（三型 × 两目标 6 个 ρ 的平均最大）。"))
    sc = []
    for i, it in enumerate(items):
        a, b = rows2d[best][i], res3[i]
        if a["status"] == "OK" and b["status"] == "OK":
            sc.append(dict(dorr=it["dorr"], f1_2d=EV.as_float(a, "f1_p95_um"), f1_3d=b["f1_p95_um"],
                           f2_2d=EV.as_float(a, "f2_g7_loss_pct"), f2_3d=b["f2_g7_loss_pct"]))
    ps.publish_figure("R2-F12", sc, plot_r2_f12, sources={"runs_csv": "campaign S2_sideplate_cal"},
                      title=f"With a {best:g} mm side plate, 2D and 3D values for the calibration designs",
                      caption="选定侧板厚度下 36 个校准设计的 2D 与 3D 目标值（f1 对数轴）。只看排序，不看绝对值。")
    cfg = (ROOT / "config.yaml").read_text(encoding="utf-8")
    cfg2 = re.sub(r"(\n  thickness: )[0-9.]+( +# mm)", lambda m: f"{m.group(1)}{best:.1f}{m.group(2)}", cfg, count=1)
    if cfg2 != cfg:
        cfg2 = cfg2.replace("side_plate:                            # 2026-09-27 新增",
                            f"side_plate:                            # 2026-09-27 按 2D–3D 秩相关校准为 {best:g} mm（R2-F11）；新增")
        (ROOT / "config.yaml").write_text(cfg2, encoding="utf-8")
    print(json.dumps({"chosen": best, **{str(k): (round(v["mean_rho"], 3), round(v["min_rho"], 3)) for k, v in out.items()}}))


if __name__ == "__main__":
    main()
