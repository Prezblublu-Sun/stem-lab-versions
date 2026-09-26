"""2D 冠状面参数化股骨（Dorr A/B/C）。

坐标：x 指向内侧（股骨头一侧）为正，z 向上为正；原点在股骨干轴线上、小转子中点高度。单位 mm。

* 外轮廓三型相同：近端用参数样条（小转子、股骨距、颈下缘、大转子）+ 头部圆 + 直的干部，闭运算圆滑。
* 内轮廓（髓腔/松质骨边界）= 外轮廓按"变厚度"内偏移：皮质厚度场 t(x, z) 在峡部由皮质指数决定，
  在 CFI 高度由 CFI 决定（内外侧按比例分配），向上平滑过渡到颈部/头部/大转子的薄壳。
  变厚度偏移用距离变换 + 零等值线实现；CFI 高度的厚度迭代校准，使实测 CFI 命中预设值。
* Dorr 判据：CFI = 小转子上 20 mm 髓腔宽 / 峡部髓腔宽；皮质指数 CI = (外径 − 髓腔宽) / 外径，
  在小转子下 100 mm 测（本模型峡部即在此高度以下）。
* 髓腔全程填松质骨（简化：真实干部为髓腔脂肪，刚度可忽略；此处松质骨模量远小于皮质，影响小）。
"""
from __future__ import annotations

import functools
import math
from dataclasses import dataclass, field

import contourpy
import numpy as np
import shapely
import yaml
from scipy.interpolate import CubicSpline
from scipy.ndimage import distance_transform_edt
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

from plotstyle import ROOT

CFG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
FC = CFG["femur"]

# 近端外轮廓控制点（从内侧干部向上，绕过颈、头、大转子，回到外侧干部）
PROX_CTRL = [
    (13.5, -60.0), (14.5, -35.0), (18.5, -15.0), (24.0, -2.0), (25.5, 6.0), (27.5, 16.0),
    (34.0, 30.5), (42.0, 37.0), (50.0, 48.0), (48.0, 70.0), (26.0, 69.4), (13.0, 58.5),
    (3.0, 57.0), (-7.0, 65.0), (-19.0, 69.0), (-28.0, 60.0), (-31.0, 40.0), (-27.5, 15.0),
    (-19.5, -10.0), (-14.5, -35.0), (-13.5, -60.0),
]
GRID_H = 0.1   # mm，距离变换栅格


def _smoothstep(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3 - 2 * t)


@functools.lru_cache(maxsize=1)
def outer_contour() -> Polygon:
    """三型共用的外轮廓（含股骨头），远端截于 distal_z。"""
    W, zd = FC["shaft_outer_halfwidth"], FC["distal_z"]
    P = np.array(PROX_CTRL, dtype=float)
    P[0, 0], P[-1, 0] = W, -W
    s = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])
    cx = CubicSpline(s, P[:, 0], bc_type=((1, 0.0), (1, 0.0)))
    cz = CubicSpline(s, P[:, 1], bc_type=((1, 1.0), (1, -1.0)))
    ss = np.linspace(0, s[-1], int(s[-1] / 0.3))
    prox = np.c_[cx(ss), cz(ss)]
    ring = np.vstack([[W, zd], prox, [-W, zd]])
    poly = Polygon(ring).buffer(0)
    head = Point(FC["head_center"]).buffer(FC["head_radius"], quad_segs=64)
    shape = unary_union([poly, head]).buffer(2.0, quad_segs=16).buffer(-2.0, quad_segs=16)
    shape = shapely.simplify(shape, 0.01)
    return shape.intersection(box(-100, zd, 100, 200))


def neck_axis():
    """颈轴单位向量 u（从干部指向头心）与它和干部轴线的交点。"""
    a = math.radians(180.0 - FC["neck_shaft_angle_deg"])      # 与干部轴线（向上）的夹角
    u = np.array([math.sin(a), math.cos(a)])
    H = np.array(FC["head_center"], dtype=float)
    t = H[0] / u[0]
    return u, H - t * u


