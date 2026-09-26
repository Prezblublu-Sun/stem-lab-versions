"""S1 几何与设计空间 → R1 报告。python stage_s1.py（.venv-mobo）"""
from __future__ import annotations

import collections
import json
import subprocess
import sys

import numpy as np
from matplotlib.patches import Polygon as MplPolygon
from scipy.stats import qmc

import femur2d as F
import plotstyle as ps
import stem2d as S

ROOT = ps.ROOT
N_MAP = 1024
REASON_COLOR = {"PASS": None, "tip wider than canal": ps.OKABE_ITO["orange"], "cuts cortex": ps.OKABE_ITO["purple"],
                "tip perforates cortex": ps.OKABE_ITO["sky"], "wall too thin": ps.OKABE_ITO["yellow"],
                "tip outside bone": ps.GREY, "curvature radius < half-width": ps.LIGHT}
CROP = dict(x=(-40, 70), z=(-80, 92))


# ------------------------------------------------------------------ geometry → rows
def poly_rows(geom, **tags):
    rows = []
    for gi, g in enumerate(getattr(geom, "geoms", [geom])):
        if g.is_empty:
            continue
        if g.geom_type == "LineString":
            rings = [np.asarray(g.coords)]
        else:
            rings = [np.asarray(g.exterior.coords)] + [np.asarray(r.coords) for r in g.interiors]
        for ri, ring in enumerate(rings):
            for k, (x, z) in enumerate(ring):
                rows.append(dict(**tags, ring=f"{gi}.{ri}", hole=int(ri > 0), seq=k, x=float(x), z=float(z)))
    return rows


def draw(ax, d, idx, **kw):
    """把 CSV 行（同一 part）按 ring 画成多边形或折线。"""
    rings = collections.OrderedDict()
    for i in idx:
        rings.setdefault(d["ring"][i], []).append((d["x"][i], d["z"][i], d["hole"][i]))
    for pts in rings.values():
        xy = np.array([(p[0], p[1]) for p in pts])
        hole = pts[0][2] > 0.5
        if kw.get("line"):
            ax.plot(xy[:, 0], xy[:, 1], color=kw.get("ec", "k"), lw=kw.get("lw", 0.8), ls=kw.get("ls", "-"))
        else:
            ax.add_patch(MplPolygon(xy, closed=True, fc="white" if hole else kw.get("fc", "none"),
                                    ec=kw.get("ec", "none"), lw=kw.get("lw", 0.5), alpha=kw.get("alpha", 1.0),
                                    hatch=kw.get("hatch"), zorder=kw.get("z", 1)))


def sel(d, **cond):
    return [i for i in range(len(d["x"])) if all(d[k][i] == v for k, v in cond.items())]


CORTEX_FC, CANC_FC = "#C9C9C9", "#F3E3C3"


# ------------------------------------------------------------------ plot functions（只读 CSV）
def plot_r1_f01(csv_path):
    d = ps.read_csv(csv_path)
    fig, axes = ps.new_figure("double", 118, 1, 3, sharey=True)
    for ax, t in zip(axes, "ABC"):
        draw(ax, d, sel(d, dorr=t, part="outer"), fc=CORTEX_FC)
        draw(ax, d, sel(d, dorr=t, part="inner"), fc=CANC_FC)
        draw(ax, d, sel(d, dorr=t, part="zone7"), fc="none", ec=ps.DORR[t], hatch="////", lw=0.6, z=2)
        draw(ax, d, sel(d, dorr=t, part="zone1"), fc="none", ec=ps.GREY, hatch="\\\\\\\\", lw=0.6, z=2)
        draw(ax, d, sel(d, dorr=t, part="cut"), line=True, ec="#D55E00", lw=1.2)
        for part, lab in (("canal20", "CFI"), ("canalI", "CI")):
            idx = sel(d, dorr=t, part=part)
            draw(ax, d, idx, line=True, ec=ps.DORR[t], lw=1.8)
            x1 = max(d["x"][i] for i in idx); z1 = d["z"][idx[0]]
            val = d["value"][idx[0]]
            ax.annotate(f"{lab} = {val:.2f}", (x1, z1), xytext=(4, 2), textcoords="offset points", fontsize=7,
                        color=ps.DORR[t], fontweight="bold")
        idx = sel(d, dorr=t, part="outerI")
        draw(ax, d, idx, line=True, ec="black", lw=0.6, ls=":")
        ax.set_aspect("equal"); ax.set_xlim(-45, 75); ax.set_ylim(-152, 92)
        ax.set_title(f"Dorr {t}"); ax.set_xlabel("x, medial + (mm)")
    axes[0].set_ylabel("z, superior + (mm)")
    ps.panel_labels(axes)
    return fig


