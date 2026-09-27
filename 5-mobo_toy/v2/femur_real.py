"""V2A 真实股骨：G:\\hip\\260429 test 2bones 的两个 STEP 件（复制在 v2/data/femur_real/，sha256 见 SHA256SUMS.txt）。

几何源的选择（见计划"股骨模型评估"）：CAE / D:\\temp\\Job-1.inp 的皮质件是"实心整根股骨 + 髓腔塞"，STL 非流形；只有 STEP 干净。
  cortical …-sorted.STEP → OCC 导入为 1 个中空实体（外膜壳 + 内膜空腔），287 cm³
  cancellous ….STEP      → 1 个实体，197 cm³

流程
1. 三角化（gmsh 2D，tess_mm）：松质件边界 = 内膜面；皮质件边界中离内膜面 > 0.3 mm 的面 = 外膜面。
2. 解剖标志：算法移植自 straight3d/realfemur.py 的 landmarks（那边作用在 Job-1 四面体外表面，这里作用在 STEP 外膜面顶点）：
   头心（球拟合 + 迭代剔除）、干轴（近端下 150–330 mm 各层质心的直线）、后髁连线、颈轴（头心出发的截面质心迭代）、
   小转子（头心下 25–95 mm"后内"方向凸出去趋势后的峰）。
3. 模型坐标（与 straight3d 相同）：z = 干轴（向近端），x = 后髁连线在横断面内的投影（指向内侧），y = z × x（后方），
   原点 = 干轴上小转子高度。右手系，STEP 可以刚体变换进来，不镜像。前方 = −y。
4. 距离场（体素 voxel_mm，范围 box_mm）：内外判定用沿 z 的射线奇偶（用整张闭合面，不受盒子截断影响）；
   距离先用 EDT，离壁 3 mm 内再用表面密采样点的 KD 树精修。canal_sdf、outer_sdf 都是"外正内负"。
5. 对 geom3d.template 暴露与解析股骨相同的接口：pose(α, e)、to_world、canal_excess、outer_excess、below_cut。
   α 在颈平面内（过截骨中心，由干轴与颈轴张成），相对干轴；柄截面 y 轴取前方。
"""
from __future__ import annotations

import hashlib
import json
import math
import pathlib
import sys
import time
from dataclasses import dataclass, field

import numpy as np
import yaml

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import geom3d as G  # noqa: E402

CFG_PATH = HERE / "config_v2a.yaml"
DATA = HERE / "data" / "femur_real"
CACHE = HERE / "cache"
OUT = HERE / "out"


def load_cfg() -> dict:
    return yaml.safe_load(CFG_PATH.read_text(encoding="utf-8"))


