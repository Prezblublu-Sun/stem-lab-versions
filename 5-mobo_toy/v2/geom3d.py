"""v2 几何：直轴短柄（截面积沿长度递减 + 不规则不对称截面）与理想化 3D 股骨髓腔的解析模型、模板化放置。

柄（局部坐标：s 沿中轴向远端，s = 0 为肩部；x 内侧 +，y 前方 +）
    截面积     A(s) = A0 · r(s),  r(s) = ρ_tip + (1 − ρ_tip)(1 − s/L)^q   （s ∈ [0, L]；s < 0 为等截面棱柱，被截骨面裁掉）
               ρ_tip = 尖端/肩部面积比（降低幅度）；q = 降低曲线形状（q > 1 近端先快速收小，q < 1 保持粗壮到远端才收）
    截面形状   单位面积的"四象限超椭圆 + 楔形"：内/外侧半宽 a_m, a_l，前/后半厚 b_a, b_p；
               前半与后半各有自己的超椭圆指数（n_a, n_p）与楔形斜度（τ_a, τ_p：该半的厚度随内外侧线性变化 1 + τ·x̂），
               所以截面既不关于内外侧中线对称，也不关于前后侧中线（y = 0）对称（只有 γ_ap = 0.5、n_a = n_p、τ_a = τ_p 的
               特例才前后镜像）。7 个无量纲量：λ = (a_m + a_l)/(b_a + b_p)，γ_ml = a_m/(a_m + a_l)，γ_ap = b_a/(b_a + b_p)，
               n_a, n_p, τ_a, τ_p
    截面形状沿长度不变、只按 √r(s) 缩放 ⇒ 各截面嵌套 ⇒ 沿中轴直线平移插入的扫掠体 = 柄本身（零过切）。
    尖端：截面沿半椭球收拢，帽长 = 0.5·√A_tip。
插入角 α（冠状面内柄轴与股骨干轴的夹角，+ = 远端偏外侧）是设计变量；头心复位时它等价于假体颈干角 130° + α。
尺寸 A0 与入口偏移 e 由模板化给出（"能放进去的最大号"）：肩部中心在截骨面上、偏离截骨中心 e；
对每个 e 二分求皮质穿透 ≤ TOL 的最大 A0，取 A0 最大者。

股骨：外形与髓腔都是沿"干—颈中心线"（干轴 → R 50 mm 圆弧 → 颈轴）放样的管，截面垂直于中心线，内外侧边界取 2D 轮廓
（v1 的"水平截面 + 颈部圆柱"拼接在截骨处有台阶，v2 改掉）；v2 新增干骺端前后不对称（后半深、前半浅，皮质厚度不变，
系数 kappa_ap，z ≥ 0 满额、z ≤ −40 为零），用来检验不对称截面是否会被优化器利用；kappa_ap = 0 为对照。
"""
from __future__ import annotations

import math
import pathlib
import sys
from dataclasses import dataclass

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import femur2d as F  # noqa: E402

CFG = F.CFG
ALPHA_LO, ALPHA_HI = 5.0, 40.0     # °，插入角范围：固定角扫描中 0–5° 几乎放不进（C 型 0%），> 40° 接近颈轴方向
DESIGN = {                      # 11 个设计变量
    "L": (40.0, 90.0),          # mm，肩部到尖端
    "rho_tip": (0.10, 0.50),    # 尖端/肩部截面积比
    "q": (0.5, 3.0),            # 面积降低曲线指数
    "lam": (1.0, 2.2),          # 截面宽厚比（内外侧宽 / 前后厚）
    "g_ml": (0.35, 0.65),       # 内侧占内外侧宽的比例
    "g_ap": (0.35, 0.65),       # 前方占前后厚的比例
    "n_a": (2.0, 6.0),          # 前半超椭圆指数（2 圆润 → 6 方正）
    "n_p": (2.0, 6.0),          # 后半超椭圆指数
    "tau_a": (-0.30, 0.30),     # 前半楔形：前半厚度随内外侧变化，+ = 内侧厚
    "tau_p": (-0.30, 0.30),     # 后半楔形
    "alpha": (ALPHA_LO, ALPHA_HI),  # °，插入角（冠状面内与干轴夹角）
}
VARS = list(DESIGN)
SHAPE_VARS = ["lam", "g_ml", "g_ap", "n_a", "n_p", "tau_a", "tau_p"]
GROUPS = {"length": ["L"], "area curve": ["rho_tip", "q"], "section shape": SHAPE_VARS, "insertion angle": ["alpha"]}
LABEL = {"L": "length L (mm)", "rho_tip": "tip/shoulder area ρ_tip", "q": "area-curve exponent q",
         "lam": "aspect ML/AP λ", "g_ml": "medial share γ_ml", "g_ap": "anterior share γ_ap",
         "n_a": "anterior squareness n_a", "n_p": "posterior squareness n_p",
         "tau_a": "anterior keystone τ_a", "tau_p": "posterior keystone τ_p", "alpha": "insertion angle α (°)"}
