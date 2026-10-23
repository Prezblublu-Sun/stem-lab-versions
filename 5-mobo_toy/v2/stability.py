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

口径（A4 转动拟合域研究，ml_efficiency_2026-10-22/plan/a4，2026-10-23）：
    转动 = 柄身界面节点对相对位移的面积加权刚体拟合，**全柄身**（rot_*_deg 等现有键，阶段 10 起的优化指标 rot_first_deg）。
    自转的排序对拟合域不敏感（Spearman ≥ 0.92），**摆动的大小随拟合域变化**（近端半段 ≈ 全柄的 2.4 倍），引用分项时必须带域。
    2026-10-23 的补丁（a4_summary.md §4）只**新增**键，现有键逐位不变，不进哈希文件，不影响作业 id：
    (a) rot_tilt_ap_{first,rev,perm}_deg / rot_tilt_ml_*_deg：有符号的摆动分量 ω·e_ap（绕前后轴 = 内外翻向）、ω·e_ml（绕内外侧轴 = 屈伸向），
        e_ap、e_ml 为 femur.pose 的柄坐标系（与 a4_analyse.py 的 *_tilt_ap/_tilt_ml 列同一公式）；
    (b) rot_first_prox_deg / rot_axial_first_prox_deg / rot_tilt_first_prox_deg：近端半段（柄身节点对沿柄轴坐标 s = (x − P0)·ax ≤ 中位数，
        按节点对个数对半，面积加权）的首次加载转动，**只作诊断**（键名带域）；
    (c) bench()：虚拟台架读数 bench_cx_*（见该函数），stability() 里用 try/except 调用，缺 cortex_conn 的作业只是没有这些键。
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
SEGS = {"first": ("RELEASE", "LOAD"), "rev": ("UNLOAD", "LOAD2"), "perm": ("RELEASE", "UNLOAD")}
BENCH_H_STEM = 10.0        # 虚拟台架：柄颈标记 = 柄的全部节点中截骨面以上 0 < h ≤ 10 mm（a4_rotfit_linux.H_STEM）
BENCH_H_BONE = 5.0         # 虚拟台架：骨环标记 = 皮质单元的全部节点中截骨面以下 −5 ≤ h < 0 mm（a4_rotfit_linux.H_BONE，CX5）


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


def _split(om: np.ndarray, ax: np.ndarray):
    """ω 按柄轴分解（度）：总转动 |ω|、自转 |ω·ax|、摆动 |ω − (ω·ax) ax|（与 a4_rotfit_linux.split 同一公式）。"""
    a = om @ ax
    return (float(np.degrees(np.linalg.norm(om))), float(np.degrees(abs(a))),
            float(np.degrees(np.linalg.norm(om - a * ax))))


def _load(d: pathlib.Path, job: str = "m_fric") -> dict:
    """stability() 与 bench() 共用的读入：节点对、股骨/柄的坐标系、界面节点坐标、四个分析步的位移表、相对位移。"""
    import femur_real as FR  # noqa: F401
    import jobs as J
    d = pathlib.Path(d)
    p = PM.pairs(d)
    spec = json.loads((d / "spec.json").read_text())
    res = json.loads((d / "result.json").read_text()) if (d / "result.json").exists() else {}
    t = res.get("templating") or json.loads((d / "prep.json").read_text()).get("templating")
    fm = J.femur_for(spec)
    P0, ax, e_ml, e_ap = fm.pose(t["alpha"], t["e"])
    ax = ax / np.linalg.norm(ax)                                       # 指向骨内（远端）
    lut = {int(n): i for i, n in enumerate(p["node_labels"])}
    X = np.array([p["nodes"][lut[int(n)]] for n in p["pair_bone"]])
    U = {s: PM._utab(d / f"{job}_csv" / f"{s}_U.csv", p["n"]) for s in STEPS}
    rel = {s: U[s][p["pair_stem"]] - U[s][p["pair_bone"]] for s in STEPS}
    return {"d": d, "p": p, "fm": fm, "P0": P0, "ax": ax, "e_ml": np.asarray(e_ml, float), "e_ap": np.asarray(e_ap, float),
            "lut": lut, "X": X, "U": U, "rel": rel}


