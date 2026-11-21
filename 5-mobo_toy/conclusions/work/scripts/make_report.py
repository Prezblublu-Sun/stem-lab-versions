"""Write the illustrated experiment summary as one self-contained HTML file. Numbers come from data/metrics.json and data/rows.csv; criteria outcomes that are not recomputed here are marked in the text as taken from the execution record.

    python -X utf8 make_report.py
"""
import base64
import csv
import json
import math
import pathlib

HERE = pathlib.Path(__file__).resolve().parent.parent
M = json.load(open(HERE / "data/metrics.json", encoding="utf-8"))
R = list(csv.DictReader(open(HERE / "data/rows.csv", encoding="utf-8-sig")))
ROW = {r["job_id"]: r for r in R}
OUT = HERE / "实验结果总结_2026-11-03.html"


def f(job, key):
    return float(ROW[job][key])


def job(prefix):
    return next(j for j in ROW if j.startswith(prefix))


def sg(v, d=3):
    return f"{v:+.{d}f}".replace("-", "−")


def img(name, alt):
    data = base64.b64encode((HERE / "figures/zh" / f"{name}.png").read_bytes()).decode("ascii")
    return f'<img src="data:image/png;base64,{data}" alt="{alt}">'


def table(head, rows, cls=""):
    th = "".join(f"<th>{h}</th>" for h in head)
    tr = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="tw"><table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>'


def figure(n, name, alt, cap):
    return f'<figure>{img(name, alt)}<figcaption><b>图 {n}</b> {cap}</figcaption></figure>'


caps = {c["cap"]: c for c in M["cost"]["caps"]}
A, W1 = M["A"], M["WS_m1"]
S = M["sensitivity"]
scan = M["one_factor"]
V = M["val1"]
P = M["prospective"]
CY = M["cycles"]
CD = M["cycles_dex_vs_A"]
mc = M["m_cost_by_condition"]
nm = M["mechanism"]["named"]
b = M["mechanism"]["bands"]
OT = {(t["design"], t["e"]): t for t in M["offset_table"]}
Ap, Am, A0 = OT[("A", 2.0)], OT[("A", -2.0)], OT[("A", 0.0)]
ep = [o for o in M["offset_rows"] if o["e"] == 2.0]
em = [t for t in M["offset_table"] if t["e"] == -2.0]
dex_em = [math.log10(t["rot"] / OT[(t["design"], 0.0)]["rot"]) for t in em]
cl = M["cluster"]
ds = M["delta_same_designs"]
tight = [v["spearman_tight"] for v in S.values() if "spearman_tight" in v]


def sm(factor, series, x):
    return next(r for r in scan if r["factor"] == factor and r["series"] == series and abs(r["x"] - x) < 0.02)


def snote(note):
    return next(r for r in scan if r["note"] == note)


slope = math.log10(sm("m", "A", 1.75)["rot"] / sm("m", "A", 1.0)["rot"]) / 0.75

# row counts by what the rows were for
GROUPS = [("设计空间探索", "贝叶斯优化、准随机、角落点、三轮主动学习选点", ("S0", "SF-1", "CR-1", "CR-T", "AL-1", "AL-1 rand", "AL-1 sts", "AL-2", "AL-2 rand", "AL-3m", "AL-3m rand", "AL-3m sts")),
          ("同形单因素", "设计 A 或 a62 的形状，每次改 m、L 或 α", ("WS m", "WS alpha", "WS m alpha", "W-0 alpha", "W-0 L", "WL-1", "WS m2")),
          ("入口偏移", "偏移固定，尺寸重新模板化", ("BD offset", "OW-2")),
          ("条件变化", "过盈、载荷大小和方向、摩擦", ("CD-0", "CD-1", "CD-1 rand", "CD-2", "TQ-0", "MU-1")),
          ("网格和噪声", "h 1.4 到 2.4，重复网格", ("NZ-1", "NZ-2", "NZ-3", "FD-0 h1.4", "FD-0 h2.4", "FD-1 h1.4")),
          ("多循环", "4 循环和 10 循环", ("CY-1",)),
          ("粘接配对", "计算骨内应变能用的粘接模型", ("BD b2", "BD sts", "BD h2.0", "BD mesh")),
          ("完整股骨参照", "无柄参照，含实测对照", ("REF", "VAL-1"))]
counts = {}
for r in R:
    counts[r["layer"]] = counts.get(r["layer"], 0) + 1
group_rows, used = [], 0
for name, what, layers in GROUPS:
    n = sum(counts.get(x, 0) for x in layers)
    used += n
    group_rows.append([name, what, f"{n}"])
assert used == len(R), (used, len(R), sorted(set(counts) - {x for g in GROUPS for x in g[2]}))