TOL = 0.25                      # mm，允许的皮质穿透（模板化；压配另由 δ 给）
A_BOUNDS = (20.0, 900.0)        # mm²，肩部面积二分区间
S_TOP = -60.0                   # mm，肩部以上等截面棱柱的长度（只在截骨面以下的部分算数）
MIN_TIP_AREA = 12.0             # mm²，尖端最小面积（≈ Ø 3.9 mm），小于此判"太细"


def from_unit(u) -> dict:
    return {k: DESIGN[k][0] + float(x) * (DESIGN[k][1] - DESIGN[k][0]) for k, x in zip(VARS, u)}


def to_unit(d: dict) -> np.ndarray:
    return np.array([(d[k] - DESIGN[k][0]) / (DESIGN[k][1] - DESIGN[k][0]) for k in VARS])


def _smoothstep(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3 - 2 * t)


# ----------------------------------------------------------------------------------------------- 柄
def unit_section(d: dict, m: int = 96) -> np.ndarray:
    """单位面积截面边界点 (m, 2)：列 0 = x（+ 内侧），列 1 = y（+ 前方），逆时针，不闭合。"""
    lam, gm, ga = d["lam"], d["g_ml"], d["g_ap"]
    a_m, a_l = lam * gm, lam * (1 - gm)
    b_a, b_p = ga, 1 - ga
    t = np.linspace(0, 2 * np.pi, m, endpoint=False)
    c, s = np.cos(t), np.sin(t)
    ant = s >= 0                                         # 前半（y ≥ 0）与后半各用自己的指数与楔形
    n = np.where(ant, d["n_a"], d["n_p"])
    tau = np.where(ant, d["tau_a"], d["tau_p"])
    u = np.sign(c) * np.abs(c) ** (2 / n)                # 在 y = 0 处两半都取 u = ±1，边界连续
    v = np.sign(s) * np.abs(s) ** (2 / n)
    x = np.where(u >= 0, u * a_m, u * a_l)
    xh = u                                               # x̂ ∈ [−1, 1]：外侧 −1 → 内侧 +1
    y = np.where(ant, v * b_a, v * b_p) * (1 + tau * xh)
    xy = np.c_[x, y]
    area = 0.5 * abs(np.dot(xy[:, 0], np.roll(xy[:, 1], -1)) - np.dot(xy[:, 1], np.roll(xy[:, 0], -1)))
    return xy / math.sqrt(area)