def stability(d: pathlib.Path, job: str = "m_fric") -> dict:
    L = _load(d, job)
    p, P0, ax, e_ml, e_ap, X, rel = L["p"], L["P0"], L["ax"], L["e_ml"], L["e_ap"], L["X"], L["rel"]
    body = ~p["pair_collar"]
    w, nrm, di = p["pair_area"], p["pair_normal"], p["pair_interf"]
    out = {}
    for name, (a, b) in SEGS.items():
        Rr = rel[b] - rel[a]
        tr, om, c, rms = rigid_fit(X[body], Rr[body], w[body])
        t0 = tr + np.cross(om, P0 - c)                                    # 柄肩中心处的平动
        out[f"rot_{name}_deg"] = float(np.degrees(np.linalg.norm(om)))
        out[f"rot_axial_{name}_deg"] = float(np.degrees(abs(om @ ax)))
        out[f"rot_tilt_{name}_deg"] = float(np.degrees(np.linalg.norm(om - (om @ ax) * ax)))
        out[f"subsid_{name}_um"] = float(t0 @ ax * 1e3)
        out[f"lateral_{name}_um"] = float(np.linalg.norm(t0 - (t0 @ ax) * ax) * 1e3)
        out[f"rigid_fit_rms_{name}_um"] = rms * 1e3
        # A4 (a)：摆动的有符号分量（全柄身口径；e_ap / e_ml 为 femur.pose 的柄坐标系）
        out[f"rot_tilt_ap_{name}_deg"] = float(np.degrees(om @ e_ap))     # 绕前后轴 = 内外翻向
        out[f"rot_tilt_ml_{name}_deg"] = float(np.degrees(om @ e_ml))     # 绕内外侧轴 = 屈伸向
    # A4 (b)：近端半段（s ≤ 柄身节点对沿柄轴坐标的中位数，面积加权），首次加载，只作诊断
    s_ax = (X - P0) @ ax
    prox = body & (s_ax <= float(np.median(s_ax[body])))
    Rr = rel["LOAD"] - rel["RELEASE"]
    _, om, _, _ = rigid_fit(X[prox], Rr[prox], w[prox])
    out["rot_first_prox_deg"], out["rot_axial_first_prox_deg"], out["rot_tilt_first_prox_deg"] = _split(om, ax)
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
    # A4 (c)：虚拟台架读数；缺 cortex_conn / stem_conn、标记集太小、股骨对象没有 C03/u3 等都只是没有这些键，不让作业失败
    try:
        out.update(_bench(L, BENCH_H_STEM, BENCH_H_BONE))
    except Exception as e:  # noqa: BLE001
        print(f"[stability] bench skipped for {L['d'].name}: {type(e).__name__}: {str(e)[:120]}", file=sys.stderr, flush=True)
    return out


