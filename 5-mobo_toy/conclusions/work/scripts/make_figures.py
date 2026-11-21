"""Render the six figures from data/*.csv and data/metrics.json, in Chinese and English. No number is typed here except the published gauge labels in the text.

    python -X utf8 make_figures.py [--lang zh en] [--only 1 2 ...]

Colours are the validated first three categorical slots (validate_palette.py --pairs all, surface white: all checks pass, aqua below 3:1, so every aqua mark carries a shape and a label).
"""
import argparse
import csv
import json
import math
import pathlib
import re
from statistics import median

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.font_manager import FontProperties  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent.parent
DATA = HERE / "data"
FIG = HERE / "figures"
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, MUTED, GRID, AXIS, CONTEXT, WASH = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#d5d4cd", "#f4f3ef"
M = json.load(open(DATA / "metrics.json", encoding="utf-8"))
NOISE = M["noise_dex"]
SNAP = M["snapshot_utc"][:16].replace("T", " ")


def read(name):
    out = []
    for r in csv.DictReader(open(DATA / name, encoding="utf-8-sig")):
        o = {}
        for k, v in r.items():
            if v in ("True", "False"):
                o[k] = v == "True"
            else:
                try:
                    o[k] = float(v)
                except (TypeError, ValueError):
                    o[k] = v
        out.append(o)
    return out


def style(lang):
    plt.rcParams.update({"font.family": ["Microsoft YaHei"] if lang == "zh" else ["Arial"], "font.size": 9, "axes.edgecolor": AXIS, "axes.linewidth": 0.6, "axes.labelcolor": INK2, "axes.labelsize": 9,
                         "xtick.color": AXIS, "ytick.color": AXIS, "xtick.labelcolor": INK2, "ytick.labelcolor": INK2, "xtick.labelsize": 8.5, "ytick.labelsize": 8.5, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
                         "axes.spines.top": False, "axes.spines.right": False, "axes.axisbelow": True, "legend.frameon": False, "legend.fontsize": 8.5, "figure.facecolor": "white", "savefig.facecolor": "white", "axes.unicode_minus": False, "pdf.fonttype": 42})


def wrap(fig, text, size, frac=0.925):
    """Wrap to the figure width by measured text width: Chinese by character, keeping punctuation on the line it ends, Latin by word."""
    r = fig.canvas.get_renderer()
    fp = FontProperties(family=plt.rcParams["font.family"], size=size)
    limit = fig.get_figwidth() * fig.dpi * frac
    out = []
    for para in text.split("\n"):
        cur = ""
        for tok in re.findall(r"[\u4e00-\u9fff][，。、；：）]*|[^\u4e00-\u9fff\s]+\s*|\s+", para):
            if cur and r.get_text_width_height_descent(cur + tok, fp, False)[0] > limit:
                out.append(cur.rstrip())
                cur = tok
            else:
                cur += tok
        out.append(cur.rstrip())
    return "\n".join(out)


def header(fig, title, sub, foot):
    h = fig.get_figheight()
    tt = fig.text(0.045, 1 - 0.14 / h, title, fontsize=12, fontweight="bold", color=INK, va="top")
    width = tt.get_window_extent(renderer=fig.canvas.get_renderer()).width / (fig.get_figwidth() * fig.dpi)
    if width > 0.93:
        tt.set_fontsize(12 * 0.93 / width)
    fig.text(0.045, 1 - 0.41 / h, wrap(fig, sub, 9), fontsize=9, color=INK2, va="top", linespacing=1.45)
    fig.text(0.045, 0.012, wrap(fig, foot, 7.5), fontsize=7.5, color=MUTED, va="bottom", linespacing=1.35)


def signed(v, fmt="+.0f"):
    return format(v, fmt).replace("-", "−")


def foot(lang):
    if lang == "zh":
        return f"单根 Sawbones 3406，空芯假设，线弹性泡沫，δ 0.10 mm，楼梯 2391 N。数据：db3406 {M['export']}。"
    return f"One Sawbones 3406, hollow-core assumption, linear-elastic foam, δ 0.10 mm, stair 2391 N. Data: db3406 {M['export']}."


def log_ticks(ax, axis, ticks, fmt="{:g}"):
    a = ax.yaxis if axis == "y" else ax.xaxis
    a.set_major_locator(FixedLocator(ticks))
    a.set_major_formatter(FuncFormatter(lambda v, _: fmt.format(v)))
    a.set_minor_locator(NullLocator())


def note(ax, xy, xytext, text, ha="left", va="center", fs=8):
    ax.annotate(text, xy=xy, xytext=xytext, fontsize=fs, color=INK, ha=ha, va=va, linespacing=1.25, zorder=8, bbox=dict(fc="white", ec="none", pad=1.2, alpha=0.88), arrowprops=dict(arrowstyle="-", color=INK2, lw=0.6, shrinkA=0, shrinkB=2))


def save(fig, lang, name):
    d = FIG / lang
    d.mkdir(parents=True, exist_ok=True)
    fig.savefig(d / f"{name}.png", dpi=220)
    if lang == "en":
        fig.savefig(d / f"{name}.pdf")
    plt.close(fig)