@dataclass
class Stem3D:
    L: float
    rho_tip: float
    q: float
    lam: float
    g_ml: float
    g_ap: float
    n_a: float
    n_p: float
    tau_a: float
    tau_p: float
    alpha: float = 20.0

    @property
    def d(self) -> dict:
        return {k: getattr(self, k) for k in VARS}

    def area_ratio(self, s):
        s = np.asarray(s, float)
        x = np.clip(1 - s / self.L, 0, 1)
        r = self.rho_tip + (1 - self.rho_tip) * x ** self.q
        return np.where(s <= 0, 1.0, r)

    def cap_length(self, A0: float) -> float:
        return 0.5 * math.sqrt(A0 * self.rho_tip)

    def local_surface(self, A0: float, s_top: float = S_TOP, ns: int = 70, m: int = 64, ncap: int = 6):
        """表面采样点（局部坐标 s, x, y），返回 (N, 3)。"""
        sec = unit_section(self.d, m)
        s = np.r_[np.linspace(s_top, 0, 8, endpoint=False), np.linspace(0, self.L, ns)]
        k = np.sqrt(A0 * self.area_ratio(s))
        pts = [np.c_[np.full(m, si), ki * sec] for si, ki in zip(s, k)]
        c = self.cap_length(A0)
        kt = math.sqrt(A0 * self.rho_tip)
        for t in np.linspace(0, 1, ncap + 1)[1:]:
            f = math.sqrt(max(1 - t * t, 0.0))
            pts.append(np.c_[np.full(m, self.L + c * t), f * kt * sec] if f > 0 else np.array([[self.L + c, 0.0, 0.0]]))
        return np.vstack(pts)

    def volume(self, A0: float) -> float:
        s = np.linspace(0, self.L, 400)
        return float(np.trapezoid(A0 * self.area_ratio(s), s)) + (2 / 3) * A0 * self.rho_tip * self.cap_length(A0)


# ----------------------------------------------------------------------------------------------- 股骨
def depth_ratio(z):
    return np.interp(z, [-40.0, 30.0], [1.0, 0.72])