def _sha256(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def check_sources(cfg: dict) -> None:
    fc = cfg["femur"]
    for k in ("cortical", "cancellous"):
        p = DATA / fc[f"step_{k}"]
        if not p.exists():
            raise FileNotFoundError(p)
        if _sha256(p) != fc[f"sha256_{k}"]:
            raise RuntimeError(f"STEP checksum mismatch: {p}")


# ------------------------------------------------------------------ 1 三角化
def tessellate(cfg: dict) -> dict:
    """CT 坐标下的内膜面 (Vc, Fc) 与外膜面 (Vo, Fo)，以及两件 OCC 体积。"""
    import gmsh
    from scipy.spatial import cKDTree
    fc = cfg["femur"]
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        occ = gmsh.model.occ
        C = [x for x in occ.importShapes(str(DATA / fc["step_cortical"])) if x[0] == 3]
        K = [x for x in occ.importShapes(str(DATA / fc["step_cancellous"])) if x[0] == 3]
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
    # 内膜面密采样（约 0.27 mm 间距）再比距离：只和顶点比时，重合面的三角形心到最近顶点也有 0.3–0.4 mm，会被误判为外膜面
    tree = cKDTree(_surface_samples(xyz, Fk, 3))
    outer, n_inner = [], 0
    for s, F in TC.items():                               # 皮质边界中远离内膜面者 = 外膜面
        d, _ = tree.query(xyz[F].mean(1))
        if np.median(d) > 0.3:
            outer.append(F)
        else:
            n_inner += 1
    if not outer:
        raise RuntimeError("no periosteal faces identified")
    if n_inner == 0:
        raise RuntimeError("no cortical faces coincide with the endosteal surface; the cortical STEP is expected to be hollow")
    Fo = np.vstack(outer)

    def compact(F):
        used = np.unique(F)
        m = np.full(len(xyz), -1); m[used] = np.arange(len(used))
        return xyz[used], m[F]
    Vc, Fc_ = compact(Fk)
    Vo, Fo_ = compact(Fo)
    return {"Vc": Vc, "Fc": Fc_, "Vo": Vo, "Fo": Fo_, "occ": vol,
            "n_faces": {"cortical_brep": len(sC), "cancellous_brep": len(sK), "periosteal_brep": len(outer),
                        "cortical_inner_shell_brep": n_inner}}


# ------------------------------------------------------------------ 2 解剖标志（移植自 straight3d/realfemur.py）
def _fit_sphere(P):
    A = np.c_[2 * P, np.ones(len(P))]
    b = (P ** 2).sum(1)
    x, *_ = np.linalg.lstsq(A, b, rcond=None)
    c = x[:3]
    return c, math.sqrt(x[3] + c @ c)


def _fit_line(P):
    c = P.mean(0)
    _, _, vt = np.linalg.svd(P - c)
    return c, vt[0]


def landmarks(V: np.ndarray) -> dict:
    """V：外膜面顶点（CT 坐标，LPS：x 左、y 后、z 上；右股骨 ⇒ 内侧 = +x）。"""
    z0, z1 = V[:, 2].min(), V[:, 2].max()
    top = V[V[:, 2] > z1 - 55]
    cand = top[top[:, 0] > np.percentile(top[:, 0], 55)]
    c, r = _fit_sphere(cand)
    for _ in range(8):
        res = np.abs(np.linalg.norm(V - c, axis=1) - r)
        sel = V[(res < 1.5) & (np.linalg.norm(V - c, axis=1) < r + 6)]
        c, r = _fit_sphere(sel)
    head_c, head_r, n_head = c, r, len(sel)
    cents = []
    for z in np.arange(z1 - 330, z1 - 150, 5.0):
        s = V[np.abs(V[:, 2] - z) < 1.0]
        if len(s) > 30:
            cents.append(s.mean(0))
    ax_c, ax_d = _fit_line(np.array(cents))
    if ax_d[2] < 0:
        ax_d = -ax_d
    dist = V[V[:, 2] < z0 + 30]
    xm = ax_c[0] + ax_d[0] * (dist[:, 2].mean() - ax_c[2]) / ax_d[2]
    med, lat = dist[dist[:, 0] > xm], dist[dist[:, 0] <= xm]
    p_med, p_lat = med[np.argmax(med[:, 1])], lat[np.argmax(lat[:, 1])]
    ez = ax_d / np.linalg.norm(ax_d)
    ex = (p_med - p_lat) - ((p_med - p_lat) @ ez) * ez
    ex /= np.linalg.norm(ex)
    ey = np.cross(ez, ex)
    Rm = np.vstack([ex, ey, ez])

    def foot(p):
        return ax_c + ((p - ax_c) @ ez) * ez
    u = head_c - foot(head_c - 40 * ez)
    u /= np.linalg.norm(u)
    for _ in range(10):
        pts = []
        for t in (head_r + 4, head_r + 8, head_r + 12):
            q = head_c - t * u
            s = V[np.abs((V - q) @ u) < 0.8]
            s = s[np.linalg.norm((s - q) - ((s - q) @ u)[:, None] * u, axis=1) < 22]
            if len(s) > 20:
                pts.append(s.mean(0))
        c_n, d_n = _fit_line(np.vstack([head_c, *pts]))
        if d_n @ u < 0:
            d_n = -d_n
        if np.linalg.norm(d_n - u) < 1e-4:
            break
        u = d_n
    Hm = (head_c - ax_c) @ Rm.T
    Vm = (V - ax_c) @ Rm.T
    zs = np.arange(Hm[2] - 95, Hm[2] - 25, 1.0)
    prom = []
    for z in zs:
        s = Vm[np.abs(Vm[:, 2] - z) < 0.5]
        prom.append(((s[:, 0] + s[:, 1]) / math.sqrt(2)).max() if len(s) else np.nan)
    prom = np.array(prom)
    trend = np.polyval(np.polyfit(zs, prom, 1), zs)
    z_lt = float(zs[np.nanargmax(prom - trend)])
    origin = ax_c + z_lt * ez
    un = u / np.linalg.norm(u)
    ccd = math.degrees(math.acos(float(np.clip(un @ ez, -1, 1))))
    un_t = un - (un @ ez) * ez
    anteversion = math.degrees(math.atan2(-(un_t @ ey), un_t @ ex))
    head_m = (head_c - origin) @ Rm.T
    u_m = un @ Rm.T
    # 偏距：头心到干轴的距离
    offset = float(np.linalg.norm(head_m[:2]))
    return {"Rm": Rm, "origin": origin, "head_c": head_c, "head_r": float(head_r), "n_head_pts": int(n_head),
            "neck_u": un, "shaft_c": ax_c, "shaft_d": ez, "p_med_condyle": p_med, "p_lat_condyle": p_lat,
            "neck_shaft_deg": 180.0 - ccd, "anteversion_deg": anteversion, "offset_mm": offset,
            "head_m": head_m, "neck_u_m": u_m / np.linalg.norm(u_m), "lt_profile": np.c_[zs, prom - trend],
            "length_mm": float(z1 - z0)}


# ------------------------------------------------------------------ 3 距离场
def _parity_inside(Vm, F, g0, h, shape, jitter=(1.3e-5, 0.7e-5)):
    """沿 +z 的射线奇偶判内外：体素中心在闭合面内为 True。Vm、F 为模型坐标下的三角网格（整张闭合面）。"""
    nx, ny, nz = shape
    xs = g0[0] + (np.arange(nx) + 0.5) * h + jitter[0]
    ys = g0[1] + (np.arange(ny) + 0.5) * h + jitter[1]
    T = Vm[F]
    A, B, C = T[:, 0], T[:, 1], T[:, 2]
    den = (B[:, 1] - C[:, 1]) * (A[:, 0] - C[:, 0]) + (C[:, 0] - B[:, 0]) * (A[:, 1] - C[:, 1])
    ok = np.abs(den) > 1e-12
    A, B, C, den = A[ok], B[ok], C[ok], den[ok]
    lo_i = np.clip(np.ceil((np.minimum.reduce([A[:, 0], B[:, 0], C[:, 0]]) - xs[0]) / h), 0, nx - 1).astype(int)
    hi_i = np.clip(np.floor((np.maximum.reduce([A[:, 0], B[:, 0], C[:, 0]]) - xs[0]) / h), -1, nx - 1).astype(int)
    lo_j = np.clip(np.ceil((np.minimum.reduce([A[:, 1], B[:, 1], C[:, 1]]) - ys[0]) / h), 0, ny - 1).astype(int)
    hi_j = np.clip(np.floor((np.maximum.reduce([A[:, 1], B[:, 1], C[:, 1]]) - ys[0]) / h), -1, ny - 1).astype(int)
    keep = (hi_i >= lo_i) & (hi_j >= lo_j)
    A, B, C, den, lo_i, hi_i, lo_j, hi_j = (a[keep] for a in (A, B, C, den, lo_i, hi_i, lo_j, hi_j))
    cols, zz = [], []
    ki, kj = (hi_i - lo_i + 1), (hi_j - lo_j + 1)
    for mi in np.unique(ki):
        for mj in np.unique(kj[ki == mi]):
            sel = np.nonzero((ki == mi) & (kj == mj))[0]
            if not len(sel):
                continue
            di, dj = np.meshgrid(np.arange(mi), np.arange(mj), indexing="ij")
            I = lo_i[sel][:, None] + di.ravel()[None]
            J = lo_j[sel][:, None] + dj.ravel()[None]
            px, py = xs[I], ys[J]
            a, b, c, dn = A[sel][:, None], B[sel][:, None], C[sel][:, None], den[sel][:, None]
            l1 = ((b[..., 1] - c[..., 1]) * (px - c[..., 0]) + (c[..., 0] - b[..., 0]) * (py - c[..., 1])) / dn
            l2 = ((c[..., 1] - a[..., 1]) * (px - c[..., 0]) + (a[..., 0] - c[..., 0]) * (py - c[..., 1])) / dn
            l3 = 1 - l1 - l2
            m = (l1 >= 0) & (l2 >= 0) & (l3 >= 0)
            z = l1 * a[..., 2] + l2 * b[..., 2] + l3 * c[..., 2]
            cols.append((I * ny + J)[m]); zz.append(z[m])
    cols = np.concatenate(cols); zz = np.concatenate(zz)
    o = np.lexsort((zz, cols))
    cols, zz = cols[o], zz[o]
    grid = np.zeros(shape, bool)
    starts = np.r_[0, np.nonzero(np.diff(cols))[0] + 1]
    ends = np.r_[starts[1:], len(cols)]
    n_odd = 0
    zc0 = g0[2] + 0.5 * h
    for s, e in zip(starts, ends):
        z = zz[s:e]
        if len(z) % 2:
            n_odd += 1
            z = z[:-1]
        c = cols[s]; i, j = divmod(int(c), ny)
        for a_, b_ in zip(z[0::2], z[1::2]):
            k0 = max(int(math.ceil((a_ - zc0) / h)), 0)
            k1 = min(int(math.floor((b_ - zc0) / h)), nz - 1)
            if k1 >= k0:
                grid[i, j, k0:k1 + 1] = True
    return grid, n_odd


def _surface_samples(Vm, F, n=3):
    """每个三角形按重心坐标取 (n+1)(n+2)/2 个点（含顶点与边上点）。"""
    ij = [(a, b) for a in range(n + 1) for b in range(n + 1 - a)]
    W = np.array([(a / n, b / n, 1 - a / n - b / n) for a, b in ij])
    T = Vm[F]
    return np.einsum("kv,tvd->tkd", W, T).reshape(-1, 3)


def signed_distance(Vm, F, g0, h, shape, band=3.0):
    from scipy.ndimage import distance_transform_edt
    from scipy.spatial import cKDTree
    inside, n_odd = _parity_inside(Vm, F, g0, h, shape)
    d_in = distance_transform_edt(inside, sampling=h)
    d_out = distance_transform_edt(~inside, sampling=h)
    sdf = np.where(inside, -(d_in - 0.5 * h), d_out - 0.5 * h).astype(np.float32)
    idx = np.nonzero(np.abs(sdf) < band)
    P = g0 + (np.c_[idx] + 0.5) * h
    tree = cKDTree(_surface_samples(Vm, F))
    d, _ = tree.query(P, workers=-1)
    sdf[idx] = np.where(inside[idx], -d, d).astype(np.float32)
    return sdf, inside, n_odd


# ------------------------------------------------------------------ 4 股骨对象
@dataclass
class RealFemur:
    lm: dict = field(repr=False)
    g0: np.ndarray = None
    h: float = 0.5
    sdf_c: np.ndarray = field(default=None, repr=False)
    sdf_o: np.ndarray = field(default=None, repr=False)
    cfg: dict = field(default=None, repr=False)
    dorr = "A (real femur)"

    def __post_init__(self):
        fc = self.cfg["femur"]
        self.H = np.asarray(self.lm["head_m"], float)
        self.u3 = np.asarray(self.lm["neck_u_m"], float)
        self.Rh = float(self.lm["head_r"])
        self.C03 = self.H - fc["cut_from_head_mm"] * self.u3
        self.ez = np.array([0.0, 0.0, 1.0])
        e = self.u3 - (self.u3 @ self.ez) * self.ez
        self.e_med0 = e / np.linalg.norm(e)                       # 颈平面内、垂直干轴、指向内侧（头侧）
        n = self.e_med0 - (self.e_med0 @ self.u3) * self.u3
        self.n3 = n / np.linalg.norm(n)                           # 截骨面内、颈平面内、指向内下
        self.ant = np.array([0.0, -1.0, 0.0])                     # +y 为后方
        self.z_trunc = float(fc["z_trunc_mm"])

    def _interp(self, grid, P, cval):
        from scipy.ndimage import map_coordinates
        idx = ((np.atleast_2d(P) - self.g0) / self.h - 0.5).T
        return map_coordinates(grid, idx, order=1, mode="constant", cval=cval)

    def canal_sdf(self, P):
        return self._interp(self.sdf_c, P, 50.0)

    def outer_sdf(self, P):
        return self._interp(self.sdf_o, P, 50.0)

    def canal_excess(self, P):
        return np.maximum(self.canal_sdf(P), 0.0)

    def outer_excess(self, P):
        return np.maximum(self.outer_sdf(P), 0.0)

    def below_cut(self, P):
        return (np.atleast_2d(P) - self.C03) @ self.u3 <= 0

    def pose(self, alpha_deg: float, e: float):
        a = math.radians(alpha_deg)
        d = -math.sin(a) * self.e_med0 - math.cos(a) * self.ez
        e_ml = math.cos(a) * self.e_med0 - math.sin(a) * self.ez
        e_ap = np.cross(d, e_ml)
        e_ap /= np.linalg.norm(e_ap)
        if e_ap @ self.ant < 0:
            e_ap = -e_ap
        return self.C03 + e * self.n3, d, e_ml, e_ap

    to_world = staticmethod(G.Femur3D.to_world)

    def labels_on_plane(self, C, e1, e2, half=25.0, h=0.2):
        """平面上的标签图：0 骨外、1 皮质、2 松质；另返回截骨面以下的掩码。"""
        u = np.arange(-half, half + h, h)
        U, V = np.meshgrid(u, u)
        P = C + U.reshape(-1, 1) * e1 + V.reshape(-1, 1) * e2
        lab = np.where(self.canal_sdf(P) <= 0, 2, np.where(self.outer_sdf(P) <= 0, 1, 0)).reshape(U.shape)
        return u, lab, self.below_cut(P).reshape(U.shape)

    def neck_plane(self):
        """颈平面基：原点 C0，e1 = e_med0（内侧），e2 = ez（向近端）。"""
        return self.C03, self.e_med0, self.ez


def _cache_key(cfg: dict) -> str:
    src = (HERE / "femur_real.py").read_bytes()
    fc = json.dumps(cfg["femur"], sort_keys=True).encode()
    return hashlib.sha1(src + fc).hexdigest()[:10]


def build(verbose: bool = False) -> RealFemur:
    cfg = load_cfg()
    fc = cfg["femur"]
    CACHE.mkdir(exist_ok=True)
    f = CACHE / f"femur_real_{_cache_key(cfg)}.npz"
    if f.exists():
        d = np.load(f, allow_pickle=True)
        return RealFemur(lm=d["lm"].item(), g0=d["g0"], h=float(d["h"]), sdf_c=d["sdf_c"], sdf_o=d["sdf_o"], cfg=cfg)
    check_sources(cfg)
    t0 = time.time()
    tess = tessellate(cfg)
    lm = landmarks(tess["Vo"])
    Rm, org = lm["Rm"], lm["origin"]
    Vc = (tess["Vc"] - org) @ Rm.T
    Vo = (tess["Vo"] - org) @ Rm.T
    h = float(fc["voxel_mm"])
    box = np.array(fc["box_mm"], float)
    g0 = box[:, 0]
    shape = tuple(int(round((b[1] - b[0]) / h)) for b in box)
    sdf_c, in_c, odd_c = signed_distance(Vc, tess["Fc"], g0, h, shape)
    sdf_o, in_o, odd_o = signed_distance(Vo, tess["Fo"], g0, h, shape)
    lm.update(occ=tess["occ"], n_faces=tess["n_faces"], n_tri={"canal": int(len(tess["Fc"])), "outer": int(len(tess["Fo"]))},
              parity_odd_columns={"canal": odd_c, "outer": odd_o},
              voxel_volume_in_box_mm3={"canal": float(in_c.sum() * h ** 3), "outer": float(in_o.sum() * h ** 3)},
              surf_sample_sdf_abs_p95={}, build_s=time.time() - t0)
    fm = RealFemur(lm=lm, g0=g0, h=h, sdf_c=sdf_c, sdf_o=sdf_o, cfg=cfg)
    # 自检：内膜面、外膜面采样点上的 |sdf| 应接近 0
    rng = np.random.default_rng(0)
    for nm, V, F, fn in (("canal", Vc, tess["Fc"], fm.canal_sdf), ("outer", Vo, tess["Fo"], fm.outer_sdf)):
        S = _surface_samples(V, F, 2)
        S = S[np.all((S > g0 + 1) & (S < box[:, 1] - 1), axis=1)]
        S = S[rng.choice(len(S), min(20000, len(S)), replace=False)]
        lm["surf_sample_sdf_abs_p95"][nm] = float(np.percentile(np.abs(fn(S)), 95))
    np.savez_compressed(f, lm=np.array(lm, dtype=object), g0=g0, h=h, sdf_c=sdf_c, sdf_o=sdf_o)
    np.savez_compressed(CACHE / "femur_real_surfaces.npz", Vc=Vc, Fc=tess["Fc"], Vo=Vo, Fo=tess["Fo"])
    if verbose:
        print(f"built in {time.time() - t0:.0f} s -> {f.name}")
    return fm


def occ_volume_in_box(fm: RealFemur) -> dict:
    """独立复核：把两件 STEP 刚体变换到模型坐标，与距离场盒子求交，比体积（松质、外膜所围）。"""
    import gmsh
    fc = fm.cfg["femur"]
    Rm, org = fm.lm["Rm"], fm.lm["origin"]
    M = np.eye(4); M[:3, :3] = Rm; M[:3, 3] = -Rm @ org
    box = np.array(fc["box_mm"], float)
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        occ = gmsh.model.occ
        C = [x for x in occ.importShapes(str(DATA / fc["step_cortical"])) if x[0] == 3]
        K = [x for x in occ.importShapes(str(DATA / fc["step_cancellous"])) if x[0] == 3]
        occ.affineTransform(C + K, list(M[:3].ravel()))
        b1 = occ.addBox(*box[:, 0], *(box[:, 1] - box[:, 0]))
        b2 = occ.addBox(*box[:, 0], *(box[:, 1] - box[:, 0]))
        Kb, _ = occ.intersect(K, [(3, b1)], removeObject=False)
        Cb, _ = occ.intersect(C, [(3, b2)], removeObject=False)
        occ.synchronize()
        v_c = sum(occ.getMass(d, t) for d, t in Kb)
        v_cort = sum(occ.getMass(d, t) for d, t in Cb)
    finally:
        gmsh.finalize()
    return {"canal_occ_mm3": v_c, "outer_occ_mm3": v_c + v_cort}


def dorr_indices(fm: RealFemur) -> dict:
    """两种量法：(a) straight3d 口径——过干轴的冠状弦（y = 0，|x| < 30）；(b) 该高度髓腔在 ML 方向的全宽（|y| < 30）。"""
    xs = np.arange(-45, 75, 0.25)

    def widths(z, full):
        if full:
            ys = np.arange(-30, 30, 0.5)
            X, Y = np.meshgrid(xs, ys)
            P = np.c_[X.ravel(), Y.ravel(), np.full(X.size, z)]
            cin = (fm.canal_sdf(P) <= 0).reshape(X.shape).any(0)
            oin = (fm.outer_sdf(P) <= 0).reshape(X.shape).any(0)
        else:
            P = np.c_[xs, np.zeros_like(xs), np.full_like(xs, z)]
            cin, oin = fm.canal_sdf(P) <= 0, fm.outer_sdf(P) <= 0
        near = np.abs(xs) < 30
        cx, ox = xs[cin & near], xs[oin & near]
        return (cx.max() - cx.min() if len(cx) else np.nan, ox.max() - ox.min() if len(ox) else np.nan)
    out = {}
    for tag, full in (("chord_y0", False), ("full_width", True)):
        zi = np.arange(-150, -40, 1.0)
        cw = np.array([widths(z, full)[0] for z in zi])
        j = int(np.nanargmin(cw))
        c20, o20 = widths(20.0, full)
        c100, o100 = widths(-100.0, full)
        cfi, ci = c20 / cw[j], (o100 - c100) / o100
        out[tag] = {"canal_LT+20": c20, "canal_isthmus": float(cw[j]), "z_isthmus": float(zi[j]),
                    "canal_LT-100": c100, "outer_LT-100": o100, "CFI": cfi, "CI": ci,
                    "dorr_by_CFI": "A" if cfi >= 4.7 else ("B" if cfi >= 3.0 else "C"),
                    "dorr_by_CI": "A" if ci >= 0.58 else ("B" if ci >= 0.49 else "C")}
    return out


def summary(fm: RealFemur) -> dict:
    lm, ref = fm.lm, fm.cfg["femur"]["reference_landmarks"]
    s = {k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in lm.items()
         if k not in ("lt_profile", "Rm")}
    s["check_vs_straight3d"] = {
        "head_r_diff_mm": lm["head_r"] - ref["head_r"],
        "neck_shaft_diff_deg": lm["neck_shaft_deg"] - ref["neck_shaft_deg"],
        "anteversion_diff_deg": lm["anteversion_deg"] - ref["anteversion_deg"]}
    s["dorr"] = dorr_indices(fm)
    s["cut_center_m"] = fm.C03.tolist()
    return s


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--check-occ", action="store_true")
    a = ap.parse_args()
    fm = build(verbose=True)
    s = summary(fm)
    if a.check_occ:
        s["occ_in_box"] = occ_volume_in_box(fm)
    OUT.mkdir(exist_ok=True)
    (OUT / "femur_real_summary.json").write_text(json.dumps(s, indent=1, default=float), encoding="utf-8")
    print(json.dumps(s, indent=1, default=float))
