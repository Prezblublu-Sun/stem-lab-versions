"""2D 共形网格（gmsh 内核）：shapely 多边形分区 → 二阶三角形 CPS6M 用的节点与单元。

做法
----
1. 把一组区域（如 皮质、松质）的边界线全部打断成互不相交的边（共享边只出现一次）。
2. 每条边按局部目标尺寸 h(x, z) 重采样（保留端点与尖角），共享边两侧用同一套点，
   所以相邻区域天然共形。
3. polygonize 得到面，按代表点归属到区域；gmsh 以这些点为边界节点（每段直线只放两端点），
   内部按 h(x, z) 生成三角形，再升为二阶（6 节点）。
4. 单元统一为逆时针（Abaqus 要求正面积），并报告最小角等质量指标。

不同的共形集合（例如 骨 与 柄）分别调用 `mesh_partition`，节点编号用 offset 错开；
集合之间不共享节点（柄–骨之间是接触或 TIE）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import shapely
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.ops import linemerge, polygonize, unary_union

SizeFn = Callable[[float, float], float]


@dataclass
class Mesh:
    node_labels: np.ndarray                       # (N,)
    nodes: np.ndarray                             # (N, 2) mm
    elems: dict[str, np.ndarray] = field(default_factory=dict)        # 区域 → (M, 6) 节点号
    elem_labels: dict[str, np.ndarray] = field(default_factory=dict)  # 区域 → (M,) 单元号
    quality: dict = field(default_factory=dict)

    @property
    def n_elems(self) -> int:
        return int(sum(len(v) for v in self.elems.values()))

    def coords(self, labels) -> np.ndarray:
        idx = self._index()[np.asarray(labels)]
        return self.nodes[idx]

    def _index(self) -> np.ndarray:
        if not hasattr(self, "_idx"):
            lut = np.full(int(self.node_labels.max()) + 1, -1, dtype=np.int64)
            lut[self.node_labels] = np.arange(len(self.node_labels))
            self._idx = lut
        return self._idx

    def centroids(self, region: str) -> np.ndarray:
        return self.coords(self.elems[region][:, :3].ravel()).reshape(-1, 3, 2).mean(axis=1)

    def areas(self, region: str) -> np.ndarray:
        p = self.coords(self.elems[region][:, :3].ravel()).reshape(-1, 3, 2)
        return 0.5 * ((p[:, 1, 0] - p[:, 0, 0]) * (p[:, 2, 1] - p[:, 0, 1])
                      - (p[:, 2, 0] - p[:, 0, 0]) * (p[:, 1, 1] - p[:, 0, 1]))

    def boundary_edges(self, regions: list[str]) -> list[tuple[int, int, int, int]]:
        """集合外边界上的边：(单元号, 面号 1–3, 角节点 a, 角节点 b)。面号按 Abaqus 三角形约定。"""
        count: dict[tuple[int, int], list] = {}
        for r in regions:
            for el, conn in zip(self.elem_labels[r], self.elems[r]):
                for face, (i, j) in enumerate(((0, 1), (1, 2), (2, 0)), start=1):
                    a, b = int(conn[i]), int(conn[j])
                    count.setdefault((min(a, b), max(a, b)), []).append((int(el), face, a, b))
        return [v[0] for v in count.values() if len(v) == 1]


def _as_polys(g) -> list[Polygon]:
    if g is None or g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    if isinstance(g, MultiPolygon):
        return list(g.geoms)
    return [p for p in getattr(g, "geoms", []) if isinstance(p, Polygon)]


def _turn_angles(coords: np.ndarray) -> np.ndarray:
    """折线内部顶点的转角（度）。"""
    d1 = coords[1:-1] - coords[:-2]
    d2 = coords[2:] - coords[1:-1]
    a1 = np.arctan2(d1[:, 1], d1[:, 0])
    a2 = np.arctan2(d2[:, 1], d2[:, 0])
    t = np.degrees(np.abs((a2 - a1 + np.pi) % (2 * np.pi) - np.pi))
    return t


def resample_edge(line: LineString, size_fn: SizeFn, corner_deg: float = 30.0,
                  min_frac: float = 0.35) -> np.ndarray:
    """按局部尺寸重采样一条边，保留两端点与尖角。返回 (K, 2) 点。"""
    c = np.asarray(line.coords)
    closed = np.allclose(c[0], c[-1])
    keep = [0]
    if len(c) > 2:
        ang = _turn_angles(c)
        keep += [i + 1 for i in np.nonzero(ang > corner_deg)[0]]
    keep.append(len(c) - 1)
    keep = sorted(set(keep))
    # 合并过近的尖角（端点永远保留）
    s = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(c, axis=0), axis=1))])
    pruned = [keep[0]]
    for k in keep[1:-1]:
        h = size_fn(*c[k])
        if s[k] - s[pruned[-1]] > min_frac * h and s[-1] - s[k] > min_frac * h:
            pruned.append(k)
    pruned.append(keep[-1])
    out = [c[0]]
    for a, b in zip(pruned[:-1], pruned[1:]):
        seg = LineString(c[a:b + 1])
        ln = seg.length
        if ln <= 0:
            continue
        # 以 ∫ds/h 决定分段数，按尺寸归一化弧长等分
        ns = max(8, int(ln / 0.2))
        tt = np.linspace(0, ln, ns + 1)
        pts = np.array([seg.interpolate(t).coords[0] for t in tt])
        hh = np.array([size_fn(x, y) for x, y in pts])
        w = np.concatenate([[0.0], np.cumsum(0.5 * (1 / hh[1:] + 1 / hh[:-1]) * np.diff(tt))])
        n = max(1, int(round(w[-1])))
        if closed and len(pruned) == 2:
            n = max(n, 3)
        targets = np.interp(np.linspace(0, w[-1], n + 1), w, tt)[1:-1]
        out += [seg.interpolate(t).coords[0] for t in targets]
        out.append(c[b])
    return np.asarray(out)


def mesh_partition(regions: dict[str, object], size_fn: SizeFn, *, node_offset: int = 0,
                   elem_offset: int = 0, name: str = "set", corner_deg: float = 30.0,
                   algorithm: int = 6) -> Mesh:
    """对一组互不重叠的区域做共形二阶三角网格。regions: 名称 → Polygon/MultiPolygon。"""
    import gmsh

    polys = {k: _as_polys(v) for k, v in regions.items()}
    rings = []
    for plist in polys.values():
        for p in plist:
            rings.append(LineString(p.exterior.coords))
            rings += [LineString(r.coords) for r in p.interiors]
    noded = unary_union(rings)                                   # 在交点处打断
    merged = linemerge(noded) if noded.geom_type != "LineString" else noded
    edges = list(getattr(merged, "geoms", [merged]))
    res_edges = [LineString(resample_edge(e, size_fn, corner_deg)) for e in edges]
    faces = list(polygonize(res_edges))
    region_union = {k: unary_union(v) for k, v in polys.items()}

    face_region = []
    for f in faces:
        rp = f.representative_point()
        owner = [k for k, g in region_union.items() if g.buffer(1e-6).contains(rp)]
        face_region.append(owner[0] if owner else None)
    # 每个区域重建后的面积须与原区域相差 < 1 %（弦近似损失在 0.5 % 以内；缺面会差出整块）
    bad = []
    for k, v in polys.items():
        tgt = sum(p.area for p in v)
        got = sum(f.area for f, r in zip(faces, face_region) if r == k)
        if tgt > 0 and abs(got - tgt) > 0.01 * tgt + 0.05:
            bad.append(f"{k}: {got:.2f} of {tgt:.2f} mm²")
    if bad:
        raise RuntimeError("partition rebuild failed: " + "; ".join(bad))

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(name)
        pt: dict[tuple, int] = {}
        ln: dict[tuple, int] = {}

        def point(xy):
            key = (round(float(xy[0]), 6), round(float(xy[1]), 6))
            if key not in pt:
                pt[key] = gmsh.model.geo.addPoint(key[0], key[1], 0.0)
            return pt[key]

        def line(a, b):
            if (a, b) in ln:
                return ln[(a, b)]
            if (b, a) in ln:
                return -ln[(b, a)]
            ln[(a, b)] = gmsh.model.geo.addLine(a, b)
            return ln[(a, b)]

        def loop(coords):
            c = list(coords)
            if np.allclose(c[0], c[-1]):
                c = c[:-1]
            ids = [point(p) for p in c]
            ids2 = [ids[0]]
            for i in ids[1:]:                       # 去掉重复点
                if i != ids2[-1]:
                    ids2.append(i)
            if ids2[-1] == ids2[0]:
                ids2 = ids2[:-1]
            tags = [line(a, b) for a, b in zip(ids2, ids2[1:] + ids2[:1])]
            return gmsh.model.geo.addCurveLoop(tags)

        surf_region: dict[int, str] = {}
        for f, r in zip(faces, face_region):
            if r is None:
                continue
            loops = [loop(f.exterior.coords)] + [loop(h.coords) for h in f.interiors]
            s = gmsh.model.geo.addPlaneSurface(loops)
            surf_region[s] = r
        gmsh.model.geo.synchronize()
        for tag in ln.values():
            gmsh.model.mesh.setTransfiniteCurve(tag, 2)          # 边界节点 = 重采样点，保证共形
        gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
        gmsh.option.setNumber("Mesh.Algorithm", algorithm)
        gmsh.option.setNumber("Mesh.SecondOrderLinear", 1)       # 直边二阶（边界本来就是折线）
        gmsh.model.mesh.setSizeCallback(lambda dim, tag, x, y, z, lc: float(size_fn(x, y)))
        gmsh.model.mesh.generate(2)
        gmsh.model.mesh.setOrder(2)

        ntags, ncoord, _ = gmsh.model.mesh.getNodes()
        ncoord = ncoord.reshape(-1, 3)[:, :2]
        order = np.argsort(ntags)
        ntags, ncoord = ntags[order], ncoord[order]
        lut = {int(t): i for i, t in enumerate(ntags)}
        elems: dict[str, list] = {}
        for s, r in surf_region.items():
            types, _, enodes = gmsh.model.mesh.getElements(2, s)
            for t, en in zip(types, enodes):
                if t != 9:
                    raise RuntimeError(f"意外单元类型 {t}（期望 9 = 6 节点三角形）")
                elems.setdefault(r, []).append(en.reshape(-1, 6))
    finally:
        gmsh.finalize()

    used = sorted({int(n) for arrs in elems.values() for a in arrs for n in a.ravel()})
    new_label = {old: node_offset + i + 1 for i, old in enumerate(used)}
    nodes = np.array([ncoord[lut[o]] for o in used])
    labels = np.array([new_label[o] for o in used])
    out = Mesh(node_labels=labels, nodes=nodes)
    e0 = elem_offset
    for r in regions:
        if r not in elems:
            continue
        conn = np.vectorize(new_label.get)(np.vstack(elems[r])).astype(np.int64)
        out.elems[r] = conn
        out.elem_labels[r] = np.arange(e0 + 1, e0 + 1 + len(conn))
        e0 += len(conn)
    # 统一为逆时针
    for r in out.elems:
        a = out.areas(r)
        neg = a < 0
        if neg.any():
            c = out.elems[r]
            c[neg] = c[neg][:, [0, 2, 1, 5, 4, 3]]
    out.quality = quality(out)
    return out


def quality(m: Mesh) -> dict:
    angs, areas = [], []
    for r in m.elems:
        p = m.coords(m.elems[r][:, :3].ravel()).reshape(-1, 3, 2)
        corner = []
        for i in range(3):
            a, b, c = p[:, i], p[:, (i + 1) % 3], p[:, (i + 2) % 3]
            u, v = b - a, c - a
            cosang = np.sum(u * v, 1) / (np.linalg.norm(u, axis=1) * np.linalg.norm(v, axis=1))
            corner.append(np.degrees(np.arccos(np.clip(cosang, -1, 1))))
        angs.append(np.min(np.vstack(corner), axis=0))
        areas.append(m.areas(r))
    angs = np.concatenate(angs)
    areas = np.concatenate(areas)
    return {"n_elems": int(len(areas)), "n_nodes": int(len(m.node_labels)),
            "min_angle_deg": float(angs.min()), "p01_angle_deg": float(np.percentile(angs, 1)),
            "n_below_15deg": int((angs < 15).sum()), "min_area": float(areas.min()),
            "all_ccw": bool((areas > 0).all())}


def graded_size(targets, h_min: float, h_max: float, ramp: float) -> SizeFn:
    """h = h_min 在 targets（shapely 几何）上，距离 ramp 处线性升到 h_max。"""
    tgt = unary_union(targets) if isinstance(targets, (list, tuple)) else targets
    shapely.prepare(tgt)

    def f(x, y):
        d = tgt.distance(shapely.Point(x, y)) if tgt is not None and not tgt.is_empty else ramp
        return float(h_min + (h_max - h_min) * min(1.0, d / ramp))
    return f
