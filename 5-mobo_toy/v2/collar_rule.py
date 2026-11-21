"""领的新规则（规格选项 collar_rule = "wrap_fit"，用户 2026-10-06）：
    wrap  领包住假体颈：领外形 = (柄在截骨面上的截口 ∪ 假体颈底面圆) 统一外扩 collar_w。
          现行规则只围绕截口外扩，柄体入口偏移时颈底面会伸出领外（401 个带领设计里 117 个），从侧面看领像被颈切掉一块。
    fit   整圈领宽都落在骨截面上：领外形必须在"骨外轮廓向内缩 COLLAR_CLIP"之内，放不下就在选号时换小一号或换入口偏移，
          不再把领修窄（现行规则会裁剪，401 个里 199 个某处被修窄）。
无领设计（collar_w = 0）不受影响。

实现：不改计入作业哈希的 geom3d.py / fe3d_geom.py / model3d_m1.py。jobs.prep 在规格带此选项时调用 install()，
只在该作业的建模进程里把 geom3d.template 与 fe3d_geom.collar_outline 换成下面的版本。

皮质余量检查的取样密度 MARGIN_CHECK（2026-10-23，规格键 margin_check；阶段 11 的 B1 重放）：
    sparse  geom3d.penetration 原样：柄面取样用 Stem3D.local_surface（肩部以上 S_TOP = −60 mm 内 8 环，约 7.5 mm 一环），
            肩部（s = 0）到截骨面之间（倾斜侧 s ≈ −2…−5 mm）没有取样点，余量在截骨面正下方没有被检查
            （ml_efficiency_2026-10-22/failures：170 个无领 DONE 作业里 a64 的最小层厚 0.13 mm，严格检查后 A0 −5.3 %）。
    dense   另加 s ∈ [−12, +2] mm 每 0.25 mm 一环、每环 96 点的密集环带（与 failures/scripts/fail_tplfine.py 的 pen_dense 逐字相同，
            结果与 failures/tables/tplfine_nis_all.csv 一致），取 max(原值, 环带值)。只换本进程的 geom3d.penetration，且只在
            调用原 template 的那一刻换（template_base），调完即还原。
    默认 sparse：已有作业、候选池、作业 id 都不变。改法：规格键 margin_check = "dense"（jobs.prep → install_neck / install /
    install_margin_check）、stage_neckopt.Phase 的 margin_check（候选池直接调 template_neck_in_shoulder，所以密集检查必须在
    template_neck_in_shoulder 本身里，而不是只在 install_neck 里）、或 set_margin_check("dense")。
"""
from __future__ import annotations

import math
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import fe3d_geom as E  # noqa: E402
import geom3d as G  # noqa: E402

_ORIG = {"template": G.template, "collar_outline": E.collar_outline, "penetration": G.penetration}
STEP, HALF = 0.2, 30.0                       # 截骨面上取等值线的网格（mm）
MARGIN_CHECK = "sparse"                      # "sparse" | "dense"，见模块说明；set_margin_check() 改
MARGIN_MODES = ("sparse", "dense")
DENSE_S = np.arange(-12.0, 2.0001, 0.25)     # 密集环带的轴向位置 s（mm；负 = 肩部以上，截骨面以上的点由 below_cut 滤掉）
DENSE_M = 96                                 # 每环点数


def set_margin_check(mode: str) -> str:
    """改本进程的默认余量检查密度；返回生效值。"""
    global MARGIN_CHECK
    if mode not in MARGIN_MODES:
        raise ValueError(f"margin_check must be one of {MARGIN_MODES}, got {mode!r}")
    MARGIN_CHECK = mode
    return MARGIN_CHECK


def penetration_dense(stem, fem, A0, pose, margin=None) -> float:
    """geom3d.penetration + 截骨面附近的密集环带（fail_tplfine.pen_dense 的原样复制）：max(原值, max(canal_sdf + m, 0) 于环带点)。"""
    base = _ORIG["penetration"](stem, fem, A0, pose, margin)
    if not hasattr(fem, "canal_sdf"):
        return base
    sec = G.unit_section(stem.d, DENSE_M)
    k = np.sqrt(A0 * stem.area_ratio(DENSE_S))
    loc = np.vstack([np.c_[np.full(len(sec), si), ki * sec] for si, ki in zip(DENSE_S, k)])
    P = fem.to_world(loc, pose)
    P = P[fem.below_cut(P)]
    if not len(P):
        return base
    margin = stem.m if margin is None else margin
    return max(base, float(np.maximum(fem.canal_sdf(P) + margin, 0.0).max()))


