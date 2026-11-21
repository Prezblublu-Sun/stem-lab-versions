"""手工设计 STL 能否插进当前股骨（Linux，只读）：用法 part_fit_check.py <stl> <axis_tip_to_head: x|y|z> <collar_underside_coord> <h_cut>
放置方式（与模型里假体的定位一致）：领底面贴在截骨面上（距头心 h_cut，沿颈轴），零件轴与解剖颈轴同轴（柄体与颈同轴 = 插入角约 42.5°），
可调的只有截骨面内的平移（s1 沿颈平面内下方向 n3，s2 前后）和绕颈轴的转角 θ（θ = 0：零件的宽向 x 对着 n3，即内外向）。
判据（与选号相同）：柄体表面（领以下）进入皮质的最大深度 ≤ 0.30 mm（余量 −0.25 + 容差 0.05）；柄体不得伸出骨外表面；
领底面要整圈落在骨外轮廓向内 0.5 mm 以内（新领规则 wrap_fit 的要求）。
输出：最佳放置与对应的穿透量，以及默认放置（θ = 0、不平移）的结果；~/mobo_toy_v2/deck/part_fit/<名>.json 与表面点（画图用）。"""
from __future__ import annotations

import json
import pathlib
import sys

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "code")); sys.path.insert(0, str(HOME / "code" / "v2"))
import numpy as np  # noqa: E402

import femur_real as FR  # noqa: E402

TOL_CORTEX = 0.30


