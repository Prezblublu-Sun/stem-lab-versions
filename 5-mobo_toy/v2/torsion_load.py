"""扭转钩子（规格键 torsion，第三版计划第 5.2 节，用户 2026-11-04 批准写钩子和冒烟）。

    spec["torsion"] = {"def": "A", "T_Nm": 10.0}   定义 A：绕柄轴的纯扭矩；头力由 spec.cfg.load 给（批次写成沿柄轴的预载）。
    spec["torsion"] = {"def": "B", "T_Nm": 10.0}   定义 B：绕颈轴（fm.u3）的扭矩；头力由 spec.cfg.load 给（批次写成起身头力）。

做法：model3d_m1.build 照常建模后，本模块只改写该作业自己的 m_fric.inp 的加载步（LOAD、LOAD2、LOADk）。不加节点，网格和接触与同设计的基线行相同，
不改 model3d_m1.py（它计入作业 id 的代码哈希）。卸载步是 *CLOAD, OP=NEW 全部清零，不用动。只解摩擦模型：spec 必须带 fric_only。
每个 HEADN 节点的力 = 头力 / N + b × r_i，r_i 从 HEADN 形心算起，b = I⁻¹ M，I = Σ(|r|² E − r rᵀ)。这是净力矩恰好等于 M、净力为 0 的最小范数解。
计划里的公式 T (ax × r_i) / Σ|r⊥|² 在节点云不对称于轴时会多出一个弯矩，所以不用。
方向：M·ax 与楼梯头力绕柄轴的扭矩同号，两者叠加；ax 是柄轴单位向量（指向远端）。
小滑移假设在界面滑移超过 0.5 mm 时失效：本模块不判，由结果评估（第三版 G33）判。
"""
from __future__ import annotations

import pathlib
import re
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from inp_writer import _f  # noqa: E402

DEFS = ("A", "B")
STAIR_LOAD = {"resultant_N": 2391.0, "alpha_front_deg": 20.0, "alpha_sagit_deg": 18.0}   # 只用来定方向：楼梯头力绕柄轴的扭矩的符号
_CLOAD = re.compile(r"^\*CLOAD, OP=NEW\nHEADN, 1, (\S+)\nHEADN, 2, (\S+)\nHEADN, 3, (\S+)$", re.M)


def validate(tq: dict) -> None:
    if not isinstance(tq, dict) or tq.get("def") not in DEFS or not isinstance(tq.get("T_Nm"), (int, float)) or not float(tq["T_Nm"]) > 0 or set(tq) - {"def", "T_Nm"}:
        raise ValueError(f"torsion must be {{'def': one of {DEFS}, 'T_Nm': > 0}}, got {tq!r}")


def axial_load(d, resultant_N: float) -> dict:
    """cfg.load（model3d_v2.load_vector 的约定）：大小 resultant_N、方向沿柄轴 d（指向远端）。"""
    d = np.asarray(d, float) / np.linalg.norm(d)
    if not d[2] < 0:
        raise ValueError(f"the stem axis must point distally, got {d.tolist()}")
    return {"resultant_N": float(resultant_N), "alpha_front_deg": float(np.degrees(np.arctan(d[0] / d[2]))), "alpha_sagit_deg": float(np.degrees(np.arctan(d[1] / -d[2])))}


def stair_sign(fm, P0, ax) -> float:
    """楼梯头力绕柄轴的扭矩的符号（力臂从柄肩 P0 到头心，与导出器 torque_stem_axis_Nmm 同一公式）。"""
    import model3d_v2 as M
    F = M.load_vector({"load": STAIR_LOAD})
    t = float(np.cross(np.asarray(fm.H, float) - np.asarray(P0, float), F) @ ax)
    if t == 0.0:
        raise ValueError("the stair head force has no torque about the stem axis; the sense of the couple is undefined")
    return float(np.sign(t))


def target_moment(tq: dict, fm, pose) -> tuple[np.ndarray, np.ndarray]:
    """目标力矩矢量（N·mm）与所绕的轴（单位向量）。"""
    validate(tq)
    P0, d = np.asarray(pose[0], float), np.asarray(pose[1], float)
    ax = d / np.linalg.norm(d)
    if tq["def"] == "A":
        axis = ax
    else:
        axis = np.asarray(fm.u3, float)
        axis = axis / np.linalg.norm(axis)
    s = stair_sign(fm, P0, ax)
    if float(axis @ ax) == 0.0:
        raise ValueError("the torsion axis is perpendicular to the stem axis; the sense of the couple is undefined")
    sense = s * float(np.sign(axis @ ax))
    return sense * float(tq["T_Nm"]) * 1000.0 * axis, axis