def bench(d: pathlib.Path, h_stem: float = BENCH_H_STEM, h_bone: float = BENCH_H_BONE, job: str = "m_fric") -> dict:
    """虚拟台架读数（a4_rotfit_linux.py 的 S10 / CX5 段，2026-10-23；a4_summary.md §2–§3）。与台架对比用的量。

    h = (x − C03)·u3，C03 为截骨面中心，u3 为颈轴单位向量（指向头心），h > 0 在截骨面以上。
      柄颈标记集 = 柄的全部节点（mesh3d.npz 的 stem_conn 中出现的节点，含孪生界面节点）中 0 < h ≤ h_stem（默认 10 mm，S10）；
      骨环标记集 = 皮质单元（cortex_conn）的全部节点中 −h_bone ≤ h < 0（默认 5 mm，CX5；界面节点做骨环 B5 不行，它带着压配残余变形）。
    两个标记集分别用其**绝对位移增量**做**不加权**刚体拟合 u ≈ t + ω × (x − c)（rigid_fit, w=None）；
      读数 ω = ω_柄颈 − ω_骨环，按柄轴 ax 分解：bench_cx_rot_{seg}_deg（总）、bench_cx_rot_axial_*（自转 |ω·ax|）、bench_cx_rot_tilt_*（摆动）；
      柄肩 P0 处的平动差 v = [t_S + ω_S×(P0−c_S)] − [t_B + ω_B×(P0−c_B)]：bench_cx_subsid_{seg}_um（v·ax，正 = 入骨）、bench_cx_lateral_*_um。
    三段与 stability() 相同：first = LOAD − RELEASE，rev = LOAD2 − UNLOAD，perm = UNLOAD − RELEASE。
    另记 bench_cx_h_stem_mm / bench_cx_h_bone_mm（标记带）与 bench_cx_n_stem / bench_cx_n_bone（标记节点数）。
    注意（A4）：首次加载的台架读数含整根股骨的弹性弯曲（约 78 % 不是界面相对运动，比 rot_first_deg 大 ≈ 6.7 倍），
      与台架比的是卸载后残留段 bench_cx_rot_perm_deg / bench_cx_subsid_perm_um（≈ 界面拟合残留段的 1.16 倍，Spearman 0.988）。
    mesh3d.npz 缺 stem_conn / cortex_conn 或标记集少于 4 个节点时抛异常（stability() 里被 try/except 吞掉）。
    """
    return _bench(_load(d, job), h_stem, h_bone)


def _bench(L: dict, h_stem: float, h_bone: float) -> dict:
    d, p, fm, P0, ax, U, lut = L["d"], L["p"], L["fm"], L["P0"], L["ax"], L["U"], L["lut"]
    m = np.load(d / "mesh3d.npz")
    for k in ("stem_conn", "cortex_conn"):
        if k not in m.files:
            raise KeyError(f"mesh3d.npz has no {k}")
    stem_labs = np.unique(m["stem_conn"])
    cort_labs = np.unique(m["cortex_conn"])
    C0 = np.asarray(fm.C03, float)
    u3 = np.asarray(fm.u3, float)
    u3 = u3 / np.linalg.norm(u3)                                       # 颈轴，指向头心；截骨面法向
    nodes = p["nodes"]

    def xyz(labs):
        return nodes[np.array([lut[int(n)] for n in labs])]

    hs = (xyz(stem_labs) - C0) @ u3
    S = stem_labs[(hs > 0) & (hs <= h_stem)]
    hc = (xyz(cort_labs) - C0) @ u3
    B = cort_labs[(hc >= -h_bone) & (hc < 0)]
    if len(S) < 4 or len(B) < 4:
        raise ValueError(f"bench marker sets too small: stem {len(S)}, bone {len(B)}")
    out = {"bench_cx_h_stem_mm": float(h_stem), "bench_cx_h_bone_mm": float(h_bone),
           "bench_cx_n_stem": int(len(S)), "bench_cx_n_bone": int(len(B))}
    XS, XB = xyz(S), xyz(B)
    for seg, (a, b) in SEGS.items():
        dU = U[b] - U[a]
        fits = []
        for Xk, labs in ((XS, S), (XB, B)):
            Uk = dU[labs]
            ok = np.isfinite(Uk).all(1)
            fits.append(rigid_fit(Xk[ok], Uk[ok], None))
        (tS, oS, cS, _), (tB, oB, cB, _) = fits
        om = oS - oB
        out[f"bench_cx_rot_{seg}_deg"], out[f"bench_cx_rot_axial_{seg}_deg"], out[f"bench_cx_rot_tilt_{seg}_deg"] = _split(om, ax)
        v = (tS + np.cross(oS, P0 - cS)) - (tB + np.cross(oB, P0 - cB))
        out[f"bench_cx_subsid_{seg}_um"] = float(v @ ax * 1e3)
        out[f"bench_cx_lateral_{seg}_um"] = float(np.linalg.norm(v - (v @ ax) * ax) * 1e3)
    return out


if __name__ == "__main__":
    for j in sys.argv[1:]:
        import jobs as J
        print(j, json.dumps({k: round(v, 4) for k, v in stability(J.QROOT / j).items()}))