# representative designs
W = "db_ws_p13_a105_91e458e3_"
reps = [("A", "sb13_a105_91e458e3", "搜索到的最好设计，余量贴下限"),
        ("A，L 44.5", W + "L44.5", "同形里最低，偏移固定 0，贴空腔"),
        ("A，m 1.0", W + "m1_2a79b613", "同形对照"),
        ("A，m 1.0，L 44", W + "wl_m1_L44", "m 1.0 的台架候选，依赖空芯假设"),
        ("A，m 1.0，α 55，L 44.75", W + "wl_m1_a55_L44.75", "超出盒子，要过 G2"),
        ("选点 11", "db_al_al3m_11", "AL-3′ 选点"),
        ("A，m 1.75", W + "m1.75", "同形扫描，贴在偏移跳变边上"),
        ("al1_07", "db_al_al1_07", "m 0.50，模板选到 e +2"),
        ("选点 1", "db_al_al3m_01_a6949792", "AL-3′ 选点，模板选到 e +2，模板选偏移时 m ≥ 1.0、≤ 6 cm³ 里最低"),
        ("A，m 1.0，e +2", W + "ow_m1_e+2", "偏移固定，小一号")]
rep_rows = []
for name, pre, why in sorted(reps, key=lambda x: -f(job(x[1]), "bone")):
    j = job(pre)
    r = ROW[j]
    e = float(r["e"])
    rep_rows.append([name, f"{float(r['m']):.2f}", sg(e, 0) if e else "0", f"{float(r['A0']):.0f}", f"{float(r['bone']):.2f}", f"{float(r['rot']):.3f}", f"{float(r['f1']):.1f}", f"{float(r['contact']):.0f}", why])

# template offset rows against A at e +2
free = [r for r in R if r["curve"] == "True" and (r["layer"] != "OW-2" or float(r["forced_e"]) == 0.0)]
reach_m1 = min(float(r["bone"]) for r in free if float(r["m"]) >= 1.0 and float(r["rot"]) <= Ap["rot"])
reach_any = min(float(r["bone"]) for r in free if float(r["rot"]) <= Ap["rot"])
tmpl_e2 = [r for r in R if r["curve"] == "True" and r["forced_e"] == "" and float(r["e"]) == 2.0]
tmpl_e2_m1 = [r for r in tmpl_e2 if float(r["m"]) >= 1.0]
best_e2_m1 = min(float(r["rot"]) for r in tmpl_e2_m1)
assert abs(best_e2_m1 - caps[6]["m_ge1_rot"]) < 1e-6
for d in ("A", "a95", "a100"):
    assert OT[(d, 0.0)]["A0"] > max(OT[(d, 2.0)]["A0"], OT[(d, -2.0)]["A0"])
strict = [r for r in R if r["strict"] == "True"]
press_over = sum(float(r["press"]) > 6.2 for r in strict)

CSS = """
:root { color-scheme: light; --ink:#0b0b0b; --ink2:#52514e; --muted:#6f6e69; --rule:#e1e0d9; --wash:#f6f5f1; --accent:#2a78d6; --warn:#a4501f; --warnbg:#fbf1ea; }
* { box-sizing: border-box; }
html { background:#ffffff; }
body { margin:0 auto; max-width:860px; padding:32px 16px 48px; background:#ffffff; color:var(--ink); font:15px/1.65 "Microsoft YaHei","Segoe UI",system-ui,sans-serif; }
h1 { font-size:26px; line-height:1.3; margin:0 0 6px; }
.sub { color:var(--ink2); margin:0 0 20px; }
h2 { font-size:20px; margin:34px 0 10px; padding-top:10px; border-top:1px solid var(--rule); }
h3 { font-size:16px; margin:24px 0 8px; }
p { margin:8px 0; }
ul { margin:8px 0; padding-left:20px; }
li { margin:4px 0; }
.lead { font-size:16px; }
.stats { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin:16px 0; }
.stat { background:var(--wash); border-radius:8px; padding:10px 12px; }
.stat b { display:block; font-size:22px; line-height:1.25; font-weight:600; }
.stat span { color:var(--ink2); font-size:13px; }
.note { background:var(--warnbg); border-left:3px solid var(--warn); padding:8px 12px; margin:12px 0; border-radius:0 6px 6px 0; }
.tw { overflow-x:auto; margin:10px 0; }
table { border-collapse:collapse; width:100%; font-size:13px; line-height:1.5; }
th { text-align:left; color:var(--ink2); font-weight:600; border-bottom:1px solid #c3c2b7; padding:5px 8px 5px 0; vertical-align:bottom; }
td { border-bottom:1px solid var(--rule); padding:5px 8px 5px 0; vertical-align:top; font-variant-numeric:tabular-nums; }
figure { margin:14px 0 18px; }
figure img { width:100%; height:auto; display:block; }
figcaption { color:var(--ink2); font-size:13px; margin-top:4px; }
.ev { color:var(--ink2); font-size:13px; }
a { color:var(--accent); }
code { font-family:inherit; }
@media (max-width:620px) { .stats { grid-template-columns:repeat(2,1fr); } body { font-size:14px; } }
@media print {
  @page { size:A4; margin:15mm 14mm; }
  body { max-width:none; padding:0; font-size:10.5pt; line-height:1.55; }
  h1 { font-size:20pt; }
  h2 { font-size:14pt; margin-top:18pt; break-after:avoid; }
  h3 { font-size:11.5pt; break-after:avoid; }
  table { font-size:9pt; }
  th, td { padding:3pt 6pt 3pt 0; }
  tr, figure, .stat, .note { break-inside:avoid; }
  figcaption, .ev { font-size:9pt; }
  .ev { break-after:avoid; }
  .stat b { font-size:15pt; }
  .tw { overflow:visible; }
  a { color:inherit; text-decoration:none; }
}
"""

