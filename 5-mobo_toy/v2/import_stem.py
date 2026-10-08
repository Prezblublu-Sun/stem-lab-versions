"""外部柄设计放进当前股骨（规格选项 import_stem，用户 2026-10-08："把 Part3-1.STL 放在当前骨中计算一遍"）。

做法：STL 是三角面，OCC 不能拿它和骨做布尔运算；这类零件由简单形体组成，按实测尺寸（deck_data/scripts/part_fit_check.py
与本会话的截面测量）在 OCC 里原样重建，再换进 M1 建模流程，其余（股骨、截骨 25 mm、材料、载荷、网格、过盈、后处理）全部不变。
略去的只有 ≤ 1 mm 的边缘圆角（尖端约 1 mm、领边约 0.5–0.8 mm）。

放置（与模型里假体的定位一致）：领底面贴在截骨面上，零件轴与解剖颈轴同轴（插入角 = 颈轴与干轴的夹角），宽向对着内外侧
（模型的 e_ml 方向），截骨面内平移 import_e（沿 n3，默认 0）。股骨头球（r 14）照常放在解剖头心，套在零件的锥颈上。

jobs.prep 对带 import_stem 的作业调用 install()，只在该建模进程里替换：geom3d.template（给出固定的放置与号）、
fe3d_geom.stem_solid（柄体）、fe3d_geom.collar_outline（领的外形）、gmsh occ.addCylinder（颈与锥颈）。不改计入哈希的文件。
规格里的 design 是一个近似的参数化柄（截面 λ、超椭圆指数、锥度按实测拟合），只用于后处理里"骨采样点是否在柄内"的屏蔽与分区长度。
"""
from __future__ import annotations

import math

import numpy as np

PARTS = {
    # Part3-1（桌面，SolidWorks 导出，2026-10-08 00:15）：沿 y 轴，尖端 y = 0，领底 y = 35.0
    "part3_1": {
        "body_len": 35.0,                   # 尖端到领底
        "flat": 6.5,                        # 跑道形截面的直边长（宽 − 厚，沿全长不变）
        "t_tip": 13.0, "t_top": 16.67,      # 厚（= 两端半圆直径），线性变化（宽、厚每侧 3.0°）
        "collar": (34.0, 22.0, 2.5),        # 领：跑道形 宽 × 厚，板厚
        # 领上表面以上：圆角 → 颈 Ø11.6 → 台阶 → 锥颈 Ø13.0 → Ø12.0；(距截骨面高度 mm, 直径 mm)
        "neck": [(2.0, 21.0), (3.0, 18.84), (4.0, 15.67), (5.0, 13.89), (6.0, 12.69), (7.0, 12.0), (8.0, 11.67), (14.6, 11.6)],
        "taper": (14.6, 13.0, 34.5, 11.96),
        "design": {"L": 35.0, "rho_tip": 0.68, "q": 1.15, "lam": 1.39, "g_ml": 0.5, "g_ap": 0.5, "n_a": 2.5, "n_p": 2.5,
                   "tau_a": 0.0, "tau_p": 0.0, "m": -0.25, "collar_w": 4.0, "collar_t": 2.5, "cap_h": 1.5},
    },
}


def neck_angle_deg(fm) -> float:
    u = np.asarray(fm.u3, float) / np.linalg.norm(fm.u3)
    return math.degrees(math.acos(float(u @ np.array([0.0, 0.0, 1.0]))))


def _t_at(p, s_below):
    """柄体在领底以下 s mm 处的厚度。"""
    f = 1.0 - s_below / p["body_len"]
    return p["t_tip"] + (p["t_top"] - p["t_tip"]) * f


def stadium_area(flat, t):
    return flat * t + math.pi * t * t / 4.0


def body_volume(p, n=400) -> float:
    s = np.linspace(0.0, p["body_len"], n)
    trap = getattr(np, "trapezoid", None) or np.trapz
    return float(trap([stadium_area(p["flat"], _t_at(p, x)) for x in s], s))


def _stadium_wire(occ, C, ex, ez, flat, t):
    r, h = t / 2.0, flat / 2.0
    P = lambda a, b: occ.addPoint(*(C + a * ex + b * ez))  # noqa: E731
    p1, p2, p3, p4 = P(h, r), P(-h, r), P(-h, -r), P(h, -r)
    m_l, m_r = P(-h - r, 0.0), P(h + r, 0.0)                         # 半圆各拆成两段 90° 弧：180° 弧的方向不唯一，可能向内凸
    c_l, c_r = P(-h, 0.0), P(h, 0.0)
    l1 = occ.addLine(p1, p2)
    a1, a2 = occ.addCircleArc(p2, c_l, m_l), occ.addCircleArc(m_l, c_l, p3)
    l2 = occ.addLine(p3, p4)
    a3, a4 = occ.addCircleArc(p4, c_r, m_r), occ.addCircleArc(m_r, c_r, p1)
    return occ.addWire([l1, a1, a2, l2, a3, a4])


