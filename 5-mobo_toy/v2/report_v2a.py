"""V2A 报告的图、表、验收（在 Linux 上跑；PDF 在本机由 report.py 打印）。

    python v2/report_v2a.py [--part geometry|verification|bo|all]

每张图先写 CSV，再由 plot_* 只读 CSV 作图（plotstyle.publish_figure），可一键重画；图题由数据生成。
验收表每次全量重算：数据未到的项记 PENDING。
"""
from __future__ import annotations

import csv
import json
import math
import pathlib
import sys
from multiprocessing import Pool

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import psv2  # noqa: E402,F401  必须先于 plotstyle
import plotstyle as ps  # noqa: E402
import femur_real as FR  # noqa: E402
import geom3d as G  # noqa: E402
import jobs as J  # noqa: E402

plt = ps.plt
MIN_A0 = math.pi * 7.0 ** 2
CORT, CANC = "#C9C9C9", "#F3E3C3"
ACOL = ps.DORR["A"]


def _read(csv_path):
    return ps.read_csv(csv_path)


def _groups(d, *keys):
    out = {}
    n = len(d[keys[0]])
    for i in range(n):
        k = tuple(d[kk][i] for kk in keys)
        out.setdefault(k, []).append(i)
    return out


# ================================================================== 几何：轮廓提取
def _contours(fm, C, e1, e2, ext1, ext2, h=0.25, cut=False):
    """平面上外膜、内膜的零等值线（contourpy），返回 [(kind, ring_id, xy)]。
    cut=True 时只取截骨面以下的保留骨（取 max(sdf, 到截骨面的有号距离)），截骨处的轮廓也是闭合的。
    范围要大于骨截面，否则等值线在窗口边上断开，填色会被错连。"""
    import contourpy
    a = np.arange(ext1[0], ext1[1], h); b = np.arange(ext2[0], ext2[1], h)
    A, B = np.meshgrid(a, b)
    P = C + A.reshape(-1, 1) * e1 + B.reshape(-1, 1) * e2
    dcut = (P - fm.C03) @ fm.u3 if cut else None
    out = []
    for kind, fn in (("outer", fm.outer_sdf), ("canal", fm.canal_sdf)):
        Z = fn(P) if dcut is None else np.maximum(fn(P), dcut)
        Z = Z.reshape(A.shape)
        for k, ln in enumerate(contourpy.contour_generator(a, b, Z).lines(0.0)):
            if len(ln) > 5:
                out.append((kind, k, ln))
    return out


def _rows_from_contours(panel, cons, extra=None):
    rows = []
    for kind, k, ln in cons:
        for j, (x, y) in enumerate(ln):
            rows.append({"panel": panel, "kind": kind, "ring": k, "pt": j, "x": float(x), "y": float(y), **(extra or {})})
    return rows


def _draw_rings(ax, d, idx):
    """按 kind/ring 画闭合轮廓：先外膜（灰），再内膜（米色）。"""
    for kind, fc in (("outer", CORT), ("canal", CANC)):
        g = _groups({k: [d[k][i] for i in idx] for k in ("kind", "ring")}, "kind", "ring")
        for (kd, ring), ii in g.items():
            if kd != kind:
                continue
            xy = np.array([[d["x"][idx[i]], d["y"][idx[i]]] for i in ii])
            ax.fill(xy[:, 0], xy[:, 1], fc=fc, ec="none")


# ================================================================== F01 股骨
def fig_f01(fm):
    rows = []
    C, e1, e2 = fm.neck_plane()
    rows += _rows_from_contours("neck_plane", _contours(fm, C, e1, e2, (-70, 55), (-205, 45), h=0.3))

    def plane_xy(P):
        Q = np.atleast_2d(P) - C
        return np.c_[Q @ e1, Q @ e2]
    marks = {"head": plane_xy(fm.H)[0], "head_r": [fm.Rh, 0.0],
             "neck_a": plane_xy(fm.H + 10 * fm.u3)[0], "neck_b": plane_xy(fm.H - 60 * fm.u3)[0],
             "shaft_a": plane_xy(np.array([0, 0, -200.0]))[0], "shaft_b": plane_xy(np.array([0, 0, 60.0]))[0],
             "cut_a": plane_xy(fm.C03 - 30 * fm.n3)[0], "cut_b": plane_xy(fm.C03 + 30 * fm.n3)[0]}
    for z, lab in ((0.0, "LT"), (20.0, "LT+20"), (-100.0, "LT-100")):
        marks[f"lvl_{lab}_a"] = plane_xy(np.array([-60, 0, z]))[0]
        marks[f"lvl_{lab}_b"] = plane_xy(np.array([70, 0, z]))[0]
    for k, (x, y) in marks.items():
        rows.append({"panel": "marks", "kind": k, "ring": 0, "pt": 0, "x": float(x), "y": float(y)})
    for z in (40.0, 20.0, 0.0, -40.0, -70.0, -100.0, -130.0, -150.0):
        cons = _contours(fm, np.array([0.0, 0.0, z]), np.array([1.0, 0, 0]), np.array([0, -1.0, 0]), (-45, 75), (-45, 45), h=0.2)
        rows += _rows_from_contours(f"z{z:+.0f}", cons)
    lm = fm.lm
    title = (f"Real right femur (STEP): head r {lm['head_r']:.1f} mm, neck–shaft {lm['neck_shaft_deg']:.1f}°, "
             f"anteversion {lm['anteversion_deg']:.1f}°, offset {lm['offset_mm']:.1f} mm")
    ps.publish_figure("V2A-F01", rows, plot_f01, title=title,
                      caption="左：颈平面（过截骨中心，由干轴与颈轴张成）切面，灰为皮质、米色为松质骨；蓝色虚圆为头球拟合，"
                              "蓝线为颈轴，绿线为干轴，橙线为颈中段截骨线（距头心 25 mm），点线为 LT、LT+20、LT−100 高度。"
                              "右：垂直干轴的 8 个横断面（z 为相对小转子的高度），内侧向右、前方向上，+ 为干轴。轮廓取距离场零等值线。",
                      units={"x": "mm", "y": "mm"}, sources={"femur": "v2/data/femur_real/*.STEP（sha256 见 SHA256SUMS.txt）"})


