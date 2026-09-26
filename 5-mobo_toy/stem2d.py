"""保颈、斜向（圆弧中轴）插入的 2D 短柄，及其几何门（CLAUDE.md §10 的 L1/L2）。

几何
----
* 颈中段截骨，截骨线垂直颈轴，中心 C0。柄体中轴是圆弧：起点 C0，初始方向 d0 = 颈轴反向（指向外下）
  再转 theta_in（+ 向远端）。设计变量用尖端位置定义圆弧：尖端在小转子下 tip_depth 处、
  在该高度髓腔宽度内的相对位置 tip_lat（0 贴内侧壁，1 贴外侧壁，按尖端半宽留出贴壁余量）。
  过 C0、在 C0 与 d0 相切、终于尖端点的圆弧唯一，由此导出曲率 kappa（正 = 向内侧弯）与弧长 L。
* 柄体 = {p(s) + v·n(s) : s ∈ [s_min, L], |v| ≤ w(s)} ∪ 尖端半圆帽。w(s) 在 s ≤ 0 为 w_p，
  0 → L 线性收窄到 w_t = taper·w_p。s_min < 0 让柄体上端完全越过截骨线，
  所以骨内部分的上边界恰是截骨线。
* 零过切：中轴为圆弧、截面沿插入方向单调不增时，绕曲率中心的旋转插入（直柄为平移）扫过的
  骨内区域恰等于柄体本身（sweep_viz/curved.py 的单参数子群结论）。`sweep_overcut` 用离散位姿
  数值复核这一点（R1-F03）。
* 假体颈（C0 → 头心的条带）与假体头（头心圆盘）只在截骨线以上，用于传载，不与骨接触。
* 锉刀腔 = 柄体按过盈量 δ 内缩（半宽 w − δ）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import shapely
import shapely.affinity
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

import femur2d as F

CFG = F.CFG
DS = CFG["design_space"]
VARS = list(DS.keys())                       # ["tip_depth", "tip_lat", "w_prox", "taper", "theta_in"]


def to_physical(u: np.ndarray) -> dict:
    """[0,1]^5 → 物理设计变量。"""
    u = np.asarray(u, dtype=float)
    return {k: DS[k]["lo"] + float(u[i]) * (DS[k]["hi"] - DS[k]["lo"]) for i, k in enumerate(VARS)}


def to_unit(d: dict) -> np.ndarray:
    return np.array([(d[k] - DS[k]["lo"]) / (DS[k]["hi"] - DS[k]["lo"]) for k in VARS])


@dataclass
class Stem2D:
    femur: F.Femur2D
    tip_depth: float
    tip_lat: float
    w_prox: float
    taper: float
    theta_in: float
    ds: float = 0.5                                   # 中轴采样步长 mm
    cache: dict = field(default_factory=dict, repr=False)
    L: float = field(init=False)
    kappa: float = field(init=False)
    tip_ok: bool = field(init=False)

    def __post_init__(self):
        """由尖端位置解圆弧：chord c = T − C0，α = d0 到 c 的有向角；κ = 2 sin α / |c|，L = |c| α / sin α。"""
        z = -self.tip_depth
        a, b = F.chord(self.femur.inner, z)
        w_t = self.w_t
        lo, hi = b - w_t, a + w_t                     # 尖端中心可放的区间（内侧壁 b，外侧壁 a）
        self.tip_ok = bool(hi < lo)
        x = lo + self.tip_lat * (hi - lo) if self.tip_ok else 0.5 * (a + b)
        self.tip = np.array([x, z])
        c = self.tip - self.C0
        ell = float(np.linalg.norm(c))
        d = self.d0
        alpha = math.atan2(d[0] * c[1] - d[1] * c[0], d[0] * c[0] + d[1] * c[1])
        if abs(alpha) < 1e-9:
            self.kappa, self.L = 0.0, ell
        else:
            self.kappa = 2.0 * math.sin(alpha) / ell
            self.L = ell * alpha / math.sin(alpha)

    # ---------------------------------------------------------------- 中轴
    @property
    def C0(self):
        return self.femur.cut[0]

    @property
    def d0(self) -> np.ndarray:
        _, u = self.femur.cut
        a = math.atan2(-u[1], -u[0]) + math.radians(self.theta_in)
        return np.array([math.cos(a), math.sin(a)])

    @property
    def n0(self) -> np.ndarray:                       # 左法向（逆时针转 90°）：柄向这一侧弯
        d = self.d0
        return np.array([-d[1], d[0]])

    @property
    def w_p(self) -> float:
        return self.w_prox * self.femur.measured["canal_halfwidth_at_cut_mm"]

    @property
    def w_t(self) -> float:
        return self.taper * self.w_p

    @property
    def s_min(self) -> float:
        return -(self.w_p * math.tan(math.radians(abs(self.theta_in))) + 3.0)

    @property
    def center(self):
        """曲率中心；直柄返回 None。"""
        if abs(self.kappa) <= 1e-9:
            return None
        return self.C0 + self.n0 / self.kappa

    def axis(self, s: np.ndarray):
        s = np.asarray(s, dtype=float)
        k = self.kappa
        d, n = self.d0, self.n0
        if abs(k) <= 1e-9:
            p = self.C0 + s[:, None] * d
            t = np.repeat(d[None], len(s), 0)
        else:
            p = self.C0 + (np.sin(k * s) / k)[:, None] * d + ((1 - np.cos(k * s)) / k)[:, None] * n
            t = np.cos(k * s)[:, None] * d + np.sin(k * s)[:, None] * n
        nrm = np.c_[-t[:, 1], t[:, 0]]
        return p, t, nrm

    def halfwidth(self, s: np.ndarray, delta: float = 0.0) -> np.ndarray:
        s = np.asarray(s, dtype=float)
        frac = np.clip(s / self.L, 0.0, 1.0)
        return self.w_p - (self.w_p - self.w_t) * frac - delta

    # ---------------------------------------------------------------- 多边形
    def body(self, delta: float = 0.0) -> Polygon:
        key = ("body", round(delta, 6))
        if key in self.cache:
            return self.cache[key]
        n = max(20, int((self.L - self.s_min) / self.ds))
        s = np.linspace(self.s_min, self.L, n + 1)
        p, t, nrm = self.axis(s)
        w = self.halfwidth(s, delta)
        left = p + w[:, None] * nrm
        right = p - w[:, None] * nrm
        # 尖端半圆帽：从左侧绕到右侧，经过切向前方
        a_l = math.atan2(nrm[-1, 1], nrm[-1, 0])
        ang = a_l - np.linspace(0, math.pi, 24)
        cap = p[-1] + w[-1] * np.c_[np.cos(ang), np.sin(ang)]
        ring = np.vstack([left, cap[1:-1], right[::-1]])
        poly = Polygon(ring).buffer(0)
        self.cache[key] = poly
        return poly

    def neck(self) -> Polygon:
        """假体颈 + 假体头 + 肩部（只在截骨线以上）。"""
        sc = CFG["stem"]
        C0, u = self.femur.cut
        H = np.array(CFG["femur"]["head_center"], dtype=float)
        nu = np.array([-u[1], u[0]])
        hw = sc["neck_halfwidth"]
        bar = Polygon([C0 + hw * nu, H + hw * nu, H - hw * nu, C0 - hw * nu])
        head = Point(H).buffer(sc["head_radius"], quad_segs=32)
        p, _, nrm = self.axis(np.array([self.s_min]))
        top = [p[0] + self.w_p * nrm[0], p[0] - self.w_p * nrm[0]]
        shoulder = shapely.convex_hull(shapely.multipoints(np.array(top + [C0 + hw * nu, C0 - hw * nu,
                                                                           C0 + 6 * u + hw * nu, C0 + 6 * u - hw * nu])))
        return unary_union([bar, head, shoulder]).difference(self.femur.kept_halfplane())

    def full(self) -> Polygon:
        return unary_union([self.body(), self.neck()]).buffer(0)

    def in_bone(self, delta: float = 0.0):
        """柄体在保留侧（截骨线以下）且在外轮廓内的部分。"""
        return self.body(delta).intersection(self.femur.kept_halfplane()).intersection(self.femur.outer)

    # ---------------------------------------------------------------- 插入扫掠（数值复核）
    def insertion_poses(self, travel: float | None = None, step: float = 0.25):
        """从完全在骨外到最终位姿的一串刚体位姿（绕曲率中心旋转；直柄为平移）。"""
        travel = travel or (self.L - self.s_min + 10.0)
        n = int(math.ceil(travel / step))
        taus = np.linspace(0.0, travel, n + 1)
        c = self.center
        out = []
        for tau in taus:
            if c is None:
                out.append(("translate", -tau * self.d0))
            else:
                out.append(("rotate", -tau * self.kappa, c))
        return out

    def sweep_overcut(self, step: float = 0.25) -> dict:
        """扫掠并集 ∩ 保留骨 − 最终柄体 的面积（mm²）；及扫掠与皮质相交面积。"""
        body = self.body()
        kept = self.femur.outer.intersection(self.femur.kept_halfplane())
        polys = []
        for pose in self.insertion_poses(step=step):
            if pose[0] == "translate":
                polys.append(shapely.affinity.translate(body, *pose[1]))
            else:
                polys.append(shapely.affinity.rotate(body, pose[1], origin=tuple(pose[2]), use_radians=True))
        swept = unary_union(polys).intersection(kept)
        final = body.intersection(kept)
        over = swept.difference(final)
        return {"swept_area": swept.area, "final_area": final.area, "overcut_area": over.area,
                "overcut_frac": over.area / max(final.area, 1e-9),
                "swept_cortex": swept.intersection(self.femur.cortex).area}


def gate(stem: Stem2D) -> dict:
    """几何门。返回 {"pass": bool, "level": "OK"/"L1"/"L2", "reason": str, 指标…}。"""
    g = CFG["gate"]
    f = stem.femur
    out = {"pass": False, "level": "L2", "reason": ""}
    # L1：参数层
    for k in VARS:
        v = getattr(stem, k)
        if not (DS[k]["lo"] - 1e-9 <= v <= DS[k]["hi"] + 1e-9):
            out.update(level="L1", reason=f"{k} out of range")
            return out
    out["kappa"], out["L"] = float(stem.kappa), float(stem.L)
    if not stem.tip_ok:
        out.update(level="L1", reason="tip wider than canal")
        return out
    if abs(stem.kappa) > 0 and 1.0 / abs(stem.kappa) <= stem.w_p + 1.0:
        out.update(level="L1", reason="curvature radius < half-width")
        return out
    H = np.array(CFG["femur"]["head_center"], dtype=float)
    neck_len = float(np.linalg.norm(H - stem.C0))
    out["neck_length"] = neck_len
    if not (g["neck_length"][0] - 1e-6 <= neck_len <= g["neck_length"][1] + 1e-6):
        out.update(level="L1", reason="neck length")
        return out
    # L2：几何层
    body = stem.body()
    if not body.is_valid or body.geom_type != "Polygon":
        out.update(reason="self-intersecting body")
        return out
    inb = stem.in_bone()
    out["overlap_cortex"] = float(inb.intersection(f.cortex).area)
    tip = stem.axis(np.array([stem.L]))[0][0]
    out["tip_x"], out["tip_z"] = float(tip[0]), float(tip[1])
    # 剩余皮质壁厚：骨内柄体到外轮廓（截骨线以下 0.5 mm 起算，截骨面本身不算）的最小距离
    C0, u = f.cut
    below = shapely.affinity.translate(f.kept_halfplane(), *(-0.5 * u))
    out["wall"] = float(inb.distance(f.outer.exterior.intersection(below))) if not inb.is_empty else 0.0
    out["area_in_bone"] = float(inb.area)
    if not f.outer.contains(Point(tip)):
        out["reason"] = "tip outside bone"
    elif not f.inner.buffer(0.5).contains(Point(tip)):
        out["reason"] = "tip perforates cortex"
    elif out["overlap_cortex"] > g["max_cortex_overlap"]:
        out["reason"] = "cuts cortex"
    elif out["wall"] < g["min_wall"]:
        out["reason"] = "wall too thin"
    elif tip[1] < CFG["femur"]["distal_z"] + 20:
        out["reason"] = "too long"
    else:
        out.update({"pass": True, "level": "OK", "reason": ""})
    return out


def make(dorr: str, design: dict, E_cancellous: float | None = None) -> Stem2D:
    return Stem2D(femur=F.build(dorr, E_cancellous), **{k: float(design[k]) for k in VARS})
