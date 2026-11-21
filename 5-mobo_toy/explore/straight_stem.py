"""探索：直柄 + 直线插入 + 内外侧不对称轮廓；柄在自身坐标系中定义（绝对尺寸，不依股骨），
再按"模板化"规则放进每个股骨。只做几何与图示，不跑 FE。

柄（局部坐标：中轴为直线，s 从肩部 0 到尖端 L；n 指向内侧）
    内侧半宽 w_m(s) = w_tip + (w_mp − w_tip)·(1 − s/L)^p_m
    外侧半宽 w_l(s) = w_tip + (w_lp − w_tip)·(1 − s/L)^p_l
    两侧都随 s 单调不增 ⇒ 沿中轴平移插入的扫掠区 = 柄本身（零过切）；尖端为半径 w_tip 的圆帽。
    p_m > 1：内侧近端迅速收窄（股骨距弧形）；p < 1：保持较宽、近尖端才收。

模板化放置（对每个柄、每个股骨）
    入口：肩部中心在截骨线上，偏离截骨中心 e（−10…+10 mm，沿截骨线，+ 向内侧）；方向与股骨干轴成 α（0–50°，+ 向外侧倾）。
    沿方向推进：下沉深度 z 从 0（肩部在截骨线）增大，取皮质相交面积 ≤ 0.5 mm² 的最大 z（楔紧位置）。
    在 α、e 网格上取"贴合度"最高者；贴合度 = 柄骨内侧缘中距内骨膜 ≤ 1 mm 的长度占比。
    拒绝：任何 α、e 下肩部都进不去（太大）；下沉 > 12 mm（太小）；尖端出骨或低于小转子下 130 mm。
"""
from __future__ import annotations

import math
import pathlib
import sys
from dataclasses import dataclass

import numpy as np
import shapely
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import femur2d as F  # noqa: E402

RANGES = {                     # 目录的设计变量（绝对尺寸）
    "L": (40.0, 90.0),         # mm，肩部到尖端（经颈中段截骨直线进入，只能是短柄；用户要求再缩短）
    "w_mp": (6.0, 15.0),       # mm，内侧近端半宽
    "w_lp": (4.0, 11.0),       # mm，外侧近端半宽
    "w_tip": (2.5, 5.5),       # mm，尖端半宽
    "p_m": (0.5, 3.0),         # 内侧轮廓指数
    "p_l": (0.5, 2.0),         # 外侧轮廓指数
}
VARS = list(RANGES)
TOL_CORTEX = 0.5               # mm²
MAX_SINK = 12.0                # mm
S_TOP = -20.0                  # mm，柄体向肩部以上延伸（下沉时仍越过截骨线，不在颈部留通道）
FILL_BAND = 1.0                # mm
REASON_TEXT = {
    "too small": f"too small (sinks > {MAX_SINK:.0f} mm without wedging)",
    "tip out of bone": "tip exits the bone",
    "blocked": "blocked at entry:\nhits cortex at every angle/offset",
}


def from_unit(u):
    return {k: RANGES[k][0] + float(x) * (RANGES[k][1] - RANGES[k][0]) for k, x in zip(VARS, u)}