def template_base(stem, fem, alphas=None, offsets=np.arange(-8.0, 8.1, 2.0), iters: int = 14, margin=None, margin_check=None) -> dict:
    """原 geom3d.template，按 margin_check（None = 模块默认 MARGIN_CHECK）决定余量检查密度；dense 时只在这次调用里把
    geom3d.penetration 换成 penetration_dense（template 内部按名字取 penetration，所以二分的每一步都走密集检查），调完还原。"""
    mode = MARGIN_CHECK if margin_check is None else margin_check
    if mode not in MARGIN_MODES:
        raise ValueError(f"margin_check must be one of {MARGIN_MODES}, got {mode!r}")
    if mode == "dense":
        prev = G.penetration
        G.penetration = penetration_dense
        try:
            r = _ORIG["template"](stem, fem, alphas=alphas, offsets=offsets, iters=iters, margin=margin)
        finally:
            G.penetration = prev
    else:
        r = _ORIG["template"](stem, fem, alphas=alphas, offsets=offsets, iters=iters, margin=margin)
    r["margin_check"] = mode
    return r


def _plane_grid(fm):
    C, e1, e2 = E._plane_basis(fm)
    g = np.arange(-HALF, HALF + STEP / 2, STEP)
    U, V = np.meshgrid(g, g)
    P = C + U.reshape(-1, 1) * e1 + V.reshape(-1, 1) * e2
    return g, U, P


def footprint(st, fm, A0, pose):
    """柄在截骨面上的截口（平面坐标，原点 = 截骨中心 C03）。"""
    g, U, P = _plane_grid(fm)
    P0, d, e_ml, e_ap = pose
    Q = P - P0
    ex = G.stem_radial_excess(st, A0, np.c_[Q @ d, Q @ e_ml, Q @ e_ap]).reshape(U.shape)
    fps = E._loops(ex, g, 0.0)
    if not fps:
        raise ValueError("stem has no footprint on the resection plane")
    return max(fps, key=lambda p: p.area)


def bone_host(fm, foot):
    """截骨面上包含截口的骨外轮廓，向内缩 COLLAR_CLIP（领外缘至少离骨外表面这么远）。"""
    g, U, P = _plane_grid(fm)
    outer = E._loops(fm.outer_sdf(P).reshape(U.shape), g, -G.COLLAR_CLIP)
    from shapely.geometry import Point
    c = foot.centroid
    host = [p for p in outer if p.contains(Point(c.x, c.y))] or [max(outer, key=lambda p: p.intersection(foot).area)]
    return host[0]


def wrapped(st, fm, foot):
    from shapely.geometry import Point
    r = float(fm.cfg["prosthesis"]["neck_radius_mm"])
    core = foot.union(Point(0.0, 0.0).buffer(r, quad_segs=32))
    col = core.buffer(float(st.collar_w), quad_segs=16).buffer(0)
    if col.geom_type != "Polygon":
        col = max(col.geoms, key=lambda p: p.area)
    return col


def collar_fits(st, fm, A0, pose, tol_mm2: float = 0.05) -> bool:
    foot = footprint(st, fm, A0, pose)
    col = wrapped(st, fm, foot)
    return col.difference(bone_host(fm, foot)).area <= tol_mm2


def collar_outline_wrap(st, fm, pl: dict, step: float = 0.15, half: float = 45.0) -> dict:
    """与 fe3d_geom.collar_outline 同样的返回字段；领 = (截口 ∪ 颈底面) 外扩 collar_w，不裁剪（放不下时报错，正常情况下选号已保证放得下）。"""
    from shapely.geometry import Point
    foot = footprint(st, fm, pl["A0"], pl["pose"])
    col = wrapped(st, fm, foot)
    over = col.difference(bone_host(fm, foot)).area
    if over > 0.05:
        raise ValueError(f"wrapped collar overhangs the bone outline by {over:.2f} mm²")
    col = col.simplify(0.05)
    ring = col.difference(foot)
    g = np.arange(-half, half + step / 2, step)
    U, V = np.meshgrid(g, g)
    C, e1, e2 = E._plane_basis(fm)
    P = C + U.reshape(-1, 1) * e1 + V.reshape(-1, 1) * e2
    inside = np.array([ring.contains(Point(u, v)) for u, v in zip(U.ravel()[::7], V.ravel()[::7])])
    Pr = P[::7][inside]
    cort = float((fm.canal_sdf(Pr) > 0).mean()) if len(Pr) else 0.0
    return {"poly": col, "footprint": foot, "area_mm2": float(col.area), "footprint_mm2": float(foot.area),
            "ring_mm2": float(ring.area), "ring_cortex_frac": cort, "overhang_mean_mm": float(ring.area / max(foot.length, 1e-9)),
            "collar_w": float(st.collar_w), "collar_t": float(st.collar_t), "rule": "wrap_fit"}