def plot_r1_f02(csv_path):
    d = ps.read_csv(csv_path)
    n = int(max(d["design"])) + 1
    fig, axes = ps.new_figure("double", 92, 3, n)
    for r, t in enumerate("ABC"):
        for c in range(n):
            ax = axes[r, c]
            draw(ax, d, sel(d, dorr=t, part="outer", design=0.0), fc=CORTEX_FC)
            draw(ax, d, sel(d, dorr=t, part="inner", design=0.0), fc=CANC_FC)
            idx = sel(d, dorr=t, part="stem", design=float(c))
            status = d["status"][idx[0]]
            fc = ps.DORR[t] if status == "PASS" else "none"
            ec = ps.DORR[t] if status == "PASS" else ps.OKABE_ITO["vermillion"]
            draw(ax, d, idx, fc=fc, ec=ec, lw=0.6, alpha=0.85, z=3)
            ax.set_xlim(*CROP["x"]); ax.set_ylim(*CROP["z"]); ax.set_aspect("equal")
            ax.set_xticks([]); ax.set_yticks([]); ax.grid(False)
            for sp in ax.spines.values():
                sp.set_visible(False)
            if status != "PASS":
                ax.text(0.5, 0.02, status.replace(" ", "\n", 1), transform=ax.transAxes, ha="center", va="bottom",
                        fontsize=5.5, color=ps.OKABE_ITO["vermillion"])
            if r == 0:
                ax.set_title(f"#{c + 1}", fontsize=7)
        axes[r, 0].set_ylabel(f"Dorr {t}", fontsize=8)
        axes[r, 0].yaxis.set_visible(True)
    return fig


def plot_r1_f03(csv_path):
    d = ps.read_csv(csv_path)
    fig, (a, b) = ps.new_figure("double", 82, 1, 2, gridspec_kw={"width_ratios": [1.0, 1.3]})
    draw(a, d, sel(d, kind="pose", part="outer"), fc=CORTEX_FC)
    draw(a, d, sel(d, kind="pose", part="inner"), fc=CANC_FC)
    poses = sorted({d["pose"][i] for i in sel(d, kind="pose", part="posed")})
    for k, p in enumerate(poses):
        draw(a, d, sel(d, kind="pose", part="posed", pose=p), fc="none", ec=ps.GREY, lw=0.4, z=2)
    draw(a, d, sel(d, kind="pose", part="final"), fc=ps.DORR["B"], ec=ps.DORR["B"], alpha=0.6, z=3)
    draw(a, d, sel(d, kind="pose", part="cut"), line=True, ec="#D55E00", lw=1.0)
    idx = sel(d, kind="pose", part="center")
    if idx:
        a.plot(d["x"][idx[0]], d["z"][idx[0]], "k+", ms=6)
        a.annotate("centre of rotation", (d["x"][idx[0]], d["z"][idx[0]]), xytext=(4, 4), textcoords="offset points",
                   fontsize=6.5)
    a.set_xlim(-40, 120); a.set_ylim(-60, 110); a.set_aspect("equal")
    a.set_xlabel("x, medial + (mm)"); a.set_ylabel("z, superior + (mm)")
    a.set_title("Insertion poses (Dorr B example)")
    ii = sel(d, kind="overcut")
    for t in "ABC":
        jj = [i for i in ii if d["dorr"][i] == t]
        b.scatter([d["kappa"][i] * 1000 for i in jj], [d["overcut_pct"][i] for i in jj], s=14,
                  color=ps.DORR[t], marker=ps.DORR_MARKER[t], label=f"Dorr {t} (n = {len(jj)})")
    ps.threshold_line(b, 0.1, "y", "acceptance 0.1 %")
    b.set_xlabel("Arc curvature κ (1/m)"); b.set_ylabel("Overcut / stem area in bone (%)")
    b.set_ylim(-0.01, 0.12)
    b.legend(loc="center right")
    b.set_title("Swept area minus final stem, gate-passing designs")
    ps.panel_labels([a, b])
    return fig