def fig1(lang):
    R = read("fig1_cost_curve.csv")
    C = M["cost"]
    cap = {c["cap"]: c for c in C["caps"]}
    by = {r["job_id"]: r for r in R}
    env1, env0 = C["env_m1"], C["env_all"]
    p1 = cap[6]["m_ge1_rot"]
    ow = [r for r in R if r["layer"] == "OW-2" and r["forced_e"] == 2.0]
    owm = [r for r in R if r["layer"] == "OW-2" and r["forced_e"] == -2.0]
    best_ow = min(ow, key=lambda r: r["rot"])
    R = [r for r in R if r["layer"] != "OW-2" or r["forced_e"] == 0.0]
    t = {"zh": dict(title=f"m ≥ 1.0 低于 6 cm³：模板选偏移时最好 {p1:.3f}°，偏移固定 +2 时已到 {best_ow['rot']:.3f}°",
                    sub=f"每点一个 FE 设计，共 {C['n_curve']} 个，这里只显示去骨 4 到 10.6 cm³、转动 2° 以内。折线只算盒内、偏移由模板选的设计。\n偏移 +2 的 {len(ow)} 行属于同一族设计，还没有算屈服、细网格和其他载荷，所以下限还不能写。",
                    x="去骨量 cm³", y="首次加载转动 °", ctx="m < 1.0，盒内", m1="m ≥ 1.0，盒内", out="超出盒子，α > 45°", e1="m ≥ 1.0 的最好值", e0="不限 m 的最好值", wash="6 到 7.4 cm³\n只有同形扫描和 1 个选点", g5="G5 门槛：≤ 6 cm³ 时 0.19°", ow="偏移固定 +2", owm="偏移固定 −2"),
         "en": dict(title=f"m ≥ 1.0 below 6 cm³: {p1:.3f}° with the template's offset, {best_ow['rot']:.3f}° with the offset held at +2",
                    sub=f"One dot per FE design, {C['n_curve']} in all, showing 4 to 10.6 cm³ and under 2°. Lines: best under each bone cap, in box, template offset.\nThe {len(ow)} rows at e +2 are one design family, with no yield, fine-mesh or other-load runs yet, so no lower limit can be stated.",
                    x="Bone removed, cm³", y="First-load rotation, °", ctx="m < 1.0, in box", m1="m ≥ 1.0, in box", out="Outside box, α > 45°", e1="Best with m ≥ 1.0", e0="Best with any m", wash="6 to 7.4 cm³\none shape scan, one pick", g5="G5 limit: 0.19° at ≤ 6 cm³", ow="Offset held at +2", owm="Offset held at −2")}[lang]
    fig, ax = plt.subplots(figsize=(7.6, 5.5))
    fig.subplots_adjust(left=0.085, right=0.975, top=0.735, bottom=0.13)
    xmax, xmin = 10.6, 4.0
    ax.axvspan(6.0, 7.38, color=WASH, lw=0, zorder=0)
    ctx = [r for r in R if not r["m_ge1"] and r["in_box"]]
    m1 = [r for r in R if r["m_ge1"] and r["in_box"]]
    out = [r for r in R if not r["in_box"]]
    ax.scatter([r["bone"] for r in ctx], [r["rot"] for r in ctx], s=14, c=CONTEXT, lw=0, zorder=2, label=t["ctx"])
    ax.scatter([r["bone"] for r in m1], [r["rot"] for r in m1], s=26, c=BLUE, edgecolors="white", linewidths=0.6, zorder=3, label=t["m1"])
    ax.scatter([r["bone"] for r in out], [r["rot"] for r in out], s=30, marker="D", facecolors="white", edgecolors=INK, linewidths=0.8, zorder=4, label=t["out"])
    ax.scatter([r["bone"] for r in ow], [r["rot"] for r in ow], s=58, marker="^", c=AQUA, edgecolors=INK, linewidths=0.8, zorder=7, label=t["ow"])
    ax.scatter([r["bone"] for r in owm], [r["rot"] for r in owm], s=42, marker="v", facecolors="white", edgecolors=AQUA, linewidths=1.2, zorder=6, label=t["owm"])
    for env, c, lab in ((env0, ORANGE, t["e0"]), (env1, BLUE, t["e1"])):
        xs, ys = [e["bone"] for e in env] + [xmax], [e["rot"] for e in env] + [env[-1]["rot"]]
        ax.step(xs, ys, where="post", color=c, lw=1.6, zorder=5, label=lab, solid_joinstyle="round")
    ax.plot([xmin, 6.0], [0.19, 0.19], color=INK2, lw=0.8, zorder=1)
    ax.text(xmin + 0.06, 0.178, t["g5"], fontsize=8, color=INK2, va="top")
    ax.text(6.69, 0.047, t["wash"], fontsize=8, color=INK2, ha="center", va="center", linespacing=1.25, zorder=6)
    ax.set(xlim=(xmin, xmax), ylim=(0.021, 2), xlabel=t["x"], ylabel=t["y"])
    ax.set_yscale("log")
    log_ticks(ax, "y", [0.03, 0.05, 0.1, 0.2, 0.5, 1, 2])
    def pt(j):
        r = next(x for x in R if x["job_id"].startswith(j))
        return r["bone"], r["rot"]
    lab = lambda j: f"{pt(j)[0]:.2f} cm³, {pt(j)[1]:.3f}°"  # noqa: E731
    W = "db_ws_p13_a105_91e458e3_"
    note(ax, pt("db_al_al3m_04"), (4.1, 0.29), lab("db_al_al3m_04"))
    note(ax, pt("db_al_al3m_01"), (6.12, 0.43), lab("db_al_al3m_01"))
    note(ax, pt(W + "m1.5"), (7.62, 0.205), "m 1.5, " + lab(W + "m1.5"))
    note(ax, pt(W + "m1.75"), (7.62, 0.42), "m 1.75, " + lab(W + "m1.75"))
    note(ax, pt("db_al_al3m_11"), (8.25, 0.128), lab("db_al_al3m_11"))
    note(ax, pt(W + "wl_m1_L44"), (8.8, 0.085), "m 1.0, " + lab(W + "wl_m1_L44"))
    note(ax, pt("db_al_al1_07"), (6.08, 0.078), "m 0.50, " + lab("db_al_al1_07"))
    note(ax, pt("sb13_a105"), (9.0, 0.0242), "A, " + lab("sb13_a105"))
    note(ax, (best_ow["bone"], best_ow["rot"]), (4.1, 0.056), f"m {best_ow['m']:.1f}, e {best_ow['e']:+g}, {best_ow['bone']:.2f} cm³, {best_ow['rot']:.3f}°")
    note(ax, pt(W + "wl_m1_a55_L44.75"), (6.65, 0.0262), "α 55, m 1.0, " + lab(W + "wl_m1_a55_L44.75"))
    h, l = ax.get_legend_handles_labels()
    order = [l.index(x) for x in (t["e1"], t["e0"], t["ow"], t["owm"], t["m1"], t["ctx"], t["out"])]
    fig.legend([h[i] for i in order], [l[i] for i in order], loc="upper left", bbox_to_anchor=(0.075, 1 - 0.92 / fig.get_figheight()), ncol=4, handlelength=1.5, columnspacing=1.3, handletextpad=0.4, labelspacing=0.3)
    header(fig, t["title"], t["sub"], foot(lang))
    save(fig, lang, "fig1_cost_curve")