@dataclass
class StraightStem:
    L: float
    w_mp: float
    w_lp: float
    w_tip: float
    p_m: float
    p_l: float

    def widths(self, s):
        s = np.clip(np.asarray(s, float), 0, self.L)
        x = 1 - s / self.L
        wm = self.w_tip + (max(self.w_mp, self.w_tip) - self.w_tip) * x ** self.p_m
        wl = self.w_tip + (max(self.w_lp, self.w_tip) - self.w_tip) * x ** self.p_l
        return wm, wl

    def local_polygon(self, s_top: float = S_TOP, n: int = 120) -> Polygon:
        """局部坐标：x = 横向（+ 内侧），y = 沿中轴向下为负（肩部 y = 0，尖端 y = −L）。"""
        s = np.linspace(s_top, self.L, n)
        wm, wl = self.widths(np.maximum(s, 0))
        med = np.c_[wm, -s]
        lat = np.c_[-wl, -s]
        ang = np.linspace(0, -math.pi, 25)
        cap = np.c_[self.w_tip * np.cos(ang), -self.L + self.w_tip * np.sin(ang)]
        ring = np.vstack([med, cap[1:-1], lat[::-1]])
        return Polygon(ring).buffer(0)

    def placed(self, P0, alpha_deg, z, s_top=S_TOP) -> Polygon:
        """放进股骨坐标：肩部中心 P0 沿方向 d 再下沉 z；d 与向下的干轴成 alpha（+ 向外侧 = −x）。"""
        a = math.radians(alpha_deg)
        d = np.array([-math.sin(a), -math.cos(a)])            # 插入方向（向下）
        nmed = np.array([-d[1], d[0]])                        # 与 d 垂直
        if nmed[0] < 0:
            nmed = -nmed                                      # 让 +n 指向内侧（+x）
        loc = np.asarray(self.local_polygon(s_top).exterior.coords)
        P = np.asarray(P0) + z * d
        xy = P + loc[:, :1] * nmed + (-loc[:, 1:2]) * d
        return Polygon(xy).buffer(0)


def seat(stem: StraightStem, f: F.Femur2D, alphas=np.arange(0.0, 50.1, 2.5), offsets=np.arange(-10.0, 10.1, 2.5)):
    """模板化：返回最佳放置 {alpha, e, z, fill, poly, ...} 或拒绝原因。"""
    C0, u = f.cut
    ncut = np.array([-u[1], u[0]])
    if ncut[0] < 0:
        ncut = -ncut
    kept = f.outer.intersection(f.kept_halfplane())
    cortex = f.cortex
    shapely.prepare(cortex)
    endo = f.inner.exterior
    best, reasons = None, []
    for e in offsets:
        P0 = C0 + e * ncut
        for a in alphas:
            def ov(z):
                p = stem.placed(P0, a, z).intersection(kept)
                return p.intersection(cortex).area
            if ov(0.0) > TOL_CORTEX:
                reasons.append("blocked")
                continue
            lo, hi = 0.0, MAX_SINK
            if ov(hi) <= TOL_CORTEX:
                reasons.append("too small")
                continue
            for _ in range(10):
                mid = 0.5 * (lo + hi)
                (lo, hi) = (mid, hi) if ov(mid) <= TOL_CORTEX else (lo, mid)
            z = lo
            poly = stem.placed(P0, a, z)
            inb = poly.intersection(kept)
            a_rad = math.radians(a)
            d = np.array([-math.sin(a_rad), -math.cos(a_rad)])
            tip = np.asarray(P0) + (z + stem.L) * d
            if not f.outer.contains(Point(tip)) or tip[1] < -130:
                reasons.append("tip out of bone")
                continue
            flank = inb.exterior.difference(kept.exterior.buffer(0.05))
            near = flank.intersection(endo.buffer(FILL_BAND))
            fill = near.length / max(flank.length, 1e-9)
            cand = {"alpha": float(a), "e": float(e), "z": float(z), "fill": float(fill), "poly": poly,
                    "tip": tip, "d": d, "P0": P0}
            if best is None or fill > best["fill"] + 1e-9 or (abs(fill - best["fill"]) < 1e-9 and z < best["z"]):
                best = cand
    if best is None:
        # 原因按"进得去之后失败"优先：只要有位姿能进入，就报它为何不合格，而不是报最常见的"进不去"
        for r in ("too small", "tip out of bone", "blocked"):
            if r in reasons:
                return {"fit": False, "reason": REASON_TEXT[r], "code": r}
        return {"fit": False, "reason": "no placement", "code": "none"}
    best["fit"] = True
    return best


def translation_overcut(stem: StraightStem, f: F.Femur2D, pl: dict) -> float:
    """数值复核：沿插入方向平移扫掠 ∩ 保留骨 − 最终柄体 的面积。"""
    kept = f.outer.intersection(f.kept_halfplane())
    parts = [stem.placed(pl["P0"], pl["alpha"], z) for z in np.linspace(-stem.L - 20, pl["z"], 200)]
    swept = unary_union(parts).intersection(kept)
    return swept.difference(pl["poly"].intersection(kept)).area