class Femur3D:
    """解析的 3D 股骨：外形与髓腔都是沿"干—颈中心线"放样的管，截面垂直于中心线。

    中心线（冠状面内）：干轴 x = 0 从 z = −150 向上 → 半径 R_BEND 的圆弧 → 颈轴直到头心。
    每个站位的截面：内外侧边界 = 该站位法线与 2D 外/内轮廓的交线段（y = 0 切片与 2D 模型一致），
    前后半厚 = depth_ratio(z)·外半宽，髓腔前后半厚 = 外前后半厚 − 平均内外侧壁厚；
    干骺端前后不对称：髓腔后半厚 × (1 + w)、前半厚 × (1 − w)，w = kappa_ap·smoothstep((z + 40)/40)，壁厚不变。
    大转子与股骨头另用椭球/球并入（与 v1 相同）。点的"外溢距离"= 在所属截面内沿射线到边界的距离（在内为 0）。
    FE 网格用同一张站位表放样（gmsh ThruSections），保证模板化与 FE 几何一致。
    """
    R_BEND = 50.0

    def __init__(self, dorr: str, kappa_ap: float = 0.15, ds: float = 2.0):
        self.dorr, self.kappa_ap = dorr, kappa_ap
        f = F.build(dorr)
        self.f2d = f
        u, Pn = F.neck_axis()                                   # 颈轴方向、颈轴与干轴交点 (0, z_n)
        H = np.array(CFG["femur"]["head_center"], float)
        th = math.acos(float(np.clip(u[1], -1, 1)))             # 干轴(+z) 与颈轴夹角
        tl = self.R_BEND * math.tan(th / 2)
        T1 = Pn - tl * np.array([0.0, 1.0])                     # 干轴上的切点
        T2 = Pn + tl * u                                        # 颈轴上的切点
        self.center = np.array([T1[0] + self.R_BEND, T1[1]])    # 曲率中心在内侧
        self.phi1 = math.pi                                     # T1 相对中心的极角
        self.phi2 = math.atan2(T2[1] - self.center[1], T2[0] - self.center[0])
        self.z_bot, self.T1, self.T2, self.u2, self.H = CFG["femur"]["distal_z"], T1, T2, u, H
        self.L1 = T1[1] - self.z_bot
        self.L2 = self.R_BEND * (self.phi1 - self.phi2)
        self.L3 = float(np.linalg.norm(H - T2))
        self.sig_max = self.L1 + self.L2 + self.L3
        sig = np.unique(np.r_[np.arange(0, self.sig_max, ds), self.sig_max])
        rows = []
        for sg in sig:
            C, t, n = self.frame2d(np.array([sg]))
            C, n = C[0], n[0]
            lo_o, hi_o = self._chord(f.outer, C, n)
            lo_i, hi_i = self._chord(f.inner, C, n)
            a, xc = (hi_o - lo_o) / 2, (hi_o + lo_o) / 2
            ai, xci = (hi_i - lo_i) / 2, (hi_i + lo_i) / 2
            b = float(depth_ratio(C[1])) * a
            bi = max(2.0, b - (a - ai))
            t_ap = b - bi
            w = float(_smoothstep((C[1] + 40.0) / 40.0)) * kappa_ap
            bi_a, bi_p = bi * (1 - w), bi * (1 + w)
            rows.append([sg, xc, a, bi_a + t_ap, bi_p + t_ap, xci, ai, bi_a, bi_p])
        self.T = np.array(rows)       # 列：σ, 外 ξc, 外 a, 外前, 外后, 腔 ξc, 腔 a, 腔前, 腔后（ξ 沿截面法线，+ 内侧）
        self.u3 = np.array([u[0], 0.0, u[1]])
        self.n3 = np.array([u[1], 0.0, -u[0]])                  # 截骨面内、指向内下方……取 x 分量为正
        if self.n3[0] < 0:
            self.n3 = -self.n3
        C0, _ = f.cut
        self.C03 = np.array([C0[0], 0.0, C0[1]])
        self.gt_c, self.gt_ax = np.array([-18.0, 0.0, 52.0]), np.array([13.0, 14.0, 17.0])
        self.Rh = CFG["femur"]["head_radius"]

    # --- 中心线
    def frame2d(self, sig):
        """σ → 中心线点 C (x, z)、切向 t、法向 n（n 指向内侧 +x 一侧）。"""
        sig = np.asarray(sig, float)
        C = np.zeros((len(sig), 2)); t = np.zeros_like(C)
        m1 = sig <= self.L1
        m3 = sig >= self.L1 + self.L2
        m2 = ~m1 & ~m3
        C[m1] = np.c_[np.zeros(m1.sum()), self.z_bot + sig[m1]]; t[m1] = [0.0, 1.0]
        ph = self.phi1 - (sig[m2] - self.L1) / self.R_BEND
        C[m2] = self.center + self.R_BEND * np.c_[np.cos(ph), np.sin(ph)]
        t[m2] = np.c_[np.sin(ph), -np.cos(ph)]
        C[m3] = self.T2 + (sig[m3] - self.L1 - self.L2)[:, None] * self.u2; t[m3] = self.u2
        n = np.c_[t[:, 1], -t[:, 0]]                            # t 顺时针转 90°：干部 t=(0,1) → n=(1,0) 内侧
        return C, t, n

    def project(self, P):
        """3D 点 → (σ, ξ, η)：所属截面（截面平面过中心线点且垂直切向）与截面内坐标；不在任何截面上 → σ = nan。"""
        x, z = P[:, 0], P[:, 2]
        sig = np.full(len(P), np.nan)
        dx, dz = x - self.center[0], z - self.center[1]
        ph = np.arctan2(dz, dx)
        ph = np.where(ph < 0, ph + 2 * np.pi, ph)
        arc = (ph >= self.phi2) & (ph <= self.phi1)
        sig[arc] = self.L1 + (self.phi1 - ph[arc]) * self.R_BEND
        s1 = z - self.z_bot
        m1 = (ph > self.phi1) & (s1 >= 0) & (s1 <= self.L1)
        sig[m1] = s1[m1]
        s3 = (np.c_[x, z] - self.T2) @ self.u2
        m3 = (ph < self.phi2) & (s3 >= 0) & (s3 <= self.L3)
        sig[m3] = self.L1 + self.L2 + s3[m3]
        ok = ~np.isnan(sig)
        xi = np.full(len(P), np.nan)
        C, t, n = self.frame2d(np.where(ok, sig, 0.0))
        xi[ok] = np.einsum("ij,ij->i", np.c_[x, z][ok] - C[ok], n[ok])
        return sig, xi, P[:, 1]

    @staticmethod
    def _chord(poly, C, n):
        from shapely.geometry import LineString, Point
        ln = LineString([C - 80 * n, C + 80 * n]).intersection(poly)
        segs = [g for g in getattr(ln, "geoms", [ln]) if g.length > 0]
        if not segs:
            return (-1.0, 1.0)
        g = min(segs, key=lambda g: g.distance(Point(C)))
        xs = [float(np.dot(np.asarray(c) - C, n)) for c in g.coords]
        return (min(xs), max(xs))

    # --- 外溢距离
    def _tube_excess(self, P, inner=True):
        sig, xi, eta = self.project(P)
        ok = ~np.isnan(sig)
        cols = (5, 6, 7, 8) if inner else (1, 2, 3, 4)
        s0 = np.where(ok, sig, 0.0)
        xc, a, ba, bp = (np.interp(s0, self.T[:, 0], self.T[:, k]) for k in cols)
        dx = np.where(ok, xi, 0.0) - xc
        b = np.where(eta >= 0, ba, bp)
        r = np.sqrt((dx / a) ** 2 + (eta / b) ** 2)
        rho = np.hypot(dx, eta)
        ex = np.where(r > 1, rho * (1 - 1 / np.maximum(r, 1e-12)), 0.0)
        return np.where(ok, ex, np.inf)

    def _gt_excess(self, P, inner=True):
        ax = self.gt_ax - (2.0 if inner else 0.0)
        v = (P - self.gt_c) / ax
        r = np.linalg.norm(v, axis=1)
        rho = np.linalg.norm(P - self.gt_c, axis=1)
        return np.where(r > 1, rho * (1 - 1 / np.maximum(r, 1e-12)), 0.0)

    def _head_excess(self, P, inner=True):
        R = self.Rh - (2.0 if inner else 0.0)
        rho = np.linalg.norm(P - np.array([self.H[0], 0.0, self.H[1]]), axis=1)
        return np.maximum(rho - R, 0.0)

    def canal_excess(self, P):
        return np.minimum.reduce([self._tube_excess(P), self._gt_excess(P), self._head_excess(P)])

    def outer_excess(self, P):
        return np.minimum.reduce([self._tube_excess(P, False), self._gt_excess(P, False), self._head_excess(P, False)])

    def below_cut(self, P):
        return (P - self.C03) @ self.u3 <= 0

    # --- 位姿
    def pose(self, alpha_deg: float, e: float):
        a = math.radians(alpha_deg)
        d = np.array([-math.sin(a), 0.0, -math.cos(a)])
        e_ml = np.array([math.cos(a), 0.0, -math.sin(a)])
        e_ap = np.array([0.0, 1.0, 0.0])
        P0 = self.C03 + e * self.n3
        return P0, d, e_ml, e_ap

    @staticmethod
    def to_world(loc, pose):
        P0, d, e_ml, e_ap = pose
        return P0 + loc[:, :1] * d + loc[:, 1:2] * e_ml + loc[:, 2:3] * e_ap


