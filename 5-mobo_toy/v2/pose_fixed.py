"""号固定、只移动位姿（规格键 pose_fixed，第三版计划第 5.3 节，用户 2026-11-04 批准写钩子和冒烟）。

    spec["pose_fixed"] = {"de": mm, "ds": mm, "rot_deg": 度, "dalpha_deg": 度}   四个键都可省，至少一个不为 0。
        de          入口偏移，沿截骨面内的 n3（正 = 内下方），同 entry_offset 的方向
        ds          坐深，沿柄轴（正 = 更深）
        rot_deg     绕柄轴转角
        dalpha_deg  插入角，冠状面内

生产选号照常给出名义的 pl（含 entry_offset 的固定偏移）；本模块不改 A0，只改位姿，所以 entry_offset 变体会重新选号而这里不会。不改 model3d_m1.py。
记录：穿透量（相对余量 m，以及相对内膜面）、卡点、接触比例、颈底伸出。templating 记录里的 alpha、e 跟着改，stability 的柄轴和 P0 才对得上；ds 不进 e，只差 P0 处的平动读数。
局限：
  * 腔和柄共形，所以这表示"腔也按偏的位置做"，不表示柄在腔里没坐到位。
  * 假体颈和头固定在股骨上（model3d_m1 按 fm.C03、fm.H 建），只有柄体移动，所以颈底可能伸出，头心不动。
  * 穿透 > 0 时柄面已进入皮质，界面仍按建模结果算，这时结果只能当排序看。
"""
from __future__ import annotations

import math

import numpy as np

KEYS = ("de", "ds", "rot_deg", "dalpha_deg")


def validate(pf: dict) -> None:
    if not isinstance(pf, dict) or set(pf) - set(KEYS) or not all(isinstance(v, (int, float)) for v in pf.values()) or not any(float(v) != 0.0 for v in pf.values()):
        raise ValueError(f"pose_fixed must set at least one of {KEYS} to a non-zero number, got {pf!r}")


def rotate(v: np.ndarray, axis: np.ndarray, deg: float) -> np.ndarray:
    a = math.radians(deg)
    return v * math.cos(a) + np.cross(axis, v) * math.sin(a) + axis * float(axis @ v) * (1.0 - math.cos(a))


def moved_pose(fm, pl: dict, pf: dict) -> tuple:
    """名义 pl 按 pf 移动后的 (alpha, e, pose)。"""
    validate(pf)
    alpha = float(pl["alpha"]) + float(pf.get("dalpha_deg", 0.0))
    e = float(pl["e"]) + float(pf.get("de", 0.0))
    P0, d, e_ml, e_ap = fm.pose(alpha, e)
    P0, d, e_ml, e_ap = np.asarray(P0, float), np.asarray(d, float), np.asarray(e_ml, float), np.asarray(e_ap, float)
    P0 = P0 + float(pf.get("ds", 0.0)) * d
    rot = float(pf.get("rot_deg", 0.0))
    if rot != 0.0:
        u = d / np.linalg.norm(d)
        e_ml, e_ap = rotate(e_ml, u, rot), rotate(e_ap, u, rot)
    return alpha, e, (P0, d, e_ml, e_ap)


def apply(st, fm, pl: dict, pf: dict) -> dict:
    """名义 pl → 移动后的 pl（A0 不变），加 pl["pose_fixed"] 记录。"""
    import collar_rule as CR
    import geom3d as G
    alpha, e, pose = moved_pose(fm, pl, pf)
    A0, m = float(pl["A0"]), float(pl["margin"])
    rec = {**{k: float(pf.get(k, 0.0)) for k in KEYS}, "A0": A0, "nominal_alpha": float(pl["alpha"]), "nominal_e": float(pl["e"]), "margin": m,
           "penetration_vs_margin_mm": G.penetration(st, fm, A0, pose, m), "penetration_vs_endosteum_mm": G.penetration(st, fm, A0, pose, 0.0),
           "neck_overhang_mm2": float(CR.neck_overhang(st, fm, A0, pose))}
    return {**pl, "alpha": alpha, "e": e, "pose": pose, "contact": G.contact_fraction(st, fm, A0, pose), "s_bind": G.binding_s(st, fm, A0, pose, m), "pose_fixed": rec}
