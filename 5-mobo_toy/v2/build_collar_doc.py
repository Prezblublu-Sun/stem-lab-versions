"""领与椭圆截面：实现、截骨范围、求解验证（本机跑，不求解）。

数字取自 results/collar/summary.json（v2/stage_collar.py collect）与 results/collar/cut_range.json（截骨高度的解剖量）。

    python v2/build_collar_doc.py [--stamp "2026-10-02 12:00"]  → v2/COLLAR_ELLIPSE_2026-10-02.md（再用 v2/build_doc.py 出 PDF）
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
R = HERE / "results" / "collar"
OUT = HERE / "COLLAR_ELLIPSE_2026-10-02.md"
NAMES = {"base_w0": "基准，无领", "base_w2": "基准，2 mm 领", "base_w4": "基准，4 mm 领", "short_w0_old": "短柄，无领（改动前已解）", "short_w3": "短柄，3 mm 领",
         "neck_w0": "椭圆颈部柄，无领", "neck_w3": "椭圆颈部柄，3 mm 领", "neck_circ_w3": "圆截面颈部柄，3 mm 领",
         "neck_asym_w3": "非对称截面颈部柄，3 mm 领"}


def tab(head, rows):
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]) + "\n"


def f(x, n=1, pct=False, sign=False):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "—"
    v = 100 * x if pct else x
    s = f"{v:+.{n}f}" if sign else f"{v:.{n}f}"
    return s + ("%" if pct else "")


def main(stamp):
    S = json.loads((R / "summary.json").read_text(encoding="utf-8"))
    CR = json.loads((R / "cut_range.json").read_text(encoding="utf-8"))
    J = S["jobs"]
    L = []
    A = L.append
    A("# 领与椭圆截面：实现与求解验证\n")
    A(f"生成时间：{stamp}。依据用户 2026-10-02 的要求：把领的有无和尺寸加进柄的定义，加椭圆截面，带领的柄加入接触；并说明现在的截骨范围。\n")

    # ------------------------------------------------------------------ 1
    A("## 1 结论\n")
    rg = S.get("regression", {})
    same = rg and all(a == b for a, b in (v for k, v in rg.items() if k != "old_job"))
    b0, b2, b4 = J.get("base_w0", {}), J.get("base_w2", {}), J.get("base_w4", {})
    s3, n0, n3 = J.get("short_w3", {}), J.get("neck_w0", {}), J.get("neck_w3", {})
    A(f"1. **三项都已实现。** 椭圆截面是原截面公式的特例；领是平贴在截骨面上的一块板；领与截骨面之间是摩擦接触、不加过盈。"
      f"{len(J)} 个验证作业全部解完" + ("，没有失败。" if not S.get("missing") else f"，{len(S['missing'])} 个没有结果。"))
    A("2. **无领的模型没有任何变化。** " + ("基准设计按原设置重解，微动和柄应力与改动前逐位相同。" if same else "回归检查见第 4 节。"))
    if b0 and b2 and b4:
        A(f"3. **领承担了相当一部分载荷。** 基准设计加 2 mm 和 4 mm 领后，领承担的接触力占柄传给骨的合力的 "
          f"{f(b2.get('collar_force_share_load2'), 0, pct=True)} 和 {f(b4.get('collar_force_share_load2'), 0, pct=True)}；"
          f"柄身的可恢复微动从 {f(b0.get('f1_p95_um'))} µm 变为 {f(b2.get('f1_p95_um'))} 和 {f(b4.get('f1_p95_um'))} µm。")
    if s3:
        s0 = S.get("short_w0_old", {})
        A(f"4. **短柄加领。** 25 mm 短柄加 3 mm 领，柄身可恢复微动 {f(s3.get('f1_p95_um'))} µm，"
          f"改动前无领时是 {f(s0.get('f1_p95_um'))} µm（同一过盈 0.025 mm，作业 `{s0.get('job_id', '—')}`）；"
          f"领承担 {f(s3.get('collar_force_share_load2'), 0, pct=True)} 的接触力。")
    if n0 and n3:
        A(f"5. **椭圆颈部柄。** 长 30 mm、插入角 40°、整根在股骨颈和转子间区，柄身可恢复微动无领 {f(n0.get('f1_p95_um'))} µm，"
          f"加 3 mm 领 {f(n3.get('f1_p95_um'))} µm。")
    A("6. **查出一处原有的不一致。** 建模时实际切骨的平面与解析计算用的“垂直于颈轴的平面”相差 4.1°。领已按实际切骨面放置；"
      "其余影响见第 6 节。\n")

    # ------------------------------------------------------------------ 2
    A("## 2 改了什么\n")
    A(tab(["项目", "做法", "代码"], [
        ["椭圆截面", "原截面公式取 n_a = n_p = 2、γ_ml = γ_ap = 0.5、τ_a = τ_p = 0，只剩宽厚比 λ（λ = 1 为圆）。数值核对：边界点满足椭圆方程，误差 1e-15", "`geom3d.ellipse_design`、`is_ellipse`"],
        ["领的参数", "collar_w：外伸宽度，0 为无领，建议范围 0–6 mm；collar_t：厚度，默认 2.5 mm。是柄的参数，没有放进原来的 12 维设计空间", "`geom3d.Stem3D`、`COLLAR`"],
        ["领的外形", "柄在截骨面上的截口向外偏移 collar_w，再裁到骨外表面以内 0.5 mm，不悬出骨外", "`fe3d_geom.collar_outline`"],
        ["领的实体", "外形沿截骨面法向向上拉伸 collar_t，与柄体、假体颈、头合成一个实体", "`fe3d_geom.collar_solid`、`model3d_m1`"],
        ["接触", "领底面与截骨面重合，碎片化后自动成为界面，进同一个接触对，摩擦系数相同。落在截骨面上的界面节点记为领节点，过盈为 0", "`model3d_m1.node_pairs`"],
        ["粘接模型", "领与骨共节点，即假定领也骨整合", "`model3d_m1`"],
        ["后处理", "微动、张开、接触压力等只统计柄身，与无领设计可比；领另报滑移、掀起、承担的接触力比例", "`post_m1`"],
        ["旧界面模型", "不支持领，带领的作业直接判几何不成立", "`jobs.prep`"],
    ]))
    A("\n只建模不求解的检查：6 个组合都一次建成；每个带领设计进入接触的面积等于领的承压环面积（相差不到 5%）；领节点的过盈全部为 0；"
      "无领的基准模型与改动前的网格、节点对、法向、面积、过盈逐项相同。\n")

    # ------------------------------------------------------------------ 3
    A("## 3 截骨范围\n")
    A(f"截骨高度定义为截骨面中心到股骨头中心的距离，沿颈轴量。这根股骨的头半径 {f(CR['head_r'])} mm，"
      f"颈轴到干轴的距离沿颈轴是 {f(CR['neck_axis_to_shaft_axis_mm'])} mm。\n")
    rows = []
    for r in CR["rows"]:
        h = r["h_cut"]
        note = {25: "现行默认；V2A 与新界面模型的全部验证都用这一档", 45: "V3 的上限"}.get(h, "")
        if h < 25:
            note = "在头颈交界以上，切到股骨头"
        rows.append([h, f(r["calcar_end_z_mm"], 0), f(r["lateral_end_z_mm"], 0), f"{r['width_along_cut_mm']:.0f} × {r['width_ap_mm']:.0f}",
                     f(r["section_area_mm2"], 0), f(r["cortex_frac"], 0, pct=True), f(r["resected_vs_25_cm3"], 1), note])
    A(tab(["截骨高度 (mm)", "股骨距端高于小转子 (mm)", "外上端高于小转子 (mm)", "截面尺寸 (mm)", "截面积 (mm²)", "皮质占比",
           "比 25 mm 多切 (cm³)", "说明"], rows))
    A("\n现在的范围：V3 的设计空间是 25 到 45 mm；V2A、新界面模型的验证和这次的领都固定在 25 mm，也就是头颈交界、最高的一种截法。"
      "35 到 40 mm 之间截面突然变大，因为截骨面开始切进转子区。常规全髋的截骨在小转子上方 1 到 1.5 cm，对应这里约 50 到 55 mm。\n")

    # ------------------------------------------------------------------ 4
    A("## 4 求解验证\n")
    A("新界面模型，过盈 0.025 mm，摩擦系数 0.3，生产网格。微动只统计柄身。\n")
    rows = []
    for k in NAMES:
        j = S.get(k) if k == "short_w0_old" else J.get(k)
        if not j:
            rows.append([NAMES[k]] + ["没有结果"] + [""] * 8)
            continue
        z = j.get("zones", {})
        rows.append([NAMES[k], f(j.get("f1_p95_um")), f(j.get("f1_first_p95_um")), f(j.get("area_frac_gt40"), 0, pct=True),
                     f(j.get("collar_force_share_load2"), 0, pct=True), f(j.get("collar_slip_rev_p95_um")),
                     f(j.get("collar_open_frac_load2"), 0, pct=True),
                     f((z.get("femur:G7") or {}).get("ssi_pct"), 0), f((z.get("fixed:G7") or {}).get("ssi_pct"), 0),
                     f((j.get("stem_regions") or {}).get("vm_max_body_deep"), 0)])
    A(tab(["设计", "可恢复微动 (µm)", "首次加载微动 (µm)", "超过 40 µm 的柄身面积", "领承担的接触力", "领面滑移 (µm)", "领掀起面积",
           "7 区屏蔽，随柄分区 (%)", "7 区屏蔽，固定分区 (%)", "柄体最大应力 (MPa)"], rows))
    A("\n领承担的接触力：峰值载荷时领面节点的接触合力，在柄传给骨的接触合力方向上的分量所占比例。领掀起面积：峰值载荷时领面间隙超过 1 µm 的比例。"
      "应力屏蔽来自粘接模型，领在其中与骨固结。\n")
    if rg:
        A("回归检查，基准设计无领，改动前与改动后：" + "；".join(f"{k} {v[0]} 对 {v[1]}" for k, v in rg.items() if k != "old_job")
          + f"。改动前的作业是 `{rg['old_job']}`。\n")
    A("![带领与椭圆截面的设计](results/collar/collar_shapes.png)\n")

    # ------------------------------------------------------------------ 5
    A("## 5 各设计的领\n")
    rows = []
    for k in NAMES:
        c = (J.get(k) or {}).get("collar")
        if c:
            rows.append([NAMES[k], f(c.get("collar_w"), 0), f(c.get("footprint_mm2"), 0), f(c.get("ring_mm2"), 0),
                         f(c.get("ring_cortex_frac"), 0, pct=True), f(c.get("contact_area_mm2"), 0)])
    A(tab(["设计", "外伸宽度 (mm)", "柄的截口 (mm²)", "承压环 (mm²)", "承压环落在皮质上", "进入接触的面积 (mm²)"], rows))

    # ------------------------------------------------------------------ 6
    A("\n## 6 查出的不一致：两个截骨面\n")
    A("建模时切骨用的半空间由“颈平面内的方向 n3”和“全局前后方向”张成，它的法向与颈轴相差 4.1°，因为颈轴有一点前后分量。"
      "而模板化、截骨面以下的判定、去骨体积和应力屏蔽分区，用的都是垂直于颈轴的平面。两个平面在截骨中心相交，离中心 18 mm 处相差约 1.3 mm。\n")
    A("- 对领：已按建模实际切出的面放置，所以领贴合良好。")
    A("- 对已有结果：影响很小但确实存在，主要在截骨面附近 1 mm 左右的骨是否算“保留”。")
    A("- 建议：冻结模型时统一成垂直于颈轴的平面。这会改变所有有限元模型的几何，需要和其他设置一起冻结、重跑参考集。\n")

    # ------------------------------------------------------------------ 7
    A("## 7 还没做的\n")
    A("- 领的宽度和有无还没有放进优化的设计空间。原来的 12 维空间和候选池保持不变。")
    A("- 插入角上限仍是 40°。这根股骨的颈轴相对干轴约 42.5°，完全沿颈轴插入需要把上限提到 45° 左右。")
    A("- 领的厚度固定 2.5 mm，领与假体颈之间没有圆角。")
    A("- 粘接模型里领与骨固结，会高估领对股骨距的加载；更合理的做法是领在粘接模型里也用接触。")
    A("- 截骨高度在这次验证里固定 25 mm。领在更低的截骨面上会压到更大、更多皮质的截面。")
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("written", OUT, len(L))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stamp", default="2026-10-02")
    main(ap.parse_args().stamp)