def fig2(lang):
    S = read("fig2_one_factor.csv")
    A = M["A"]
    ws = {(s["factor"], s["series"], round(s["x"], 2)): s for s in S}
    m1 = ws[("m", "A", 1.0)]
    L44 = next(s for s in S if s["factor"] == "L" and s["series"] == "m1.0" and abs(s["x"] - 44) < 1e-6)
    a50 = next(s for s in S if s["factor"] == "alpha" and s["series"] == "m1.0" and abs(s["x"] - 50) < 1e-6)
    t = {"zh": dict(title=f"在已测范围内余量影响最大：m 1.0 的转动是 A 的 {m1['times_A']:.2f} 倍，L 和 α 只能收回一部分",
                    sub=f"都是设计 A 的形状，每次只改一个量。相对 m 1.0 版，L 44 是 {L44['times_ctrl']:.2f} 倍，α 50 是 {a50['times_ctrl']:.2f} 倍。\n点的大小约等于噪声 ±{NOISE} dex。L 行的入口偏移固定为 0。",
                    r="首次加载转动 °", b="去骨量 cm³", xm="皮质余量 m，mm", xl="柄长 L，mm", xa="插入角 α，°", k1="m 0.5", k2="m 1.0", k3="m 1.0 × α 50", k4="空心：超出 v1 盒子", box="盒子上限 45°", l44="依赖空芯假设", jump="m {m:g} 跳到 e −2\n{rot:.3f}°，超出本图"),
         "en": dict(title=f"Over the tested range margin matters most: m 1.0 rotates {m1['times_A']:.2f} times A, L and α recover only part",
                    sub=f"All on the shape of design A, one variable at a time. Against the m 1.0 version, L 44 gives {L44['times_ctrl']:.2f} times and α 50 gives {a50['times_ctrl']:.2f} times.\nDot size is about the ±{NOISE} dex noise. L rows hold the entry offset at 0.",
                    r="First-load rotation, °", b="Bone removed, cm³", xm="Cortical margin m, mm", xl="Stem length L, mm", xa="Insertion angle α, °", k1="m 0.5", k2="m 1.0", k3="m 1.0 × α 50", k4="Hollow: outside the v1 box", box="Box limit 45°", l44="relies on the hollow core", jump="m {m:g} jumps to e −2\n{rot:.3f}°, off this plot")}[lang]
    fig, axes = plt.subplots(2, 3, figsize=(7.6, 5.4), sharex="col", gridspec_kw={"height_ratios": [1.65, 1], "hspace": 0.1, "wspace": 0.12})
    fig.subplots_adjust(left=0.085, right=0.985, top=0.77, bottom=0.135)
    (a1, a2, a3), (b1, b2, b3) = axes

    def draw(top, bot, rows, color, marker="o", line=True):
        rows = sorted(rows, key=lambda r: r["x"])
        xs, rot, bone = [r["x"] for r in rows], [r["rot"] for r in rows], [r["bone"] for r in rows]
        if line:
            top.plot(xs, rot, color=color, lw=1.6, zorder=3)
            bot.plot(xs, bone, color=color, lw=1.6, zorder=3)
        for r in rows:
            face = color if r["in_box"] else "white"
            top.scatter(r["x"], r["rot"], s=34, marker=marker, facecolors=face, edgecolors=color if not r["in_box"] else "white", linewidths=1.1 if not r["in_box"] else 0.7, zorder=5)
            bot.scatter(r["x"], r["bone"], s=30, marker=marker, facecolors=face, edgecolors=color if not r["in_box"] else "white", linewidths=1.1 if not r["in_box"] else 0.7, zorder=5)

    M_all = sorted([s for s in S if s["factor"] == "m"], key=lambda r: r["x"])
    M_rows = [r for r in M_all if r["e"] == 0.0]            # m 2.0 jumps to e -2 and is reported as text
    jump = [r for r in M_all if r["e"] != 0.0]
    a1.plot([r["x"] for r in M_rows], [r["rot"] for r in M_rows], color=AXIS, lw=1.2, zorder=2)
    b1.plot([r["x"] for r in M_rows], [r["bone"] for r in M_rows], color=AXIS, lw=1.2, zorder=2)
    draw(a1, b1, [r for r in M_rows if r["x"] == 0.5], ORANGE, line=False)
    draw(a1, b1, [r for r in M_rows if r["x"] > 0.5], BLUE, line=False)
    for r in M_rows:
        if r["x"] == 1.6:
            continue
        a1.annotate(f"{r['rot']:.4f}°" if r["x"] == 0.5 else f"×{r['times_A']:.2f}", (r["x"], r["rot"]), xytext=(-14 if r["x"] == 1.5 else -2, 6 if r["x"] == 1.5 else 8), textcoords="offset points", ha="center", fontsize=8, color=INK)
        b1.annotate(f"{r['bone']:.2f}", (r["x"], r["bone"]), xytext=(0, 7), textcoords="offset points", ha="center", fontsize=8, color=INK)
    for r in jump:
        b1.scatter(r["x"], r["bone"], s=34, marker="v", facecolors="white", edgecolors=BLUE, linewidths=1.1, zorder=5)
        a1.text(0.97, 0.05, t["jump"].format(m=r["x"], rot=r["rot"]), transform=a1.transAxes, ha="right", va="bottom", fontsize=7.5, color=INK2, linespacing=1.25)
    combo = [s for s in S if s["factor"] == "combo" and s["series"] == "a50"] + [dict(s, x=min(q["x"] for q in S if q["factor"] == "L" and q["series"] == "m1.0")) for s in S if s["factor"] == "alpha" and s["series"] == "m1.0" and abs(s["x"] - 50) < 1e-6]
    draw(a2, b2, [s for s in S if s["factor"] == "L" and s["series"] == "m0.5"], ORANGE)
    draw(a2, b2, [s for s in S if s["factor"] == "L" and s["series"] == "m1.0"], BLUE)
    draw(a2, b2, combo, AQUA, marker="s")
    draw(a3, b3, [s for s in S if s["factor"] == "alpha" and s["series"] == "m0.5"], ORANGE)
    draw(a3, b3, [s for s in S if s["factor"] == "alpha" and s["series"] == "m1.0"], BLUE)
    a3.axvline(45, color=INK2, lw=0.8, zorder=1)
    b3.axvline(45, color=INK2, lw=0.8, zorder=1)
    a3.text(45.5, 0.108, t["box"], fontsize=8, color=INK2, va="top")
    a2.annotate(f"L 44\n{t['l44']}", (L44["x"], L44["rot"]), xytext=(43.4, 0.083), fontsize=8, color=INK, ha="center", va="center", linespacing=1.25, arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.6, shrinkB=3))
    for ax in (a1, a2, a3):
        ax.set_yscale("log")
        ax.set_ylim(0.0285, 1.35 * max(r["rot"] for r in M_rows))
        log_ticks(ax, "y", [0.03, 0.04, 0.05, 0.06, 0.08, 0.1, 0.15, 0.2, 0.3])
    for ax in (a2, a3):
        ax.tick_params(labelleft=False)
    for ax in (b1, b2, b3):
        ax.set_ylim(min(r["bone"] for r in M_all) - 0.35, 10)
    for ax in (b2, b3):
        ax.tick_params(labelleft=False)
    a1.set_ylabel(t["r"])
    b1.set_ylabel(t["b"])
    b1.set_xlabel(t["xm"])
    b2.set_xlabel(t["xl"])
    b3.set_xlabel(t["xa"])
    b1.set_xlim(0.38, max(r["x"] for r in M_all) + 0.14)
    b1.set_xticks([0.5, 1.0, 1.5, 2.0])
    b2.set_xlim(42.2, 44.8)
    b2.set_xticks([42.5, 43, 43.5, 44, 44.5])
    b3.set_xlim(43, 61.5)
    b3.set_xticks([45, 50, 55, 60])
    handles = [Line2D([], [], color=ORANGE, marker="o", lw=1.6, ms=5.5, label=t["k1"]), Line2D([], [], color=BLUE, marker="o", lw=1.6, ms=5.5, label=t["k2"]), Line2D([], [], color=AQUA, marker="s", lw=1.6, ms=5.5, label=t["k3"]), Line2D([], [], color=INK2, marker="o", mfc="white", lw=0, ms=5.5, label=t["k4"])]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.075, 1 - 0.92 / fig.get_figheight()), ncol=4, handlelength=1.8, columnspacing=1.4)
    header(fig, t["title"], t["sub"], foot(lang))
    save(fig, lang, "fig2_one_factor")


