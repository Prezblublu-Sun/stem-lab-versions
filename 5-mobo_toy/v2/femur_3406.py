"""Sawbones 3406（Churun 的未切割模型，右侧化烘焙件）接入现有管线的钩子模块。**不计入作业哈希**（jobs.code_hash 只盖
femur_real / geom3d / fe3d_geom / model3d_v2 / post / config_v2a / model3d_m1 / post_m1），与 collar_rule.py、import_stem.py 同类。

数据：v2/data/femur_3406/3406R_cortical.STEP + 3406R_cancellous_v2.STEP（v2 = 导针孔填孔后再同轴扩孔 r+0.3 mm、两端 +4 mm 回填，无盲窝，
完整股骨才能划网格；v1 文件保留；由 v2/tools/bake_3406.py 烘焙：原生左股骨只把 z 取反，
diag(1, 1, −1) ⇒ 右股骨、x 内侧、y 后方、z 近端，正是 femur_real.landmarks 假定的约定；来源与校验和见该目录的 PROVENANCE.md）。
烘焙还填掉了 Churun 松质芯里的一条导针孔（半径 2.3 mm、长 97 mm，沿颈部 120° 轴从外侧皮质界面穿到头部芯表面；
留着它，距离场会在颈部多一道"墙"，模板化把所有穿过它的柄判成穿透；松质体积 127 952 → 128 494 mm³，两端在皮质下各留 ≤ 6 mm 的盲窝）。

与 CT 股骨（femur_real.py）的差别，以及为什么要自己的 build()
1. 配置：femur_real.build() 从 config_v2a.yaml 读配置并按 sha1(femur_real.py + cfg['femur']) 缓存；这里 CFG = 深拷贝后覆盖
   femur 节（绝对路径的 STEP、SHA256、E_cancellous 155 MPa（Sawbones 第四代 PCF 20 泡沫）、README 的参考标志、box x 上限放到 85
   —— 3406 的头内侧极点在模型坐标 x ≈ 78，原盒子 75 会切掉 3 mm）。cut_from_head 25、z_trunc −150、voxel 0.5、tess 0.8 不变。
   materials.cortical.E 16 800、titanium.E 110 000、interface.mu 0.3 已经等于 README 的 Sawbones 值，不改。
2. 皮质壳是**开放**的（远端横销孔连通髓腔，没有封闭的内膜空腔）：哈希代码对"外膜面"做 z 向射线奇偶会得到 342 条奇数列、
   体积错 11 %。这里 outer 距离场的内外判定用 奇偶(全部 869 个皮质面) ∪ 奇偶(松质芯)（两者都闭合，0 奇数列，体积误差 0.1 %），
   近壁精修的采样面 = 分类器判为外膜的皮质面 ∪ 暴露在空髓腔里的松质芯面（6 个底面/锥面）。canal 距离场照常只用松质芯（闭合）。
   结果：松质芯以下（模型 z ≲ −39）髓腔是空的，canal_sdf > 0、outer_sdf > 0 ⇒ 柄不能伸进空腔（README 第 4 条"柄必须由泡沫支撑"）。
3. 标志点：FR.landmarks 原样作用在分类器的外膜顶点集上（头心、干轴、后髁、小转子都能用）。颈轴另有争议（见 NECK_AXIS）。
4. dorr_indices()/summary() 在 3406 上会抛异常（z −150…−40 的髓腔宽度全是 NaN）；本模块导入时给 FR.summary / FR.dorr_indices
   套一层类型守卫：传入 Femur3406 对象就报清楚的 TypeError，CT 对象原样放行。用 femur_3406.summary() / validate()。
5. 肩部面积上限：geom3d.A_BOUNDS = (20, 900) 在 template 里按调用时读取；3406 的髓腔截面 h25 ≈ 760、h32 ≈ 1370 mm²（CT 股骨 ≈ 610），
   m 0.5 / h_cut ≥ 28 会撞上限并判 "canal larger than largest size"。install() 只在本进程把 G.A_BOUNDS 改成 (20, A_BOUNDS_CAP)，
   并返回记录（S3 把它写进 prep.json）。collar_rule 读的 G.A_BOUNDS[0] 不变。

颈轴（NECK_AXIS，S0 决定，用户未定前默认 DEFAULT_NECK_AXIS）
    "detector"  哈希检测器：头心 + 距头心 head_r+4/8/12 的截面质心拟合直线（在 3406 上落在转子区）→ 颈干角 ≈ 134°、前倾 ≈ 2°
    "readme"    README 的颈部中心线（A 系 head→shaft (−0.7637, −0.2335, −0.6018) → 烘焙系 shaft→head (0.7637, −0.2335, 0.6018)）
                → 在检测器的干坐标系里 ≈ 125.5° / 17.1°（README 自己的干系里 127° / 17°）
    "isthmus"   头心 → 颈最细截面（面积最小）的质心，迭代到截面垂直于该轴；建模时算，连同全部候选一起存进缓存
                （2026-10-23 实测 112.4° / −3.8°：颈最窄处质心在 a、b 两条线的上外侧 6–9 mm，所以头心→质心的线比两者都平）
    "silhouette" 冠状面投影轮廓（X 线片做法）：垂直试探轴的最窄上下弦，取弦中点与头心连线，迭代（111.4° / 0°，与 isthmus 相差 1°；
                厂家 CAD 点云经 ICP 配到同一坐标后同法得 112.3°）
    [ux, uy, uz] 烘焙坐标下自干向头的任意单位向量
    颈轴只改 lm 的 neck_u / neck_u_m / neck_shaft_deg / anteversion_deg（截骨面、柄的位姿、模板化都随之变），
    不改干坐标系与距离场，所以缓存按"不含 neck_axis 的 cfg"键入，切换颈轴不用重建。

规格键 femur_id（S3 在 jobs.py 里接线；本模块只定义语义）
    spec["femur_id"] = "sawbone3406"  → jobs.femur_for：import femur_3406 as F6; F6.install(); fm = F6.build(neck_axis=spec.get("neck_axis"))
                                        之后 with_cut / cfg 覆盖逻辑不变；prep 把 install() 的返回与 femur_id 写进 prep.json。
    没有该键 → 现行 CT 股骨 FR.build()。femur_id（与 neck_axis）像其它规格键一样进 job_id 的哈希，3406 作业自动得到不同 id。
    参照隔离：jobs.intact_ref 按 ref_intact_h* 的 glob 找参照、只比 E_canc，不看股骨 —— 3406 的设计作业必须显式给 intact_job，
    3406 的完整股骨参照 stage 用 "sb…"（不能用 "ref"，也不能用 "neck*"，stage_neckopt.in_family 只看前缀）。

用法
    python femur_3406.py --build [--neck-axis detector|readme|isthmus] [--check-occ]   # 建缓存并打印 summary
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import pathlib
import sys
import time

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import femur_real as FR  # noqa: E402
import geom3d as G  # noqa: E402

FEMUR_ID = "sawbone3406"
DATA = HERE / "data" / "femur_3406"
CACHE = FR.CACHE
SHA256 = {"cortical": "9b1bf9494728c3533c9cd04db8669008c97dd88701ffea56cd7e12e6bd8cab1f",       # bake 2026-10-23 16:5x（填孔版）
          "cancellous": "3455b8c9c21bb9f1eae62da357744b4ee1235939c8bc058fb29d0d109c0c7940"}   # v2 2026-10-23：填孔 + 扩孔再填（bake_3406.py --refill）；v1 f478e1b4… 保留作回溯
A_BOUNDS_CAP = 2000.0                        # mm²，3406 的肩部面积二分上限（哈希值 900；侦察建议 2000）
E_CANCELLOUS = 155.0                         # MPa，Sawbones 第四代 PCF 20 泡沫（README）
BOX_MM = [[-45.0, 85.0], [-45.0, 45.0], [-160.0, 110.0]]
DEFAULT_NECK_AXIS = "isthmus"                # S0：用户 2026-10-24 采纳建议 c（头心 → 颈最细截面中心）；检测器轴在 neck_in_shoulder 下无可行设计
# README（A 系 x 内侧、y 前方、z 近端）→ 烘焙系（x, −y_A, z_A）
README = {"head_c": np.array([49.6099353810299, +1.7912299193830443, 109.59714234641827]),
          "head_r": 25.531883498460367, "head_r_cancellous": 22.199497413426844,
          "neck_u": np.array([0.7637389365391908, -0.2334984255246394, 0.6018150231520484]),      # 自干向头
          "neck_shaft_deg": 127.0, "anteversion_deg": 17.0, "neck_isthmus_diam_mm": 42.5166527639569,
          "length_mm": 487.0233026181097, "gt_above_head_mm": 11.8, "core_bottom_below_head_mm": 88.0}
EXPOSED_GAP_MM = 0.3                         # 松质芯面离皮质面的中位距离 > 此值 ⇒ 暴露在空髓腔里（与 FR 的分类阈值相同）


def load_cfg(neck_axis=None) -> dict:
    cfg = copy.deepcopy(FR.load_cfg())
    fc = cfg["femur"]
    fc.update(step_cortical=str(DATA / "3406R_cortical.STEP"), step_cancellous=str(DATA / "3406R_cancellous_v2.STEP"),
              sha256_cortical=SHA256["cortical"], sha256_cancellous=SHA256["cancellous"], E_cancellous=E_CANCELLOUS,
              reference_landmarks={"head_r": README["head_r"], "neck_shaft_deg": README["neck_shaft_deg"],
                                   "anteversion_deg": README["anteversion_deg"]},
              box_mm=[list(b) for b in BOX_MM], femur_id=FEMUR_ID,
              neck_axis=_axis_option(neck_axis))
    return cfg


def _axis_option(neck_axis):
    if neck_axis is None:
        return DEFAULT_NECK_AXIS
    if isinstance(neck_axis, str):
        if neck_axis not in ("detector", "readme", "isthmus", "silhouette"):
            raise ValueError(f"neck_axis {neck_axis!r}: use detector | readme | isthmus | silhouette | [ux, uy, uz]")
        return neck_axis
    u = np.asarray(neck_axis, float).ravel()
    if u.shape != (3,) or not np.isfinite(u).all() or np.linalg.norm(u) < 1e-9:
        raise ValueError("neck_axis vector must be 3 finite numbers")
    return [float(x) for x in u / np.linalg.norm(u)]


# ------------------------------------------------------------------ 1 三角化（FR.tessellate 的扩展版：多返回全部皮质面与暴露的芯面）
def tessellate(cfg: dict) -> dict:
    """烘焙坐标下：松质芯面 (Vc, Fc)、外膜面 (Vo, Fo, 分类器)、全部皮质面 (Va, Fa)、暴露的芯面 Fx（Vc 的索引）、两件 OCC 体积。"""
    import gmsh
    from scipy.spatial import cKDTree
    fc = cfg["femur"]
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.NumThreads", 1)
        occ = gmsh.model.occ
        C = [x for x in occ.importShapes(fc["step_cortical"]) if x[0] == 3]
        K = [x for x in occ.importShapes(fc["step_cancellous"]) if x[0] == 3]
        occ.synchronize()
        if len(C) != 1 or len(K) != 1:
            raise RuntimeError(f"expected 1 cortical + 1 cancellous volume, got {len(C)} + {len(K)}")
        vol = {"cortical_mm3": occ.getMass(*C[0]), "cancellous_mm3": occ.getMass(*K[0])}
        sC = [t for d, t in gmsh.model.getBoundary(C, oriented=False) if d == 2]
        sK = [t for d, t in gmsh.model.getBoundary(K, oriented=False) if d == 2]
        for k, v in (("Mesh.MeshSizeMax", fc["tess_mm"]), ("Mesh.MeshSizeMin", 0.5 * fc["tess_mm"]),
                     ("Mesh.MeshSizeFromCurvature", 0), ("Mesh.Algorithm", 6)):
            gmsh.option.setNumber(k, v)
        gmsh.model.mesh.generate(2)
        ntag, xyz, _ = gmsh.model.mesh.getNodes()
        xyz = xyz.reshape(-1, 3)
        lut = np.full(int(ntag.max()) + 1, -1)
        lut[ntag.astype(int)] = np.arange(len(ntag))

        def tris(surfs):
            out = {}
            for s in surfs:
                ty, _, en = gmsh.model.mesh.getElements(2, s)
                T = [e.reshape(-1, 3) for t, e in zip(ty, en) if t == 2]
                if T:
                    out[s] = lut[np.vstack(T).astype(int)]
            return out
        TK, TC = tris(sK), tris(sC)
    finally:
        gmsh.finalize()
    Fk = np.vstack(list(TK.values()))
    Fa = np.vstack(list(TC.values()))
    tree_k = cKDTree(FR._surface_samples(xyz, Fk, 3))          # 与 FR.tessellate 相同：皮质面离芯面 > 0.3 mm ⇒ 外膜（这里也含空髓腔壁）
    outer, n_inner = [], 0
    for s, F in TC.items():
        d, _ = tree_k.query(xyz[F].mean(1))
        if np.median(d) > 0.3:
            outer.append(F)
        else:
            n_inner += 1
    if not outer or n_inner == 0:
        raise RuntimeError(f"cortical face classification failed: outer {len(outer)}, inner {n_inner}")
    Fo = np.vstack(outer)
    tree_c = cKDTree(FR._surface_samples(xyz, Fa, 3))          # 芯面离皮质面 > 0.3 mm ⇒ 暴露在空髓腔里（底面 / 锥面）
    exposed = []
    for s, F in TK.items():
        d, _ = tree_c.query(xyz[F].mean(1))
        if np.median(d) > EXPOSED_GAP_MM:
            exposed.append(F)
    Fx = np.vstack(exposed) if exposed else np.zeros((0, 3), int)

    def compact(F):
        used = np.unique(F)
        m = np.full(len(xyz), -1); m[used] = np.arange(len(used))
        return xyz[used], m[F]
    Vc, Fc_ = compact(Fk)
    mc = np.full(len(xyz), -1); mc[np.unique(Fk)] = np.arange(len(np.unique(Fk)))
    Fx_ = mc[Fx] if len(Fx) else Fx
    Vo, Fo_ = compact(Fo)
    Va, Fa_ = compact(Fa)
    return {"Vc": Vc, "Fc": Fc_, "Fx": Fx_, "Vo": Vo, "Fo": Fo_, "Va": Va, "Fa": Fa_, "occ": vol,
            "n_faces": {"cortical_brep": len(sC), "cancellous_brep": len(sK), "periosteal_brep": len(outer),
                        "cortical_inner_shell_brep": n_inner, "core_exposed_brep": len(exposed)}}


# ------------------------------------------------------------------ 2 颈轴候选
def axis_fields(lm: dict, u) -> dict:
    """femur_real.landmarks 203–214 行的公式：给定颈轴 u（烘焙坐标，自干向头）→ 颈干角、前倾角、模型坐标下的单位向量。"""
    Rm = np.asarray(lm["Rm"], float)
    ex, ey, ez = Rm
    un = np.asarray(u, float) / np.linalg.norm(u)
    ccd = math.degrees(math.acos(float(np.clip(un @ ez, -1, 1))))
    un_t = un - (un @ ez) * ez
    av = math.degrees(math.atan2(-(un_t @ ey), un_t @ ex))
    u_m = un @ Rm.T
    return {"neck_u": un, "neck_shaft_deg": 180.0 - ccd, "anteversion_deg": av, "neck_u_m": u_m / np.linalg.norm(u_m)}


def section_loops(V, F, q, n):
    """三角网格与平面 (q, n) 的交线，按闭合环返回 3D 点列（每环一个 (k, 3) 数组）。"""
    n = np.asarray(n, float) / np.linalg.norm(n)
    s = (V - q) @ n
    s = np.where(s == 0.0, 1e-9, s)
    sv = s[F]
    cr = (sv.min(1) < 0) & (sv.max(1) > 0)
    T = F[cr]; st = sv[cr]
    pts, keys = [], []
    for i, j in ((0, 1), (1, 2), (2, 0)):
        m = st[:, i] * st[:, j] < 0
        a, b = T[m, i], T[m, j]
        t = st[m, i] / (st[m, i] - st[m, j])
        P = V[a] + (V[b] - V[a]) * t[:, None]
        k = np.where(a < b, a * len(V) + b, b * len(V) + a)
        pts.append(np.full((len(T), 3), np.nan)); pts[-1][m] = P
        keys.append(np.full(len(T), -1, np.int64)); keys[-1][m] = k
    pts = np.stack(pts, 1); keys = np.stack(keys, 1)                     # (nt, 3, 3), (nt, 3)
    ok = keys >= 0
    sel = ok.sum(1) == 2                                                 # 正常每个穿越三角形恰有两条边穿过平面
    pts, keys, ok = pts[sel], keys[sel], ok[sel]
    if not len(keys):
        return []
    seg_k = keys[ok].reshape(-1, 2)
    seg_p = pts[ok].reshape(-1, 2, 3)
    uk, inv = np.unique(seg_k, return_inverse=True)
    inv = inv.reshape(-1, 2)
    xyz = np.zeros((len(uk), 3)); xyz[inv.ravel()] = seg_p.reshape(-1, 3)
    adj = {}
    for e, (a, b) in enumerate(inv):
        adj.setdefault(int(a), []).append(e); adj.setdefault(int(b), []).append(e)
    used = np.zeros(len(inv), bool)
    loops = []
    for e0 in range(len(inv)):
        if used[e0]:
            continue
        used[e0] = True
        a, b = int(inv[e0, 0]), int(inv[e0, 1])
        chain = [a, b]
        cur, prev_e = b, e0
        while cur != a:
            nxt = [e for e in adj.get(cur, []) if not used[e]]
            if not nxt:
                break
            e = nxt[0]; used[e] = True
            cur = int(inv[e, 1]) if int(inv[e, 0]) == cur else int(inv[e, 0])
            chain.append(cur)
        if len(chain) >= 4 and chain[-1] == a:
            loops.append(xyz[chain[:-1]])
    return loops


def _plane_basis(n):
    n = np.asarray(n, float) / np.linalg.norm(n)
    a = np.array([0.0, 0.0, 1.0]) if abs(n[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    e1 = np.cross(n, a); e1 /= np.linalg.norm(e1)
    e2 = np.cross(n, e1)
    return e1, e2


def section_at(V, F, q, n, r_max=45.0):
    """过 q、法向 n 的截面中包含 q 的那一环（没有就取质心最近的）：面积、面积质心（3D）、等效直径、环。"""
    from shapely.geometry import Point, Polygon
    e1, e2 = _plane_basis(n)
    best = None
    for L in section_loops(V, F, q, n):
        if np.linalg.norm(L.mean(0) - q) > r_max:
            continue
        uv = np.c_[(L - q) @ e1, (L - q) @ e2]
        pg = Polygon(uv).buffer(0)
        if pg.is_empty or pg.area < 1.0:
            continue
        if pg.geom_type != "Polygon":
            pg = max(pg.geoms, key=lambda p: p.area)
        inside = pg.contains(Point(0.0, 0.0))
        dist = 0.0 if inside else pg.distance(Point(0.0, 0.0))
        if best is None or (inside, -dist) > (best["inside"], -best["dist"]):
            c = pg.centroid
            best = {"inside": inside, "dist": dist, "area_mm2": float(pg.area), "d_eq_mm": 2 * math.sqrt(pg.area / math.pi),
                    "centroid": q + c.x * e1 + c.y * e2, "loop": L}
    return best


def isthmus_axis(Vo, Fo, head_c, head_r, u0, d_lo=None, d_hi=30.0, step=0.5, iters=8) -> dict:
    """头心 → 颈最细截面（面积最小）质心。沿当前轴在距头心 d ∈ [d_lo, d_hi] 处取垂直截面，取面积最小者的质心定新轴，迭代。"""
    u = np.asarray(u0, float) / np.linalg.norm(u0)
    d_lo = head_r - 8.0 if d_lo is None else d_lo
    ds = np.arange(d_lo, d_hi + 1e-9, step)
    hist = []
    for it in range(iters):
        prof = []
        for d in ds:
            sec = section_at(Vo, Fo, head_c - d * u, u)
            if sec is not None:
                prof.append((float(d), sec["area_mm2"], sec["centroid"]))
        if not prof:
            raise RuntimeError("isthmus: no neck sections found")
        d_min, A_min, c_min = min(prof, key=lambda r: r[1])
        u_new = head_c - c_min
        u_new /= np.linalg.norm(u_new)
        ang = math.degrees(math.acos(float(np.clip(u @ u_new, -1, 1))))
        hist.append({"iter": it, "d_mm": d_min, "area_mm2": A_min, "turn_deg": ang})
        u = u_new
        if ang < 0.02:
            break
    prof = [(d, A) for d, A, _ in prof]
    return {"u": u, "d_mm": d_min, "area_mm2": A_min, "d_eq_mm": 2 * math.sqrt(A_min / math.pi), "centroid": c_min,
            "profile_d_area": prof, "iterations": hist}


def silhouette_axis(xz, h2, u0, d_lo=16.0, d_hi=30.0, step=0.5, iters=12) -> dict:
    """冠状面投影（X 线片做法）：垂直试探轴、距头心 d 的带内取上下轮廓的最窄弦，弦中点与头心连线为新轴，迭代。xz: (n, 2)，h2: 头心 (x, z)。"""
    u = np.asarray(u0, float) / np.linalg.norm(u0)
    hist = []
    for it in range(iters):
        n = np.array([-u[1], u[0]])
        s = (h2 - xz) @ u
        r = (xz - h2) @ n
        best = None
        for dd in np.arange(d_lo, d_hi + 1e-9, step):
            m = (np.abs(s - dd) < 0.5) & (np.abs(r) < 32.0)
            if m.sum() < 10:
                continue
            w = r[m].max() - r[m].min()
            if best is None or w < best[0]:
                best = (float(w), float(dd), 0.5 * float(r[m].max() + r[m].min()))
        if best is None:
            raise RuntimeError("silhouette: no neck band found")
        w, dd, rmid = best
        mid = h2 - dd * u + rmid * n
        u_new = h2 - mid
        u_new /= np.linalg.norm(u_new)
        turn = math.degrees(math.acos(float(np.clip(u @ u_new, -1, 1))))
        hist.append({"iter": it, "d_mm": dd, "width_mm": w, "turn_deg": turn})
        u = u_new
        if turn < 0.02:
            break
    return {"u_xz": u, "d_mm": dd, "width_mm": w, "mid_xz": mid, "iterations": hist}


def neck_axis_candidates(lm: dict, Vo, Fo) -> dict:
    """颈轴定义（烘焙坐标，自干向头）+ 它们在检测器干坐标系里的颈干角 / 前倾角。"""
    det = np.asarray(lm["neck_u"], float)
    Rm, org = np.asarray(lm["Rm"], float), np.asarray(lm["origin"], float)
    out = {"detector": {"u": det, "source": "femur_real.landmarks: head centre + section centroids at head_r+4/8/12"},
           "readme": {"u": README["neck_u"], "source": "README neck-only centroid line (A frame) mapped to the baked frame"}}
    ist = isthmus_axis(Vo, Fo, np.asarray(lm["head_c"], float), float(lm["head_r"]), det)
    out["isthmus"] = {"u": ist["u"], "source": "head centre -> centroid of the minimum-area neck section (iterated)",
                      "d_mm": ist["d_mm"], "area_mm2": ist["area_mm2"], "d_eq_mm": ist["d_eq_mm"], "centroid": ist["centroid"],
                      "profile_d_area": ist["profile_d_area"], "iterations": ist["iterations"]}
    Vm = (Vo - org) @ Rm.T                                                # 模型坐标：冠状面 = (x, z)
    hm = np.asarray(lm["head_m"], float) if "head_m" in lm else (np.asarray(lm["head_c"], float) - org) @ Rm.T
    sil = silhouette_axis(Vm[Vm[:, 2] > -10][:, [0, 2]], hm[[0, 2]], (det @ Rm.T)[[0, 2]])
    u_m = np.array([sil["u_xz"][0], 0.0, sil["u_xz"][1]])
    out["silhouette"] = {"u": u_m @ Rm, "source": "coronal-silhouette narrowest chord midpoint -> head centre (radiographic construction, iterated)",
                         "d_mm": sil["d_mm"], "width_mm": sil["width_mm"], "mid_m": [float(sil["mid_xz"][0]), float(hm[1]), float(sil["mid_xz"][1])],
                         "iterations": sil["iterations"]}
    for k, v in out.items():
        f = axis_fields(lm, v["u"])
        v.update(neck_shaft_deg=f["neck_shaft_deg"], anteversion_deg=f["anteversion_deg"], neck_u_m=f["neck_u_m"],
                 angle_to_detector_deg=math.degrees(math.acos(float(np.clip(v["u"] @ det, -1, 1)))))
    return out


def apply_neck_axis(lm: dict, option) -> dict:
    """按 option 选颈轴，改写 lm 的 neck_u / neck_u_m / neck_shaft_deg / anteversion_deg；记录来源。返回新 lm（浅拷贝）。"""
    option = _axis_option(option)
    lm = dict(lm)
    if isinstance(option, str):
        cand = lm["neck_axis_candidates"][option]
        u, src = cand["u"], cand["source"]
    else:
        u, src = np.asarray(option, float), "explicit vector (spec neck_axis)"
    lm.update(axis_fields(lm, u))
    lm["neck_axis"] = {"option": option, "u_baked": [float(x) for x in lm["neck_u"]], "source": src}
    return lm


# ------------------------------------------------------------------ 3 距离场（outer = 皮质 ∪ 松质芯）
def signed_distance_union(Va, Fa, Vc, Fc, Vo, Fo, Fx, g0, h, shape, band=3.0, workers=4):
    """outer 距离场：内 = 奇偶(全部皮质面) ∪ 奇偶(芯)；EDT；离壁 band 内用 外膜面 ∪ 暴露芯面 的密采样 KD 树精修。"""
    from scipy.ndimage import distance_transform_edt
    from scipy.spatial import cKDTree
    in_a, odd_a = FR._parity_inside(Va, Fa, g0, h, shape)
    in_c, odd_c = FR._parity_inside(Vc, Fc, g0, h, shape)
    inside = in_a | in_c
    d_in = distance_transform_edt(inside, sampling=h)
    d_out = distance_transform_edt(~inside, sampling=h)
    sdf = np.where(inside, -(d_in - 0.5 * h), d_out - 0.5 * h).astype(np.float32)
    del d_in, d_out
    idx = np.nonzero(np.abs(sdf) < band)
    P = g0 + (np.c_[idx] + 0.5) * h
    S = [FR._surface_samples(Vo, Fo)]
    if len(Fx):
        S.append(FR._surface_samples(Vc, Fx))
    tree = cKDTree(np.vstack(S))
    d, _ = tree.query(P, workers=workers)
    sdf[idx] = np.where(inside[idx], -d, d).astype(np.float32)
    return sdf, inside, {"all_cortical": int(odd_a), "core": int(odd_c)}, {"cortex_only": in_a, "core": in_c}


# ------------------------------------------------------------------ 4 股骨对象
class Femur3406(FR.RealFemur):
    """与 RealFemur 同接口（pose / to_world / canal_sdf / outer_sdf / below_cut / with_cut / resected_volume / labels_on_plane）。"""
    dorr = "Sawbones 3406 (synthetic composite; Dorr index not defined)"
    femur_id = FEMUR_ID


def _guard_fr() -> None:
    """FR.summary / FR.dorr_indices 在 3406 上会在 nanargmin 处崩（空髓腔）；套一层只对 Femur3406 报错的守卫，CT 对象原样放行。"""
    if getattr(FR, "_guard_3406", False):
        return
    s0, d0 = FR.summary, FR.dorr_indices

    def summary_guard(fm):
        if isinstance(fm, Femur3406):
            raise TypeError("femur_real.summary() is for the CT femur; use femur_3406.summary(fm) / validate(fm)")
        return s0(fm)

    def dorr_guard(fm):
        if isinstance(fm, Femur3406):
            raise TypeError("dorr_indices() is undefined for the Sawbones 3406 (empty canal between z -150 and -40)")
        return d0(fm)
    FR.summary, FR.dorr_indices, FR._guard_3406 = summary_guard, dorr_guard, True


_guard_fr()


def _cache_key(cfg: dict) -> str:
    src = (HERE / "femur_3406.py").read_bytes()
    fc = {k: v for k, v in cfg["femur"].items() if k != "neck_axis"}       # 颈轴不进键：切换颈轴不用重建距离场
    return hashlib.sha1(src + json.dumps(fc, sort_keys=True).encode()).hexdigest()[:10]


def build(verbose: bool = False, neck_axis=None) -> Femur3406:
    cfg = load_cfg(neck_axis)
    fc = cfg["femur"]
    CACHE.mkdir(exist_ok=True)
    f = CACHE / f"femur_3406_{_cache_key(cfg)}.npz"
    if f.exists():
        d = np.load(f, allow_pickle=True)
        lm = apply_neck_axis(d["lm"].item(), fc["neck_axis"])
        return Femur3406(lm=lm, g0=d["g0"], h=float(d["h"]), sdf_c=d["sdf_c"], sdf_o=d["sdf_o"], cfg=cfg)
    FR.check_sources(cfg)
    t0 = time.time()
    tess = tessellate(cfg)
    t_tess = time.time() - t0
    lm = FR.landmarks(tess["Vo"])                                          # 分类器的外膜顶点集（含空髓腔壁；头、髁、小转子都在外膜上）
    lm["neck_axis_candidates"] = neck_axis_candidates(lm, tess["Vo"], tess["Fo"])
    Rm, org = lm["Rm"], lm["origin"]
    Vc = (tess["Vc"] - org) @ Rm.T
    Vo = (tess["Vo"] - org) @ Rm.T
    Va = (tess["Va"] - org) @ Rm.T
    h = float(fc["voxel_mm"])
    box = np.array(fc["box_mm"], float)
    g0 = box[:, 0]
    shape = tuple(int(round((b[1] - b[0]) / h)) for b in box)
    sdf_c, in_c, odd_c = FR.signed_distance(Vc, tess["Fc"], g0, h, shape)
    sdf_o, in_o, odd_o, parts = signed_distance_union(Va, tess["Fa"], Vc, tess["Fc"], Vo, tess["Fo"], tess["Fx"], g0, h, shape)
    lm.update(femur_id=FEMUR_ID, occ=tess["occ"], n_faces=tess["n_faces"],
              n_tri={"canal": int(len(tess["Fc"])), "outer": int(len(tess["Fo"])), "all_cortical": int(len(tess["Fa"])),
                     "core_exposed": int(len(tess["Fx"]))},
              parity_odd_columns={"canal": int(odd_c), "outer_all_cortical": odd_o["all_cortical"], "outer_core": odd_o["core"]},
              voxel_volume_in_box_mm3={"canal": float(in_c.sum() * h ** 3), "outer": float(in_o.sum() * h ** 3),
                                       "cortex_only": float(parts["cortex_only"].sum() * h ** 3),
                                       "cortex_core_overlap": float((parts["cortex_only"] & parts["core"]).sum() * h ** 3)},
              core_extent_m={"min": Vc.min(0).tolist(), "max": Vc.max(0).tolist()},
              periosteal_extent_m={"min": Vo.min(0).tolist(), "max": Vo.max(0).tolist()},
              surf_sample_sdf_abs_p95={}, build_s=time.time() - t0, tess_s=t_tess)
    fm = Femur3406(lm=lm, g0=g0, h=h, sdf_c=sdf_c, sdf_o=sdf_o, cfg=cfg)
    rng = np.random.default_rng(0)
    So = [FR._surface_samples(Vo, tess["Fo"], 2)]
    if len(tess["Fx"]):
        So.append(FR._surface_samples(Vc, tess["Fx"], 2))
    for nm, S, fn in (("canal", FR._surface_samples(Vc, tess["Fc"], 2), fm.canal_sdf), ("outer", np.vstack(So), fm.outer_sdf)):
        S = S[np.all((S > g0 + 1) & (S < box[:, 1] - 1), axis=1)]
        S = S[rng.choice(len(S), min(20000, len(S)), replace=False)]
        lm["surf_sample_sdf_abs_p95"][nm] = float(np.percentile(np.abs(fn(S)), 95))
    np.savez_compressed(f, lm=np.array(lm, dtype=object), g0=g0, h=h, sdf_c=sdf_c, sdf_o=sdf_o)
    np.savez_compressed(CACHE / "femur_3406_surfaces.npz", Vc=Vc, Fc=tess["Fc"], Fx=tess["Fx"], Vo=Vo, Fo=tess["Fo"])
    fm.lm = apply_neck_axis(lm, fc["neck_axis"])
    fm.__post_init__()
    if verbose:
        print(f"built in {time.time() - t0:.0f} s -> {f.name}")
    return fm


# ------------------------------------------------------------------ 5 进程内安装（jobs.prep 对带 femur_id 的作业调用）
_ORIG = {"A_BOUNDS": tuple(G.A_BOUNDS)}


def install(a_cap: float = A_BOUNDS_CAP) -> dict:
    """只在本进程把 geom3d.A_BOUNDS 的上限放到 a_cap（template 按调用时读取）；返回记录，S3 写进 prep.json。"""
    G.A_BOUNDS = (float(_ORIG["A_BOUNDS"][0]), float(a_cap))
    return {"femur_id": FEMUR_ID, "A_BOUNDS": [float(x) for x in G.A_BOUNDS], "A_BOUNDS_hashed": [float(x) for x in _ORIG["A_BOUNDS"]],
            "E_cancellous": E_CANCELLOUS, "default_neck_axis": DEFAULT_NECK_AXIS}


def uninstall() -> None:
    G.A_BOUNDS = _ORIG["A_BOUNDS"]


# ------------------------------------------------------------------ 6 摘要与验证（不调 dorr_indices）
def summary(fm: Femur3406) -> dict:
    lm, ref = fm.lm, fm.cfg["femur"]["reference_landmarks"]
    s = {k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in lm.items()
         if k not in ("lt_profile", "Rm", "neck_axis_candidates")}
    s["neck_axis_candidates"] = {k: {kk: (vv.tolist() if isinstance(vv, np.ndarray) else vv) for kk, vv in v.items() if kk != "iterations"}
                                 for k, v in lm["neck_axis_candidates"].items()}
    s["check_vs_readme"] = {"head_r_diff_mm": lm["head_r"] - ref["head_r"],
                            "neck_shaft_diff_deg": lm["neck_shaft_deg"] - ref["neck_shaft_deg"],
                            "anteversion_diff_deg": lm["anteversion_deg"] - ref["anteversion_deg"],
                            "head_c_diff_mm": float(np.linalg.norm(np.asarray(lm["head_c"]) - README["head_c"])),
                            "length_diff_mm": lm["length_mm"] - README["length_mm"]}
    s["cut_center_m"] = fm.C03.tolist()
    s["dorr"] = fm.dorr
    return s


def cut_centres(fm: Femur3406, h_cuts=(25.0, 32.0)) -> dict:
    return {f"h{h:g}": fm.with_cut(h).C03.tolist() for h in h_cuts}


def validate(fm: Femur3406, occ: bool = True) -> dict:
    """V1：奇偶列、体素 vs OCC 体积（< 0.5 %）、表面 |sdf| p95；标志点对 README；截骨中心；芯底；头与盒子。"""
    lm, h = fm.lm, fm.h
    box = np.array(fm.cfg["femur"]["box_mm"], float)
    out = {"femur_id": FEMUR_ID, "neck_axis": lm["neck_axis"], "parity_odd_columns": lm["parity_odd_columns"],
           "surf_sample_sdf_abs_p95": lm["surf_sample_sdf_abs_p95"], "voxel_volume_in_box_mm3": lm["voxel_volume_in_box_mm3"],
           "n_faces": lm["n_faces"], "n_tri": lm["n_tri"], "build_s": lm.get("build_s")}
    if occ:
        v = FR.occ_volume_in_box(fm)
        out["occ_volume_in_box_mm3"] = v
        out["volume_rel_err_pct"] = {"canal": 100.0 * (lm["voxel_volume_in_box_mm3"]["canal"] / v["canal_occ_mm3"] - 1.0),
                                     "outer": 100.0 * (lm["voxel_volume_in_box_mm3"]["outer"] / v["outer_occ_mm3"] - 1.0)}
    hc = np.asarray(lm["head_c"], float)
    out["landmarks_vs_readme"] = {
        "head_c_baked": hc.tolist(), "head_c_readme_baked": README["head_c"].tolist(), "head_c_diff_mm": float(np.linalg.norm(hc - README["head_c"])),
        "head_r": lm["head_r"], "head_r_readme": README["head_r"], "length_mm": lm["length_mm"], "length_readme": README["length_mm"],
        "offset_mm": lm["offset_mm"], "lt_below_head_mm": float(lm["head_m"][2]),
        "neck_shaft_deg": lm["neck_shaft_deg"], "anteversion_deg": lm["anteversion_deg"],
        "readme": {"neck_shaft_deg": README["neck_shaft_deg"], "anteversion_deg": README["anteversion_deg"]}}
    out["neck_axis_options"] = {k: {"neck_shaft_deg": v["neck_shaft_deg"], "anteversion_deg": v["anteversion_deg"],
                                    "angle_to_detector_deg": v["angle_to_detector_deg"], "u_baked": [float(x) for x in v["u"]],
                                    **({"d_mm": v["d_mm"], "area_mm2": v["area_mm2"], "d_eq_mm": v["d_eq_mm"]} if k == "isthmus" else {}),
                                    **({"d_mm": v["d_mm"], "width_mm": v["width_mm"]} if k == "silhouette" else {})}
                                for k, v in lm["neck_axis_candidates"].items()}
    out["cut_centres_m"] = cut_centres(fm)
    out["core_extent_m"] = lm["core_extent_m"]
    out["core_bottom_below_head_mm"] = float(lm["head_m"][2] - lm["core_extent_m"]["min"][2])
    head_top = float(lm["head_m"][2] + lm["head_r"]); head_med = float(lm["head_m"][0] + lm["head_r"])
    out["head_box_check"] = {"head_top_z": head_top, "box_z_max": float(box[2, 1]), "head_top_inside": head_top < box[2, 1],
                             "head_medial_x": head_med, "box_x_max": float(box[0, 1]), "head_medial_inside": head_med < box[0, 1],
                             "periosteal_extent_m": lm["periosteal_extent_m"]}
    gz = fm.g0[2] + (np.arange(fm.sdf_c.shape[2]) + 0.5) * h                     # 空髓腔：每层是否有松质 / 皮质
    has_core = (fm.sdf_c <= 0).any(axis=(0, 1))
    out["empty_canal"] = {"lowest_z_with_core": float(gz[has_core].min()) if has_core.any() else None,
                          "z_trunc": fm.z_trunc, "core_present_at_z_trunc": bool(has_core[np.argmin(np.abs(gz - fm.z_trunc))])}
    out["checks"] = {"parity_zero": all(v == 0 for v in lm["parity_odd_columns"].values()),
                     "sdf_p95_ok": all(v < 0.1 for v in lm["surf_sample_sdf_abs_p95"].values()),
                     "volume_ok": (all(abs(v) < 0.5 for v in out["volume_rel_err_pct"].values()) if occ else None),
                     "head_c_ok": out["landmarks_vs_readme"]["head_c_diff_mm"] < 1.0,
                     "head_in_box": head_top < box[2, 1] and head_med < box[0, 1]}
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--neck-axis", default=None)
    ap.add_argument("--check-occ", action="store_true")
    a = ap.parse_args()
    fm = build(verbose=True, neck_axis=a.neck_axis)
    s = summary(fm)
    if a.check_occ:
        s["validate"] = validate(fm, occ=True)
    FR.OUT.mkdir(exist_ok=True)
    (FR.OUT / "femur_3406_summary.json").write_text(json.dumps(s, indent=1, default=float), encoding="utf-8")
    print(json.dumps(s, indent=1, default=float))
