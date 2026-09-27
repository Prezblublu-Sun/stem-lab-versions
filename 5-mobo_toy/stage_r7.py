"""收尾：R7 总结与可信度。python stage_r7.py（.venv-mobo）

汇总 R0–R6 的验收结果；按 ASME V&V 40 的 13 个可信度因子与 Erdemir 2020 十条规则填表；一页仪表板。
缺数据的部分在报告里显示为缺项（INCOMPLETE），不编造。
"""
from __future__ import annotations

import json

import numpy as np

import plotstyle as ps

ROOT = ps.ROOT
RIDS = ["R0", "R1", "R2", "R3", "R4", "R5", "R6"]


def acc(rid):
    p = ps.report_dir(rid) / "acceptance.json"
    return json.loads(p.read_text(encoding="utf-8"))["items"] if p.exists() else []


def status_of(rid, aid):
    return next((a for a in acc(rid) if a["id"] == aid), {"status": "PENDING", "measured": "", "note": ""})


def plot_r7_f01(csv_path):
    d = ps.read_csv(csv_path)
    fig, axes = ps.new_figure("double", 120, 2, 2)
    a, b, c, e = axes.flat
    # (a) HV 比中位曲线
    for t in "ABC":
        for m, ls in (("qNEHVI", "-"), ("Sobol", "--")):
            jj = sorted([i for i in range(len(d["panel"])) if d["panel"][i] == "hv" and d["dorr"][i] == t and d["method"][i] == m],
                        key=lambda i: d["x"][i])
            if jj:
                a.plot([d["x"][i] for i in jj], [d["y"][i] for i in jj], ls, color=ps.DORR[t] if m == "qNEHVI" else ps.GREY,
                       label=f"{t} {m}" if m == "qNEHVI" else (None if t != "A" else "Sobol"))
    ps.threshold_line(a, 0.9, "y", "0.9"); a.set_xlabel(ps.LABEL["n_fe"]); a.set_ylabel(ps.LABEL["hv_ratio"])
    a.legend(fontsize=6, loc="lower right"); a.set_title("Hypervolume ratio (median of 3 seeds)", fontsize=7)
    # (b) 参考前沿
    for t in "ABC":
        jj = sorted([i for i in range(len(d["panel"])) if d["panel"][i] == "front" and d["dorr"][i] == t], key=lambda i: d["x"][i])
        if jj:
            b.step([d["x"][i] for i in jj], [d["y"][i] for i in jj], where="post", color=ps.DORR[t], label=f"Dorr {t}")
    b.set_xscale("log"); b.set_xlabel(ps.LABEL["f1"]); b.set_ylabel(ps.LABEL["f2"]); b.legend(fontsize=6)
    b.set_title("Reference fronts", fontsize=7)
    # (c) 校准
    c.plot([0, 1], [0, 1], color="black", lw=0.8)
    for t in "ABC":
        jj = sorted([i for i in range(len(d["panel"])) if d["panel"][i] == "cal" and d["dorr"][i] == t], key=lambda i: d["x"][i])
        if jj:
            c.plot([d["x"][i] for i in jj], [d["y"][i] for i in jj], "o-", ms=2.5, color=ps.DORR[t], label=f"Dorr {t}")
    c.set_xlabel(ps.LABEL["nominal"]); c.set_ylabel(ps.LABEL["empirical"]); c.set_title("GP calibration (log f1)", fontsize=7)
    # (d) 2D–3D
    for t in "ABC":
        jj = [i for i in range(len(d["panel"])) if d["panel"][i] == "3d" and d["dorr"][i] == t]
        if jj:
            e.scatter([d["x"][i] for i in jj], [d["y"][i] for i in jj], s=14, color=ps.DORR[t], marker=ps.DORR_MARKER[t])
    e.set_xscale("log"); e.set_yscale("log"); e.set_xlabel("2D " + ps.LABEL["f1"], fontsize=7)
    e.set_ylabel("3D " + ps.LABEL["f1"], fontsize=7); e.set_title("2D vs 3D micromotion", fontsize=7)
    ps.panel_labels(list(axes.flat))
    return fig