def fig3(lang):
    R = read("fig3_mechanism.csv")
    S = sorted([s for s in read("fig2_one_factor.csv") if s["factor"] == "m" and s["e"] == 0.0], key=lambda s: s["x"])
    bands = M["mechanism"]["bands"]
    nm = M["mechanism"]["named"]
    tight, loose = bands[0], bands[-1]
    spin_ratio, tilt_ratio = nm["WS_m1"]["spin"] / nm["A"]["spin"], nm["WS_m1"]["tilt"] / nm["A"]["tilt"]
    t = {"zh": dict(title=f"紧的设计靠一次落座后稳定，松的设计持续摆动；加大余量主要放大自转",
                    sub=f"转动 < 0.1° 的设计，{tight['perm_share_median']*100:.0f} % 的转动卸载后留下；> 1° 的设计只留 {loose['perm_share_median']*100:.0f} %。严格基线 {len(R)} 个设计。\n同形只改余量：m 0.5 到 1.0，自转变为 {spin_ratio:.1f} 倍，倾摆只变为 {tilt_ratio:.2f} 倍。",
                    a="卸载后留下的份额", ax="首次加载转动 °", b="第二次加载的接触面积 mm²", c="转动分量 °", cx="皮质余量 m，mm", ca="a  永久份额", cb="b  接触面积", cc="c  设计 A 的形状", tilt="倾摆", spin="自转", med="分段中位数", m1="m ≥ 1.0", m0="m < 1.0"),
         "en": dict(title="Tight designs settle once and hold, loose designs keep rocking; more margin mainly amplifies spin",
                    sub=f"Below 0.1°, {tight['perm_share_median']*100:.0f} % of the rotation stays after unloading; above 1° only {loose['perm_share_median']*100:.0f} % does. Strict baseline, {len(R)} designs.\nSame shape, margin only: from m 0.5 to 1.0, spin grows {spin_ratio:.1f} times and tilt only {tilt_ratio:.2f} times.",
                    a="Share left after unloading", ax="First-load rotation, °", b="Contact area at second load, mm²", c="Rotation component, °", cx="Cortical margin m, mm", ca="a  Permanent share", cb="b  Contact area", cc="c  Shape of design A", tilt="Tilt", spin="Spin", med="Band median", m1="m ≥ 1.0", m0="m < 1.0")}[lang]
    fig, (a, b, c) = plt.subplots(1, 3, figsize=(7.6, 4.4), gridspec_kw={"wspace": 0.34, "width_ratios": [1.1, 1.1, 0.9]})
    fig.subplots_adjust(left=0.075, right=0.975, top=0.72, bottom=0.17)
    for ax, key in ((a, "perm_share"), (b, "contact")):
        for flag, col, sz, lab in ((False, CONTEXT, 10, t["m0"]), (True, BLUE, 12, t["m1"])):
            s = [r for r in R if r["m_ge1"] == flag]
            ax.scatter([r["rot"] for r in s], [r[key] for r in s], s=sz, c=col, lw=0, alpha=0.9 if not flag else 0.75, zorder=2, label=lab)
        ax.set_xscale("log")
        ax.set_xlim(0.025, 40)
        log_ticks(ax, "x", [0.03, 0.1, 0.3, 1, 3, 10, 30])
        ax.set_xlabel(t["ax"])
    edges = [(0, 0.1), (0.1, 0.3), (0.3, 1), (1, 1e9)]
    for ax, key in ((a, "perm_share"), (b, "contact")):
        pts = [(median(r["rot"] for r in s), median(r[key] for r in s)) for lo, hi in edges for s in [[r for r in R if lo <= r["rot"] < hi]]]
        ax.plot(*zip(*pts), color=INK, lw=1.4, marker="o", ms=4.5, mfc=INK, mec="white", mew=0.6, zorder=4, label=t["med"])
    a.set_ylim(0, 1.12)
    a.set_ylabel(t["a"])
    a.set_title(t["ca"], loc="left", fontsize=9, color=INK, fontweight="bold")
    b.set_ylim(0, 2700)
    b.set_ylabel(t["b"])
    b.set_title(t["cb"], loc="left", fontsize=9, color=INK, fontweight="bold")
    for n, off in (("A", (6, 10)), ("init29", (-34, -15)), ("C", (-16, -16))):
        r = nm[n]
        a.annotate(n, (r["rot"], r["perm"] / r["rot"]), xytext=off, textcoords="offset points", fontsize=8, color=INK, arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.6, shrinkB=1))
    a.scatter([nm[n]["rot"] for n in nm if n != "WS_m1"], [nm[n]["perm"] / nm[n]["rot"] for n in nm if n != "WS_m1"], s=26, facecolors="none", edgecolors=INK, linewidths=0.9, zorder=5)
    for n, off in (("A", (8, 8)), ("init29", (-34, -15)), ("C", (-20, -15))):
        r = nm[n]
        b.annotate(n, (r["rot"], r["contact"]), xytext=off, textcoords="offset points", fontsize=8, color=INK, arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.6, shrinkB=1))
    b.scatter([nm[n]["rot"] for n in nm if n != "WS_m1"], [nm[n]["contact"] for n in nm if n != "WS_m1"], s=26, facecolors="none", edgecolors=INK, linewidths=0.9, zorder=5)
    a.legend(loc="lower left", handletextpad=0.3, borderaxespad=0.1, markerscale=1.3, labelspacing=0.25)
    xs = [s["x"] for s in S]
    c.plot(xs, [s["rot_tilt"] for s in S], color=INK2, lw=1.6, marker="o", ms=5, mec="white", mew=0.6, label=t["tilt"])
    c.plot(xs, [s["rot_axial"] for s in S], color=AQUA, lw=1.6, marker="s", ms=5, mec="white", mew=0.6, label=t["spin"])
    c.annotate(f"{t['tilt']} ×{S[-1]['rot_tilt'] / S[0]['rot_tilt']:.1f}", (xs[-1], S[-1]["rot_tilt"]), xytext=(1.8, 0.052), ha="right", fontsize=8, color=INK)
    c.annotate(f"{t['spin']} ×{S[-1]['rot_axial'] / S[0]['rot_axial']:.1f}", (xs[-1], S[-1]["rot_axial"]), xytext=(1.5, 0.113), ha="right", fontsize=8, color=INK)
    c.set(xlim=(0.4, 1.85), ylim=(0, 0.125), xlabel=t["cx"], ylabel=t["c"])
    c.set_xticks([0.5, 1.0, 1.5])
    c.set_title(t["cc"], loc="left", fontsize=9, color=INK, fontweight="bold")
    c.legend(loc="upper left", borderaxespad=0.1, handlelength=1.6)
    header(fig, t["title"], t["sub"], foot(lang))
    save(fig, lang, "fig3_mechanism")