def read_stl(path):
    b = pathlib.Path(path).read_bytes()
    if b[:5] == b"solid" and b"facet" in b[:400]:
        v = [list(map(float, ln.split()[1:4])) for ln in b.decode(errors="replace").splitlines() if ln.strip().startswith("vertex")]
        return np.array(v).reshape(-1, 3, 3)
    n = int(np.frombuffer(b[80:84], np.uint32)[0])
    rec = np.frombuffer(b[84:84 + 50 * n], dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
    return rec["v"].astype(float)


def sample(tri, h=0.5):
    """三角面上按约 h mm 间距采样（含顶点）。"""
    out = [tri.reshape(-1, 3)]
    for t in tri:
        L = max(np.linalg.norm(t[1] - t[0]), np.linalg.norm(t[2] - t[0]), np.linalg.norm(t[2] - t[1]))
        k = int(np.ceil(L / h))
        if k < 2:
            continue
        a, b = np.meshgrid(np.linspace(0, 1, k + 1), np.linspace(0, 1, k + 1))
        msk = a + b <= 1
        a, b = a[msk], b[msk]
        out.append(t[0] + a[:, None] * (t[1] - t[0]) + b[:, None] * (t[2] - t[0]))
    return np.unique(np.round(np.vstack(out), 4), axis=0)


if __name__ == "__main__":
    stl, ax, y_col, h_cut = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4])
    tri = read_stl(stl)
    P = sample(tri)
    k = "xyz".index(ax)
    others = [i for i in range(3) if i != k]
    c = P[:, others].mean(0)                                            # 零件轴（同轴，取截面形心）
    axial = P[:, k] - y_col                                              # < 0 = 领以下（骨内）
    q1, q2 = P[:, others[0]] - c[0], P[:, others[1]] - c[1]
    body = axial < -1e-6
    fm = FR.build().with_cut(h_cut)
    u, n = fm.u3 / np.linalg.norm(fm.u3), fm.n3 / np.linalg.norm(fm.n3)
    v = np.cross(u, n)
    # 领底面外轮廓（axial ≈ 0 的点里离轴最远的一圈）
    ring = np.abs(axial) < 0.05

    def place(theta, s1, s2, pts_mask):
        th = np.radians(theta)
        b1 = np.cos(th) * n + np.sin(th) * v
        b2 = np.cross(u, b1)
        O = fm.C03 + s1 * n + s2 * v
        return O + axial[pts_mask, None] * u + q1[pts_mask, None] * b1 + q2[pts_mask, None] * b2

    def score(theta, s1, s2):
        W = place(theta, s1, s2, body)
        cs = fm.canal_sdf(W)
        os_ = fm.outer_sdf(W)
        Wc = place(theta, s1, s2, ring)
        col = fm.outer_sdf(Wc)
        return {"theta_deg": theta, "s1_mm": s1, "s2_mm": s2, "max_into_cortex_mm": float(cs.max()), "max_outside_bone_mm": float(os_.max()),
                "frac_body_surface_in_cortex": float((cs > 0).mean()), "collar_max_outer_sdf_mm": float(col.max()) if len(col) else None,
                "fits_cortex": bool(cs.max() <= TOL_CORTEX), "inside_bone": bool(os_.max() <= 0), "collar_fits": bool(len(col) and col.max() <= -0.5)}

    default = score(0.0, 0.0, 0.0)
    best = None
    for th in np.arange(-45, 46, 5.0):
        for s1 in np.arange(-8, 8.1, 1.0):
            for s2 in np.arange(-6, 6.1, 1.0):
                r = score(th, s1, s2)
                if best is None or r["max_into_cortex_mm"] < best["max_into_cortex_mm"]:
                    best = r
    # 最佳附近细化
    for th in np.arange(best["theta_deg"] - 4, best["theta_deg"] + 4.1, 1.0):
        for s1 in np.arange(best["s1_mm"] - 0.8, best["s1_mm"] + 0.81, 0.2):
            for s2 in np.arange(best["s2_mm"] - 0.8, best["s2_mm"] + 0.81, 0.2):
                r = score(th, s1, s2)
                if r["max_into_cortex_mm"] < best["max_into_cortex_mm"]:
                    best = r
    # 领放得下的最佳放置：在柄体满足皮质判据的放置里，取领伸出骨外轮廓最少的
    best_col = None
    for th in np.arange(-90, 91, 3.0):
        for s1 in np.arange(-8, 8.1, 0.5):
            for s2 in np.arange(-6, 6.1, 0.5):
                r = score(th, s1, s2)
                if r["fits_cortex"] and r["inside_bone"] and (best_col is None or r["collar_max_outer_sdf_mm"] < best_col["collar_max_outer_sdf_mm"]):
                    best_col = r
    # 领在截骨面上可用空间：骨外轮廓内缩 0.5 mm 后最大能放下多大的同形领（按比例缩放领外轮廓，在最佳放置下二分）
    def collar_scale_ok(sc, r):
        th = np.radians(r["theta_deg"]); b1 = np.cos(th) * n + np.sin(th) * v; b2 = np.cross(u, b1)
        O = fm.C03 + r["s1_mm"] * n + r["s2_mm"] * v
        Wc = O + sc * (q1[ring, None] * b1 + q2[ring, None] * b2)
        return fm.outer_sdf(Wc).max() <= -0.5
    lo, hi = 0.5, 1.0
    for _ in range(14):
        mid = 0.5 * (lo + hi)
        (lo, hi) = (mid, hi) if collar_scale_ok(mid, best_col) else (lo, mid)
    collar_max_scale = lo
    # 最佳放置下，哪些部位进了皮质（按零件轴向位置分段）
    W = place(best["theta_deg"], best["s1_mm"], best["s2_mm"], body)
    cs = fm.canal_sdf(W)
    seg = {}
    for lo, hi in ((-5, 0), (-15, -5), (-25, -15), (-40, -25)):
        msk = (axial[body] >= lo) & (axial[body] < hi)
        if msk.any():
            seg[f"{-hi:.0f}-{-lo:.0f} mm below the collar"] = {"max_into_cortex_mm": float(cs[msk].max()), "frac_in_cortex": float((cs[msk] > 0).mean())}
    name = pathlib.Path(stl).stem
    out = HOME / "deck" / "part_fit"
    out.mkdir(parents=True, exist_ok=True)
    rep = {"stl": stl, "n_surface_points": int(len(P)), "body_length_mm": float(-axial.min()), "h_cut": h_cut, "default": default, "best": best,
           "best_by_depth": seg, "best_for_collar": best_col, "collar_scale_that_fits": collar_max_scale,
           "collar_outline_extent_mm": [float(np.ptp(q1[ring])), float(np.ptp(q2[ring]))]}
    (out / f"{name}.json").write_text(json.dumps(rep, indent=1))
    np.savez_compressed(out / f"{name}_best.npz", W=W, cs=cs)
    print(json.dumps(rep, indent=1))