def template_wrap_fit(stem, fem, alphas=None, offsets=np.arange(-8.0, 8.1, 2.0), iters: int = 14, margin=None, min_A0: float = 0.0,
                      margin_check=None):
    """现行选号（每个入口偏移下按皮质余量求最大号）之上再加"包住颈的整圈领放得下"：每个偏移从最大号往下二分到放得下的最大号；
    在所有偏移里取最大（平手取 |e| 小）。无领设计直接用现行选号。margin_check：None = 模块默认（见 template_base）。"""
    if not getattr(stem, "has_collar", False):
        return template_base(stem, fem, alphas=alphas, offsets=offsets, iters=iters, margin=margin, margin_check=margin_check)
    best, reasons = None, []
    for e in offsets:
        r = template_base(stem, fem, alphas=alphas, offsets=np.array([e]), iters=iters, margin=margin, margin_check=margin_check)
        if not r.get("fit"):
            reasons.append(f"e {e:+.0f}: {r.get('reason')}")
            continue
        a, A_hi = r["alpha"], r["A0"]
        ps = fem.pose(a, e)
        lo_lim = max(min_A0, G.A_BOUNDS[0])
        if A_hi < lo_lim:                                   # 这个偏移下按皮质余量的最大号已低于假体颈下限
            reasons.append(f"e {e:+.0f}: shoulder {A_hi:.0f} mm² < {lo_lim:.0f} mm² before the collar check")
            continue
        if collar_fits(stem, fem, A_hi, ps):
            A = A_hi
        elif A_hi <= lo_lim or not collar_fits(stem, fem, lo_lim, ps):
            reasons.append(f"e {e:+.0f}: collar does not fit even at {lo_lim:.0f} mm²")
            continue
        else:
            lo, hi = lo_lim, A_hi
            for _ in range(iters):
                mid = math.sqrt(lo * hi)
                (lo, hi) = (mid, hi) if collar_fits(stem, fem, mid, ps) else (lo, mid)
            A = lo
        if A * stem.rho_tip < G.MIN_TIP_AREA:
            reasons.append(f"e {e:+.0f}: tip too thin at {A:.0f} mm²")
            continue
        cand = {"alpha": float(a), "e": float(e), "A0": float(A), "A0_cortex_rule": float(A_hi)}
        if best is None or A > best["A0"] * 1.005 or (abs(A - best["A0"]) <= best["A0"] * 0.005 and abs(e) < abs(best["e"])):
            best = cand
    margin = stem.m if margin is None else float(margin)
    if best is None:
        return {"fit": False, "reason": "collar_rule wrap_fit: no offset works (" + "; ".join(reasons)[:400] + ")", "margin": margin}
    ps = fem.pose(best["alpha"], best["e"])
    best.update(fit=True, pose=ps, volume=stem.volume(best["A0"]), contact=G.contact_fraction(stem, fem, best["A0"], ps),
                s_bind=G.binding_s(stem, fem, best["A0"], ps, margin), margin=margin, w_eq=2 * math.sqrt(best["A0"] / math.pi),
                collar_rule="wrap_fit", margin_check=MARGIN_CHECK if margin_check is None else margin_check)
    return best


def neck_overhang(st, fm, A0, pose) -> float:
    """假体颈底面圆伸出柄截口的面积（mm²）。无领时这部分压在截骨面上，M1 会把它当普通界面（带过盈），等于一块小领。"""
    from shapely.geometry import Point
    neck = Point(0.0, 0.0).buffer(float(fm.cfg["prosthesis"]["neck_radius_mm"]), quad_segs=32)
    return float(neck.difference(footprint(st, fm, A0, pose)).area)