def fig4(lang):
    S = read("fig4_sensitivity.csv")
    E = M["sensitivity"]
    running = {}
    for x in M["not_done"]:
        running.setdefault(x["batch"], []).append(x)
    # row key, zh label, en label
    groups = [
        (("数值设置", "Numerics"), [("mesh_h1.94_2.06", "网格 h 1.94、2.06", "Mesh h 1.94, 2.06"), ("mesh_h2.4", "网格 h 2.4", "Mesh h 2.4"), ("mesh_h1.4", "网格 h 1.4", "Mesh h 1.4"), ("element_nlgeom", "单元类型、几何非线性", "Element type, NLGEOM")]),
        (("加载历程", "Load history"), [("cycles4", "4 循环", "4 cycles"), ("cycles10", "10 循环", "10 cycles")]),
        (("物理假设", "Physics"), [("delta0.2", "过盈 δ 0.20", "Interference δ 0.20"), ("delta0.05", "过盈 δ 0.05", "Interference δ 0.05"), ("delta0.025", "过盈 δ 0.025", "Interference δ 0.025"), ("mu0.5", "摩擦 μ 0.5", "Friction μ 0.5"), ("mu0.2", "摩擦 μ 0.2", "Friction μ 0.2"), ("mu0.15", "摩擦 μ 0.15", "Friction μ 0.15"), ("cortex10.7", "皮质模量 10.7 GPa", "Cortex 10.7 GPa"), ("foam_yield", "泡沫屈服 6.2 MPa", "Foam yield 6.2 MPa")]),
        (("载荷", "Load"), [("rise3839", "起身 3839 N", "Sit-to-stand 3839 N"), ("rise1714", "起身 1714 N", "Sit-to-stand 1714 N"), ("stair3606", "楼梯方向 3606 N", "Stair direction 3606 N"), ("sag40", "矢状角 40°", "Sagittal angle 40°"), ("delta0.05_rise3839", "δ 0.05 且 3839 N", "δ 0.05 with 3839 N")]),
        (("还没有数据", "No data yet"), [("_pose", "放置偏差", "Placement error"), ("_torsion", "纯扭转", "Pure torsion"), ("_femur", "第二根股骨", "Second femur"), ("_muscle", "肌肉力", "Muscle forces")]),
    ]
    yld = E["foam_yield"]
    t = {"zh": dict(title="绝对值对物理假设很敏感，对数值设置不敏感；已测假设下排序基本不变",
                    sub=f"每点是一个设计相对自身基线的转动倍数，竖线是中位数，灰带是噪声 ±{NOISE} dex。ρ 是与基线排序的 Spearman。\n泡沫屈服中位 {yld['times_median']:.1f} 倍，前 5 名重合 {yld['top5_overlap']} 个，A 仍第 1。下面 4 项没有算过，所以不能说对它们稳健。",
                    x="相对基线的转动倍数", n="设计数", rho="ρ", none="0 行", run="b17 在跑", run_b18="b18 在跑"),
         "en": dict(title="Absolute values depend strongly on physics, weakly on numerics; ranks hold under what was tested",
                    sub=f"Dot: one design against its own baseline. Tick: median. Band: ±{NOISE} dex noise. ρ: Spearman with the baseline rank.\nFoam yield: median {yld['times_median']:.1f} times, {yld['top5_overlap']} of the top 5 kept, A still first. The last 4 rows have no runs, so no claim can be made.",
                    x="Rotation against baseline, times", n="Designs", rho="ρ", none="0 rows", run="b17 running", run_b18="b18 running")}[lang]
    nrows = sum(len(g[1]) for g in groups) + len(groups)
    fig, ax = plt.subplots(figsize=(7.6, 7.0))
    fig.subplots_adjust(left=0.235, right=0.83, top=0.835, bottom=0.16)
    y = nrows
    rng = np.random.default_rng(3406)
    idx = 0 if lang == "zh" else 1
    labs, pos = [], []
    ax.axvspan(-NOISE, NOISE, color=GRID, lw=0, zorder=0)
    ax.axvline(0, color=AXIS, lw=0.8, zorder=1)
    for head, rows in groups:
        y -= 1
        ax.text(-0.02, y, head[idx], transform=ax.get_yaxis_transform(), ha="right", va="center", fontsize=9, fontweight="bold", color=INK)
        for key, zh, en in rows:
            y -= 1
            labs.append(zh if lang == "zh" else en)
            pos.append(y)
            pts = [s["dex"] for s in S if s["label"] == key]
            if pts:
                j = rng.uniform(-0.2, 0.2, len(pts)) if len(pts) > 2 else np.zeros(len(pts))
                ax.scatter(pts, y + j, s=16, c=BLUE, alpha=0.55, lw=0, zorder=3)
                md = median(pts)
                ax.plot([md, md], [y - 0.33, y + 0.33], color=INK, lw=1.8, zorder=4, solid_capstyle="round")
                e = E[key]
                ax.text(1.02, y, f"{e['n']}", transform=ax.get_yaxis_transform(), ha="center", va="center", fontsize=8.5, color=INK2)
                rho = e.get("spearman_reported", e.get("spearman"))
                ax.text(1.14, y, "" if rho is None else f"{rho:.3f}", transform=ax.get_yaxis_transform(), ha="center", va="center", fontsize=8.5, color=INK2)
                if key in ("mu0.2", "mu0.15") and "b18" in running:
                    ax.text(max(pts) + 0.03, y, t["run_b18"], ha="left", va="center", fontsize=8, color=INK2)
                if key in ("stair3606", "sag40") and "b17" in running:
                    ax.text(max(pts) + 0.03, y, t["run"], ha="left", va="center", fontsize=8, color=INK2)
            else:
                pending = {"stair3606": "b17", "sag40": "b17"}.get(key)
                ax.text(0.02, y, t["run"] if pending and pending in running else t["none"], ha="left", va="center", fontsize=8.5, color=INK2)
    top = nrows
    ax.text(1.02, top + 0.2, t["n"], transform=ax.get_yaxis_transform(), ha="center", va="bottom", fontsize=8.5, color=INK2)
    ax.text(1.14, top + 0.2, t["rho"], transform=ax.get_yaxis_transform(), ha="center", va="bottom", fontsize=8.5, color=INK2)
    ax.set_yticks(pos)
    ax.set_yticklabels(labs)
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="y", visible=False)
    ax.set_ylim(-0.7, nrows + 0.2)
    ticks = [0.2, 0.5, 1, 2, 5]
    ax.set_xticks([math.log10(v) for v in ticks])
    ax.set_xticklabels([f"×{v:g}" for v in ticks])
    ax.set_xlim(-0.85, 0.95)
    ax.set_xlabel(t["x"])
    ds = M["delta_same_designs"]
    vals = [v["spearman_tight"] for v in E.values() if "spearman_tight" in v]
    extra = {"zh": f"ρ 跨越整个转动范围；只看转动 < 0.1° 的设计，ρ 在 {min(vals):.2f} 到 {max(vals):.2f}，行数更少。偏移固定 +2 的设计不在图内。δ 各行的设计集不同；同一批 {ds['n']} 个设计上，δ 0.025、0.05、0.20 的中位倍数是 {10 ** ds['delta0.025']:.1f}、{10 ** ds['delta0.05']:.1f}、{10 ** ds['delta0.2']:.2f}。\n",
             "en": f"ρ spans the whole rotation range; for designs under 0.1° it is {min(vals):.2f} to {max(vals):.2f} on fewer rows. Designs at offset +2 are not shown. δ rows use different design sets; on the same {ds['n']} designs, δ 0.025, 0.05, 0.20 give median {10 ** ds['delta0.025']:.1f}, {10 ** ds['delta0.05']:.1f}, {10 ** ds['delta0.2']:.2f} times.\n"}[lang]
    header(fig, t["title"], t["sub"], extra + foot(lang))
    save(fig, lang, "fig4_sensitivity")


