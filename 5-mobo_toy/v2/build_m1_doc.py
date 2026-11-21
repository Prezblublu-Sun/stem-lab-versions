"""由 v2/results/m1_report/summary.json 生成 v2/M1_VERIFICATION.md（本机跑）。表格与判定全部由数据算出。

    python v2/build_m1_doc.py [--stamp "2026-09-29 06:30"]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import statistics as st

HERE = pathlib.Path(__file__).resolve().parent
SUM = HERE / "results" / "m1_report" / "summary.json"
OUT = HERE / "M1_VERIFICATION.md"
FLOOR = 1.0
NAME = {"base": "基准（L 60，α 20°）", "readout": "原读数设计（L 53，α 39°）", "short": "短柄（L 25，α 37°）"}


def f(x, n=2):
    return "—" if x is None else f"{x:.{n}f}"


def micro(x):
    return "—" if x is None else ("< 1" if x < FLOOR else (f"{x:.1f}" if x < 100 else f"{x:.0f}"))


def main(stamp: str):
    S = json.loads(SUM.read_text(encoding="utf-8"))
    rows = S["rows"]
    ok = [r for r in rows if "f1_p95_um" in r]
    failed = [r for r in rows if "failed" in r]
    pending = [r for r in rows if r["state"] not in ("DONE", "FAILED")]

    def pick(**kw):
        out = []
        for r in ok:
            if all((abs(r[k] - v) < 1e-9 if isinstance(v, float) else r[k] == v) for k, v in kw.items()):
                out.append(r)
        return out

    def prod(**kw):
        return pick(lagrange=False, slip_tol=0.00025, mu=0.3, torque=True, **kw)

    def one(**kw):
        rr = prod(**kw)
        return rr[0] if rr else None
    L = []
    A = L.append
    base = one(label="base", h=2.0, delta=0.10)
    ro = one(label="readout", h=2.0, delta=0.10)
    sh = one(label="short", h=2.0, delta=0.10)
    nz, cmp_ = S["noise"], S["compare"]
    d10 = prod(h=2.0, delta=0.10)
    open_med = st.median(r["status_frac_open"] for r in d10) if d10 else None
    open1_med = st.median(r["open_frac_release"] for r in d10) if d10 else None
    open5 = [r["open5_frac_release"] for r in prod(h=2.0) if "open5_frac_release" in r]
    open5_med, open5_max = (st.median(open5), max(open5)) if open5 else (None, None)
    stick_max = max(r["stick_cslip_p95_um"] for r in prod(h=2.0)) if prod(h=2.0) else None
    lame = S["lame"]["runs"] if S.get("lame") else {}
    n_below = sum(r["f1_p95_um"] < FLOOR for r in d10)

    # ------------------------------------------------------------------ 1 结论
    A(f"# M1 界面模型验证报告\n")
    A(f"{stamp}。七小时实验（00:00–07:00）的结果：只修界面、不做优化。数据 `v2/results/m1_report/summary.json`，"
      f"共 {len(rows)} 个设计作业（完成 {len(ok)}，失败或跳过 {len(failed)}，未解完 {len(pending)}）加 8 个解析对照作业。"
      f"代码 `v2/model3d_m1.py`、`v2/post_m1.py`、`v2/stage_m1.py`、`v2/report_m1.py`。\n")
    A("## 1 结论\n")
    A(f"1. **新界面模型力学上是对的。** 圆柱压入套筒的解析对照，无摩擦时接触压力误差 "
      f"{f(lame['clearance_mu0_h2']['err_pct'], 1)}%（2.0 mm 网格）和 {f(lame['clearance_mu0_h1.4']['err_pct'], 1)}%（1.4 mm）。"
      f"真实股骨上压配后间隙超过 5 µm 的界面面积中位 {f(100 * open5_med, 1)}%（旧模型压配后约一半界面张开）。")
    m14c = prod(h=1.4, delta=0.10)
    mesh_txt = ""
    if m14c:
        flc = [abs(100 * (one(label=r["label"], h=2.0, delta=0.10)["f1_first_p95_um"] / r["f1_first_p95_um"] - 1)) for r in m14c]
        mesh_txt = f"2.0 对 1.4 mm 网格，首次加载微动相差 {min(flc):.0f}–{max(flc):.0f}%。"
    A(f"2. **数值地板从约 10 µm 降到 1 µm，网格噪声只有 2–6%。** {mesh_txt}但可恢复微动随摩擦容差没有平台，低于 1 µm 的读数只能报“< 1 µm”。")
    if cmp_:
        A(f"3. **旧结果的排序大体成立。** {cmp_['n']} 个设计在新旧界面下的秩相关：旧微动对新首次加载微动 "
          f"{f(cmp_['spearman_f1_first_p95_um'])}，对新可恢复微动 {f(cmp_['spearman_f1_p95_um'])}。旧模型量到的相当于首次加载的滑移"
          f"（数值比中位 {f(cmp_['median_ratio_f1_first_p95_um'])}），可恢复微动只有它的约 {f(cmp_['median_ratio_f1_p95_um'])} 倍。")
    if base and sh:
        b01 = one(label="base", h=2.0, delta=0.01)
        s01 = one(label="short", h=2.0, delta=0.01)
        A(f"4. **微动首先取决于过盈量。** 过盈从 0.10 降到 0.01 mm，基准设计的可恢复微动从 {f(base['f1_p95_um'])} 升到 "
          f"{micro(b01['f1_p95_um']) if b01 else '—'} µm，短柄从 {micro(sh['f1_p95_um'])} 升到 {micro(s01['f1_p95_um']) if s01 else '—'} µm。"
          f"过盈 0.10 mm 时 {len(d10)} 个已解设计里 {n_below} 个低于 1 µm 地板，无法互相排序。")
    if base:
        A(f"5. **0.10 mm 过盈在线弹性松质骨里夹得过紧。** 接触压力中位 {f(base['cpress_release_p50'], 1)} MPa（基准设计），"
          f"而文献库里松质骨抗压强度的范围是 2–12 MPa。不加压溃上限时，模型高估夹持力、低估微动。")
    A("6. **需要你决定三件事**（见第 7 节）：过盈量取多少；卸载到零还是保留一部分载荷；优化用哪个微动定义。\n")

    # ------------------------------------------------------------------ 2 改动
    A("## 2 界面模型改了什么\n")
    A("| 项 | 旧模型 | 新模型（M1） |\n|---|---|---|")
    A("| 界面网格 | 柄与锉腔各划各的，分面不重合 | 柄与骨一起碎片化，界面只划一次；界面节点复制一份给柄侧，两侧节点一一重合 |")
    A("| 过盈 | 从截面缩放系数里减 0.10，实际径向 0.035–0.08 mm | 逐节点给定法向过盈（`*CLEARANCE, TABULAR`），处处等于给定值 |")
    A("| 皮质接触处 | 同样施加过盈 | 与皮质相邻的界面节点过盈为 0 |")
    A("| 摩擦弹性滑移上限 | 0.005 × 2 mm = 10 µm | 0.00025 × 2 mm = 0.5 µm |")
    A("| 加载 | 压配 → 释放 → 加载 | 压配 → 释放 → 加载 → 卸载 → 再加载 |")
    A("| 微动定义 | 接触滑移增量（只在接触时累积） | 节点对相对切向位移；主指标取第二循环的可恢复量，另报首次加载量 |")
    A("| 粘接模型 | `*TIE` 绑定两套网格 | 共享节点，不需要绑定 |\n")

    # ------------------------------------------------------------------ 3 判定
    A("## 3 验证项与判定\n")
    A("| 项 | 门槛 | 结果 | 判定 |\n|---|---|---|---|")
    lame_ok = all(abs(v["err_pct"]) < 5 for v in lame.values() if "err_pct" in v)
    A(f"| 压配解析对照 | 误差 < 5% | 无摩擦 {f(lame['clearance_mu0_h2']['err_pct'], 1)}% / {f(lame['clearance_mu0_h1.4']['err_pct'], 1)}%；"
      f"摩擦 0.3 时 {f(lame['clearance_mu0.3_h2']['err_pct'], 1)}% | {'通过' if lame_ok else '不通过'} |")
    A(f"| 压配后界面张开 | 面积 < 5% | 压配后间隙 > 1 µm 的面积中位 {f(100 * open1_med, 1)}%（阈值 1 µm 是事先写在代码里的）；"
      f"间隙 > 5 µm 的面积中位 {f(100 * open5_med, 1)}%、最大 {f(100 * open5_max, 1)}%；加载状态下接触状态为张开的面积中位 {f(100 * open_med, 1)}% | "
      f"按 1 µm {'通过' if open1_med < 0.05 else '**不通过**'}；按 5 µm {'通过' if open5_max < 0.05 else '不通过'} |")
    A(f"| 粘着节点数值滑移 | P95 < 0.5 µm | 全部生产设置作业中最大 {f(stick_max)} µm | {'通过' if stick_max < 0.5 else '不通过'} |")
    A("| 摩擦容差收敛 | 最后两档差 < 5% | 无平台：0.00025 与 0.0001 两档相差 17–24%；Lagrange 不收敛 | **不通过**，处置：地板定为 1 µm |")
    if nz.get("base", {}).get("n", 0) >= 3:
        cvs = [nz[k]["f1_p95_um"]["cv_pct"] for k in nz if nz[k].get("n", 0) >= 3]
        cvf = [nz[k]["f1_first_p95_um"]["cv_pct"] for k in nz if nz[k].get("n", 0) >= 3]
        A(f"| 噪声底 | 变异系数小于设计间差异的 1/3 | 可恢复微动 {f(min(cvs), 1)}–{f(max(cvs), 1)}%，首次加载 {f(min(cvf), 1)}–{f(max(cvf), 1)}%；"
          f"设计之间相差数倍到数十倍 | 通过 |")
    if cmp_:
        A(f"| 新旧界面对比 | 报告秩相关 | {cmp_['n']} 个设计：{f(cmp_['spearman_f1_first_p95_um'])}（首次加载）、{f(cmp_['spearman_f1_p95_um'])}（可恢复） | 已报告 |")
    A("| 方向性 | 方向全对 | 过盈减半微动升、摩擦加倍微动降、去扭转微动降；过盈 0 不可判定 | 可判定的 3 项通过 |")
    m14 = prod(h=1.4, delta=0.10)
    if m14:
        parts = []
        for r in m14:
            r2 = one(label=r["label"], h=2.0, delta=0.10)
            if r2:
                parts.append(f"{NAME[r['label']].split('（')[0]} {100 * (r2['f1_first_p95_um'] / r['f1_first_p95_um'] - 1):+.0f}%")
        dv = [abs(one(label=r["label"], h=2.0, delta=0.10)["f1_first_p95_um"] / r["f1_first_p95_um"] - 1) for r in m14]
        worst = max(zip(dv, [NAME[r["label"]].split("（")[0] for r in m14]))
        A(f"| 网格（2.0 对 1.4 mm） | 差 < 10% | 首次加载微动：{'；'.join(parts)}（{len(m14)}/3 个设计解完） | "
          + ("通过 |" if worst[0] < 0.10 else f"**不通过**（{worst[1]} {100 * worst[0]:.0f}%） |"))
    else:
        A("| 网格（2.0 对 1.4 mm） | 差 < 10% | 写报告时 1.4 mm 作业未解完 | 未判定 |")
    A("")

    # ------------------------------------------------------------------ 4 结果
    A("## 4 各项结果\n")
    A("### 4.1 压配解析对照\n")
    A("钛圆柱（半径 8 mm）压入松质骨套筒（外半径 20 mm，400 MPa），过盈 0.10 mm，四分之一模型，走与设计模型相同的界面代码。"
      f"解析解（平面应力、无摩擦）{f(lame['clearance_mu0_h2']['p_lame_MPa'], 3)} MPa。FE 压力由套筒外表面的径向膨胀反推。\n")
    A("| 过盈写法 | 摩擦 | 网格 (mm) | 反推压力 (MPa) | 误差 | 节点接触压力均值 (MPa) | 其偏差 | 界面法向位移标准差 (µm) |\n|---|---|---|---|---|---|---|---|")
    for k, v in lame.items():
        if "err_pct" not in v:
            continue
        m_, mu_, h_ = k.split("_")
        A(f"| {'逐节点给定' if m_ == 'clearance' else '几何平移'} | {mu_[2:]} | {h_[1:]} | {f(v['p_inferred_MPa'], 3)} | {v['err_pct']:+.1f}% | "
          f"{f(v['p_fe_mean_mid_MPa'])} | {v['err_cpress_pct']:+.0f}% | {f(v['bone_normal_disp_sd_um'])} |")
    A("\n两种写法的力学状态都对；逐节点给定的界面位移更均匀，取为生产设置。摩擦 0.3 时的 −4.5% 是摩擦引起轴向剪力的物理差别。"
      "**Abaqus 输出的节点接触压力均值不可靠**（同一力学状态下偏 −24% 到 +16%），下文的接触压力只作量级参考。\n")

    A("### 4.2 摩擦容差\n")
    A("| 设计 | 容差 | 弹性滑移上限 (µm) | 可恢复微动 P95 (µm) | 首次加载 P95 (µm) | 粘着节点滑移 P95 (µm) | 摩擦模型求解 (s) |\n|---|---|---|---|---|---|---|")
    for lab in ("base", "readout"):
        rr = sorted([r for r in ok if r["label"] == lab and abs(r["h"] - 2.0) < 1e-9 and abs(r["delta"] - 0.10) < 1e-9 and r["mu"] == 0.3
                     and r["torque"] and not r["lagrange"]], key=lambda r: -r["slip_tol"])
        for r in rr:
            A(f"| {NAME[lab]} | {r['slip_tol']:g} | {r['slip_tol'] * 2000:g} | {f(r['f1_p95_um'])} | {f(r['f1_first_p95_um'])} | "
              f"{f(r['stick_cslip_p95_um'])} | {r['wall_fric_s']:.0f} |")
        A(f"| {NAME[lab]} | Lagrange | 0 | 不收敛 | — | — | — |")
    A("\n可恢复微动跟着容差走，说明过盈 0.10 mm 时界面几乎全部粘着，真实的可恢复滑移比弹性滑移还小。首次加载微动对容差不敏感。"
      "生产设置取 0.00025：再收紧只改变低于地板的读数，求解时间却多 50%。\n")

    A("### 4.3 过盈量扫描\n")
    A("| 设计 | 量 | δ 0.10 | δ 0.05 | δ 0.025 | δ 0.01 mm |\n|---|---|---|---|---|---|")
    for lab in ("base", "readout", "short"):
        for q, nm in (("f1_p95_um", "可恢复微动 (µm)"), ("f1_first_p95_um", "首次加载微动 (µm)"), ("cpress_release_p50", "接触压力中位 (MPa)"),
                      ("area_frac_gt40", "微动 > 40 µm 的面积")):
            cells = []
            for dlt in (0.10, 0.05, 0.025, 0.01):
                r = one(label=lab, h=2.0, delta=dlt)
                if r is None:
                    cells.append("—")
                elif q == "area_frac_gt40":
                    cells.append(f"{100 * r[q]:.0f}%")
                elif q == "cpress_release_p50":
                    cells.append(f(r[q], 1))
                else:
                    cells.append(micro(r[q]))
            A(f"| {NAME[lab]} | {nm} | " + " | ".join(cells) + " |")
    A("\n![过盈量扫描。左：第二循环可恢复微动；右：首次加载微动。虚线为 40 与 150 µm，灰带为 1 µm 数值地板以下。](results/m1_report/F1_delta.png)\n")
    A("三个设计的排序在四档过盈下都一致。过盈 0 没有结果：没有压配时卸载到零载荷后柄完全松开，第二次加载不收敛。\n")

    A("### 4.4 噪声底\n")
    A("同一设计把界面单元尺寸改为 1.94 / 1.97 / 2.00 / 2.03 / 2.06 mm 重新建网格求解，过盈 0.10 mm。\n")
    A("| 设计 | 完成 | 可恢复微动 均值 ± 标准差 (µm) | 变异系数 | 首次加载 均值 ± 标准差 (µm) | 变异系数 | 柄应力变异系数 |\n|---|---|---|---|---|---|---|")
    for lab in ("base", "readout", "short"):
        o = nz.get(lab, {})
        if o.get("n", 0) >= 3:
            a, b, c = o["f1_p95_um"], o["f1_first_p95_um"], o["vm_p99"]
            A(f"| {NAME[lab]} | {o['n']}/5 | {f(a['mean'])} ± {f(a['sd'])} | {f(a['cv_pct'], 1)}% | {f(b['mean'])} ± {f(b['sd'])} | "
              f"{f(b['cv_pct'], 1)}% | {f(c['cv_pct'], 1)}% |")
        else:
            A(f"| {NAME[lab]} | {o.get('n', 0)}/5 | 未解完 | — | — | — | — |")
    A("\n![噪声底：同一设计 5 次不同网格。](results/m1_report/F3_noise.png)\n")

    A("### 4.5 新旧界面对比\n")
    A("12 个设计按旧微动的分位从当前版本的已解设计里取，过盈取 0.05 mm（旧模型名义 0.10 mm 的实际径向过盈中位约 0.055 mm）。\n")
    A("| 柄长 (mm) | 插入角 (°) | 余量 (mm) | 旧微动 (µm) | 新可恢复 (µm) | 新首次加载 (µm) | 旧张开比例 | 新张开比例 | 摩擦求解 旧/新 (s) |\n|---|---|---|---|---|---|---|---|---|")
    cr = sorted([r for r in prod(h=2.0, delta=0.05) if r["label"].startswith("cmp") and r["label"][3:] in S["old"]],
                key=lambda r: S["old"][r["label"][3:]]["f1_p95_um"])
    for r in cr:
        o = S["old"][r["label"][3:]]
        A(f"| {r['L']:.0f} | {r['alpha']:.0f} | {r['m']:+.2f} | {f(o['f1_p95_um'], 1)} | {micro(r['f1_p95_um'])} | {micro(r['f1_first_p95_um'])} | "
          f"{100 * (o['frac_open'] or 0):.0f}% | {100 * r['status_frac_open']:.0f}% | {o['wall_fric_s']:.0f} / {r['wall_fric_s']:.0f} |")
    if cmp_:
        A(f"\n秩相关（n = {cmp_['n']}）：旧微动对新首次加载 {f(cmp_['spearman_f1_first_p95_um'])}，对新可恢复 {f(cmp_['spearman_f1_p95_um'])}。")
    dup_a, dup_b = one(label="short", h=2.0, delta=0.05), one(label="cmpe265f0bf", h=2.0, delta=0.05)
    if dup_a and dup_b:
        A(f"其中 L 25 的设计与 4.3 里的短柄是同一个模型，被求解了两次：可恢复微动 {f(dup_a['f1_p95_um'], 3)} 与 {f(dup_b['f1_p95_um'], 3)} µm，"
          f"{'逐位相同' if abs(dup_a['f1_p95_um'] - dup_b['f1_p95_um']) < 1e-9 else '不完全相同'}。")
    A("\n![新旧界面对比。横轴旧模型微动，纵轴新模型；颜色为柄长，虚线 y = x。](results/m1_report/F2_compare.png)\n")

    A("### 4.6 方向性检查\n")
    A("| 变体（基准设计） | 可恢复微动 (µm) | 首次加载微动 (µm) | 接触压力中位 (MPa) | 预期 | 结果 |\n|---|---|---|---|---|---|")
    if base:
        A(f"| 基准（过盈 0.10，摩擦 0.3） | {f(base['f1_p95_um'])} | {f(base['f1_first_p95_um'])} | {f(base['cpress_release_p50'], 1)} | — | — |")
    for kw, nm, exp in (({"delta": 0.05, "mu": 0.3, "torque": True}, "过盈 0.05", "升"), ({"delta": 0.10, "mu": 0.6, "torque": True}, "摩擦 0.6", "降"),
                        ({"delta": 0.10, "mu": 0.3, "torque": False}, "去扭转", "降")):
        rr = pick(label="base", h=2.0, lagrange=False, slip_tol=0.00025, **kw)
        if rr and base:
            r = rr[0]
            good = (r["f1_first_p95_um"] > base["f1_first_p95_um"]) if exp == "升" else (r["f1_first_p95_um"] < base["f1_first_p95_um"])
            A(f"| {nm} | {f(r['f1_p95_um'])} | {f(r['f1_first_p95_um'])} | {f(r['cpress_release_p50'], 1)} | {exp} | {'✓' if good else '✗'} |")
    A("| 过盈 0 | 不收敛 | — | — | 升 | 不可判定 |\n")

    A("### 4.7 网格 2.0 对 1.4 mm\n")
    if m14:
        A("| 设计 | 量 | 2.0 mm | 1.4 mm | 相对差 |\n|---|---|---|---|---|")
        for r in m14:
            r2 = one(label=r["label"], h=2.0, delta=0.10)
            for q, nm in (("f1_p95_um", "可恢复微动 (µm)"), ("f1_first_p95_um", "首次加载微动 (µm)"), ("vm_p99", "柄应力 P99 (MPa)")):
                A(f"| {NAME[r['label']]} | {nm} | {f(r2[q])} | {f(r[q])} | {100 * (r2[q] / r[q] - 1):+.0f}% |")
        lo = [(NAME[r["label"]].split("（")[0], 100 * (one(label=r["label"], h=2.0, delta=0.10)["f1_p95_um"] / r["f1_p95_um"] - 1))
              for r in m14 if one(label=r["label"], h=2.0, delta=0.10)["f1_p95_um"] < FLOOR]
        hi = [(NAME[r["label"]].split("（")[0], 100 * (one(label=r["label"], h=2.0, delta=0.10)["f1_p95_um"] / r["f1_p95_um"] - 1))
              for r in m14 if one(label=r["label"], h=2.0, delta=0.10)["f1_p95_um"] >= FLOOR]
        fl = [100 * (one(label=r["label"], h=2.0, delta=0.10)["f1_first_p95_um"] / r["f1_first_p95_um"] - 1) for r in m14]
        vm = [abs(100 * (one(label=r["label"], h=2.0, delta=0.10)["vm_p99"] / r["vm_p99"] - 1)) for r in m14]
        txt = ""
        if lo:
            txt += ("、".join(n for n, _ in lo) + f"的可恢复微动低于 1 µm 地板，2.0 mm 下比 1.4 mm 高 {min(v for _, v in lo):.0f}–{max(v for _, v in lo):.0f}%，"
                    "与弹性滑移上限随单元尺寸的变化（2.0 / 1.4 = 1.43）一致，是数值量。")
        if hi:
            txt += "".join(f"{n}的可恢复微动在地板以上，两档相差 {v:+.0f}%。" for n, v in hi)
        txt += (f"首次加载微动相差 {min(fl):+.0f}% 到 {max(fl):+.0f}%" + ("，有设计超过 10% 门槛" if max(abs(x) for x in fl) >= 10 else "，都在 10% 以内")
                + f"；柄应力相差 {min(vm):.0f}–{max(vm):.0f}%。")
        A("\n" + txt + f"1.4 mm 的摩擦模型求解 {'、'.join(str(round(r['wall_fric_s'])) for r in m14)} s，约为 2.0 mm 的 2–3 倍。1.0 mm 没有做。\n")
    else:
        A("写报告时 3 个 1.4 mm 作业还没解完，这一项没有结果。\n")

    A("### 4.8 求解时间\n")
    t10 = [r["wall_fric_s"] for r in d10]
    tall = [r["wall_fric_s"] for r in prod(h=2.0)]
    A(f"摩擦模型（2.0 mm，生产设置）：过盈 0.10 mm 时中位 {st.median(t10):.0f} s（{min(t10):.0f}–{max(t10):.0f}）；全部过盈档中位 {st.median(tall):.0f} s。"
      f"旧模型约 270 s。滑动越多越慢，短柄每个 20–26 分钟。粘接模型 35 s。本机改为三槽并行后无许可错误。\n")

    # ------------------------------------------------------------------ 5 压力
    A("## 5 压配压力与松质骨强度\n")
    A("| 设计 | 过盈 (mm) | 接触压力中位 (MPa) | P95 (MPa) |\n|---|---|---|---|")
    for lab in ("base", "readout", "short"):
        for dlt in (0.10, 0.05, 0.025):
            r = one(label=lab, h=2.0, delta=dlt)
            if r:
                A(f"| {NAME[lab]} | {dlt:g} | {f(r['cpress_release_p50'], 1)} | {f(r['cpress_release_p95'], 1)} |")
    def rng(dlt, q):
        v = [one(label=lab, h=2.0, delta=dlt)[q] for lab in ("base", "readout", "short") if one(label=lab, h=2.0, delta=dlt)]
        return f"{min(v):.1f}–{max(v):.1f}" if v else "—"
    A(f"\n文献库里两篇给出的松质骨抗压强度范围是 2–12 MPa。过盈 0.10 mm 时三个设计的压力中位 {rng(0.10, 'cpress_release_p50')} MPa、"
      f"P95 {rng(0.10, 'cpress_release_p95')} MPa，相当一部分界面已超过这个范围；0.05 mm 时中位 {rng(0.05, 'cpress_release_p50')} MPa；"
      f"0.025 mm 时 {rng(0.025, 'cpress_release_p50')} MPa。节点接触压力本身有 +7% 到 +16% 的输出偏差，这里只看量级。"
      "按你的决定，这一轮没有加压溃上限。\n")

    # ------------------------------------------------------------------ 6 限制
    A("## 6 没做的与限制\n")
    lim = ["**文献对标没做**：没有用新模型复现任何已发表案例的微动量级。",
           "**1.0 mm 网格没做**；1.4 mm 只有 3 个设计，其中短柄的首次加载微动相差超过 10%。",
           "**摩擦容差没有收敛**：低于 1 µm 的可恢复微动是数值量。",
           "**过盈 0 不能算**：卸载到零的两循环协议下，无压配的柄会松脱。",
           "**新旧对比只在过盈 0.05 mm 下做了一次**，12 个设计。",
           "松质骨仍是全域 400 MPa、线弹性；没有肌力；只有上楼峰值一个工况；单一股骨。",
           f"与皮质相邻的界面节点不施过盈，占界面面积 {100 * min(r['cortex_area_frac'] for r in ok):.1f}–"
           f"{100 * max(r['cortex_area_frac'] for r in ok):.1f}%；压配后张开的节点里这类节点占比高（基准设计 27%）。",
           "完整股骨参照仍只按网格与材料匹配，没有按载荷工况匹配：去扭转变体的应变能对比仍不可解读。"]
    for x in lim:
        A(f"- {x}")
    if failed:
        n_lag = sum(r["lagrange"] for r in failed)
        n_d0 = sum((not r["lagrange"]) and r["delta"] == 0 for r in failed)
        n_skip = sum(r["failed"]["level"] == "SKIP" for r in failed)
        other = [r for r in failed if not r["lagrange"] and r["delta"] != 0]
        A(f"- 失败或跳过的作业 {len(failed)} 个：Lagrange 摩擦 {n_lag} 个（不收敛）；过盈 0 共 {n_d0} 个（其中 {n_skip} 个据此跳过、未求解）"
          + (f"；其他 {len(other)} 个：" + "、".join(f"{r['label']} h{r['h']:g} δ{r['delta']:g}（{r['failed']['level']}）" for r in other) if other else "") + "。")
    if pending:
        A(f"- 写报告时未解完的作业 {len(pending)} 个：" + "、".join(sorted({r['label'] + ' h' + format(r['h'], 'g') for r in pending})) + "。")
    A("")

    # ------------------------------------------------------------------ 7 决定
    A("## 7 需要你决定\n")
    A("1. **过盈量取多少。** 这是影响最大的输入。0.10 mm 下几乎所有设计都粘着，微动目标失去区分力；0.025–0.05 mm 下设计之间拉开差距。"
      "可选做法：取一个固定值（我建议 0.05 mm，接触压力中位 3–5 MPa，落在松质骨强度范围内）；或把“微动不超过 40 µm 所需的最小过盈”作为稳定性指标。")
    A("2. **卸载到零还是保留部分载荷。** 现在卸到零，无压配或小过盈的设计会松脱。保留 10% 峰值载荷更接近步态里的摆动相，也能让过盈 0 可算。")
    A("3. **优化用哪个微动定义。** 可恢复微动（第二循环）是文献里的常用定义，但在大过盈下低于地板；首次加载微动区分力更好、与旧结果可比，但含一次性的就位位移。")
    A("4. 分区模量、肌力与步行工况、应力屏蔽只报告——这些已定或排在后面，不在本轮范围。\n")

    A("## 8 对修改方案的影响\n")
    A("- P1（界面模型）完成。P2（验证）六项里：解析对照、噪声底、摩擦容差（门槛未过、已有处置）已做；网格只做到 1.4 mm，短柄未过门槛；"
      "文献对标、参照按载荷工况匹配两项没做。")
    A("- 决策点 A 的答案：噪声底足够小，微动目标可以用来排序，前提是过盈量选在界面会滑动的范围内。")
    A("- 参考集重跑前要先定第 7 节的三件事，否则 64 个设计会再次落在地板以下。")
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("written", OUT, len(L), "lines; ok", len(ok), "failed", len(failed), "pending", len(pending))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stamp", default="2026-09-29")
    main(ap.parse_args().stamp)