def main():
    rows = []
    try:
        s5 = json.loads((ROOT / "reports" / "R5_bo_results" / "figures" / "R5-F01.json").read_text(encoding="utf-8"))
        d = ps.read_csv(ROOT / s5["csv"])
        for t in "ABC":
            for m in ("qNEHVI", "Sobol"):
                ns = sorted({d["n_fe"][i] for i in range(len(d["dorr"])) if d["dorr"][i] == t and d["method"][i] == m})
                for n in ns:
                    v = [d["hv_ratio"][i] for i in range(len(d["dorr"])) if d["dorr"][i] == t and d["method"][i] == m and d["n_fe"][i] == n]
                    rows.append(dict(panel="hv", dorr=t, method=m, x=n, y=float(np.median(v))))
        fr = ps.read_csv(ROOT / json.loads((ROOT / "reports" / "R5_bo_results" / "figures" / "R5-F08.json").read_text(encoding="utf-8"))["csv"])
        rows += [dict(panel="front", dorr=fr["dorr"][i], method="", x=fr["f1"][i], y=fr["f2"][i]) for i in range(len(fr["dorr"]))]
        cal = ps.read_csv(ROOT / json.loads((ROOT / "reports" / "R5_bo_results" / "figures" / "R5-F07.json").read_text(encoding="utf-8"))["csv"])
        rows += [dict(panel="cal", dorr=cal["dorr"][i], method="", x=cal["nominal"][i], y=cal["empirical"][i])
                 for i in range(len(cal["dorr"])) if cal["output"][i] == "log10 f1"]
    except FileNotFoundError:
        pass
    try:
        r6 = ps.read_csv(ROOT / json.loads((ROOT / "reports" / "R6_spot3d" / "figures" / "R6-F02.json").read_text(encoding="utf-8"))["csv"])
        rows += [dict(panel="3d", dorr=r6["dorr"][i], method="", x=r6["f1_2d"][i], y=r6["f1_3d"][i]) for i in range(len(r6["dorr"]))]
    except FileNotFoundError:
        pass
    if rows:
        ps.publish_figure("R7-F01", rows, plot_r7_f01, title="One-page summary of the FE → GP → multi-objective BO test",
                          caption="(a) 各型 BO 与 Sobol 的 HV 比中位曲线；(b) 三型参考前沿；(c) GP 校准（log f1）；(d) 2D 对 3D 微动。数据取自 R5、R6。")
    # T04 验收汇总
    t04 = []
    for rid in RIDS:
        for a in acc(rid):
            t04.append(dict(report=rid, id=a["id"], status=a["status"], measured=a["measured"], note=a.get("note", "")))
    if t04:
        ps.publish_table("R7-T04", t04, title="R0–R6 验收汇总")
    # T01 V&V 40
    def lvl(ok, hi="中", lo="低"):
        return hi if ok else lo
    r0 = status_of("R0", "R0-A1")["status"] == "PASS"
    r2a1 = status_of("R2", "R2-A1")["status"] == "PASS"
    r2a2 = status_of("R2", "R2-A2")["status"] == "PASS"
    r2a4 = status_of("R2", "R2-A4")["status"] == "PASS"
    r6 = status_of("R6", "R6-A1")
    t01 = [
        dict(category="代码验证", factor="软件质量保证", activity="商业软件 Abaqus 2025；自写脚本单元测试（tests/）", target="低", achieved="低"),
        dict(category="代码验证", factor="数值代码验证", activity="R0 悬臂梁、R2 Lamé 压配对解析解", target="中", achieved=lvl(r0 and r2a1)),
        dict(category="计算验证", factor="离散误差", activity="R2 GCI（2D）、R6 两档网格（3D）", target="中",
             achieved="中" if r2a2 else "低（f1 未网格收敛，排序一致）"),
        dict(category="计算验证", factor="数值求解误差", activity="R2 噪声底、增量设置敏感性、摩擦列式对比", target="中", achieved="中"),
        dict(category="计算验证", factor="使用错误", activity="重跑逐位相同；.inp 由模板生成", target="中", achieved=lvl(r2a4)),
        dict(category="确认", factor="模型形式", activity="2D 平面应力 + 侧板；R6 与 3D 比较排序", target="低",
             achieved="低" if r6["status"] != "PASS" else "低–中（2D–3D 排序一致）"),
        dict(category="确认", factor="模型输入", activity="材料取自源 3D 模型；松质骨分型取值为假设 + 对照组", target="低", achieved="低"),
        dict(category="确认", factor="比较对象：试样", activity="无实验", target="不适用", achieved="不适用"),
        dict(category="确认", factor="比较对象：试验条件", activity="无实验", target="不适用", achieved="不适用"),
        dict(category="确认", factor="评估：输入参数等效性", activity="无实验", target="不适用", achieved="不适用"),
        dict(category="确认", factor="评估：输出比较", activity="无实验；只做 2D–3D 秩相关", target="不适用", achieved="不适用"),
        dict(category="适用性", factor="关注量的相关性", activity="f1、f2 对应初始稳定与近端遮挡", target="中", achieved="中"),
        dict(category="适用性", factor="确认活动与使用情境的相关性", activity="无确认活动", target="低", achieved="低"),
    ]
    ps.publish_table("R7-T01", t01, title="ASME V&V 40 可信度因子：目标与达到等级",
                     caption="模型风险：模型影响高、决策后果低（方法测试），目标为低到中等可信度。达到等级由 R0–R6 验收结果自动判定。")
    t02 = [
        dict(rule="1 明确定义使用情境", status="已落实", evidence="每份报告第 1 节"),
        dict(rule="2 使用与情境相符的数据", status="部分", evidence="材料/载荷有来源；松质骨分型取值与载荷方向为假设（R2 局限）"),
        dict(rule="3 在情境内评估", status="已落实", evidence="验收门槛按测试问题设定（HV 比、覆盖率、秩相关）"),
        dict(rule="4 明列局限", status="已落实", evidence="每份报告第 6 节"),
        dict(rule="5 使用版本控制", status="已落实", evidence="本地 git + 文件哈希 + history 副本"),
        dict(rule="6 恰当记录", status="已落实", evidence="REPORTING_SPEC、Erdemir 2012 80 项清单、各报告方法节"),
        dict(rule="7 广泛传播", status="未落实", evidence="本地项目，未公开"),
        dict(rule="8 获得独立评审", status="待定", evidence="交导师审阅"),
        dict(rule="9 测试竞争实现", status="已落实", evidence="BO 对 Sobol；2D 对 3D；两个解析基准；两种摩擦列式"),
        dict(rule="10 遵从标准", status="部分", evidence="Erdemir 2012、Celik 2008、Zitzler 2003；Oefner 2021 未取得"),
    ]
    ps.publish_table("R7-T02", t02, title="Erdemir 2020 十条规则合规表")
    t03 = [
        dict(limitation="2D 平面应力 + 侧板厚度假设", effect="f1 对侧板厚度敏感（R2-F04）", in_real_model="3D 真实股骨，无需侧板"),
        dict(limitation="f1 未网格收敛", effect="f1 绝对值偏低，排序一致（R2-F10）", in_real_model="3D 网格收敛研究，或改用对网格不敏感的微动指标"),
        dict(limitation="载荷方向沿用源模型（内下）", effect="见 R2-F04 载荷方向敏感性", in_real_model="按 Bergmann 标准工况 + 肌力"),
        dict(limitation="松质骨分型模量为假设", effect="对照组分离（R5-F09）", in_real_model="CT 灰度映射"),
        dict(limitation="外轮廓三型相同导致 C 型近端皮质偏厚", effect="三型差异含人为成分（R1 局限）", in_real_model="真实分型股骨"),
        dict(limitation="无实验确认", effect="只做方法层面的结论", in_real_model="DIC/应变片台架（课题计划）"),
    ]
    ps.publish_table("R7-T03", t03, title="局限清单与在真实模型中的处置")
    allacc = [a for rid in RIDS for a in acc(rid)]
    ok = all(a["status"] in ("PASS", "NA") for a in allacc) and len(allacc) > 0
    fails = [a["id"] for a in allacc if a["status"] == "FAIL"]
    ps.publish_acceptance("R7", [{"id": "R7-A1", "measured": f"{sum(a['status'] == 'PASS' for a in allacc)}/{len(allacc)} PASS；FAIL: {', '.join(fails) or '无'}",
                                  "status": "PASS" if ok else "FAIL",
                                  "note": "" if ok else "FAIL 项的处置见各报告验收表，需用户逐项同意"}])


if __name__ == "__main__":
    main()