def fig5(lang):
    V = read("fig5_validation.csv")
    o, n = M["val1"]["ours"], M["val1"]["naghavi"]
    t = {"zh": dict(title=f"第一份实测对仿真：10 个测点全部偏低，中位误差 {o['median_rel_pct']:.1f} %，还不算验证通过",
                    sub=f"同型号 3406 完整股骨，1200 N，ISO 7206-4。这里没有柄。已发表的 Naghavi 模型中位误差 {n['median_rel_pct']:.1f} %，与我们相近，\n但 Pearson {o['pearson']:.3f} 对 {n['pearson']:.3f}，一致性界限也更宽。靠近颈部的测点偏得最多，那正是柄所在的区域。",
                    y="Mises 应力 MPa", x="小转子下距离 mm", med="内侧", lat="外侧", me="实测", ou="本项目模型，远场 2.5 mm", na="Naghavi 模型", wash="靠近颈部", row="本项目相对实测的误差", foot=f"实测和 Naghavi 模型从论文图 5-23a 按像素读取。我们的骨来自 CAD，不是这一根的 CT。测点沿圆周转 ±15° 时中位误差在 {M['val1']['plus15']['median_rel_pct']:.1f} 到 {M['val1']['minus15']['median_rel_pct']:.1f} %。"),
         "en": dict(title=f"First measured-versus-simulated check: all 10 gauges read low, median error {o['median_rel_pct']:.1f} %, not yet a pass",
                    sub=f"Same-model 3406 intact femur, 1200 N, ISO 7206-4, no stem. The published Naghavi model has {n['median_rel_pct']:.1f} %, close to ours, but Pearson is {o['pearson']:.3f} against {n['pearson']:.3f} and its limits of agreement are narrower. Gauges near the neck, where the stem sits, are furthest off.",
                    y="Mises stress, MPa", x="Distance below lesser trochanter, mm", med="Medial", lat="Lateral", me="Measured", ou="This project, far field 2.5 mm", na="Naghavi model", wash="Near the neck", row="This project against measured", foot=f"Measured and Naghavi values read by pixel from thesis figure 5-23a. Our bone comes from CAD, not a CT of that specimen. Turning the gauges ±15° round the shaft moves the median error between {M['val1']['plus15']['median_rel_pct']:.1f} and {M['val1']['minus15']['median_rel_pct']:.1f} %.")}[lang]
    fig, axes = plt.subplots(1, 2, figsize=(7.6, 4.5), sharey=True, gridspec_kw={"wspace": 0.08})
    fig.subplots_adjust(left=0.075, right=0.985, top=0.73, bottom=0.17)
    for ax, side, head in ((axes[0], "medial", t["med"]), (axes[1], "lateral", t["lat"])):
        r = sorted([v for v in V if v["side"] == side], key=lambda v: v["depth_mm"])
        x = [v["depth_mm"] for v in r]
        ax.axvspan(-7, 16 if side == "medial" else 8, color=WASH, lw=0, zorder=0)
        ax.plot(x, [v["measured"] for v in r], color=INK, lw=1.6, marker="o", ms=6, mec="white", mew=0.7, zorder=5, label=t["me"])
        ax.plot(x, [v["model_far2.5"] for v in r], color=BLUE, lw=1.6, marker="s", ms=5.5, mec="white", mew=0.7, zorder=4, label=t["ou"])
        ax.plot(x, [v["naghavi_fe"] for v in r], color=ORANGE, lw=1.6, marker="^", ms=6, mec="white", mew=0.7, zorder=3, label=t["na"])
        for v in r:
            ax.text(v["depth_mm"], 1.25, f"{signed(v['rel_err_pct'])} %", ha="center", va="center", fontsize=8, color=INK)
        ax.text(-5.5, 3.1, t["row"], ha="left", va="center", fontsize=7.5, color=INK2)
        ax.set_title(head, loc="left", fontsize=9, fontweight="bold", color=INK)
        ax.text(-5.5, 27.2, t["wash"], fontsize=8, color=INK2, ha="left", va="center")
        ax.set(xlim=(-7, 102), ylim=(0, 28.5), xlabel=t["x"])
        ax.set_xticks([0, 16, 32, 48, 64, 95] if side == "medial" else [0, 32, 64, 95])
    axes[0].set_ylabel(t["y"])
    axes[1].legend(loc="upper right", borderaxespad=0.1, handlelength=2)
    header(fig, t["title"], t["sub"], t["foot"])
    save(fig, lang, "fig5_validation")