def chord(poly, z: float) -> tuple[float, float]:
    """水平线 z 与多边形的交线段的 (x_min, x_max)，取最长连通段。"""
    ln = LineString([(-200, z), (200, z)]).intersection(poly)
    segs = [g for g in getattr(ln, "geoms", [ln]) if g.length > 0]
    if not segs:
        return (math.nan, math.nan)
    g = max(segs, key=lambda g: g.length)
    xs = [c[0] for c in g.coords]
    return (min(xs), max(xs))


@dataclass
class Femur2D:
    dorr: str
    E_cancellous: float
    outer: Polygon
    inner: Polygon
    targets: dict
    measured: dict = field(default_factory=dict)

    @property
    def cortex(self):
        return self.outer.difference(self.inner)

    @property
    def cancellous(self):
        return self.inner

    # ---- 颈中段截骨
    @property
    def cut(self):
        """截骨线中心 C0、颈轴 u；保留侧为 (p − C0)·u ≤ 0。"""
        u, _ = neck_axis()
        H = np.array(FC["head_center"], dtype=float)
        C0 = H - FC["neck_cut_from_head"] * u
        return C0, u

    def kept_halfplane(self, extent: float = 400.0) -> Polygon:
        C0, u = self.cut
        n = np.array([-u[1], u[0]])
        a, b = C0 + extent * n, C0 - extent * n
        return Polygon([a, b, b - extent * u, a - extent * u])

    def cut_segment(self) -> LineString:
        """截骨线与外轮廓相交的那一段（颈部横截线）。"""
        C0, u = self.cut
        n = np.array([-u[1], u[0]])
        ln = LineString([C0 - 60 * n, C0 + 60 * n]).intersection(self.outer)
        segs = [g for g in getattr(ln, "geoms", [ln]) if g.length > 0]
        return min(segs, key=lambda g: g.distance(Point(C0)))

    def canal_halfwidth_at_cut(self) -> float:
        C0, u = self.cut
        n = np.array([-u[1], u[0]])
        ln = LineString([C0 - 60 * n, C0 + 60 * n]).intersection(self.inner)
        segs = [g for g in getattr(ln, "geoms", [ln]) if g.length > 0]
        g = min(segs, key=lambda g: g.distance(Point(C0)))
        return g.length / 2.0

    def zones(self) -> dict[str, Polygon]:
        """Gruen 7（内侧）与 Gruen 1（外侧）ROI：截骨线以下、z ≥ z_min 的骨。"""
        q = CFG["qoi"]
        kept = self.outer.intersection(self.kept_halfplane())
        z7 = kept.intersection(box(q["zone7"]["x_min"], q["zone7"]["z_min"], 200, 200))
        z1 = kept.intersection(box(-200, q["zone1"]["z_min"], q["zone1"]["x_max"], 200))
        return {"gruen7": z7, "gruen1": z1}


def _thickness_field(X, Z, targets, t20_total):
    """皮质厚度场 t(x, z)（mm）。"""
    W = FC["shaft_outer_halfwidth"]
    ci_t = W - targets["c_i"]                                   # 峡部两侧壁厚
    fm = FC["medial_wall_fraction"]
    t_med20, t_lat20 = fm * t20_total, (1 - fm) * t20_total
    z_i, z20 = FC["isthmus_top_z"], FC["cfi_level_z"]
    shell = FC["shell_thickness"]
    # 峡部 → CFI 高度
    s1 = _smoothstep((Z - z_i) / (z20 - z_i))
    t_med = ci_t + (t_med20 - ci_t) * s1
    t_lat = ci_t + (t_lat20 - ci_t) * s1
    # CFI 高度 → 颈部/大转子薄壳
    s2 = _smoothstep((Z - z20) / 25.0)
    t_med = t_med + (shell - t_med) * s2
    t_lat = t_lat + (shell - t_lat) * s2
    # 内外侧平滑分配（以该高度外轮廓中点为界）
    w_med = 1.0 / (1.0 + np.exp(-(X - targets["x_mid"](Z)) / 3.0))
    return w_med * t_med + (1 - w_med) * t_lat