def penetration(stem: Stem3D, fem: Femur3D, A0: float, pose) -> float:
    P = fem.to_world(stem.local_surface(A0), pose)
    P = P[fem.below_cut(P)]
    return float(fem.canal_excess(P).max()) if len(P) else 0.0


def contact_fraction(stem: Stem3D, fem: Femur3D, A0: float, pose, band: float = 0.5) -> float:
    """柄在骨内的表面点中距髓腔壁 ≤ band 的比例（截面沿径向外扩 band 后穿出髓腔者计为贴壁）。"""
    loc = stem.local_surface(A0)
    P = fem.to_world(loc, pose)
    keep = fem.below_cut(P)
    if not keep.any():
        return 0.0
    loc2 = loc[keep].copy()
    rad = np.linalg.norm(loc2[:, 1:], axis=1, keepdims=True)
    loc2[:, 1:] *= np.maximum(rad + band, 1e-9) / np.maximum(rad, 1e-9)
    return float(np.mean(fem.canal_excess(fem.to_world(loc2, pose)) > 0))


def binding_s(stem: Stem3D, fem: Femur3D, A0: float, pose) -> float:
    """最紧处（皮质穿透最大的表面点）的轴向位置 s（mm，< 0 表示在肩部以上、截骨面以下的柄体）。"""
    loc = stem.local_surface(A0)
    P = fem.to_world(loc, pose)
    keep = fem.below_cut(P)
    ex = fem.canal_excess(P[keep])
    return float(loc[keep][int(np.argmax(ex)), 0])