def couple_forces(X: np.ndarray, M: np.ndarray) -> np.ndarray:
    """节点坐标 X（N × 3）上净力为 0、绕形心净力矩为 M 的最小范数节点力（N × 3）。"""
    r = X - X.mean(0)
    n2 = (r * r).sum(1)
    I = np.eye(3) * n2.sum() - r.T @ r
    if np.linalg.cond(I) > 1e8:
        raise ValueError("HEADN nodes are nearly collinear; the couple is ill-conditioned")
    return np.cross(np.linalg.solve(I, M), r)


def head_nodes(text: str) -> list:
    m = re.search(r"^\*NSET, NSET=HEADN\s*\n((?:[^*\n][^\n]*\n)+)", text, re.M | re.I)
    if not m:
        raise ValueError("m_fric.inp has no *NSET, NSET=HEADN block")
    return [int(x) for x in re.split(r"[,\s]+", m.group(1).strip()) if x]


def rewrite(text: str, nodes: list, X: np.ndarray, M: np.ndarray) -> tuple[str, dict]:
    """把每个加载步的均布 HEADN *CLOAD 换成逐节点的力。卸载步（值全 0）不动。其他行逐字不变。"""
    N = len(nodes)
    Fc = couple_forces(X, M)
    seen, n_load = [], 0

    def sub(m):
        nonlocal n_load
        vals = np.array([float(m.group(k)) for k in (1, 2, 3)])
        if not vals.any():
            return m.group(0)
        n_load += 1
        seen.append(tuple(m.group(k) for k in (1, 2, 3)))
        out = ["*CLOAD, OP=NEW"]
        for n_, f_ in zip(nodes, vals + Fc):
            out += [f"{n_}, {k + 1}, {_f(f_[k])}" for k in range(3)]
        return "\n".join(out)

    new = _CLOAD.sub(sub, text)
    if not n_load:
        raise ValueError("m_fric.inp: no loaded HEADN *CLOAD block found")
    if len(set(seen)) != 1:
        raise ValueError(f"m_fric.inp: the loaded steps carry different head forces: {sorted(set(seen))}")
    F = np.array([float(x) for x in seen[0]]) * N
    Ft = np.array([float(x) for x in seen[0]]) + Fc
    r = X - X.mean(0)
    res_f = float(np.linalg.norm(Ft.sum(0) - F))
    res_m = float(np.linalg.norm(np.cross(r, Fc).sum(0) - M))
    if res_f > 1e-6 * max(np.linalg.norm(F), 1.0) or res_m > 1e-6 * np.linalg.norm(M):
        raise ValueError(f"couple check failed: residual force {res_f:g} N, residual moment {res_m:g} N*mm")
    return new, {"n_head": N, "n_load_steps": n_load, "couple_force_max_N": float(np.linalg.norm(Fc, axis=1).max()), "residual_force_N": res_f, "residual_moment_Nmm": res_m}


def apply(d: pathlib.Path, spec: dict, fm, pl: dict) -> dict:
    """作业目录 d 已由 model3d_m1.build 写好；按 spec["torsion"] 改写 m_fric.inp。返回写进 prep.json 的记录。"""
    tq = spec["torsion"]
    validate(tq)
    if not spec.get("fric_only"):
        raise ValueError("torsion is friction-model only: the spec must carry fric_only")
    M, axis = target_moment(tq, fm, pl["pose"])
    path = pathlib.Path(d) / "m_fric.inp"
    text = path.read_text()
    nodes = head_nodes(text)
    z = np.load(pathlib.Path(d) / "mesh3d.npz")
    labs = z["node_labels"].astype(int)
    idx = {int(n): i for i, n in enumerate(labs)}
    X = z["nodes"][[idx[n] for n in nodes]]
    new, rec = rewrite(text, nodes, X, M)
    path.write_text(new, encoding="ascii")
    centre = X.mean(0)
    return {"torsion": {"def": tq["def"], "T_Nm": float(tq["T_Nm"]), "axis": axis.tolist(), "M_Nmm": M.tolist(), "head_centroid": centre.tolist(), **rec}}