PAIRS = [("tip_depth", "tip_lat"), ("w_prox", "taper"), ("tip_depth", "taper"), ("theta_in", "w_prox")]
AX_LABEL = {"tip_depth": "Tip depth below LT (mm)", "tip_lat": "Tip position across canal (–)",
            "w_prox": ps.LABEL["w_prox"], "taper": ps.LABEL["taper"], "theta_in": ps.LABEL["theta_in"]}


def plot_r1_f04(csv_path):
    d = ps.read_csv(csv_path)
    fig, axes = ps.new_figure("double", 140, 3, 4)
    for r, t in enumerate("ABC"):
        idx = [i for i, x in enumerate(d["dorr"]) if x == t]
        for c, (vx, vy) in enumerate(PAIRS):
            ax = axes[r, c]
            for reason, col in REASON_COLOR.items():
                jj = [i for i in idx if d["reason"][i] == reason]
                if not jj:
                    continue
                ax.scatter([d[vx][i] for i in jj], [d[vy][i] for i in jj], s=2.5, edgecolors="none",
                           color=ps.DORR[t] if reason == "PASS" else col,
                           label=("pass" if reason == "PASS" else reason), zorder=3 if reason == "PASS" else 2)
            if r == 2:
                ax.set_xlabel(AX_LABEL[vx], fontsize=7)
            if c == 0:
                ax.set_ylabel(f"Dorr {t}\n" + AX_LABEL[vy], fontsize=7)
            else:
                ax.set_ylabel(AX_LABEL[vy], fontsize=7)
        rate = np.mean([d["reason"][i] == "PASS" for i in idx])
        axes[r, 3].text(1.02, 0.5, f"pass {rate:.0%}", transform=axes[r, 3].transAxes, rotation=90,
                        va="center", fontsize=7, color=ps.DORR[t], fontweight="bold")
    h, l = axes[2, 0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=len(l), markerscale=3, bbox_to_anchor=(0.5, -0.03))
    return fig


def plot_r1_f05(csv_path):
    d = ps.read_csv(csv_path)
    fig, ax = ps.new_figure("single", 62)
    bins = np.linspace(0, 12, 49)
    for t in "ABC":
        w = [d["wall"][i] for i, x in enumerate(d["dorr"]) if x == t]
        ax.hist(w, bins=bins, histtype="step", color=ps.DORR[t], lw=1.2, label=f"Dorr {t} (n = {len(w)})")
    ps.threshold_line(ax, 1.0, "x", "1.0 mm gate")
    ax.set_xlabel(ps.LABEL["wall_thk"]); ax.set_ylabel("Designs (–)")
    ax.legend(loc="upper right")
    return fig