def template(stem: Stem3D, fem: Femur3D, alphas=None, offsets=np.arange(-8.0, 8.1, 2.0),
             iters: int = 14) -> dict:
    """模板化：α 默认取设计变量 stem.alpha；对每个 (α, e) 二分求最大 A0；返回最佳（A0 最大，平手取 |e| 小）或失败原因。
    传入 alphas 网格时同时搜索 α（只用于"若 α 由模板化决定会选多少"的对照）。"""
    alphas = [stem.alpha] if alphas is None else alphas
    best = None
    lo0, hi0 = A_BOUNDS
    for a in alphas:
        for e in offsets:
            ps = fem.pose(a, e)
            if penetration(stem, fem, lo0, ps) > TOL:
                continue
            lo, hi = lo0, hi0
            if penetration(stem, fem, hi, ps) <= TOL:
                lo = hi
            else:
                for _ in range(iters):
                    mid = math.sqrt(lo * hi)
                    (lo, hi) = (mid, hi) if penetration(stem, fem, mid, ps) <= TOL else (lo, mid)
            cand = {"alpha": float(a), "e": float(e), "A0": float(lo)}
            if best is None or lo > best["A0"] * 1.005 or (abs(lo - best["A0"]) <= best["A0"] * 0.005 and abs(e) < abs(best["e"])):
                best = cand
    if best is None:
        return {"fit": False, "reason": "blocked (smallest size hits cortex at every offset)"}
    if best["A0"] >= hi0 - 1e-6:
        return {"fit": False, "reason": "canal larger than largest size", **best}
    if best["A0"] * stem.rho_tip < MIN_TIP_AREA:
        return {"fit": False, "reason": f"tip too thin ({best['A0'] * stem.rho_tip:.0f} mm² < {MIN_TIP_AREA:.0f})", **best}
    ps = fem.pose(best["alpha"], best["e"])
    best.update(fit=True, pose=ps, volume=stem.volume(best["A0"]), contact=contact_fraction(stem, fem, best["A0"], ps),
                s_bind=binding_s(stem, fem, best["A0"], ps),
                w_eq=2 * math.sqrt(best["A0"] / math.pi))
    return best


def inside_stem(stem: Stem3D, A0: float, loc: np.ndarray, tol: float = 1e-3) -> np.ndarray:
    """局部坐标点 (s, x, y) 是否在柄体内（含肩部以上棱柱与尖端帽）。"""
    sec = unit_section(stem.d, 720)
    th_s = np.arctan2(sec[:, 1], sec[:, 0])
    r_s = np.hypot(sec[:, 0], sec[:, 1])
    o = np.argsort(th_s)
    th_s, r_s = th_s[o], r_s[o]
    th = np.arctan2(loc[:, 2], loc[:, 1])
    r_unit = np.interp(th, np.r_[th_s - 2 * np.pi, th_s, th_s + 2 * np.pi], np.r_[r_s, r_s, r_s])
    s = loc[:, 0]
    k = np.sqrt(A0 * stem.area_ratio(np.minimum(s, stem.L)))
    c = stem.cap_length(A0)
    tcap = np.clip((s - stem.L) / max(c, 1e-9), 0, None)
    k = np.where(s > stem.L, math.sqrt(A0 * stem.rho_tip) * np.sqrt(np.clip(1 - tcap ** 2, 0, 1)), k)
    k = np.where(s > stem.L + c, -1.0, k)
    return np.hypot(loc[:, 1], loc[:, 2]) <= k * r_unit + tol


def overcut_check(stem: Stem3D, fem: "Femur3D", A0: float, pose, travel: float = 120.0, n_steps: int = 60) -> dict:
    """数值复核零过切：柄沿插入方向从远处平移到最终位置，途中每个位置的表面点若落在保留骨内，必须也在最终柄体内。"""
    loc = stem.local_surface(A0)
    bad, total = 0, 0
    for t in np.linspace(0.0, travel, n_steps)[1:]:
        loc_t = loc.copy()
        loc_t[:, 0] -= t                                   # 往回退 t（沿 −d），在最终柄的局部坐标里 s 减小
        P = fem.to_world(loc_t, pose)
        m = fem.below_cut(P) & (fem.outer_excess(P) == 0)
        total += int(m.sum())
        if m.any():
            bad += int((~inside_stem(stem, A0, loc_t[m], tol=0.02)).sum())
    return {"points_in_bone": total, "points_outside_final_stem": bad}