body = f"""
<h1>只占股骨颈短柄有限元实验：结果总结</h1>
<p class="sub">2026-11-03，数据版本 db3406 {M['export']}，执行记录截至 19:57 UTC。所有结果来自一根 Sawbones 3406 的有限元，没有台架验证。正在跑的 OW-3 不在其中。</p>

<div class="stats">
<div class="stat"><b>{M['n_rows']:,}</b><span>有限元作业，{M['n_done']:,} 个成功，{M['n_failed']} 个失败</span></div>
<div class="stat"><b>13</b><span>设计变量，另有入口偏移和号由模板决定</span></div>
<div class="stat"><b>1</b><span>根复合股骨，假定松质芯底部为空芯</span></div>
<div class="stat"><b>0</b><span>台架数据；实测对照只有完整股骨</span></div>
</div>

<h2>结论摘要</h2>
<p class="lead">这批实验能比较设计之间的优劣，还不能给出绝对的稳定性。最重要的新结果是：之前认为的去骨下限，其实来自选号规则。</p>
{table(["问题", "结果", "证据"], [
    ["最稳的设计是什么", f"搜索到的最好设计是 A：转动 {A['rot']:.4f}°，去骨 {A['bone']:.2f} cm³，微动 {A['f1']:.1f} µm。它比第 2 名好 {cl['A_to_second_dex']:.3f} dex，第 2–5 名之间分不开。同一形状把 L 加到 44.5，还能降到 {sm('L', 'm0.5', 44.5)['rot']:.4f}°。", "跨设计 FE"],
    ["余量的代价多大", f"同一形状，m 1.0 的转动是 m 0.5 的 {W1['rot'] / A['rot']:.2f} 倍，m 1.75 是 {sm('m', 'A', 1.75)['times_A']:.2f} 倍，约每毫米 {slope:.2f} dex。去骨同时从 {A['bone']:.2f} 降到 {sm('m', 'A', 1.75)['bone']:.2f} cm³。", "同形单因素 FE"],
    ["能少去多少骨", f"模板选偏移时，m ≥ 1.0 在 ≤ 6 cm³ 最好 {caps[6]['m_ge1_rot']:.3f}°。A 这一族偏移固定 +2 时，{min(o['bone'] for o in ep):.2f}–{max(o['bone'] for o in ep):.2f} cm³ 已到 {min(o['rot'] for o in ep):.3f}–{max(o['rot'] for o in ep):.3f}°。下限还不能写，OW-3 正在补这一段。", "同形单因素 FE，3 行同族"],
    ["靠什么稳住", f"转动 &lt; 0.1° 的设计，{b[0]['perm_share_median'] * 100:.0f} % 的转动卸载后留下；&gt; 1° 的只留 {b[-1]['perm_share_median'] * 100:.0f} %。加大余量主要放大自转：m 0.5 到 1.0，自转 {nm['WS_m1']['spin'] / nm['A']['spin']:.1f} 倍，倾摆 {nm['WS_m1']['tilt'] / nm['A']['tilt']:.2f} 倍。", "跨设计加同形 FE"],
    ["结论稳不稳", f"排序在网格、循环、过盈、摩擦、载荷、泡沫屈服下基本不变。绝对值变化很大：δ 0.05 且 3839 N 时转动中位 {S['delta0.05_rise3839']['times_median']:.1f} 倍，μ 0.15 时 {S['mu0.15']['times_median']:.1f} 倍，泡沫屈服时 {S['foam_yield']['times_median']:.1f} 倍。固定 e +2 这一族还没有这些数据。", "同设计配对 FE"],
    ["模型和实测差多少", f"同型号完整股骨的 10 个测点全部偏低，中位误差 {V['ours']['median_rel_pct']:.1f} %，靠近颈部的测点低 {abs(V['near_neck']['M1']):.0f}–{abs(V['near_neck']['MX1']):.0f} %。与已发表模型的 {V['naghavi']['median_rel_pct']:.1f} % 同一水平，不算验证通过。", "实测对照，无柄"],
])}
<div class="note"><b>现在不能下的结论：</b>优于已有的柄，因为还没有同模型参照柄；模型已验证；能预测长期迁移；对放置偏差或纯扭转稳健，这两项都是 0 行；适用于人骨。</div>

<h2>1 实验做了什么</h2>
<p>对象是只靠股骨颈固定的非骨水泥短柄，压配，无领。目标是转动小、接触面积大、去骨少。</p>
{table(["项", "设置"], [
    ["设计变量", "柄长 L 20–45 mm，插入角 α 15–45°，截骨深度 h_cut 16–32 mm，皮质余量 m 0.5–2 mm，另有 9 个形状变量"],
    ["尺寸和入口偏移", "不是设计变量，由模板化决定：在 2 mm 一档的入口偏移里，取肩面积 A0 最大的一档。下文“模板选偏移”指这条规则，“偏移固定”指强制某一档，尺寸在该档重新模板化"],
    ["几何", "Sawbones 3406 皮质和松质，松质底部按空芯建模，这一点还没有确认"],
    ["材料", "皮质 16.8 GPa，泡沫 155 MPa，钛合金 110 GPa，都是线弹性，基线没有泡沫屈服"],
    ["界面", "面对面接触，摩擦 μ 0.3，松质过盈 δ 0.10 mm，暂定值"],
    ["载荷", "头部受力，楼梯 2391 N；另有起身 1714、3839 N 和几组变体；没有肌肉力"],
    ["分析步", "压配、释放、加载、卸载、再加载；多循环行重复后两步"],
    ["主要读数", "首次加载转动，第二次加载的接触面积，微动 P95，去骨量"],
])}
{table(["用途", "内容", "作业数"], group_rows + [["<b>合计</b>", "", f"<b>{len(R):,}</b>"]])}
<p class="ev">读法：倍数和 dex 都是相对值，dex = log10(倍数)，+0.209 dex 就是 {10 ** 0.209:.2f} 倍。差异在噪声 ±{M['noise_dex']} dex 内不比较。判据写在结果之前，见第 3 节。</p>

<h3>代表设计</h3>
{table(["设计", "m mm", "偏移 e", "肩面积 mm²", "去骨 cm³", "转动 °", "微动 µm", "接触 mm²", "说明"], rep_rows)}

<h2>2 结果</h2>

<h3>2.1 少去骨的代价，取决于入口偏移</h3>
{figure(1, "fig1_cost_curve", "去骨量对转动的散点和最好值折线", "去骨量和首次加载转动。折线是每个去骨上限下的最好转动。")}
<ul>
<li><b>模板选偏移时：</b>m ≥ 1.0 在 ≤ 6 cm³ 最好 {caps[6]['m_ge1_rot']:.3f}°，高于判据 G5 的 0.19°。{caps[7]['m_ge1_bone']:.2f} cm³ 是 {caps[7]['m_ge1_rot']:.3f}°，{caps[7.5]['m_ge1_bone']:.2f} cm³ 是 {caps[7.5]['m_ge1_rot']:.3f}°，{caps[8.5]['m_ge1_bone']:.2f} cm³ 是 {caps[8.5]['m_ge1_rot']:.3f}°。</li>
<li><b>偏移固定 +2 时：</b>3 行都低于 0.19°，A {OT[('A', 2.0)]['bone']:.2f} cm³ {OT[('A', 2.0)]['rot']:.3f}°，a95 {OT[('a95', 2.0)]['bone']:.2f} cm³ {OT[('a95', 2.0)]['rot']:.3f}°，a100 {OT[('a100', 2.0)]['bone']:.2f} cm³ {OT[('a100', 2.0)]['rot']:.3f}°。模板选偏移的行要达到 A e +2 的转动，m ≥ 1.0 至少去骨 {reach_m1:.2f} cm³，不限 m 至少 {reach_any:.2f} cm³。</li>
<li><b>为什么之前没看到：</b>选号规则对每个形状只取肩面积最大的一档偏移。A、a95、a100 的这一档是 e 0，它们的 e +2 版以前没有算过。全库模板选到 e +2 的有 {len(tmpl_e2)} 行，其中 m ≥ 1.0 的 {len(tmpl_e2_m1)} 行最好 {best_e2_m1:.3f}°，就是选点 1。优化和主动学习的候选都按这条规则生成，所以搜索碰不到 A 的 e +2。</li>
<li><b>所以：</b>“约 8 cm³ 为下限”不再成立。新的下限也还不能写：这 3 行属于同一族设计，还没有算屈服、细网格、其他载荷和多循环。判据 G28 已写定，OW-3 结束后下限按固定偏移的行写，现在这个量是 {min(o['bone'] for o in ep):.2f} cm³。</li>
</ul>

<h3>2.2 入口偏移的影响不对称</h3>
{figure(2, "fig7_offset", "入口偏移对转动、可逆转动、微动和去骨量的影响", "m 1.0，入口偏移固定为 −2、0、+2，尺寸在该偏移下重新模板化，所以这不是放置误差。e 在截骨面内，正向指向内下方，即股骨距一侧。")}
{table(["设计 A，m 1.0", "e −2", "e 0", "e +2", "e +2 相对 e 0"], [
    ["肩面积 A0 mm²", f"{Am['A0']:.1f}", f"{A0['A0']:.1f}", f"{Ap['A0']:.1f}", f"{Ap['A0'] / A0['A0']:.2f} 倍"],
    ["去骨 cm³", f"{Am['bone']:.2f}", f"{A0['bone']:.2f}", f"{Ap['bone']:.2f}", f"{Ap['bone'] / A0['bone']:.2f} 倍"],
    ["首次转动 °", f"{Am['rot']:.4f}", f"{A0['rot']:.4f}", f"{Ap['rot']:.4f}", f"{Ap['rot'] / A0['rot']:.2f} 倍"],
    ["卸载后残留 °", f"{Am['rot_perm']:.4f}", f"{A0['rot_perm']:.4f}", f"{Ap['rot_perm']:.4f}", f"{Ap['rot_perm'] / A0['rot_perm']:.2f} 倍"],
    ["可逆转动 °", f"{Am['rot_rev']:.4f}", f"{A0['rot_rev']:.4f}", f"{Ap['rot_rev']:.4f}", f"{Ap['rot_rev'] / A0['rot_rev']:.1f} 倍"],
    ["微动 P95 µm", f"{Am['f1']:.1f}", f"{A0['f1']:.1f}", f"{Ap['f1']:.1f}", f"{Ap['f1'] / A0['f1']:.1f} 倍"],
    ["接触面积 mm²", f"{Am['contact']:.0f}", f"{A0['contact']:.0f}", f"{Ap['contact']:.0f}", f"{Ap['contact'] / A0['contact']:.2f} 倍"],
    ["柄体应力 P99 MPa", f"{Am['vm']:.1f}", f"{A0['vm']:.1f}", f"{Ap['vm']:.1f}", f"{Ap['vm'] / A0['vm']:.2f} 倍"],
])}
<ul>
<li><b>e −2 很差：</b>5 个设计都升高 {sg(min(dex_em))} 到 {sg(max(dex_em))} dex，约 {10 ** min(dex_em):.1f}–{10 ** max(dex_em):.1f} 倍。0 FE 模板化显示，卡点在 e −0.5 和 −1 之间从约 13 mm 跳到入口。转动的悬崖是否就在这里还没有 FE 数据，OW-3 正在算。</li>
<li><b>e +2 的代价在可逆部分：</b>残留转动几乎不变，可逆转动和微动明显增大。只看首次转动的 {Ap['rot'] / A0['rot']:.2f} 倍，会低估这部分代价。</li>
<li><b>同形扫描也碰到同一个跳变：</b>m 2.0 模板跳到 e −2，转动 {sm('m', 'A', 2.0)['rot']:.3f}°，比外推大约 2.1 倍。m 1.75 正贴在跳变边上，所以 {sm('m', 'A', 1.75)['bone']:.2f} cm³、{sm('m', 'A', 1.75)['rot']:.3f}° 这个点很脆弱。</li>
<li><b>e 为正时离柄长的硬边界很近：</b>0 FE 模板化显示，L 44 在 e +0.5 到 +2.5 全部低于号下限，L 43.75 从 e +1.5 起颈底伸出超限。A 的 L 43.06 离这个边界不到 0.7 mm，所以低去骨候选不能再靠加长 L。a82、a96 的 e +2 也因颈底伸出超限不可用。</li>
</ul>

<h3>2.3 已测范围内，余量的影响大于柄长和插入角</h3>
{figure(3, "fig2_one_factor", "余量、柄长、插入角的单因素扫描", "都是设计 A 的形状，每次只改一个量。上排是转动，下排是去骨量。")}
{table(["m mm", "0.5", "0.75", "1.0", "1.5", "1.6", "1.75", "2.0，跳到 e −2"], [
    ["转动 °"] + [f"{sm('m', 'A', x)['rot']:.4f}" for x in (0.5, 0.75, 1.0, 1.5, 1.6, 1.75, 2.0)],
    ["相对 m 0.5，倍"] + [f"{sm('m', 'A', x)['times_A']:.2f}" for x in (0.5, 0.75, 1.0, 1.5, 1.6, 1.75, 2.0)],
    ["去骨 cm³"] + [f"{sm('m', 'A', x)['bone']:.2f}" for x in (0.5, 0.75, 1.0, 1.5, 1.6, 1.75, 2.0)],
])}
<ul>
<li>相对 m 1.0 版：L 44 是 {sm('L', 'm1.0', 44)['times_ctrl']:.2f} 倍，去骨只多 {sm('L', 'm1.0', 44)['bone'] - W1['bone']:.2f} cm³；α 50 是 {sm('alpha', 'm1.0', 50)['times_ctrl']:.2f} 倍，去骨多 {sm('alpha', 'm1.0', 50)['bone'] - W1['bone']:.2f} cm³；两者叠加 {snote('wl_m1_a50_L44')['times_ctrl']:.2f} 倍，转动 {snote('wl_m1_a50_L44')['rot']:.4f}°。</li>
<li>L 变长的增益贴着空腔，依赖还没确认的空芯假设。之前的“L 悬崖”不是物理效应，而是模板跳偏移造成的，偏移固定时 L 变长转动一直下降。</li>
<li>α 超过 45° 已在设计盒外。头力范围内 α 没有明显的扭转代价，纯扭矩下还不知道。</li>
</ul>

<h3>2.4 紧的设计一次落座后稳定，松的设计持续摆动</h3>
{figure(4, "fig3_mechanism", "永久份额、接触面积和自转倾摆分量", "a、b 是严格基线全库，c 是设计 A 形状的余量扫描。")}
{table(["转动范围", "设计数", "永久份额中位", "可逆份额中位", "自转份额中位", "接触面积中位 mm²"], [
    [("&lt; 0.1°" if x['lo'] == 0 else (f"&gt; 1°" if x['lo'] == 1.0 else f"{x['lo']:g}–{x['hi']:g}°")), f"{x['n']}", f"{x['perm_share_median']:.2f}", f"{x['rev_share_median']:.2f}", f"{x['spin_share_median']:.2f}", f"{x['contact_median']:.0f}"] for x in b
])}
<ul>
<li>转动和接触面积的 Spearman 是 {sg(M['mechanism']['spearman_rot_contact'], 2)}，这是相关，不能直接读成因果。</li>
<li>余量从 0.5 到 1.0，自转从 {nm['A']['spin']:.4f}° 到 {nm['WS_m1']['spin']:.4f}°，倾摆从 {nm['A']['tilt']:.4f}° 到 {nm['WS_m1']['tilt']:.4f}°。自转是绕柄轴的分量，倾摆是垂直于柄轴的分量。所以加大余量主要放大自转，它和抗扭能力的关系要等纯扭矩结果。</li>
<li>这里的泡沫是线弹性的，没有压溃，所以机制只说到界面滑移这一层。</li>
</ul>

<h3>2.5 绝对值很敏感，排序基本不变</h3>
{figure(5, "fig4_sensitivity", "各假设下相对基线的转动倍数", "每点是一个设计相对自身基线的转动倍数。偏移固定 +2 的设计不在这张图里，它们还没有条件行。")}
{table(["m 1.0 相对 A", "楼梯 2391 N", "楼梯方向 3606 N", "矢状 40°", "μ 0.2", "μ 0.15"], [
    ["差值 dex"] + [sg(mc[k]) for k in ("stair", "stair3606", "sag40", "mu0.2", "mu0.15")],
    ["倍数"] + [f"{10 ** mc[k]:.2f}" for k in ("stair", "stair3606", "sag40", "mu0.2", "mu0.15")],
])}
{table(["10 循环", "第 1 循环峰值 °", "第 10 循环峰值 °", "倍数", "第 9 循环下沉增量 µm", "可逆转动，第 9 / 第 1 循环"], [
    [k.replace("A m1", "A，m 1.0"), f"{CY[k]['peak1']:.4f}", f"{CY[k]['peak10']:.4f}", f"{CY[k]['ratio_10_1']:.3f}", f"{abs(CY[k]['sub_inc9']):.2f}", f"{CY[k]['rev9'] / CY[k]['rev1']:.2f}"] for k in ("A", "A m1", "init29", "C")
])}
<ul>
<li><b>数值设置影响小：</b>网格 h 1.94、2.06 是 {S['mesh_h1.94_2.06']['times_min']:.2f}–{S['mesh_h1.94_2.06']['times_max']:.2f} 倍，噪声 2 倍 rms {cl['nz3_2rms']:.3f} dex。</li>
<li><b>物理假设影响大：</b>μ 0.2、0.15 是 {S['mu0.2']['times_median']:.2f}、{S['mu0.15']['times_median']:.2f} 倍；泡沫屈服 {S['foam_yield']['times_median']:.2f} 倍；3606 N 载荷只大 1.5 倍，转动却是 {S['stair3606']['times_min']:.1f}–{S['stair3606']['times_max']:.1f} 倍，所以 2391 N 下的绝对值偏乐观。</li>
<li><b>排序：</b>全范围 Spearman 大多 ≥ 0.99，只看转动 &lt; 0.1° 的设计是 {min(tight):.2f}–{max(tight):.2f}，行数更少。b9p 的 Kendall τ 是 {M['g18']['delta0.05']['kendall']:.3f}、{M['g18']['rise3839']['kendall']:.3f}、{M['g18']['delta0.05_rise3839']['kendall']:.3f}，第一名在各自的设计集内都不变。</li>
<li><b>循环：</b>4 个设计的排序从第 1 到第 10 循环不变。紧的设计接近饱和，松的设计还在下沉。这个模型没有压溃和塑性，只说明界面滑移在收敛，不能预测长期迁移。</li>
</ul>

<h3>2.6 第一份实测对仿真，还不算验证通过</h3>
{figure(6, "fig5_validation", "10 个测点的实测和两个模型", "同型号 3406 完整股骨，1200 N，ISO 7206-4，没有柄。实测和 Naghavi 模型从论文图 5-23a 按像素读取。")}
{table(["口径", "中位相对误差 %", "偏差 MPa", "一致性界限 MPa", "Pearson"], [
    ["本项目，远场 2.5 mm，主比较", f"{V['ours']['median_rel_pct']:.1f}", sg(V['ours']['bias_mpa'], 2), f"{sg(V['ours']['loa'][0], 2)} 到 {sg(V['ours']['loa'][1], 2)}", f"{V['ours']['pearson']:.3f}"],
    ["本项目，远场 6 mm", f"{V['ours_far6']['median_rel_pct']:.1f}", sg(V['ours_far6']['bias_mpa'], 2), f"{sg(V['ours_far6']['loa'][0], 2)} 到 {sg(V['ours_far6']['loa'][1], 2)}", f"{V['ours_far6']['pearson']:.3f}"],
    ["测点沿圆周转 +15°", f"{V['plus15']['median_rel_pct']:.1f}", sg(V['plus15']['bias_mpa'], 2), f"{sg(V['plus15']['loa'][0], 2)} 到 {sg(V['plus15']['loa'][1], 2)}", f"{V['plus15']['pearson']:.3f}"],
    ["测点沿圆周转 −15°", f"{V['minus15']['median_rel_pct']:.1f}", sg(V['minus15']['bias_mpa'], 2), f"{sg(V['minus15']['loa'][0], 2)} 到 {sg(V['minus15']['loa'][1], 2)}", f"{V['minus15']['pearson']:.3f}"],
    ["Naghavi 自己的模型", f"{V['naghavi']['median_rel_pct']:.1f}", sg(V['naghavi']['bias_mpa'], 2), f"{sg(V['naghavi']['loa'][0], 2)} 到 {sg(V['naghavi']['loa'][1], 2)}", f"{V['naghavi']['pearson']:.3f}"],
])}
<ul>
<li>中位误差和 Naghavi 2023 的模型相近，但 Pearson 明显更低、一致性界限更宽，所以分布形状不如它。</li>
<li>偏得最多的是靠近颈部的测点，那正是柄所在的区域。去掉离固支面近的 M4、L4 后，中位误差是 29.1 %，高于 27 %；判据写的是 10 个测点，所以判定不变。</li>
<li>测点沿圆周转 ±15°，中位误差就在 19.5–36.5 % 之间，比网格的影响大得多。两个模型都低约 4 MPa，可能有实测方面的共同偏差，现在分不开。</li>
<li>已知差异：我们的骨来自 CAD，不是这一根的 CT；头力在头心 14 mm 球内分载，不是平面加载头；固支在小转子下 150 mm，不是灌封面。这些是可能原因，还没有验证。另一组 Bath 实测的股骨更小，映射失败，只作记录。</li>
</ul>

<h3>2.7 代理模型的预测都由之后的 FE 核对过</h3>
{figure(7, "fig6_prospective", "GP 预测和 FE 实算的对比", "预测在 FE 之前冻结。这里只画优化选点，改了载荷的行不算。")}
<ul>
<li>各轮搜索的区域不同，所以数字变小不全是模型变好。AL-3′ 的 sd 只有约 {P['al3m']['opt']['sd_median']:.3f} dex，{P['al3m']['opt']['n']} 行里 {P['al3m']['opt']['n_worse']} 行 FE 比预测差，平均偏差 {sg(P['al3m']['opt']['bias'])} dex，预测略偏乐观。</li>
<li>探索组 {P['al3m']['global']['n']} 行 RMSE {P['al3m']['global']['rmse']:.3f} dex，随机组 {P['al3m']['random']['n']} 行 {P['al3m']['random']['rmse']:.3f} dex。</li>
<li>场模型：U-Net v0.5 只算探索性结果，3 个种子。柄体 vM p99 的 RMSE，test_corner 3.64 对 GP 3.92 MPa，差值在噪声内；test_unbiased 3.11 对 5.36 MPa，只有 10 行；整个测试集 6.32 对 5.57 MPa，GP 更好。所以不写 U-Net 好于 GP，标量和选点继续用 GP，U-Net 只负责体积场。数字取自神经网络技术路线第 9.8 节。</li>
</ul>

<h2>3 事先写定的判据，结果如何</h2>
<p class="ev">这些判据都写在对应结果之前。结果取自执行记录，带数字的项除 G4 外都由本报告的数据复算过。</p>
{table(["判据", "问什么", "结果", "走向"], [
    ["G1", "m 1.0 版 α 放宽的最好改进 ≤ −0.04 dex", f"α 50 {sg(sm('alpha', 'm1.0', 50)['dex_vs_ctrl'])} dex", "第一个条件成立；放宽 α 还要过 G2，要纯扭矩结果"],
    ["G3", "AL-3′ 优化选点的前瞻误差", f"RMSE {P['al3m']['opt']['rmse']:.3f} dex，覆盖 {P['al3m']['opt']['n_in90']} / {P['al3m']['opt']['n']}", "不触发，局部 GP 可信"],
    ["G4", "m ≥ 1.0 各去骨上限的改进 ≥ 0.04 dex", "≤ 5.5、≤ 6、≤ 8 cm³ 都超过", "可提议 AL-4，已批准 AL-4m"],
    ["G5", "m ≥ 1.0、≤ 6 cm³ 的最好转动 ≤ 0.19°", f"{caps[6]['m_ge1_rot']:.3f}°", "走“约 8 cm³ 为下限”一行，后被 G25 更正：0.273° 只在模板选偏移时成立"],
    ["G10", "μ 改变时排序是否稳定", f"Spearman {S['mu0.2']['spearman']:.3f}、{S['mu0.15']['spearman']:.3f}，第一名不变", "μ 只作全局条件"],
    ["G11", "VAL-1 10 个测点的中位相对误差", f"{V['ours']['median_rel_pct']:.1f} %", "20–27 % 中间档，与已发表模型同一水平，不等于验证通过"],
    ["G15", "第 2–5 名的差异是否超过噪声", f"相邻差最大 {max(cl['adjacent_dex']):.4f} dex", "报“第 1 名加一簇”"],
    ["G16", "偏移固定时 L 变长是否转动升高", f"一直下降，A 到 L 44.5 是 {sg(sm('L', 'm0.5', 44.5)['dex_vs_ctrl'])} dex", "L 悬崖是模板跳变，不是物理效应"],
    ["G18", "条件变化下的 Kendall τ ≥ 0.8", f"{M['g18']['delta0.05']['kendall']:.3f}、{M['g18']['rise3839']['kendall']:.3f}、{M['g18']['delta0.05_rise3839']['kendall']:.3f}", "写“稳健”，只说排序；固定 e +2 这一族不在其中"],
    ["G20", "头力范围内的扭矩放大效应", f"α 60 升高 +0.031 dex，未到 0.04；m 1.0 升高 {sg(mc['sag40'] - mc['stair'])} dex，正好在线上", "α 的扭矩臂猜测未获支持；余量的代价随扭矩放大，幅度不大"],
    ["G21", "m 1.0 上 L 44 及其与 α 的叠加", f"L 44 {sg(sm('L', 'm1.0', 44)['dex_vs_ctrl'])} dex；再加 α 50 约 −0.085 dex", "台架候选改用 L 44 版；可以叠加，依赖空芯假设"],
    ["G25", "入口偏移是否敏感；e +2 是否低于 0.19°", f"e −2 {sg(min(dex_em))} 到 {sg(max(dex_em))} dex；e +2 有 {len(ep)} 行低于 0.19°", "两条都触发：偏移敏感，低去骨方向重开"],
    ["G22–G24", "AL-4m 的下限、前瞻误差、搜索收口", "B 部分先不喂", "未判"],
    ["G26–G28", "e 是否连续、悬崖位置、固定偏移下的下限", "OW-3 在算", "未判"],
])}

<h2>4 这些结果的限制</h2>
{table(["限制", "现状", "影响"], [
    ["单根复合骨", "只有一根 Sawbones 3406，没有第二根骨", "结论不能外推到其他股骨，也不能外推到人骨"],
    ["空芯假设", "松质底部按空芯建模，没有确认", "L 的上限和 L 44 的增益都依赖它"],
    ["线弹性泡沫", f"严格基线 {len(strict)} 行里 {press_over} 行的压配 P95 高于泡沫强度 6.2 MPa；屈服面板转动中位放大 {S['foam_yield']['times_median']:.1f} 倍", "绝对值不能当结论；余量代价在屈服下还没算"],
    ["没有参照柄", "同模型上没有算过已上市的柄", "转动只能在设计之间比，不能写相对优势"],
    ["放置偏差", "0 行；文献（Dopico-González 2010）报告放置参数最敏感", "对放置的稳健性完全未知"],
    ["纯扭转和肌肉力", "各 0 行；楼梯工况下头力绕柄轴的扭矩在 A 上只有 4.72 N·m", "抗扭结论还不能下"],
    ["骨折", "没有判据；筛查 Z1 未开始，已存的场数据够做，不用新 FE", "转动和微动都不反映骨折风险"],
    ["贴边界", "最优区贴着 h_cut 16 mm 下限和 q 3.0 上限，m 贴 0.5", "最优可能受设计盒限制"],
    ["e +2 这一族", "3 行同族，没有屈服、细网格、其他载荷、多循环、颈部皮质应变", "不算设计空间里的独立证据"],
    ["实测对照", "只有完整股骨，没有柄", "不验证柄和骨的界面"],
])}

<h2>5 还没定的实验决定</h2>
<p class="ev">状态取自 2026-11-03 19:57 UTC 的执行记录。</p>
{table(["事项", "现状", "谁定"], [
    ["OW-3，批次 b22，更细的入口偏移", "用户已批准，9 行，19:56 UTC 开跑，结果不在本报告。提议的第 10 行 WL_m1_L44 × e +2 模板化不可行，已去掉。判据 G26–G28 已写定", "已定，等结果"],
    ["AL-4m 的 B 部分，批次 b21", "用 v0.8 选出 7 行，不是原定的 12 行，这 7 行的预测都被 A 的 e +2 压过。先不喂，等 OW-3 的结果再定", "用户"],
    ["PF-1 放置、TQ-1 纯扭转、FY-2 屈服、REF-1 参照柄", "都未批准，还差两个钩子", "用户"],
    ["起身扭转的定义和扭矩", "待定，默认定义 A、B 都冒烟", "导师"],
    ["放置公差", "待定", "用户或导师"],
    ["参照柄款式", "待定，默认不开 REF-1", "导师"],
    ["余量和截骨下限", "待定，默认 m ≥ 1.0、h_cut 16 不动", "导师"],
    ["松质底部是否空芯", "没有答复，继续空芯假设", "Churun、导师"],
])}

<h2>6 数据和核对</h2>
<ul>
<li>数据：db3406 {M['export']}，11-03 17:46 UTC 导出，{M['n_rows']:,} 行，{M['n_done']:,} 行成功，{M['n_failed']} 行失败。多循环和实测对照的逐点读数来自 2026-11-03 对队列的只读读取。</li>
<li>核对：脚本把本报告用到的数字和执行记录逐项比较，81 项里 79 项一致。不一致的 2 项是 AL-1 的旧记录 0.118 dex 和覆盖 0.63，复算是 {P['al1']['opt']['rmse']:.3f} dex 和 {P['al1']['opt']['cov90']:.2f}，已在 11-03 更正。</li>
<li>和执行记录不同的一处：记录写“e +2 这一档从未被选到”，全库其实有 {len(tmpl_e2)} 行模板选到 e +2。这句话只对 A、a95、a100 成立，本报告按数据写。</li>
<li>文件：逐行数字、生成脚本和中英文图都在研究日志的 <code>结果整理_2026-11-03</code> 文件夹。</li>
</ul>
"""

html = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>股骨颈短柄实验总结</title>
<style>{CSS}</style>
</head>
<body>
{body}
</body>
</html>
"""
OUT.write_text(html, encoding="utf-8")
print("written", OUT, round(OUT.stat().st_size / 1e6, 2), "MB")