def fig6(lang):
    A = read("fig6_prospective.csv")
    P = M["prospective"]
    rounds = [("al1", "AL-1", BLUE, "o"), ("al2", "AL-2", ORANGE, "^"), ("al3m", "AL-3′", AQUA, "s")]
    t = {"zh": dict(title=f"优化选点的预测都由之后的 FE 核对：RMSE {P['al1']['opt']['rmse']:.3f}、{P['al2']['opt']['rmse']:.3f}、{P['al3m']['opt']['rmse']:.3f} dex",
                    sub="预测在 FE 之前冻结，这里只画优化选点，改了载荷的行不算。各轮搜索的区域不同，所以数字变小不全是模型变好。\nAL-3′ 的 sd 只有约 0.015 dex，18 行里 15 行 FE 比预测差，预测仍略偏乐观。",
                    x="GP 预测转动 °", y="FE 实算转动 °", one="预测等于实算", h=("轮次", "行", "RMSE", "偏差", "90 % 覆盖"), unit="dex，FE 减预测为偏差"),
         "en": dict(title=f"Optimised picks were each checked by later FE: RMSE {P['al1']['opt']['rmse']:.3f}, {P['al2']['opt']['rmse']:.3f}, {P['al3m']['opt']['rmse']:.3f} dex",
                    sub="Predictions were frozen before the FE. Optimised picks only, changed-load rows left out. The rounds search different regions, so a smaller number is not all model gain. AL-3′ has sd of about 0.015 dex and 15 of 18 rows came out worse than predicted.",
                    x="GP predicted rotation, °", y="FE rotation, °", one="Prediction equals FE", h=("Round", "n", "RMSE", "Bias", "90 % cover"), unit="dex; bias is FE minus prediction")}[lang]
    fig, ax = plt.subplots(figsize=(7.6, 4.9))
    fig.subplots_adjust(left=0.085, right=0.61, top=0.79, bottom=0.135)
    lo, hi = 0.03, 1.2
    ax.plot([lo, hi], [lo, hi], color=INK2, lw=0.9, zorder=1, label=t["one"])
    for key, name, col, mk in rounds:
        s = [r for r in A if r["round"] == key and r["group"] == "opt"]
        ax.scatter([r["pred_deg"] for r in s], [r["fe_deg"] for r in s], s=30, c=col, marker=mk, edgecolors="white", linewidths=0.6, zorder=3, label=name)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set(xlim=(lo, hi), ylim=(lo, hi), xlabel=t["x"], ylabel=t["y"])
    log_ticks(ax, "x", [0.03, 0.05, 0.1, 0.2, 0.5, 1])
    log_ticks(ax, "y", [0.03, 0.05, 0.1, 0.2, 0.5, 1])
    ax.set_aspect("equal", adjustable="box")
    ax.legend(loc="upper left", borderaxespad=0.1, handletextpad=0.4)
    tb = fig.add_axes([0.63, 0.30, 0.36, 0.40])
    tb.axis("off")
    cols = [0.09, 0.30, 0.47, 0.70, 0.98]
    for x, h in zip(cols, t["h"]):
        tb.text(x, 0.92, h, fontsize=8.5, color=INK2, ha="left" if x == cols[0] else "right", va="center", fontweight="bold")
    tb.plot([0, 1], [0.84, 0.84], color=AXIS, lw=0.6, transform=tb.transAxes, clip_on=False)
    for i, (key, name, col, mk) in enumerate(rounds):
        y = 0.70 - i * 0.16
        e = P[key]["opt"]
        tb.scatter([0.035], [y], s=26, c=col, marker=mk, edgecolors="white", linewidths=0.5, transform=tb.transAxes, clip_on=False)
        for x, v in zip(cols, (name, f"{e['n']}", f"{e['rmse']:.3f}", signed(e['bias'], "+.3f"), f"{e['n_in90']} / {e['n']}")):
            tb.text(x, y, v, fontsize=8.5, color=INK, ha="left" if x == cols[0] else "right", va="center")
    tb.text(0, 0.16, t["unit"], fontsize=8, color=MUTED, va="center")
    tb.set_xlim(0, 1)
    tb.set_ylim(0, 1)
    header(fig, t["title"], t["sub"], foot(lang))
    save(fig, lang, "fig6_prospective")


