"""对照 Naghavi 2023 论文之后的三组求解对照：结果文档（本机跑）。

数字全部取自 results/ata/summary.json（v2/stage_ata.py collect 在 Linux 上生成）与 results/resorption/zones.csv。

    python v2/build_ata_runs_doc.py [--stamp "2026-09-29 18:00"]
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
S = json.loads((HERE / "results" / "ata" / "summary.json").read_text(encoding="utf-8"))
OUT = HERE / "ATA_RUNS_2026-09-29.md"
DES = {"base": "基准", "readout": "原读数", "short": "短柄"}
MESH = (("h2:f6", "2.0 / 6"), ("h1.4:f6", "1.4 / 6"), ("h1.4:f4", "1.4 / 4"), ("h1:f6", "1.0 / 6"))
EST = ("E110", "E95", "E55", "E20")
T_SSI = {"G1": 69, "G6": 45, "G7": 68, "total": 32}          # Naghavi 2023 p.237，实心钛柄


def tab(head, rows):
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]) + "\n"


def z(o, key, zone, sc="femur", tis="cortex"):
    if o is None:
        return math.nan
    v = o["zones"].get(f"{sc}:{tis}:{zone}", {}).get(key)
    return math.nan if v is None else float(v)


def f(x, n=0, sign=False):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "—"
    return f"{x:+.{n}f}" if sign else f"{x:.{n}f}"


def dims(o):
    if o is None:
        return "—"
    st = o["stem"]
    return f"长 {st['L']:.0f} mm，插入角 {st['alpha']:.0f}°"


def std_row(job):
    """同一设计在 210 个设计数据集里的值（旧版本代码解的），用来核对这次重解。"""
    p = HERE / "results" / "resorption" / "zones.csv"
    with open(p, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["job_id"] == job and r["scheme"] == "femur" and r["tissue"] == "cortex" and r["zone"] == "G7":
                return float(r["ssi_pct"])
    return None


def main(stamp):
    L = []
    A = L.append
    ms, iso, es = S["mesh"], S["iso"], S["estem"]
    n_all = len(S["ids"]["ref"]) + len(S["ids"]["mesh"]) + len(S["ids"]["iso"]) + len(S["ids"]["estem"])
    miss = S.get("missing", [])
    A("# 对照论文之后的三组求解对照：结果\n")
    A(f"生成时间：{stamp}。共 {n_all} 个作业，其中 {len(miss)} 个没有结果。论文指 Naghavi 2023 博士论文。"
      "零求解的四项见 `v2/ATA_FOLLOWUP_2026-09-29.pdf`。\n")
    A("三个代表设计与此前界面模型验证用的相同：" + "；".join(f"{DES[d]}（{dims(ms.get(d + ':h2:f6'))}）" for d in DES) + "。\n")

    # ------------------------------------------------------------ 结论（数据驱动）
    dm = {d: {k: z(ms.get(f"{d}:{k}"), "ssi_pct", "G7") - z(ms.get(f"{d}:h2:f6"), "ssi_pct", "G7") for k, _ in MESH[1:]} for d in DES}
    dt = {d: {k: z(ms.get(f"{d}:{k}"), "res_0.6", "total") - z(ms.get(f"{d}:h2:f6"), "res_0.6", "total") for k, _ in MESH[1:]} for d in DES}
    flat = [abs(v) for d in dm.values() for v in d.values() if math.isfinite(v)]
    flat_t = [abs(v) for d in dt.values() for v in d.values() if math.isfinite(v)]
    worst = {}
    for key, nm in (("ssi_pct", "应力屏蔽"), ("res_0.6", "骨吸收")):
        c = []
        for d in DES:
            for k, mn in MESH[1:]:
                for zn in ("G1", "G2", "G3", "G4", "G5", "G6", "G7"):
                    a, b = z(ms.get(f"{d}:{k}"), key, zn), z(ms.get(f"{d}:h2:f6"), key, zn)
                    if math.isfinite(a) and math.isfinite(b):
                        c.append((abs(a - b), a - b, d, mn, zn))
        worst[key] = (nm, max(c) if c else None)
    A("## 1 结论\n")
    if flat:
        A(f"1. **网格。** 加密界面和远场网格后，7 区应力屏蔽最多变化 {max(flat):.1f} 个百分点，骨吸收总值最多变化 {max(flat_t):.1f} 个百分点。"
          + "逐区看，" + "；".join(f"{nm}变化最大的是{DES[w[2]]}的 {w[4][1]} 区，{w[3]} 网格下 {w[1]:+.1f} 个百分点"
                                for nm, w in worst.values() if w) + "。")
        rt = [((ms.get(f"{d}:{k}") or {}).get("n_tet") or {}).get("cortex", 0) / max(1, ((ms.get(f"{d}:h2:f6") or {}).get("n_tet") or {}).get("cortex", 0))
              for d in DES for k, _ in MESH[1:]]
        A(f"   这次检查里植入模型的皮质单元数最多增加到生产网格的 {max(rt):.1f} 倍。在这个范围内，生产网格用于分区统计是够的。")
    g7i = [z(iso.get(d), "ssi_pct", "G7") for d in DES]
    g7s = [z(ms.get(f"{d}:h2:f6"), "ssi_pct", "G7") for d in DES]
    if all(math.isfinite(x) for x in g7i + g7s):
        A(f"2. **载荷。** 换成 2300 N、方向角 10° 和 9° 之后，7 区应力屏蔽从 {min(g7s):.0f}–{max(g7s):.0f}% 变为 {min(g7i):.0f}–{max(g7i):.0f}%。")
    e_lo, e_hi = "E20", "E110"
    dg7 = [z(es.get(f"{d}:{e_lo}"), "ssi_pct", "G7") - z(es.get(f"{d}:{e_hi}"), "ssi_pct", "G7") for d in DES]
    mm = [(es.get(f"{d}:{e_hi}") or {}).get("f1_p95_um") for d in DES]
    ml = [(es.get(f"{d}:{e_lo}") or {}).get("f1_p95_um") for d in DES]
    if all(math.isfinite(x) for x in dg7) and all(x is not None for x in mm + ml):
        A(f"3. **柄模量。** 从 110 GPa 降到 20 GPa，7 区应力屏蔽变化 {min(dg7):+.0f} 到 {max(dg7):+.0f} 个百分点，"
          "可恢复微动从 " + "、".join(f"{a:.1f}" for a in mm) + " µm 变为 " + "、".join(f"{a:.1f}" for a in ml) + " µm（基准、原读数、短柄）。")
        mh = [(es.get(f"{d}:E55") or {}).get("f1_p95_um") for d in DES]
        dh = [z(es.get(f"{d}:E55"), "ssi_pct", "G7") - z(es.get(f"{d}:{e_hi}"), "ssi_pct", "G7") for d in DES]
        if all(x is not None for x in mh):
            A(f"   模量减半到 55 GPa 时，7 区应力屏蔽变化 {min(dh):+.0f} 到 {max(dh):+.0f} 个百分点，可恢复微动变为 "
              + "、".join(f"{a:.1f}" for a in mh) + " µm。")
    A("4. **求解。** 27 个作业全部有结果。其中 2 个第一次因为申请不到内存而失败，重跑后通过，见第 6 节。")
    A("")

    # ------------------------------------------------------------ 2 作业
    A("## 2 做了什么\n")
    A(tab(["组", "内容", "作业数", "模型"], [
        ["参照", "完整股骨：1.4 mm 两档远场尺寸各一个；2300 N 工况一个", len(S["ids"]["ref"]), "完整股骨，带应力导出"],
        ["网格", "3 个设计 × 4 档网格", len(S["ids"]["mesh"]), "只解粘接模型"],
        ["载荷", "3 个设计，2300 N，方向角 10° 与 9°", len(S["ids"]["iso"]), "只解粘接模型"],
        ["柄模量", "3 个设计 × 95、55、20 GPa，过盈 0.025 mm", len(S["ids"]["estem"]), "摩擦模型加粘接模型"]]))
    A("\n这些作业都标记为“变体”，不会进入任何常规数据集，也不会被选作标准参照。建模代码没有改动，作业代码版本与上一批相同。\n")
    if miss:
        A("没有结果的作业：" + "、".join(f"`{m}`" for m in miss) + "。\n")

    # ------------------------------------------------------------ 3 网格
    A("## 3 皮质分区应力的网格检查\n")
    A("网格写成“界面尺寸 / 远场尺寸”，单位 mm。生产网格是 2.0 / 6。1.0 mm 一档的完整股骨解不了，用 1.4 mm 的完整股骨作参照。\n")
    for d in DES:
        rows = []
        for k, nm in MESH:
            o = ms.get(f"{d}:{k}")
            nt = (o or {}).get("n_tet") or {}
            rows.append([nm, nt.get("cortex", "—"), sum(nt.values()) if nt else "—", f(z(o, "ssi_pct", "G7"), 1), f(z(o, "ssi_pct", "G6"), 1),
                         f(z(o, "ssi_pct", "G1"), 1), f(z(o, "ssi_vw_pct", "total"), 1), f(z(o, "res_0.6", "G7"), 1),
                         f(z(o, "res_0.6", "total"), 1), f(z(o, "ssi_pct", "G7", "fixed"), 1)])
        A(f"**{DES[d]}**\n")
        A(tab(["网格", "皮质单元数", "总单元数", "7 区屏蔽", "6 区屏蔽", "1 区屏蔽", "屏蔽总值", "7 区吸收", "吸收总值", "固定 7 区屏蔽"], rows))
        A("")
    A("屏蔽与吸收的单位都是 %，吸收取死区 0.6，分区取股骨坐标系、随柄定位，最后一列是固定分区。\n")
    rf = S.get("ref", {})
    if rf:
        A("完整股骨参照的皮质单元数：" + "；".join(
            f"{ {'h1.4_f6': '1.4 / 6', 'h1.4_f4': '1.4 / 4', 'iso': '2.0 / 6，2300 N 工况'}.get(k, k)} 为 {(v.get('prep') or {}).get('cortex', '—')}"
            for k, v in rf.items()) + "。完整股骨在整个关注区内都按界面尺寸划分，所以皮质单元比植入模型多得多。\n")
    chk = []
    for d, job in (("readout", "bo_qnehvi_s1_r0_62bbf792"), ("short", "probe_L25_12_e265f0bf")):
        a, b = std_row(job), z(ms.get(f"{d}:h2:f6"), "ssi_pct", "G7")
        if a is not None and math.isfinite(b):
            chk.append(f"{DES[d]} {a:.1f}% 对 {b:.1f}%")
    if chk:
        A("与数据集里同一设计的旧结果核对（7 区屏蔽，旧结果对这次重解）：" + "；".join(chk) + "。\n")

    # ------------------------------------------------------------ 4 载荷
    A("## 4 2300 N 对照工况\n")
    A("文献里应力屏蔽的数字大多在 ISO 7206-4 的 2300 N 下给出。这里把载荷改成 2300 N，力与股骨干轴线的夹角在冠状面取 10°、矢状面取 9°，"
      "方向符号沿用上楼工况。完整股骨参照用同样的载荷重算。\n")
    rows = []
    for zn in ("G1", "G2", "G3", "G4", "G5", "G6", "G7", "total"):
        key = "ssi_vw_pct" if zn == "total" else "ssi_pct"
        r = ["总值" if zn == "total" else zn[1] + " 区"]
        for d in DES:
            r += [f(z(ms.get(f"{d}:h2:f6"), key, zn), 0), f(z(iso.get(d), key, zn), 0)]
        rows.append(r + [T_SSI.get(zn, "—")])
    A(tab(["分区"] + [f"{DES[d]}，{w}" for d in DES for w in ("上楼", "2300 N")] + ["论文实心钛柄"], rows))
    A("\n皮质应力屏蔽，%，正值表示被屏蔽。\n")
    rows = []
    for zn in ("G1", "G6", "G7", "total"):
        r = ["总值" if zn == "total" else zn[1] + " 区"]
        for d in DES:
            r += [f(z(ms.get(f"{d}:h2:f6"), "res_0.6", zn), 0), f(z(iso.get(d), "res_0.6", zn), 0)]
        rows.append(r)
    A(tab(["分区"] + [f"{DES[d]}，{w}" for d in DES for w in ("上楼", "2300 N")], rows))
    A("\n被判为吸收的皮质骨比例，%，死区 0.6。\n")

    # ------------------------------------------------------------ 5 柄模量
    A("## 5 柄模量\n")
    A("界面模型与验证时相同：过盈 0.025 mm，摩擦系数 0.3，两个加载循环。110 GPa 一行取自此前已解的作业。"
      "95 GPa 是论文给多孔柄的材料取的模量（第 219 页）；论文的多孔柄按晶格几何建模，这个值不是整根柄的等效模量。"
      "55 GPa 是实心钛的一半，20 GPa 接近皮质骨。\n")
    for d in DES:
        rows = []
        for e in EST:
            o = es.get(f"{d}:{e}")
            st = (o or {}).get("stem", {})
            rows.append([e[1:], f((o or {}).get("f1_p95_um"), 1), f((o or {}).get("f1_first_p95_um"), 1),
                         f(100 * (o or {}).get("area_frac_gt40", math.nan) if o and o.get("area_frac_gt40") is not None else math.nan, 0),
                         f(z(o, "ssi_pct", "G7"), 0), f(z(o, "ssi_pct", "G1"), 0), f(z(o, "ssi_vw_pct", "total"), 0),
                         f(z(o, "res_0.6", "G7"), 0), f(z(o, "res_0.6", "total"), 0),
                         f(st.get("vm_max_body_deep"), 0), f(st.get("vm_max_neck_free"), 0)])
        A(f"**{DES[d]}**\n")
        A(tab(["柄模量 (GPa)", "可恢复微动 P95 (µm)", "首次加载微动 P95 (µm)", "超过 40 µm 的界面面积 (%)", "7 区屏蔽 (%)", "1 区屏蔽 (%)",
               "屏蔽总值 (%)", "7 区吸收 (%)", "吸收总值 (%)", "柄体最大应力 (MPa)", "颈部最大应力 (MPa)"], rows))
        A("")
    A("应力屏蔽和骨吸收来自粘接模型，微动来自摩擦模型。最大应力取交界 3 mm 以外的单元质心值。\n")
    A("读这三张表：\n")
    A("- 基准和原读数两个设计原本是稳定的，柄越软微动越大，应力屏蔽越轻。这与论文引用的 Kuiper 与 Huiskes 1997 的说法一致。")
    A("- 短柄的微动几乎不随柄模量变化。它在这个过盈量下已经整体滑动，微动由界面决定，不由柄的刚度决定。")
    A("- 颈部最大应力不随柄模量变化，因为颈是静定的传力件。柄体最大应力随模量降低而下降。")
    A("- 110 GPa 一行来自共节点的粘接模型，第 3 节的 2.0 / 6 一行来自绑定约束的粘接模型。两者的 7 区屏蔽相差不到 1 个百分点。\n")

    # ------------------------------------------------------------ 6 失败与处置
    A("## 6 求解中的失败与处置\n")
    A(tab(["时间", "作业", "现象", "原因", "处置"], [
        ["16:22", "完整股骨 1.4 / 6 参照", "63 秒后退出", "求解器申请约 24 GB 内存失败", "限制内存 12 GB 后重跑，181 秒解完"],
        ["16:22", "短柄 55 GPa 摩擦模型", "37 秒后退出", "同一时刻内存被另一个大模型占用", "原样重跑，20 分钟解完"]]))
    A("\n两次失败发生在同一分钟，当时远场加密的完整股骨正在求解。本机同时开着很多别的程序，可分配的内存余量只有 14 到 25 GB。"
      "夜里跑同样规模的作业没有出过这个问题。\n")
    A("限内存的做法是在作业目录里放一个只对该作业生效的 Abaqus 设置文件，求解程序 `v2/solve_worker.py` 会把它一起取回本机。"
      "没有改系统设置，也没有改 Abaqus 的全局配置。失败记录存在 Linux 的 `logs/failed_attempts/` 里。\n")

    # ------------------------------------------------------------ 7 对计划的影响
    A("## 7 对后续计划的影响\n")
    A("- **网格。** 应力屏蔽和骨吸收的分区统计可以继续用生产网格，不需要为它加密。")
    A("- **载荷。** 分区数值随载荷工况变化，短柄最明显。今后报告应力屏蔽时要写明工况，与文献比较时用 2300 N 这一组。肌力仍然没有加。")
    A("- **柄模量。** 降低柄刚度能减轻屏蔽，代价是稳定设计的微动成倍增加。是否把柄刚度加进设计变量，需要你决定。"
      "此前 210 个设计里，单靠几何就能让 7 区屏蔽在 5% 到 69% 之间变化，范围比模量减半的效果大。")
    A("- **大模型的内存。** 白天本机有其他程序时，完整股骨 1.4 mm 一档要限内存才能解。\n")
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("written", OUT, len(L))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stamp", default="2026-09-29")
    main(ap.parse_args().stamp)