@functools.lru_cache(maxsize=8)
def build(dorr: str, E_cancellous: float | None = None) -> Femur2D:
    D = CFG["dorr"][dorr]
    E_c = float(E_cancellous if E_cancellous is not None else D["E_cancellous"])
    W, zd = FC["shaft_outer_halfwidth"], FC["distal_z"]
    outer = outer_contour()
    c_i = W * (1 - D["ci"])                                     # 峡部髓腔半宽
    canal20_target = D["cfi"] * 2 * c_i
    ext = unary_union([outer, box(-W, zd - 60, W, zd + 1)])     # 向下延伸，避免远端截面影响距离场

    # 各高度外轮廓中点（用于内外侧分配），在 z 上插值
    zs = np.arange(zd - 60, 95, 1.0)
    mids = []
    for z in zs:
        a, b = chord(ext, z)
        mids.append(0.5 * (a + b) if not math.isnan(a) else 0.0)
    mids = np.array(mids)
    x_mid = lambda Z: np.interp(Z, zs, mids)                    # noqa: E731

    xg = np.arange(-45, 75, GRID_H)
    zg = np.arange(zd - 60, 92, GRID_H)
    X, Z = np.meshgrid(xg, zg)
    mask = shapely.contains_xy(ext, X, Z)
    dist = distance_transform_edt(mask) * GRID_H - 0.5 * GRID_H
    gen_x, gen_z = xg, zg

    ol, orr = chord(outer, FC["cfi_level_z"])
    t20 = (orr - ol) - canal20_target                           # 初值：水平壁厚总和
    targets = {"c_i": c_i, "x_mid": x_mid}
    inner = None
    for _ in range(8):
        phi = dist - _thickness_field(X, Z, targets, t20)
        lines = contourpy.contour_generator(gen_x, gen_z, phi).lines(0.0)
        ring = max(lines, key=len)
        inner = shapely.simplify(Polygon(ring).buffer(0), 0.02).intersection(outer)
        a, b = chord(inner, FC["cfi_level_z"])
        err = (b - a) - canal20_target
        if abs(err) < 0.02:
            break
        t20 += err
    fem = Femur2D(dorr=dorr, E_cancellous=E_c, outer=outer, inner=inner,
                  targets={"cfi": D["cfi"], "ci": D["ci"], "c_i": c_i, "canal20": canal20_target,
                           "t20_total": t20})
    fem.measured = measure(fem)
    return fem


def measure(f: Femur2D) -> dict:
    a, b = chord(f.inner, FC["cfi_level_z"])
    ci_a, ci_b = chord(f.inner, FC["ci_level_z"])
    oa, ob = chord(f.outer, FC["ci_level_z"])
    o20a, o20b = chord(f.outer, FC["cfi_level_z"])
    canal20, canal_i, outer_i = b - a, ci_b - ci_a, ob - oa
    # 皮质最薄处（采样外边界点到内轮廓的距离）
    pts = shapely.points(np.asarray(f.outer.exterior.coords))
    kept = [p for p in pts if p.y > FC["distal_z"] + 1.0]
    tmin = float(min(f.inner.exterior.distance(p) for p in kept))
    return {"cfi": canal20 / canal_i, "ci": (outer_i - canal_i) / outer_i, "canal20_mm": canal20,
            "canal_isthmus_mm": canal_i, "outer_isthmus_mm": outer_i, "outer20_mm": o20b - o20a,
            "wall20_medial_mm": o20b - b, "wall20_lateral_mm": a - o20a, "min_cortex_mm": tmin,
            "canal_halfwidth_at_cut_mm": f.canal_halfwidth_at_cut()}


def dorr_band(kind: str, value: float) -> str:
    if kind == "cfi":
        return "A" if value >= 4.7 else ("B" if value >= 3.0 else "C")
    return "A" if value >= 0.58 else ("B" if value >= 0.49 else "C")