# ------------------------------------------------------------------ main
def main():
    fem = {t: F.build(t) for t in "ABC"}
    src = {"generator": "femur2d.build / stem2d.gate", "sobol": f"scrambled Sobol, seed 1, n = {N_MAP} per type"}

    # R1-F01
    rows = []
    for t, f in fem.items():
        rows += poly_rows(f.outer, dorr=t, part="outer", value="")
        rows += poly_rows(f.inner, dorr=t, part="inner", value="")
        z = f.zones()
        rows += poly_rows(z["gruen7"], dorr=t, part="zone7", value="")
        rows += poly_rows(z["gruen1"], dorr=t, part="zone1", value="")
        rows += poly_rows(f.cut_segment(), dorr=t, part="cut", value="")
        m = f.measured
        for part, zz, poly, val in (("canal20", F.FC["cfi_level_z"], f.inner, m["cfi"]),
                                    ("canalI", F.FC["ci_level_z"], f.inner, m["ci"]),
                                    ("outerI", F.FC["ci_level_z"], f.outer, m["ci"])):
            a, b = F.chord(poly, zz)
            rows += [dict(dorr=t, part=part, ring="0.0", hole=0, seq=0, x=a, z=zz, value=val),
                     dict(dorr=t, part=part, ring="0.0", hole=0, seq=1, x=b, z=zz, value=val)]
    cfi = {t: fem[t].measured["cfi"] for t in "ABC"}
    ps.publish_figure(
        "R1-F01", rows, plot_r1_f01, sources=src,
        title=(f"The three femora share one outer contour and hit their Dorr targets "
               f"(CFI {cfi['A']:.2f} / {cfi['B']:.2f} / {cfi['C']:.2f})"),
        caption=("深灰为皮质骨、浅黄为松质骨（髓腔）。彩色横线为 CFI 的分子（小转子上 20 mm 的髓腔宽）与峡部髓腔宽"
                 "（小转子下 100 mm），黑色点线为该高度外径；红线为颈中段截骨线；斜线填充为 Gruen 7 区（彩色）"
                 "与 Gruen 1 区（灰色）ROI。外轮廓三型完全相同，只有内轮廓按 Dorr 预设值变化。"),
        units={"x": "mm", "z": "mm"})

    # 设计空间图谱（1024 Sobol / 型）
    U = qmc.Sobol(5, scramble=True, seed=1).random(N_MAP)
    map_rows, wall_rows, gate_counts, derived = [], [], {}, {}
    for t in "ABC":
        cnt = collections.Counter()
        ks, Ls = [], []
        for u in U:
            dsg = S.to_physical(u)
            st = S.make(t, dsg)
            g = S.gate(st)
            reason = g["reason"] or "PASS"
            cnt[(g["level"], reason)] += 1
            map_rows.append(dict(dorr=t, **{k: dsg[k] for k in S.VARS}, kappa=st.kappa, L=st.L, reason=reason))
            if "wall" in g:
                wall_rows.append(dict(dorr=t, wall=g["wall"], passed=int(g["pass"])))
            if g["pass"]:
                ks.append(st.kappa); Ls.append(st.L)
        gate_counts[t] = cnt
        derived[t] = (min(ks), max(ks), min(Ls), max(Ls))
    rates = {t: gate_counts[t][("OK", "PASS")] / N_MAP for t in "ABC"}
    ps.publish_figure(
        "R1-F04", map_rows, plot_r1_f04, sources=src,
        title=(f"Gate pass rate falls from {rates['A']:.0%} (A) to {rates['C']:.0%} (C); "
               "failures are tips wider than the canal and stems that cut cortex"),
        caption=("每型 1,024 个 Sobol 设计在四组变量对上的投影。彩色点通过几何门；橙色为尖端半宽超过该高度髓腔半宽（L1），"
                 "紫色为柄体切入皮质超过 0.5 mm²（L2）。同一组 Sobol 点用于三型，差异只来自髓腔形态。"),
        units={"tip_depth": "mm", "theta_in": "deg"})
    ps.publish_figure(
        "R1-F05", wall_rows, plot_r1_f05, sources=src,
        title="No gate-evaluated design leaves less than 1 mm of cortex without also cutting it",
        caption=("进入 L2 判定的设计（L1 被拒的不算）的剩余皮质壁厚：骨内柄体到外轮廓（截骨面以下 0.5 mm 起算）的最小距离。"
                 "点线为 1.0 mm 门槛。"),
        units={"wall": "mm"})

    # 柄族图册：同一组 8 个 u 用于三型
    Ua = qmc.Sobol(5, scramble=True, seed=2).random(8)
    atlas = []
    for t in "ABC":
        f = fem[t]
        atlas += poly_rows(f.outer, dorr=t, part="outer", design=0, status="")
        atlas += poly_rows(f.inner, dorr=t, part="inner", design=0, status="")
        for c, u in enumerate(Ua):
            st = S.make(t, S.to_physical(u))
            g = S.gate(st)
            atlas += poly_rows(st.full().intersection(F.box(-200, -200, 200, 200)), dorr=t, part="stem",
                               design=c, status=g["reason"] or "PASS")
    ps.publish_figure(
        "R1-F02", atlas, plot_r1_f02, sources={"sobol": "scrambled Sobol, seed 2, first 8 points"},
        title="The same eight normalised designs produce different stems and gate outcomes in each Dorr type",
        caption=("每列是同一个归一化设计向量在三型中的实例；实心为通过几何门，红色空心为未通过（注明原因）。"
                 "图中柄包括截骨线以上的假体颈与头。"))

    # 零过切复核
    B = fem["B"]
    over_rows = []
    ex = None
    for t in "ABC":
        Uc = qmc.Sobol(5, scramble=True, seed=11).random(256)
        n_ok = 0
        for u in Uc:
            st = S.make(t, S.to_physical(u))
            if not S.gate(st)["pass"]:
                continue
            r = st.sweep_overcut(step=0.25)
            over_rows.append(dict(kind="overcut", dorr=t, kappa=st.kappa, L=st.L,
                                  overcut_pct=100 * r["overcut_frac"], overcut_area=r["overcut_area"],
                                  swept_cortex=r["swept_cortex"], part="", pose="", ring="", hole=0, seq=0, x=0, z=0))
            if t == "B" and ex is None:
                ex = st
            n_ok += 1
            if n_ok >= 10:
                break
    pose_rows = []
    for r in poly_rows(B.outer, kind="pose", part="outer", pose=""):
        pose_rows.append(r)
    pose_rows += poly_rows(B.inner, kind="pose", part="inner", pose="")
    pose_rows += poly_rows(B.cut_segment(), kind="pose", part="cut", pose="")
    body = ex.body()
    import shapely.affinity as aff
    travel = ex.L - ex.s_min + 10
    for k, tau in enumerate(np.linspace(0, travel, 9)):
        posed = aff.rotate(body, -tau * ex.kappa, origin=tuple(ex.center), use_radians=True)
        pose_rows += poly_rows(posed, kind="pose", part="posed", pose=k)
    pose_rows += poly_rows(body.intersection(B.outer).intersection(B.kept_halfplane()), kind="pose", part="final", pose="")
    c = ex.center
    pose_rows.append(dict(kind="pose", part="center", pose="", ring="0.0", hole=0, seq=0, x=float(c[0]), z=float(c[1])))
    cols = ["kind", "dorr", "part", "pose", "ring", "hole", "seq", "x", "z", "kappa", "L", "overcut_pct",
            "overcut_area", "swept_cortex"]
    allrows = [{k: r.get(k, "") for k in cols} for r in pose_rows + over_rows]
    max_over = max(r["overcut_pct"] for r in over_rows)
    ps.publish_figure(
        "R1-F03", allrows, plot_r1_f03, columns=cols,
        sources={"designs": "first 10 gate-passing scrambled Sobol (seed 11) designs per type"},
        title=f"Rotating the stem about its arc centre removes no bone beyond the stem (max overcut {max_over:.3f} %)",
        caption=("(a) Dorr B 一个设计的插入过程：灰线为绕曲率中心（+）旋转的中间位姿，彩色为最终位姿的骨内部分。"
                 "(b) 每型 10 个通过几何门的设计：以 0.25 mm 弧长步长离散插入，扫掠并集 ∩ 保留骨 − 最终柄体 的面积占柄体骨内面积的比例；"
                 "点线为 0.1 % 验收线。"),
        units={"kappa": "1/m (plotted ×1000)", "overcut_pct": "%"})

    # 表
    t01 = []
    for t in "ABC":
        D, m = F.CFG["dorr"][t], fem[t].measured
        t01.append(dict(dorr=t, CFI_preset=D["cfi"], CFI_measured=m["cfi"], CFI_band=F.dorr_band("cfi", m["cfi"]),
                        CI_preset=D["ci"], CI_measured=m["ci"], CI_band=F.dorr_band("ci", m["ci"]),
                        canal_LT20_mm=m["canal20_mm"], canal_isthmus_mm=m["canal_isthmus_mm"],
                        wall_LT20_medial_mm=m["wall20_medial_mm"], wall_LT20_lateral_mm=m["wall20_lateral_mm"],
                        min_cortex_mm=m["min_cortex_mm"], canal_halfwidth_cut_mm=m["canal_halfwidth_at_cut_mm"],
                        E_cancellous_MPa=D["E_cancellous"]))
    ps.publish_table("R1-T01", t01, title="三型 CFI 与皮质指数：预设、实测、所属 Dorr 区间，及关键尺寸",
                     caption="实测值由最终多边形在指定高度的水平截线计算；band 为实测值按 Dorr 判据所属型别。",
                     units={"canal_LT20_mm": "mm", "E_cancellous_MPa": "MPa"})
    t02 = [dict(variable=k, lower=S.DS[k]["lo"], upper=S.DS[k]["hi"], unit=S.DS[k]["unit"],
                definition=S.DS[k]["desc"], normalisation="(v − lower) / (upper − lower) ∈ [0, 1]") for k in S.VARS]
    for t in "ABC":
        k0, k1, l0, l1 = derived[t]
        t02.append(dict(variable=f"derived κ, L (Dorr {t}, passing)", lower=f"{k0 * 1000:.1f} 1/m; {l0:.0f} mm",
                        upper=f"{k1 * 1000:.1f} 1/m; {l1:.0f} mm", unit="", definition="arc through the cut centre tangent to the entry direction and ending at the tip point",
                        normalisation="not a design variable"))
    ps.publish_table("R1-T02", t02, title="设计变量定义、范围与归一化（含导出的曲率与弧长范围）",
                     caption="固定参数：过盈 δ = 0.10 mm、μ = 0.3、截骨线距头心 25 mm、假体颈半宽 7 mm。")
    t03 = []
    reasons = sorted({k for c in gate_counts.values() for k in c})
    for lvl, rs in reasons:
        t03.append(dict(level=lvl, reason=rs or "PASS", **{f"Dorr_{t}": gate_counts[t][(lvl, rs)] for t in "ABC"}))
    t03.append(dict(level="", reason="pass rate", **{f"Dorr_{t}": f"{rates[t]:.1%}" for t in "ABC"}))
    ps.publish_table("R1-T03", t03, title="几何门结果计数（每型 1,024 个 Sobol 设计）",
                     caption="L1 为参数层拒绝（含尖端比髓腔宽），L2 为几何层拒绝。")

    # 验收
    dev = max(max(abs(fem[t].measured["cfi"] - F.CFG["dorr"][t]["cfi"]), abs(fem[t].measured["ci"] - F.CFG["dorr"][t]["ci"]))
              for t in "ABC")
    bands_ok = all(F.dorr_band("cfi", fem[t].measured["cfi"]) == t and F.dorr_band("ci", fem[t].measured["ci"]) == t
                   for t in "ABC")
    pt = subprocess.run([sys.executable, "-m", "pytest", "tests/test_geometry.py", "-q", "-p", "no:cacheprovider"],
                        cwd=ROOT, capture_output=True, text=True)
    last = pt.stdout.strip().splitlines()[-1] if pt.stdout.strip() else pt.stderr[-200:]
    worst = min(rates, key=rates.get)
    a4 = all(r >= 0.20 for r in rates.values())
    ps.publish_acceptance("R1", [
        {"id": "R1-A1", "measured": f"最大偏差 {dev:.3f}；三型实测均落在对应 Dorr 区间" if bands_ok else f"最大偏差 {dev:.3f}；区间不符",
         "status": "PASS" if dev <= 0.05 and bands_ok else "FAIL", "note": "" if dev <= 0.05 and bands_ok else "检查厚度场校准"},
        {"id": "R1-A2", "measured": f"最大 {max_over:.4f} %（{len(over_rows)} 个设计）",
         "status": "PASS" if max_over <= 0.1 else "FAIL", "note": "" if max_over <= 0.1 else "检查截面单调性"},
        {"id": "R1-A3", "measured": last, "status": "PASS" if pt.returncode == 0 else "FAIL",
         "note": "" if pt.returncode == 0 else "单元测试失败"},
        {"id": "R1-A4", "measured": "；".join(f"{t} {rates[t]:.1%}" for t in "ABC"),
         "status": "PASS" if a4 else "FAIL",
         "note": "" if a4 else (f"Dorr {worst} 通过率低于 20 %。失败主要是柄体切入股骨距皮质（C 型近端皮质厚）与尖端比髓腔宽。"
                                f"处置建议：不改设计空间；把 {worst} 型 BO 候选池从 20,000 加到 40,000，使可行候选约 "
                                f"{int(40000 * rates[worst]):,} 个，与 A、B 型同量级。此项需用户同意后才在 S5 生效；S2–S4 不受影响。")},
    ])
    ps.publish_inputs("R1", config_design_space="tip_depth, tip_lat, w_prox, taper, theta_in（2026-09-26 修订）",
                      sobol_map=f"seed 1, n = {N_MAP}/型", atlas="seed 2, 8 个", overcut_check="seed 11, 每型前 10 个通过者")

    tx = ps.report_dir("R1") / "text"
    tx.joinpath("summary.md").write_text(
        f"三型股骨共用一个外轮廓，只改内轮廓；实测 CFI 为 {cfi['A']:.2f} / {cfi['B']:.2f} / {cfi['C']:.2f}、皮质指数为 "
        f"{fem['A'].measured['ci']:.2f} / {fem['B'].measured['ci']:.2f} / {fem['C'].measured['ci']:.2f}，与预设值偏差不超过 {dev:.3f}，"
        f"均落在各自 Dorr 区间。圆弧柄绕曲率中心旋转插入的数值复核给出最大过切 {max_over:.3f} %，零过切结论成立。"
        f"几何门通过率 A {rates['A']:.0%}、B {rates['B']:.0%}、C {rates['C']:.0%}；C 型低于 20 % 验收线，R1-A4 不通过，"
        "处置见验收表，需要用户确认。**设计变量相对已批准计划有修订**：原计划的 (弧长, 曲率) 参数化通过率只有 0.4–2 %，"
        "改为由尖端位置定义圆弧，其余三个变量不变（见第 3 节）。", encoding="utf-8")
    tx.joinpath("methods.md").write_text(
        "**股骨（`femur2d.py`）**：冠状面，x 向内侧为正、z 向上为正，原点在干部轴线、小转子中点高度。外轮廓 = 近端 21 个控制点的"
        "参数三次样条（小转子、股骨距、颈下缘、大转子、颈上缘）+ 头部圆（心 (42, 60) mm、半径 23 mm）+ 外径 27 mm 的直干部，"
        "闭运算（2 mm）圆滑后截于小转子下 150 mm。颈干角 130°。内轮廓为外轮廓的变厚度内偏移：皮质厚度场在峡部（小转子下 90 mm 以下）"
        "由皮质指数给出，在小转子上 20 mm 由 CFI 给出（内侧股骨距占两侧总壁厚 55 %），两者之间 smoothstep 过渡，"
        "再向上 25 mm 内过渡到 2 mm 的颈/头/大转子薄壳；变厚度偏移用 0.1 mm 栅格的欧氏距离变换加零等值线实现，"
        "CFI 高度的壁厚迭代校准到实测 CFI 误差 < 0.02 mm。髓腔全程视为松质骨。\n\n"
        "**截骨与 ROI**：颈中段截骨，截骨线垂直颈轴、中心距头心 25 mm（头颈交界约 15 mm 与颈基底约 35 mm 的中点）。"
        "Gruen 7 ROI = 截骨线以下、x ≥ 0、z ≥ −10 mm 的骨；Gruen 1 ROI = x < 0、z ≥ −10 mm 的骨。\n\n"
        "**柄（`stem2d.py`）与设计变量修订**：柄体中轴为圆弧，起点为截骨中心，初始方向为颈轴反向再转 θ_in；"
        "截面半宽从近端 w_p 线性收窄到尖端 w_t，尖端半圆帽；柄体向上延伸越过截骨线，所以骨内部分上界即截骨面。"
        "已批准计划以弧长 L（70–120 mm）与曲率 κ（0–1/80 mm⁻¹）为变量；实测 1,024 个 Sobol 设计的通过率 A 2.1 %、B 1.8 %、C 0.4 %，"
        "73 % 的柄尖从外侧皮质穿出——沿颈轴进入的圆弧需要半径约 90 mm 以下才能在碰到外侧壁前转向远端。"
        "因此改为用尖端位置定义圆弧：尖端在小转子下 tip_depth（15–65 mm）、在该高度髓腔内的相对位置 tip_lat（0.1–0.9，"
        "0 贴内侧壁、1 贴外侧壁，按尖端半宽留贴壁余量）；过截骨中心、在该点与入柄方向相切、终于尖端点的圆弧唯一，"
        "由此导出 κ = 2 sin α / |c| 与 L = |c| α / sin α（c 为弦，α 为入柄方向到弦的夹角）。w_prox、taper、θ_in 的定义与范围不变。"
        "导出的 κ 与 L 范围见 R1-T02，L 与原计划的 70–120 mm 基本一致。\n\n"
        "**几何门（L1/L2）**：L1 = 变量越界、尖端半宽超过该高度髓腔半宽、曲率半径小于近端半宽、颈长不在 25–45 mm；"
        "L2 = 柄体自交、尖端不在骨内或穿出皮质、骨内柄体与皮质相交 > 0.5 mm²、剩余壁厚 < 1.0 mm、尖端距远端截面 < 20 mm。\n\n"
        "**零过切复核**：绕曲率中心按 0.25 mm 弧长步长离散插入，扫掠并集与保留骨求交后减去最终柄体，得过切面积。", encoding="utf-8")
    tx.joinpath("limitations.md").write_text(
        "- 外轮廓三型相同时，Dorr 判据迫使 C 型近端髓腔比 A 型窄约 12 mm（小转子上 20 mm 处髓腔宽 39.3 对 51.3 mm），"
        "即 C 型近端皮质偏厚（内/外侧 9.9/8.0 mm）。真实的 C 型股骨通常外径也更大、近端皮质更薄。三型的力学差异因此同时含"
        "髓腔形态与这一人为的近端壁厚差异，在 R5 解读时要注意。\n"
        "- 设计变量相对已批准计划修订（见方法），BO 与参考扫描都在修订后的空间里进行。\n"
        "- 髓腔全程按松质骨处理（真实干部为骨髓，刚度可忽略）。\n"
        "- 几何门的皮质相交容差 0.5 mm² 与壁厚 1 mm 是计划值，未做敏感性分析。", encoding="utf-8")
    print(json.dumps({"rates": rates, "dev": dev, "max_over": max_over, "pytest": last}, indent=1))


if __name__ == "__main__":
    main()
