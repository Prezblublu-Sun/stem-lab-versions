"""初始稳定性的分解（用户 2026-10-10 会议后："可以接受柄受压向骨内部沉降，但旋转必须避免"；目标还要看完全接触面积）。

只用已有的结果文件（m_fric_csv/*_U.csv、mesh3d.npz），不需要重算，也不改计入哈希的文件。
* 柄相对骨的刚体运动：界面节点对的相对位移 r = u_柄 − u_骨，最小二乘拟合 r ≈ t + ω × (x − c)。
  用相对位移而不是柄的绝对位移，是为了不把整根股骨的弯曲算成柄的转动。
  - 转动：|ω|（度），分成绕柄轴（自转）与垂直柄轴（摆动）两部分；
  - 平动：在柄肩中心（截骨面上的入口点）处的位移，沿柄轴的分量记为下沉（正 = 向骨内），其余为侧移。
  分三段：首次加载 LOAD − RELEASE（含就位，转动与下沉的总量）、第二循环 LOAD2 − UNLOAD（可恢复部分）、
  卸载后残留 UNLOAD − RELEASE（永久部分）。
* 切向微动按方向分解（第二循环，柄身节点）：沿柄轴（下沉方向）与绕柄轴的周向（转动方向）两个分量的面积加权 P95。
* 完全接触面积：LOAD 与 LOAD2 时间隙 ≤ 1 µm 的柄身界面面积（mm²）及其占柄身界面的比例。
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import post_m1 as PM  # noqa: E402

STEPS = ("RELEASE", "LOAD", "UNLOAD", "LOAD2")


def rigid_fit(X: np.ndarray, R: np.ndarray, w: np.ndarray | None = None):
    """R ≈ t + ω × (X − c)，加权最小二乘；返回 (t 于 c, ω, c, 残差 RMS)。"""
    c = X.mean(0) if w is None else (X * w[:, None]).sum(0) / w.sum()
    Q = X - c
    n = len(X)
    A = np.zeros((3 * n, 6))
    A[0::3, 0] = A[1::3, 1] = A[2::3, 2] = 1.0
    # ω × q = (ωy qz − ωz qy, ωz qx − ωx qz, ωx qy − ωy qx)
    A[0::3, 4], A[0::3, 5] = Q[:, 2], -Q[:, 1]
    A[1::3, 3], A[1::3, 5] = -Q[:, 2], Q[:, 0]
    A[2::3, 3], A[2::3, 4] = Q[:, 1], -Q[:, 0]
    b = R.reshape(-1)
    sw = np.ones(3 * n) if w is None else np.repeat(np.sqrt(w / w.mean()), 3)
    sol, *_ = np.linalg.lstsq(A * sw[:, None], b * sw, rcond=None)
    res = b - A @ sol
    return sol[:3], sol[3:], c, float(np.sqrt(np.mean(res ** 2)))


def stability(d: pathlib.Path, job: str = "m_fric") -> dict:
    import femur_real as FR  # noqa: F401
    import jobs as J
    d = pathlib.Path(d)
    p = PM.pairs(d)
    spec = json.loads((d / "spec.json").read_text())
    res = json.loads((d / "result.json").read_text()) if (d / "result.json").exists() else {}
    t = res.get("templating") or json.loads((d / "prep.json").read_text()).get("templating")
    fm = J.femur_for(spec)
    P0, ax, _, _ = fm.pose(t["alpha"], t["e"])
    ax = ax / np.linalg.norm(ax)                                       # 指向骨内（远端）
    lut = {int(n): i for i, n in enumerate(p["node_labels"])}
    X = np.array([p["nodes"][lut[int(n)]] for n in p["pair_bone"]])
    U = {s: PM._utab(d / f"{job}_csv" / f"{s}_U.csv", p["n"]) for s in STEPS}
    rel = {s: U[s][p["pair_stem"]] - U[s][p["pair_bone"]] for s in STEPS}
    body = ~p["pair_collar"]
    w, nrm, di = p["pair_area"], p["pair_normal"], p["pair_interf"]
    out = {}
    for name, (a, b) in {"first": ("RELEASE", "LOAD"), "rev": ("UNLOAD", "LOAD2"), "perm": ("RELEASE", "UNLOAD")}.items():
        Rr = rel[b] - rel[a]
        tr, om, c, rms = rigid_fit(X[body], Rr[body], w[body])
        t0 = tr + np.cross(om, P0 - c)                                    # 柄肩中心处的平动
        out[f"rot_{name}_deg"] = float(np.degrees(np.linalg.norm(om)))
        out[f"rot_axial_{name}_deg"] = float(np.degrees(abs(om @ ax)))
        out[f"rot_tilt_{name}_deg"] = float(np.degrees(np.linalg.norm(om - (om @ ax) * ax)))
        out[f"subsid_{name}_um"] = float(t0 @ ax * 1e3)
        out[f"lateral_{name}_um"] = float(np.linalg.norm(t0 - (t0 @ ax) * ax) * 1e3)
        out[f"rigid_fit_rms_{name}_um"] = rms * 1e3
    # 切向微动按方向分解（第二循环，柄身）
    Rv = (rel["LOAD2"] - rel["UNLOAD"])[body]
    nb, wb, Xb = nrm[body], w[body], X[body]
    tang = Rv - (Rv * nb).sum(1)[:, None] * nb
    q = Xb - P0
    radial = q - (q @ ax)[:, None] * ax
    radial /= np.maximum(np.linalg.norm(radial, axis=1, keepdims=True), 1e-9)
    e_th = np.cross(ax, radial)
    out["slip_axial_p95_um"] = PM._wq(np.abs(tang @ ax) * 1e3, wb, 0.95)
    out["slip_circ_p95_um"] = PM._wq(np.abs((tang * e_th).sum(1)) * 1e3, wb, 0.95)
    # 完全接触面积
    for s in ("LOAD", "LOAD2"):
        gap = -(di[body] + (rel[s][body] * nb).sum(1)) * 1e3
        closed = gap <= PM.OPEN_UM
        out[f"contact_area_{s.lower()}_mm2"] = float(wb[closed].sum())
        out[f"contact_frac_{s.lower()}"] = float(wb[closed].sum() / wb.sum())
    out["body_interface_mm2"] = float(wb.sum())
    return out


if __name__ == "__main__":
    for j in sys.argv[1:]:
        import jobs as J
        print(j, json.dumps({k: round(v, 4) for k, v in stability(J.QROOT / j).items()}))