def stadium_poly(cx, cy, ax, ay, w, t, n=48):
    """平面坐标里的跑道形（宽 w 沿单位向量 (ax, ay)）。"""
    from shapely.geometry import LineString
    h = (w - t) / 2.0
    seg = LineString([(cx - h * ax, cy - h * ay), (cx + h * ax, cy + h * ay)])
    return seg.buffer(t / 2.0, quad_segs=n)


def install(spec: dict, fm) -> dict:
    import gmsh

    import fe3d_geom as E
    import geom3d as G
    p = PARTS[spec["import_stem"]]
    alpha = neck_angle_deg(fm)
    e_off = float(spec.get("import_e", 0.0))
    A_top = stadium_area(p["flat"], p["t_top"])
    V_body = body_volume(p)
    orig = {"contact": G.contact_fraction, "bind": G.binding_s}

    def template(stem, fem, alphas=None, offsets=None, iters=14, margin=None):
        ps = fem.pose(alpha, e_off)
        mg = stem.m if margin is None else float(margin)
        return {"fit": True, "alpha": float(alpha), "e": e_off, "A0": float(A_top), "pose": ps, "volume": V_body,
                "contact": float(orig["contact"](stem, fem, A_top, ps)), "s_bind": float(orig["bind"](stem, fem, A_top, ps, mg)),
                "margin": mg, "w_eq": 2 * math.sqrt(A_top / math.pi), "import_stem": spec["import_stem"]}

    def stem_solid(occ, st, A0, pose, delta=0.0, n_body=24, m=40):
        P0, d, ex, ez = (np.asarray(v, float) for v in pose)
        wires = [_stadium_wire(occ, P0 + p["body_len"] * d, ex, ez, p["flat"], p["t_tip"]),
                 _stadium_wire(occ, P0, ex, ez, p["flat"], p["t_top"]),
                 _stadium_wire(occ, P0 - 1.0 * d, ex, ez, p["flat"], p["t_top"])]          # 截骨面以上多 1 mm，之后被半空间裁掉
        return occ.addThruSections(wires, makeSolid=True, makeRuled=True)

    def collar_outline(st, fem, pl, step=0.15, half=45.0):
        C, e1, e2 = E._plane_basis(fem)
        P0, d, ex, ez = (np.asarray(v, float) for v in pl["pose"])
        cx, cy = float((P0 - C) @ e1), float((P0 - C) @ e2)
        ax, ay = float(ex @ e1), float(ex @ e2)
        w, t, ct = p["collar"]
        poly = stadium_poly(cx, cy, ax, ay, w, t)
        foot = stadium_poly(cx, cy, ax, ay, p["flat"] + p["t_top"], p["t_top"])
        return {"poly": poly, "footprint": foot, "area_mm2": float(poly.area), "footprint_mm2": float(foot.area),
                "ring_mm2": float(poly.area - foot.area), "ring_cortex_frac": None, "overhang_mean_mm": float((poly.area - foot.area) / foot.length),
                "collar_w": None, "collar_t": float(ct), "rule": f"import:{spec['import_stem']}"}

    occ = gmsh.model.occ

    def add_cylinder(x, y, z, dx, dy, dz, r, *args, **kw):
        a = np.array([x, y, z], float)
        u = np.array([dx, dy, dz], float); u /= np.linalg.norm(u)
        ref = np.cross(u, [0.0, 0.0, 1.0]) if abs(u[2]) < 0.9 else np.cross(u, [1.0, 0.0, 0.0])
        ref /= np.linalg.norm(ref)
        wires = []
        for h, dia in p["neck"]:
            c = occ.addCircle(*(a + h * u), dia / 2.0, zAxis=u.tolist(), xAxis=ref.tolist())
            wires.append(occ.addWire([c]))
        loft = occ.addThruSections(wires, makeSolid=True, makeRuled=False)
        h0, d0, h1, d1 = p["taper"]
        cone = occ.addCone(*(a + h0 * u), *((h1 - h0) * u), d0 / 2.0, d1 / 2.0)
        out, _ = occ.fuse(loft, [(3, cone)])
        vols = [t for dd, t in out if dd == 3]
        if len(vols) != 1:
            raise RuntimeError(f"import_stem neck: {len(vols)} volumes after fuse")
        return vols[0]

    G.template = template
    E.stem_solid = stem_solid
    E.collar_outline = collar_outline
    occ.addCylinder = add_cylinder
    return {"alpha_deg": alpha, "A0": A_top, "body_volume_mm3": V_body, "import_e": e_off}