def template_neck_in_shoulder(stem, fem, alphas=None, offsets=np.arange(-8.0, 8.1, 2.0), iters: int = 14, margin=None,
                              min_A0: float = 0.0, tol_mm2: float = 2.0, margin_check=None):
    """无领设计的选号（规格选项 collar_rule = "neck_in_shoulder"，用户 2026-10-07 定）：假体颈底面必须整个落在柄截口里
    （伸出 ≤ tol_mm2；2 mm² ≈ 截口等值线在 0.2 mm 网格上的面积误差），否则颈底会压在截骨面上成为一块小领。截口随号单调变大，所以每个入口偏移只需检查皮质余量允许的最大号；
    在满足的偏移里取号最大（平手取 |e| 小）。带领设计不用此规则。
    margin_check：None = 模块默认 MARGIN_CHECK；"dense" = 截骨面下密集环带的严格余量检查（候选池与建模都经过这里，所以两者一致）。"""
    if getattr(stem, "has_collar", False):
        raise ValueError("collar_rule neck_in_shoulder is for collarless designs only")
    best, reasons = None, []
    for e in offsets:
        r = template_base(stem, fem, alphas=alphas, offsets=np.array([e]), iters=iters, margin=margin, margin_check=margin_check)
        if not r.get("fit"):
            reasons.append(f"e {e:+.0f}: {r.get('reason')}")
            continue
        if r["A0"] < max(min_A0, G.A_BOUNDS[0]):
            reasons.append(f"e {e:+.0f}: shoulder {r['A0']:.0f} mm² < {max(min_A0, G.A_BOUNDS[0]):.0f} mm²")
            continue
        ov = neck_overhang(stem, fem, r["A0"], r["pose"])
        if ov > tol_mm2:
            reasons.append(f"e {e:+.0f}: neck base overhangs the shoulder by {ov:.1f} mm²")
            continue
        if best is None or r["A0"] > best["A0"] * 1.005 or (abs(r["A0"] - best["A0"]) <= best["A0"] * 0.005 and abs(e) < abs(best["e"])):
            best = {**r, "neck_overhang_mm2": ov}
    mode = MARGIN_CHECK if margin_check is None else margin_check
    if best is None:
        return {"fit": False, "reason": "collar_rule neck_in_shoulder: no offset works (" + "; ".join(reasons)[:400] + ")",
                "margin": stem.m if margin is None else float(margin), "margin_check": mode}
    best["collar_rule"] = "neck_in_shoulder"
    best["margin_check"] = mode
    return best


def install_neck(min_A0: float = 0.0, tol_mm2: float = 2.0, margin_check: str | None = None) -> None:
    """只在当前进程里把 geom3d.template 换成 neck_in_shoulder 版（jobs.prep 对带 collar_rule = "neck_in_shoulder" 的作业调用）。
    margin_check 给定时（规格键 margin_check）同时设本进程的默认密度；None = 保持当前默认（sparse）。"""
    if margin_check is not None:
        set_margin_check(margin_check)
    G.template = lambda stem, fem, alphas=None, offsets=np.arange(-8.0, 8.1, 2.0), iters=14, margin=None: \
        template_neck_in_shoulder(stem, fem, alphas=alphas, offsets=offsets, iters=iters, margin=margin, min_A0=min_A0, tol_mm2=tol_mm2)


def install(min_A0: float = 0.0, margin_check: str | None = None) -> None:
    """只在当前进程里替换选号与领外形（jobs.prep 对带 collar_rule = "wrap_fit" 的作业调用）。margin_check 同 install_neck。"""
    if margin_check is not None:
        set_margin_check(margin_check)
    G.template = lambda stem, fem, alphas=None, offsets=np.arange(-8.0, 8.1, 2.0), iters=14, margin=None: \
        template_wrap_fit(stem, fem, alphas=alphas, offsets=offsets, iters=iters, margin=margin, min_A0=min_A0)
    E.collar_outline = collar_outline_wrap


def install_margin_check(mode: str) -> None:
    """无领规则（collar_rule 为空）的作业只改余量检查密度：本进程的 geom3d.template 换成 template_base（jobs.prep 对只带
    margin_check 的作业调用）。"""
    set_margin_check(mode)
    G.template = lambda stem, fem, alphas=None, offsets=np.arange(-8.0, 8.1, 2.0), iters=14, margin=None: \
        template_base(stem, fem, alphas=alphas, offsets=offsets, iters=iters, margin=margin)