def plot_f01(csv_path):
    from matplotlib.patches import Circle
    d = _read(csv_path)
    fig = plt.figure(figsize=(ps.WIDTH_MM["double"] * ps.MM, 118 * ps.MM))
    gs = fig.add_gridspec(2, 5, width_ratios=[1.6, 1, 1, 1, 1])
    panels = _groups(d, "panel")
    ax = fig.add_subplot(gs[:, 0])
    _draw_rings(ax, d, panels[("neck_plane",)])
    m = {d["kind"][i]: (d["x"][i], d["y"][i]) for i in panels[("marks",)]}
    ax.add_patch(Circle(m["head"], m["head_r"][0], fill=False, ls="--", lw=0.6, color="#0072B2"))
    ax.plot(*zip(m["neck_a"], m["neck_b"]), color="#0072B2", lw=0.7, label="neck axis")
    ax.plot(*zip(m["shaft_a"], m["shaft_b"]), color="#009E73", lw=0.7, label="shaft axis")
    ax.plot(*zip(m["cut_a"], m["cut_b"]), color="#D55E00", lw=0.9, label="neck cut")
    for lab in ("LT", "LT+20", "LT-100"):
        a, b = m[f"lvl_{lab}_a"], m[f"lvl_{lab}_b"]
        ax.plot(*zip(a, b), color=ps.GREY, lw=0.4, ls=":")
        ax.text(a[0] + 2, a[1] + 1, lab.replace("-", "−"), fontsize=5.5, color=ps.GREY)
    ax.set_aspect("equal"); ax.set_xlim(-70, 55); ax.set_ylim(-205, 45); ax.axis("off")
    ax.legend(fontsize=5.5, loc="lower right")
    for i, z in enumerate((40, 20, 0, -40, -70, -100, -130, -150)):
        a2 = fig.add_subplot(gs[i // 4, 1 + i % 4])
        _draw_rings(a2, d, panels[(f"z{z:+d}",)])
        a2.plot(0, 0, "+", color="#009E73", ms=4)
        a2.set_aspect("equal"); a2.set_xlim(-30, 50); a2.set_ylim(-40, 40); a2.axis("off")
        a2.set_title(f"z = {z:+d} mm", fontsize=6.5)
    return fig


# ================================================================== F02 Dorr 宽度剖面
def fig_f02(fm):
    xs = np.arange(-45, 75, 0.25)
    rows = []
    for z in np.arange(-150.0, 40.1, 1.0):
        P0 = np.c_[xs, np.zeros_like(xs), np.full_like(xs, z)]
        cin0, oin0 = fm.canal_sdf(P0) <= 0, fm.outer_sdf(P0) <= 0
        ys = np.arange(-30, 30, 0.5)
        X, Y = np.meshgrid(xs, ys)
        P = np.c_[X.ravel(), Y.ravel(), np.full(X.size, z)]
        cin = (fm.canal_sdf(P) <= 0).reshape(X.shape).any(0)
        oin = (fm.outer_sdf(P) <= 0).reshape(X.shape).any(0)
        near = np.abs(xs) < 30

        def w(m):
            x = xs[m & near]
            return float(x.max() - x.min()) if len(x) else float("nan")
        rows.append({"z": z, "canal_full": w(cin), "outer_full": w(oin), "canal_chord": w(cin0), "outer_chord": w(oin0)})
    di = FR.dorr_indices(fm)
    fw, ch = di["full_width"], di["chord_y0"]
    title = (f"Dorr {fw['dorr_by_CI']} by cortical index ({fw['CI']:.2f}); canal flare index {fw['CFI']:.2f} by full width "
             f"vs {ch['CFI']:.2f} by the chord through the shaft axis")
    ps.publish_figure("V2A-F02", rows, plot_f02, title=title,
                      caption="内外侧（x）方向宽度沿干轴高度 z（z = 0 为小转子）。实线：该高度截面在内外侧方向的全宽"
                              "（对应正位片投影，Dorr 判据的量法）；虚线：过干轴的冠状弦（y = 0）。"
                              "CFI = LT+20 髓腔宽 / 峡部髓腔宽；CI = (外径 − 髓腔)/外径 @ LT−100。",
                      units={"z": "mm", "width": "mm"})


def plot_f02(csv_path):
    d = _read(csv_path)
    fig, ax = ps.new_figure("single", 70)
    z = np.array(d["z"], float)
    for key, col, ls, lab in (("outer_full", ps.GREY, "-", "outer, full width"), ("canal_full", ACOL, "-", "canal, full width"),
                              ("outer_chord", ps.GREY, "--", "outer, chord y = 0"), ("canal_chord", ACOL, "--", "canal, chord y = 0")):
        ax.plot(np.array(d[key], float), z, color=col, ls=ls, lw=1.0, label=lab)
    for zz, lab in ((20, "LT+20"), (0, "LT"), (-100, "LT−100")):
        ax.axhline(zz, color=ps.LIGHT, lw=0.5, ls=":")
        ax.text(ax.get_xlim()[1] if False else 62, zz + 1.5, lab, fontsize=6, color=ps.GREY, ha="right")
    ax.set_xlabel("medial–lateral width (mm)"); ax.set_ylabel("height z above lesser trochanter (mm)")
    ax.set_xlim(0, 65); ax.legend(fontsize=6, loc="lower right")
    return fig


# ================================================================== F03 截面形状、F04 面积曲线
def fig_f03():
    import cases as CS
    rows = []
    k = math.sqrt(250.0)
    for v in G.SHAPE_VARS:
        lo, hi = G.DESIGN[v]
        for lev, val in (("low", lo), ("mid", 0.5 * (lo + hi)), ("high", hi)):
            dd = dict(CS.REF); dd[v] = val
            sec = G.unit_section(dd, 160) * k
            for j, (x, y) in enumerate(sec):
                rows.append({"var": v, "level": lev, "value": val, "pt": j, "x": float(x), "y": float(y)})
    n_asym = sum(1 for v in G.SHAPE_VARS)
    ps.publish_figure("V2A-F03", rows, plot_f03,
                      title=f"Seven cross-section variables; the anterior and posterior halves carry their own squareness and keystone",
                      caption="每列只变一个截面变量，其余取一个不对称基准（γ_ml 0.56、γ_ap 0.44、n_a 3、n_p 5、τ_a 0.15、τ_p −0.10）；"
                              "截面面积统一 250 mm²，内侧向右、前方向上。橙色虚线为关于前后侧中线（y = 0）的镜像，与实形不重合即前后不对称。",
                      units={"x": "mm", "y": "mm"})


def plot_f03(csv_path):
    d = _read(csv_path)
    fig, axes = ps.new_figure("double", 95, 3, len(G.SHAPE_VARS))
    g = _groups(d, "var", "level")
    for c, v in enumerate(G.SHAPE_VARS):
        for r, lev in enumerate(("low", "mid", "high")):
            ii = g[(v, lev)]
            xy = np.array([[d["x"][i], d["y"][i]] for i in ii])
            ax = axes[r, c]
            ax.fill(xy[:, 0], xy[:, 1], fc="#9BB8D3", ec="#1f4e79", lw=0.6)
            ax.plot(xy[:, 0], -xy[:, 1], color="#D55E00", lw=0.5, ls=(0, (2, 1.5)))
            ax.axhline(0, color=ps.GREY, lw=0.3, ls=":"); ax.axvline(0, color=ps.GREY, lw=0.3, ls=":")
            ax.set_xlim(-20, 20); ax.set_ylim(-14, 14); ax.set_aspect("equal"); ax.axis("off")
            ax.set_title(f"{G.LABEL[v].split(' ')[-1]} = {d['value'][ii[0]]:.2f}", fontsize=5.8)
    return fig


def fig_f04():
    rows = []
    x = np.linspace(0, 1, 101)
    base = G.from_unit(np.full(len(G.VARS), 0.5))
    for q in (0.5, 1.0, 2.0, 3.0):
        st = G.Stem3D(**{**base, "q": q, "rho_tip": 0.3, "L": 1.0})
        rows += [{"family": "q", "param": q, "t": float(t), "r": float(r)} for t, r in zip(x, st.area_ratio(x))]
    for rt in (0.1, 0.3, 0.5):
        st = G.Stem3D(**{**base, "q": 1.0, "rho_tip": rt, "L": 1.0})
        rows += [{"family": "rho_tip", "param": rt, "t": float(t), "r": float(r)} for t, r in zip(x, st.area_ratio(x))]
    ps.publish_figure("V2A-F04", rows, plot_f04,
                      title="Area-reduction curve A(s)/A0 = ρ_tip + (1 − ρ_tip)(1 − s/L)^q: q sets where the area is lost, ρ_tip how much",
                      caption="左：固定 ρ_tip = 0.3 改变 q；右：固定 q = 1 改变 ρ_tip。s 从肩部（0）到尖端（L）。", units={"t": "s/L"})


def plot_f04(csv_path):
    d = _read(csv_path)
    fig, axes = ps.new_figure("double", 55, 1, 2)
    for ax, fam, lab in ((axes[0], "q", "q"), (axes[1], "rho_tip", "ρ_tip")):
        g = _groups(d, "family", "param")
        for (f, p), ii in sorted(g.items()):
            if f != fam:
                continue
            ax.plot([d["t"][i] for i in ii], [d["r"][i] for i in ii], label=f"{lab} = {p:g}")
        ax.set_xlabel("s / L (shoulder → tip)"); ax.set_ylabel("A(s) / A0"); ax.set_ylim(0, 1.05); ax.legend(fontsize=6)
    return fig


# ================================================================== F05 可行性
_FM = {}


def _tmpl(u):
    if "fm" not in _FM:
        _FM["fm"] = FR.build()
    st = G.Stem3D(**G.from_unit(u))
    r = G.template(st, _FM["fm"])
    feas = bool(r["fit"] and r["A0"] >= MIN_A0)
    reason = "" if feas else (r.get("reason", "").split(" (")[0] if not r["fit"] else "shoulder smaller than prosthetic neck")
    return {**{k: float(v) for k, v in st.d.items()}, "fit": bool(r["fit"]), "A0": float(r.get("A0", math.nan)),
            "s_bind": float(r.get("s_bind", math.nan)), "feasible": feas, "reason": reason}


def feasibility_table(n=8192, seed=999) -> list[dict]:
    f = J.RESULTS / f"feasibility_n{n}_s{seed}_{J.code_hash()}.json"
    if f.exists():
        return json.loads(f.read_text())
    from scipy.stats import qmc
    U = qmc.Sobol(len(G.VARS), scramble=True, seed=10_000 + seed).random(n)
    with Pool(10) as p:
        rows = p.map(_tmpl, list(U), chunksize=32)
    f.write_text(json.dumps(rows))
    return rows


def fig_f05():
    rows = feasibility_table()
    ok = np.array([r["feasible"] for r in rows])
    ps.publish_figure("V2A-F05", rows, plot_f05,
                      title=f"{ok.mean():.0%} of {len(rows)} random designs fit the real femur; short stems at 15–25° fit best",
                      caption="8192 点打乱 Sobol 设计（与 S4′ 参考集同一池种子 999）逐一模板化。可行 = 最小号能进、尖端面积 ≥ 12 mm²、"
                              "肩部面积 ≥ 假体颈截面（π·7² = 154 mm²）。左、中：按插入角与长度分箱的可行率；右：肩部面积分布，灰为全部能放进去的，"
                              "蓝为可行的，虚线为 154 mm²。",
                      units={"alpha": "deg", "L": "mm", "A0": "mm2"})


def plot_f05(csv_path):
    d = _read(csv_path)
    ok = np.array([str(v) == "True" or v is True for v in d["feasible"]])
    fit = np.array([str(v) == "True" or v is True for v in d["fit"]])
    a, L, A0 = (np.array(d[k], float) for k in ("alpha", "L", "A0"))
    fig, axes = ps.new_figure("double", 58, 1, 3)
    for ax, x, bins, lab in ((axes[0], a, np.arange(G.ALPHA_LO, G.ALPHA_HI + 0.1, 5.0), "insertion angle α (°)"),
                             (axes[1], L, np.arange(40.0, 90.1, 10.0), "length L (mm)")):
        rate = [ok[(x >= lo) & (x < hi)].mean() for lo, hi in zip(bins[:-1], bins[1:])]
        ax.step(bins, np.r_[rate, rate[-1]], where="post", color=ACOL)
        ax.set_xlabel(lab); ax.set_ylabel("fraction feasible"); ax.set_ylim(0, 1.05)
    axes[2].hist(A0[fit], bins=np.arange(0, 600, 20), color=ps.LIGHT, label="fits (any size)")
    axes[2].hist(A0[ok], bins=np.arange(0, 600, 20), color=ACOL, label="feasible")
    axes[2].axvline(MIN_A0, color="black", lw=0.6, ls="--")
    axes[2].set_xlabel("shoulder area A0 (mm²)"); axes[2].set_ylabel("designs"); axes[2].legend(fontsize=6)
    return fig


# ================================================================== F06 模板化示例
def fig_f06(fm):
    import cases as CS
    rows = []
    C, e1, e2 = fm.neck_plane()
    np_cons = _contours(fm, C, e1, e2, (-80, 70), (-140, 80), h=0.3, cut=True)
    info = []
    for ex, (name, dd) in enumerate(CS.EXAMPLES.items()):
        st = G.Stem3D(**dd)
        pl = G.template(st, fm)
        rows += _rows_from_contours("neck_plane", np_cons, {"example": ex})
        P0, d, e_ml, e_ap = pl["pose"]
        sec = G.unit_section(st.d, 120)
        s = np.r_[np.linspace(G.S_TOP, 0, 10, endpoint=False), np.linspace(0, st.L, 60)]
        kk = np.sqrt(pl["A0"] * st.area_ratio(s))
        ring = np.r_[[P0 + si * d + ki * sec[:, 0].max() * e_ml for si, ki in zip(s, kk)],
                     [P0 + (st.L + st.cap_length(pl["A0"])) * d],
                     [P0 + si * d + ki * sec[:, 0].min() * e_ml for si, ki in zip(s[::-1], kk[::-1])]]
        from shapely.geometry import Polygon as SP
        Q = ring - C
        poly = SP(np.c_[Q @ e1, Q @ e2]).buffer(0)
        u2 = np.array([fm.u3 @ e1, fm.u3 @ e2]); n2 = np.array([-u2[1], u2[0]])
        half = SP([400 * n2, -400 * n2, -400 * n2 - 400 * u2, 400 * n2 - 400 * u2])      # 截骨面以下（颈平面上）
        poly = poly.intersection(half)
        poly = max(getattr(poly, "geoms", [poly]), key=lambda g: g.area)
        for j, (x, y) in enumerate(np.asarray(poly.exterior.coords)):
            rows.append({"panel": "neck_plane", "kind": "stem", "ring": 0, "pt": j, "x": float(x), "y": float(y), "example": ex})
        cut = [C - 30 * fm.n3, C + 30 * fm.n3]
        for j, P in enumerate(cut):
            q = P - C
            rows.append({"panel": "neck_plane", "kind": "cut", "ring": 0, "pt": j, "x": float(q @ e1), "y": float(q @ e2), "example": ex})
        for fr in (0.15, 0.5, 0.85):
            sc = fr * st.L
            cons = _contours(fm, P0 + sc * d, e_ml, e_ap, (-60, 60), (-60, 60), h=0.2, cut=True)
            rows += _rows_from_contours(f"s{fr:.2f}", cons, {"example": ex})
            sp = G.unit_section(st.d, 120) * math.sqrt(pl["A0"] * float(st.area_ratio(sc)))
            rows += [{"panel": f"s{fr:.2f}", "kind": "stem", "ring": 0, "pt": j, "x": float(x), "y": float(y), "example": ex}
                     for j, (x, y) in enumerate(sp)]
        info.append({"example": ex, "name": name, "alpha": st.alpha, "A0": pl["A0"], "s_bind": pl["s_bind"],
                     "feasible": pl["fit"] and pl["A0"] >= MIN_A0})
    n_ok = sum(i["feasible"] for i in info)
    cols = ["panel", "kind", "ring", "pt", "x", "y", "example", "alpha", "feasible"]
    for i in info:                                              # 每个示例的注释写进 CSV
        rows.append({"panel": "info", "kind": i["name"], "ring": 0, "pt": 0, "x": i["A0"], "y": i["s_bind"],
                     "example": i["example"], "alpha": i["alpha"], "feasible": i["feasible"]})
    ps.publish_figure("V2A-F06", rows, plot_f06,
                      title=f"Three example stems in the real femur: {n_ok} of 3 are large enough to carry the prosthetic neck",
                      caption="每行一根示例柄（插入角为其设计值）。左：颈平面，橙线为截骨线，蓝色为柄在颈平面上的投影；右三列：垂直于柄轴、"
                              "距肩部 0.15/0.50/0.85 L 的截面（内侧向右、前方向上），灰为皮质、米色为松质、蓝为柄截面；只画截骨面以下的保留骨。尺寸为皮质穿透 ≤ 0.25 mm 的最大号。",
                      units={"x": "mm", "y": "mm", "A0": "mm2"}, columns=cols)


def plot_f06(csv_path):
    d = _read(csv_path)
    fig, axes = ps.new_figure("double", 150, 3, 4)
    g = _groups(d, "example", "panel")
    for ex in range(3):
        for c, panel in enumerate(("neck_plane", "s0.15", "s0.50", "s0.85")):
            ax = axes[ex, c]
            ii = g.get((ex, panel), [])
            _draw_rings(ax, d, [i for i in ii if d["kind"][i] in ("outer", "canal")])
            st = np.array([[d["x"][i], d["y"][i]] for i in ii if d["kind"][i] == "stem"])
            if len(st):
                ax.fill(st[:, 0], st[:, 1], fc=ACOL, ec=ACOL, alpha=0.85, lw=0.5)
            cu = np.array([[d["x"][i], d["y"][i]] for i in ii if d["kind"][i] == "cut"])
            if len(cu):
                ax.plot(cu[:, 0], cu[:, 1], color="#D55E00", lw=0.8)
            ax.set_aspect("equal"); ax.axis("off")
            if panel == "neck_plane":
                ax.set_xlim(-70, 55); ax.set_ylim(-130, 45)
                inf = [i for i in g.get((ex, "info"), [])]
                if inf:
                    i = inf[0]
                    ok = str(d["feasible"][i]) == "True"
                    ax.text(0.02, 0.02, f"{d['kind'][i]}\nα {float(d['alpha'][i]):.1f}°, shoulder {d['x'][i]:.0f} mm²"
                            f"{'' if ok else ' (< 154: infeasible)'}\ntightest at s = {d['y'][i]:.0f} mm",
                            transform=ax.transAxes, fontsize=5, bbox=dict(fc="white", ec="none", alpha=0.85, pad=1))
            else:
                ax.set_xlim(-20, 20); ax.set_ylim(-20, 20)
            if ex == 0:
                ax.set_title({"neck_plane": "neck plane", "s0.15": "0.15 L", "s0.50": "0.50 L", "s0.85": "0.85 L"}[panel], fontsize=6.5)
    return fig


# ================================================================== 表 T01–T03
def tables_geometry(fm):
    lm, ref = fm.lm, fm.cfg["femur"]["reference_landmarks"]
    di = FR.dorr_indices(fm)
    occ = FR.occ_volume_in_box(fm)
    vox = lm["voxel_volume_in_box_mm3"]
    rows = [
        {"item": "cortical STEP", "value": fm.cfg["femur"]["step_cortical"], "check": f"sha256 {fm.cfg['femur']['sha256_cortical'][:12]}…; OCC volume {lm['occ']['cortical_mm3']:.0f} mm³ (hollow)"},
        {"item": "cancellous STEP", "value": fm.cfg["femur"]["step_cancellous"], "check": f"sha256 {fm.cfg['femur']['sha256_cancellous'][:12]}…; OCC volume {lm['occ']['cancellous_mm3']:.0f} mm³"},
        {"item": "B-rep faces", "value": f"cortical {lm['n_faces']['cortical_brep']} = periosteal {lm['n_faces']['periosteal_brep']} + inner shell {lm['n_faces']['cortical_inner_shell_brep']}", "check": f"cancellous {lm['n_faces']['cancellous_brep']}"},
        {"item": "canal volume in box (SDF vs OCC)", "value": f"{vox['canal']:.0f} vs {occ['canal_occ_mm3']:.0f} mm³", "check": f"{100 * (vox['canal'] / occ['canal_occ_mm3'] - 1):+.2f}%"},
        {"item": "outer volume in box (SDF vs OCC)", "value": f"{vox['outer']:.0f} vs {occ['outer_occ_mm3']:.0f} mm³", "check": f"{100 * (vox['outer'] / occ['outer_occ_mm3'] - 1):+.2f}%"},
        {"item": "surface |SDF| P95 (canal / outer)", "value": f"{lm['surf_sample_sdf_abs_p95']['canal']:.3f} / {lm['surf_sample_sdf_abs_p95']['outer']:.3f} mm", "check": "parity odd columns 0 / 0" if not any(lm["parity_odd_columns"].values()) else str(lm["parity_odd_columns"])},
        {"item": "head radius", "value": f"{lm['head_r']:.2f} mm", "check": f"straight3d {ref['head_r']:.1f} mm ({lm['head_r'] - ref['head_r']:+.2f})"},
        {"item": "neck–shaft angle", "value": f"{lm['neck_shaft_deg']:.1f}°", "check": f"straight3d {ref['neck_shaft_deg']:.1f}° ({lm['neck_shaft_deg'] - ref['neck_shaft_deg']:+.1f})"},
        {"item": "anteversion (to posterior condylar line)", "value": f"{lm['anteversion_deg']:.1f}°", "check": f"straight3d {ref['anteversion_deg']:.1f}° ({lm['anteversion_deg'] - ref['anteversion_deg']:+.1f})"},
        {"item": "offset", "value": f"{lm['offset_mm']:.1f} mm", "check": ""},
        {"item": "CFI / CI, full width", "value": f"{di['full_width']['CFI']:.2f} / {di['full_width']['CI']:.2f}", "check": f"Dorr {di['full_width']['dorr_by_CFI']} / {di['full_width']['dorr_by_CI']}"},
        {"item": "CFI / CI, chord y = 0", "value": f"{di['chord_y0']['CFI']:.2f} / {di['chord_y0']['CI']:.2f}", "check": f"Dorr {di['chord_y0']['dorr_by_CFI']} / {di['chord_y0']['dorr_by_CI']}"},
        {"item": "isthmus canal (full width)", "value": f"{di['full_width']['canal_isthmus']:.1f} mm at z = {di['full_width']['z_isthmus']:.0f} mm", "check": ""},
    ]
    ps.publish_table("V2A-T01", rows, title="Real femur model: sources, volume checks, landmarks and Dorr indices",
                     caption="距离场体积与 OCC 体积都限于距离场盒子（模型坐标 x −45…75、y −45…45、z −160…110 mm）。"
                             "straight3d 的对照值来自同一根股骨的 Job-1 四面体体素化（线性单元会略缩小曲面）。")
    rows2 = [{"group": [k for k, v in G.GROUPS.items() if var in v][0], "variable": var, "label": G.LABEL[var],
              "low": G.DESIGN[var][0], "high": G.DESIGN[var][1]} for var in G.VARS]
    ps.publish_table("V2A-T02", rows2, title="Eleven design variables in four groups",
                     caption="尺寸 A0 与入口偏移 e 不是设计变量，由模板化给出（最大号，皮质穿透 ≤ 0.25 mm）。")
    return occ, di


def table_t03(fm):
    import model3d_v2 as M
    F = M.load_vector(fm.cfg)
    done = [J.result(d.name) for d in J.QROOT.glob("*") if (d / "DONE").exists()]
    des = [r for r in done if r and r.get("spec", {}).get("kind") == "design" and r["spec"]["h_int"] == 2.0]
    wf = [r["solve"]["m_fric"]["wall_s"] for r in des if "m_fric" in r.get("solve", {})]
    wb = [r["solve"]["m_bond"]["wall_s"] for r in des if "m_bond" in r.get("solve", {})]
    nt = [sum(r["n_tet"].values()) for r in des if r.get("n_tet")]
    c = fm.cfg
    rows = [
        {"item": "geometry", "value": "real femur STEP (cortex hollow solid + cancellous solid), truncated at LT−150 mm, mid-neck cut 25 mm from head centre"},
        {"item": "elements", "value": f"C3D10 (straight-sided), gmsh; interface {c['mesh']['h_int_mm']} mm, far field {c['mesh']['h_far_mm']} mm; median {np.median(nt):.0f} elements" if nt else "C3D10"},
        {"item": "materials", "value": f"cortex {c['materials']['cortical']['E']:.0f} MPa, cancellous {c['femur']['E_cancellous']:.0f} MPa, Ti6Al4V {c['materials']['titanium']['E']:.0f} MPa, ν 0.3, linear elastic"},
        {"item": "interface (friction model)", "value": f"surface-to-surface small sliding, μ {c['interface']['mu']}, hard contact; press-fit δ {c['interface']['delta_mm']} mm by *CONTACT INTERFERENCE, SHRINK"},
        {"item": "interface (bonded model)", "value": f"*TIE, ADJUST=NO, position tolerance {c['interface']['tie_position_tolerance_mm']} mm"},
        {"item": "steps (friction)", "value": "PRESSFIT (head fixed) → RELEASE → LOAD"},
        {"item": "load", "value": f"F = ({F[0]:.0f}, {F[1]:.0f}, {F[2]:.0f}) N in model axes (+x medial, +y posterior, +z proximal), |F| = {np.linalg.norm(F):.0f} N, on all prosthetic-head nodes"},
        {"item": "boundary", "value": "all nodes on the truncation plane (z = −150 mm) fixed"},
        {"item": "QoIs", "value": "f1 = area-weighted P95 of tangential slip increment LOAD−RELEASE (µm); f2 = Gruen 7 SED loss vs intact (%); c = stem vM P99 (below cut) − 440 MPa"},
        {"item": "solver / wall time", "value": f"Abaqus/Standard 2025, 4 cores per job; friction median {np.median(wf):.0f} s, bonded median {np.median(wb):.0f} s (n = {len(wf)})" if wf else "Abaqus/Standard 2025"},
    ]
    ps.publish_table("V2A-T03", rows, title="FE model reporting items (Erdemir 2012)", caption="按 Erdemir 2012 的模型结构与仿真结构类目概括。")


# ================================================================== 验收
def acceptance(fm, occ, di) -> list[dict]:
    lm, ref = fm.lm, fm.cfg["femur"]["reference_landmarks"]
    out = []
    dr, dn, da = lm["head_r"] - ref["head_r"], lm["neck_shaft_deg"] - ref["neck_shaft_deg"], lm["anteversion_deg"] - ref["anteversion_deg"]
    ok = abs(dr) < 1 and abs(dn) < 1 and abs(da) < 1
    out.append({"id": "V2A-A1", "measured": f"head r {dr:+.2f} mm, NSA {dn:+.2f}°, anteversion {da:+.2f}°", "status": "PASS" if ok else "FAIL",
                "note": "" if ok else "与 straight3d 的差超过门槛"})
    vox = lm["voxel_volume_in_box_mm3"]
    e1, e2 = vox["canal"] / occ["canal_occ_mm3"] - 1, vox["outer"] / occ["outer_occ_mm3"] - 1
    ok = abs(e1) < 0.005 and abs(e2) < 0.005
    out.append({"id": "V2A-A2", "measured": f"canal {100 * e1:+.2f}%, outer {100 * e2:+.2f}%", "status": "PASS" if ok else "FAIL",
                "note": "" if ok else "距离场体积偏差超过 0.5%"})
    return out


def overcut_and_cad(fm, n=20):
    """A3 零过切（沿插入路径采样）与 A4 CAD 柄 ∩ 皮质体积（OCC），取参考池前 n 个可行设计。"""
    import problem_v2a as PB
    import gmsh
    import fe3d_geom as E
    import model3d_v2 as M
    pool = PB.gated_pool(8192, 999)[:n]
    n_in, n_out, fr = 0, 0, []
    for u in pool:
        st = G.Stem3D(**G.from_unit(u))
        pl = G.template(st, fm)
        oc = G.overcut_check(st, fm, pl["A0"], pl["pose"])
        n_in += oc["points_in_bone"]; n_out += oc["points_outside_final_stem"]
        gmsh.initialize()
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            occ = gmsh.model.occ
            C, K = M._femur_shapes(occ, fm)
            Ck, _ = occ.intersect(C, M._keep(occ, fm))
            body = E.stem_solid(occ, st, pl["A0"], pl["pose"], delta=0.0)
            bin_, _ = occ.intersect(body, E.kept_halfspace(occ, fm))
            occ.synchronize()
            v_stem = sum(occ.getMass(d, t) for d, t in bin_)
            ov, _ = occ.intersect(bin_, Ck, removeObject=False, removeTool=False)
            occ.synchronize()
            v_ov = sum(occ.getMass(d, t) for d, t in ov)
            fr.append(v_ov / v_stem)
        finally:
            gmsh.finalize()
    res = {"n": n, "points_in_bone": n_in, "points_outside": n_out, "cad_overlap_frac_max": float(max(fr)),
           "cad_overlap_frac_median": float(np.median(fr))}
    (J.RESULTS / "overcut_cad.json").write_text(json.dumps(res, indent=1))
    return res


def part_geometry():
    fm = FR.build()
    fig_f01(fm); fig_f02(fm); fig_f03(); fig_f04(); fig_f05(); fig_f06(fm)
    occ, di = tables_geometry(fm)
    table_t03(fm)
    oc = overcut_and_cad(fm)
    feas = feasibility_table()
    rate = float(np.mean([r["feasible"] for r in feas]))
    return fm, occ, di, oc, rate


def publish_all_acceptance(fm, occ, di, oc, rate, verif=None, bo=None):
    items = acceptance(fm, occ, di)
    items.append({"id": "V2A-A3", "measured": f"{oc['points_outside']} of {oc['points_in_bone']:,} swept points outside the final stem ({oc['n']} designs)",
                  "status": "PASS" if oc["points_outside"] == 0 else "FAIL",
                  "note": "" if oc["points_outside"] == 0 else "插入路径越出最终柄体"})
    items.append({"id": "V2A-A4", "measured": f"max {100 * oc['cad_overlap_frac_max']:.2f}% (median {100 * oc['cad_overlap_frac_median']:.2f}%) of stem volume, {oc['n']} designs",
                  "status": "PASS" if oc["cad_overlap_frac_max"] <= 0.005 else "FAIL",
                  "note": "" if oc["cad_overlap_frac_max"] <= 0.005 else "CAD 中柄与皮质重叠超过 0.5%"})
    items.append({"id": "V2A-A8", "measured": f"{100 * rate:.1f}% of 8192", "status": "PASS" if rate >= 0.30 else "FAIL",
                  "note": "" if rate >= 0.30 else "可行率低于 30%"})
    for k in ("V2A-A5", "V2A-A6", "V2A-A7", "V2A-A9", "V2A-A10", "V2A-A11", "V2A-A12"):
        if not any(i["id"] == k for i in (verif or []) + (bo or [])):
            items.append({"id": k, "measured": "", "status": "PENDING", "note": ""})
    items += (verif or []) + (bo or [])
    order = [a["id"] for a in ps.load_spec()["reports"]["V2A"]["acceptance"]]
    items.sort(key=lambda a: order.index(a["id"]))
    ps.publish_acceptance("V2A", items)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", default="geometry", choices=["geometry", "verification", "bo", "interim", "all"])
    a = ap.parse_args()
    fm, occ, di, oc, rate = part_geometry()
    verif = bo = None
    if a.part in ("verification", "interim", "all"):
        import report_v2a_fe as RF
        verif = RF.part_verification(fm)
    if a.part in ("bo", "interim", "all"):
        import report_v2a_fe as RF
        bo = RF.part_bo(fm)
    if a.part == "interim":
        print(json.dumps(RF.part_bo_interim(), indent=1, default=float))
    publish_all_acceptance(fm, occ, di, oc, rate, verif, bo)
    print("published", a.part)
