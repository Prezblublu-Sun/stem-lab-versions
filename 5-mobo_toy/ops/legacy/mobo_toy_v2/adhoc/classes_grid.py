"""第一阶段九类的“类卡片”组图（Linux，只读）：3 × 3（行 = 柄长 短/中/长，列 = 领 无/窄/宽）。
每张卡片：放大的冠状面（截到近端），画椭圆例子的柄与领，标小转子水平线与柄尖相对小转子的高度；
右下内嵌该类三个候选（圆 / 椭圆 / 非对称）在 0.5 L 的截面，各标肩部面积。输出 adhoc/out/classes_grid.png。"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "adhoc"))
import front_shapes as FS  # noqa: E402
from front_shapes import CR, G, ps, plt  # noqa: E402
import collar_shapes as CS  # noqa: E402
import fe3d_geom as E  # noqa: E402

OUT = HOME / "adhoc" / "out"
COL = ps.DORR["A"]
COLLAR_C = "#D55E00"
LEN = {25.0: ("S", "short stem 25 mm"), 30.0: ("M", "medium stem 30 mm"), 35.0: ("L", "long stem 35 mm")}
COLLAR = {0.0: "no collar", 2.0: "narrow collar 2 mm", 4.0: "wide collar 4 mm"}
SEC = {"circ": "circular", "ell": "elliptical", "asym": "asymmetric"}
XLIM, YLIM = (-55.0, 40.0), (-112.0, 44.0)        # 下方留出一行给三个候选的截面          # 颈平面坐标，原点 = 截骨中心


def name_of(cls: str, L: float, w: float) -> str:
    return "neck_w0" if (cls, L, w) == ("ell", 30.0, 0.0) else f"neck_{cls}_L{L:g}_w{w:g}"


def main():
    ids = json.loads((HOME / "results" / "collar_ids.json").read_text())["jobs"]
    fig, axes = plt.subplots(3, 3, figsize=(ps.WIDTH_MM["double"] * ps.MM, 280 * ps.MM))
    img = None
    fm = None
    for r, L in enumerate(LEN):
        for c, w in enumerate(COLLAR):
            ax = axes[r, c]
            klass = f"{LEN[L][0]}{w:g}"
            tmpl = {}
            for cls in SEC:
                spec = FS.spec_of(ids[name_of(cls, L, w)])
                st, fm, pl = FS.template(spec)
                tmpl[cls] = (st, pl)
            if img is None:
                img = CR.neck_plane_image(fm)
            st, pl = tmpl["ell"]
            CR.draw_neck_plane(ax, fm, img, st, pl, COL, arrow=(r == 0 and c == 0))
            if st.has_collar:
                info = E.collar_outline(st, fm, pl)
                CS.hull_patch(ax, CR._plane_xy(fm, CS.collar_pts3(fm, info, st.collar_t)), COLLAR_C)
            # 小转子水平线（项目坐标 z = 0）与柄尖高度
            lt = CR._plane_xy(fm, np.vstack([np.array([0.0, 0.0, 0.0]) - 80 * fm.e_med0, np.array([0.0, 0.0, 0.0]) + 80 * fm.e_med0]))
            ax.plot(lt[:, 0], lt[:, 1], color="black", lw=0.5, ls=":")
            P0, d = pl["pose"][0], pl["pose"][1]
            tip = P0 + (st.L + st.cap_length(pl["A0"])) * d
            tq = CR._plane_xy(fm, tip)[0]
            ax.annotate(f"tip {tip[2]:+.0f} mm", xy=tuple(tq), xytext=(tq[0] - 22, tq[1] - 9), fontsize=5,
                        arrowprops=dict(arrowstyle="-", lw=0.4, color="black"))
            ax.text(0.02, 0.985, f"{klass}  {LEN[L][1]}, {COLLAR[w]}", transform=ax.transAxes, fontsize=6.2, va="top", weight="bold")
            if c == 0:
                ax.text(XLIM[0] + 1.5, lt[0, 1] + 1.5, "lesser trochanter level", fontsize=4.6, ha="left")
            ax.set_xlim(*XLIM); ax.set_ylim(*YLIM)
            ax.set_aspect("equal", adjustable="datalim")        # 填满格子，必要时放宽数据范围，而不是缩小坐标框
            # 内嵌：三个候选的 0.5 L 截面
            ax.text(0.02, 0.945, "drawn: the elliptical stem of this class", transform=ax.transAxes, fontsize=4.6, va="top", color="#1f5f8b")
            # 横排而不是竖排：竖排会被读成同一根柄在不同深度的截面（用户 12:20 的误读）
            ax.text(0.5, 0.245, "three candidate stems, one section shape each (mid-length)",
                    transform=ax.transAxes, fontsize=4.4, ha="center")
            for i, cls in enumerate(SEC):
                sti, pli = tmpl[cls]
                ins = ax.inset_axes([0.02 + 0.33 * i, 0.005, 0.30, 0.19])
                CR.draw_section(ins, fm, sti, pli, 0.5, COL, half=17.0)
                for t in list(ins.texts):
                    t.remove()
                ins.set_title(f"{SEC[cls]}\n{pli['A0']:.0f} mm²", fontsize=4.4, pad=1.0, linespacing=0.9)
    fig.suptitle("Stage 1 classes: rows = stem length, columns = collar. Coronal view of the elliptical candidate (blue), collar in orange, "
                 "tip height relative to the lesser trochanter.\nBottom row of each panel: the class's three candidate stems (circular, elliptical, "
                 "asymmetric), each with one section shape along its whole length, shown in section at mid-length with shoulder area", fontsize=6.2)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.955, bottom=0.005, wspace=0.03, hspace=0.07)
    fig.savefig(OUT / "classes_grid.png", dpi=220)
    plt.close(fig)
    print("ok", OUT / "classes_grid.png")


if __name__ == "__main__":
    main()