def fig7(lang):
    T = read("fig7_offset.csv")
    A = {r["e"]: r for r in T if r["design"] == "A"}
    t = {"zh": dict(title=f"入口偏移的影响不对称：e −2 转动放大约 {A[-2.0]['rot'] / A[0.0]['rot']:.1f} 倍，e +2 去骨少 {100 * (1 - A[2.0]['bone'] / A[0.0]['bone']):.0f} %，转动只放大 {A[2.0]['rot'] / A[0.0]['rot']:.2f} 倍",
                    sub="都是 m 1.0，入口偏移固定，尺寸在该偏移下重新模板化，所以这不是放置误差。a82、a96 的 e +2 不可用。\n三行 e +2 属于同一族设计，代价主要在可逆转动和微动。",
                    x="入口偏移 e，mm", a="首次加载转动 °", b="可逆转动 °", c="微动 P95 µm", d="去骨量 cm³", ka="设计 A", ko="a100、a95、a82、a96"),
         "en": dict(title=f"The entry offset acts unevenly: e −2 multiplies rotation by about {A[-2.0]['rot'] / A[0.0]['rot']:.1f}; e +2 removes {100 * (1 - A[2.0]['bone'] / A[0.0]['bone']):.0f} % less bone at {A[2.0]['rot'] / A[0.0]['rot']:.2f} times the rotation",
                    sub="All at m 1.0 with the offset held and the size re-templated at that offset, so this is not a placement error. e +2 is not usable for a82 and a96.\nThe three e +2 rows belong to one design family; the cost is mainly reversible rotation and micromotion.",
                    x="Entry offset e, mm", a="First-load rotation, °", b="Reversible rotation, °", c="Micromotion P95, µm", d="Bone removed, cm³", ka="Design A", ko="a100, a95, a82, a96")}[lang]
    fig, axes = plt.subplots(1, 4, figsize=(7.6, 3.9), gridspec_kw={"wspace": 0.52})
    fig.subplots_adjust(left=0.075, right=0.985, top=0.645, bottom=0.19)
    keys = (("rot", t["a"], True, (0.04, 0.45), [0.05, 0.1, 0.2, 0.4]), ("rot_rev", t["b"], True, (0.004, 0.2), [0.01, 0.03, 0.1]), ("f1", t["c"], True, (3.5, 130), [5, 10, 30, 100]), ("bone", t["d"], False, (4.4, 9), None))
    for ax, (k, lab, lg, lim, ticks) in zip(axes, keys):
        for d in ("a100", "a95", "a82", "a96"):
            s = sorted([r for r in T if r["design"] == d], key=lambda r: r["e"])
            ax.plot([r["e"] for r in s], [r[k] for r in s], color=CONTEXT, lw=1.2, marker="o", ms=4, mec="white", mew=0.5, zorder=2)
        s = sorted([r for r in T if r["design"] == "A"], key=lambda r: r["e"])
        ax.plot([r["e"] for r in s], [r[k] for r in s], color=BLUE, lw=1.8, marker="o", ms=5.5, mec="white", mew=0.7, zorder=4)
        for r in s:
            ax.annotate(f"{r[k]:.3f}" if k in ("rot", "rot_rev") else (f"{r[k]:.1f}" if k == "f1" else f"{r[k]:.2f}"), (r["e"], r[k]), xytext=(0, -13 if (r["e"] == 0.0 and k != "bone") or (r["e"] == 2.0 and k == "bone") else 7), textcoords="offset points", ha="center", fontsize=7.5, color=INK, zorder=6)
        if lg:
            ax.set_yscale("log")
            log_ticks(ax, "y", ticks)
        ax.set_ylim(*lim)
        ax.set_xlim(-2.7, 2.7)
        ax.set_xticks([-2, 0, 2])
        ax.set_xticklabels(["−2", "0", "+2"])
        ax.set_xlabel(t["x"])
        ax.set_title(lab, loc="left", fontsize=8.5, color=INK, fontweight="bold")
    handles = [Line2D([], [], color=BLUE, marker="o", lw=1.8, ms=5.5, label=t["ka"]), Line2D([], [], color=CONTEXT, marker="o", lw=1.2, ms=4, label=t["ko"])]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.06, 1 - 0.86 / fig.get_figheight()), ncol=2, handlelength=1.8, columnspacing=1.4)
    header(fig, t["title"], t["sub"], foot(lang))
    save(fig, lang, "fig7_offset")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", nargs="+", default=["zh", "en"])
    ap.add_argument("--only", nargs="+", type=int, default=[1, 2, 3, 4, 5, 6, 7])
    a = ap.parse_args()
    F = {1: fig1, 2: fig2, 3: fig3, 4: fig4, 5: fig5, 6: fig6, 7: fig7}
    for lang in a.lang:
        style(lang)
        for i in a.only:
            F[i](lang)
    print("figures written to", FIG)


main()
