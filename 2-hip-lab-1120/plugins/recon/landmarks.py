"""【自由】找标志点。有哪几个、在什么坐标系里，由骨模型的格式定；这里管怎么找。

输入是皮质实体的表面三角网，坐标就是骨源自己的坐标，不换系。每个标志点的定义跟着点一起给出：
同一根骨的角度只有在同一种定义下才能比，换了找法就要换定义的文字。

    干轴      从近端往下 150 到 330 mm 这一段，每隔 10 mm 一个截面，最外圈的形心拟合的直线
    头心      近端、靠头那一侧的外壁顶点拟合球：按面积加权，反复剔掉离球面超过 1.5 mm 的点
    颈中心    从头心朝骨干方向走，截面先变小后变大，第一个谷就是颈最细处，取它最外圈的形心；颈轴改成头心到它，反复到不动
    小转子    头心下 25 到 95 mm 这一段里朝后内方向鼓出来的包里最突出的那个的顶，先减掉这一段的走势再找
"""
from __future__ import annotations

import math

import numpy as np
from scipy.signal import find_peaks

DEFINITIONS = {
    "head_center": "股骨头外壁的拟合球心：近端靠头一侧的外壁顶点，按面积加权拟合，反复剔掉离球面超过 1.5 mm 的点",
    "neck_center": "股骨颈最细截面最外圈的形心：从头心往骨干走，截面面积回升超过 15% 之前最小的那个截面；"
                   "截面垂直于头心到它的连线，反复到这条线不再动",
    "shaft_proximal": "干轴上的近端点：从骨的近端往下 150 mm 处。干轴是 150 到 330 mm 这一段各截面最外圈形心拟合的直线",
    "shaft_distal": "干轴上的远端点：从骨的近端往下 330 mm 处（骨不够长就取到骨长的四分之三）",
    "lesser_trochanter": "头心下 25 到 95 mm 这一段，每 1 mm 一个垂直于干轴的截面，最外圈朝后内方向伸得最远的点连成一条曲线；"
                         "减掉这条曲线的走势（最小二乘直线）之后，这一段里面鼓出来的包里最突出的那个的顶"
                         "（突出多少：从包顶到它两边谷底里较高的那个的落差；这一段两头的不算包）",
}


# ---------------------------------------------------------------- 截面

def section_loops(vertices, triangles, origin, normal) -> list:
    """平面和三角网的交线，接成一圈一圈的。每圈是按顺序排好的点 (k, 3)。"""
    normal = np.asarray(normal, float) / np.linalg.norm(normal)
    signed = (vertices - origin) @ normal
    corner = signed[triangles]
    crossing = (corner.min(1) < 0) & (corner.max(1) >= 0)
    segments = []
    for corners, distance in zip(triangles[crossing], corner[crossing]):
        points = []
        for a, b in ((0, 1), (1, 2), (2, 0)):
            if (distance[a] < 0) != (distance[b] < 0):
                t = distance[a] / (distance[a] - distance[b])
                points.append(vertices[corners[a]] + t * (vertices[corners[b]] - vertices[corners[a]]))
        if len(points) == 2:
            segments.append(points)
    if not segments:
        return []
    segments = np.array(segments)
    _, ids = np.unique(np.round(segments.reshape(-1, 3) / 1e-6).astype(np.int64), axis=0, return_inverse=True)
    ids = ids.reshape(-1, 2)
    points = np.zeros((ids.max() + 1, 3))
    points[ids.reshape(-1)] = segments.reshape(-1, 3)
    neighbours: dict[int, list[int]] = {}
    for a, b in ids:
        if a != b:
            neighbours.setdefault(int(a), []).append(int(b))
            neighbours.setdefault(int(b), []).append(int(a))
    loops, seen = [], set()
    for first in neighbours:
        if first in seen:
            continue
        loop, previous, current = [first], None, first
        seen.add(first)
        while True:
            following = [other for other in neighbours[current] if other != previous and other not in seen]
            if not following:
                break
            previous, current = current, following[0]
            loop.append(current)
            seen.add(current)
        if len(loop) >= 3:
            loops.append(points[loop])
    return loops


def loop_area_centroid(loop, normal) -> tuple:
    """一圈围出的面积和形心。"""
    normal = np.asarray(normal, float) / np.linalg.norm(normal)
    base = loop[0]
    signed = np.cross(loop[1:-1] - base, loop[2:] - base) @ normal / 2.0
    area = signed.sum()
    if abs(area) < 1e-12:
        return 0.0, loop.mean(0)
    centroid = ((base + loop[1:-1] + loop[2:]) / 3.0 * signed[:, None]).sum(0) / area
    return abs(float(area)), centroid


def outer_section(vertices, triangles, origin, normal, near=None, within: float = 40.0):
    """截面上最外面的那一圈：面积最大的。给了 near，就只看形心离它不超过 within 的那些圈。返回（面积，形心，这一圈），没有就是 None。"""
    best = None
    for loop in section_loops(vertices, triangles, origin, normal):
        area, centroid = loop_area_centroid(loop, normal)
        if near is not None and np.linalg.norm(centroid - near) > within:
            continue
        if best is None or area > best[0]:
            best = (area, centroid, loop)
    return best


# ---------------------------------------------------------------- 各个标志点

def outward(vertices, triangles) -> np.ndarray:
    """每个顶点的外法向：相邻三角形的法向按面积加权。"""
    a, b, c = (vertices[triangles[:, k]] for k in range(3))
    normals = np.cross(b - a, c - a)
    summed = np.zeros_like(vertices)
    for k in range(3):
        np.add.at(summed, triangles[:, k], normals)
    return summed / np.maximum(np.linalg.norm(summed, axis=1, keepdims=True), 1e-12)


def vertex_areas(vertices, triangles) -> np.ndarray:
    a, b, c = (vertices[triangles[:, k]] for k in range(3))
    areas = np.linalg.norm(np.cross(b - a, c - a), axis=1) / 2.0
    summed = np.zeros(len(vertices))
    for k in range(3):
        np.add.at(summed, triangles[:, k], areas / 3.0)
    return summed


def lengthwise(vertices) -> np.ndarray:
    """骨的长方向，指向近端（有股骨头的那一头：那一头的点离长轴更远）。"""
    centred = vertices - vertices.mean(0)
    _, _, vt = np.linalg.svd(centred[:: max(1, len(centred) // 20000)], full_matrices=False)
    axis = vt[0]
    along = centred @ axis
    spread = np.linalg.norm(centred - np.outer(along, axis), axis=1)
    top, bottom = spread[along > np.percentile(along, 85)].max(), spread[along < np.percentile(along, 15)].max()
    return axis if top >= bottom else -axis


def shaft_axis(vertices, triangles, direction, start: float = 150.0, stop: float = 330.0, step: float = 10.0) -> dict:
    along = vertices @ direction
    top = along.max()
    reachable = 0.75 * (top - along.min())
    if stop > reachable:                                                # 骨不够长：这一段按比例缩短
        start, stop = start * reachable / stop, reachable
    centroids = []
    for below in np.arange(start, stop + 1e-9, step):
        found = outer_section(vertices, triangles, direction * (top - below), direction)
        if found:
            centroids.append(found[1])
    centroids = np.array(centroids)
    centre = centroids.mean(0)
    _, _, vt = np.linalg.svd(centroids - centre)
    axis = vt[0] if vt[0] @ direction > 0 else -vt[0]

    def at(below: float) -> np.ndarray:
        return centre + ((direction * (top - below) - centre) @ direction) / (axis @ direction) * axis

    return {"point": centre, "direction": axis, "proximal": at(start), "distal": at(stop),
            "spread_mm": float(np.linalg.norm((centroids - centre) - np.outer((centroids - centre) @ axis, axis), axis=1).max())}


def _sphere(points, weights) -> tuple:
    root = np.sqrt(weights)
    solution, *_ = np.linalg.lstsq(np.c_[2 * points, np.ones(len(points))] * root[:, None], (points ** 2).sum(1) * root, rcond=None)
    centre = solution[:3]
    return centre, math.sqrt(max(solution[3] + centre @ centre, 0.0))


def head_sphere(vertices, triangles, shaft: dict, keep: float = 1.5, rounds: int = 12, slab: float = 55.0) -> dict:
    normals, weights = outward(vertices, triangles), vertex_areas(vertices, triangles)
    along = (vertices - shaft["point"]) @ shaft["direction"]
    radial = vertices - shaft["point"] - np.outer(along, shaft["direction"])
    top = along > along.max() - slab
    far = radial[top][np.argmax(np.linalg.norm(radial[top], axis=1))]     # 头在哪一侧：近端离干轴最远的那个点
    side = radial @ (far / np.linalg.norm(far))
    chosen = top & (side > np.percentile(side[top], 55))
    centre, radius = _sphere(vertices[chosen], weights[chosen])
    for _ in range(rounds):
        offset = vertices - centre
        reach = np.linalg.norm(offset, axis=1)
        outer = (normals * offset).sum(1) > 0.5 * reach                 # 法向背着球心：是外壁，不是皮质壳的内壁
        chosen = outer & (np.abs(reach - radius) < keep) & (reach < radius + 6.0)
        if chosen.sum() < 30:
            break
        centre, radius = _sphere(vertices[chosen], weights[chosen])
    residual = np.abs(np.linalg.norm(vertices[chosen] - centre, axis=1) - radius)
    rms = float(np.sqrt((residual ** 2 * weights[chosen]).sum() / max(weights[chosen].sum(), 1e-12))) if chosen.any() else float("inf")
    return {"centre": centre, "radius": float(radius), "rms_mm": rms, "points": int(chosen.sum())}


def first_dip(areas, rise: float = 1.15) -> int:
    """从头往骨干走的一串截面面积里，第一个谷在第几个：面积回升超过 15% 之前最小的那个。

    只认第一个谷：再往外是转子和骨干，截面还会再变小（截到骨头的边上了），那不是颈。
    一直没有回升，就取最小的那个。
    """
    low = 0
    for index in range(1, len(areas)):
        if areas[index] < areas[low]:
            low = index
        elif areas[index] > rise * areas[low]:
            return low
    return int(np.argmin(areas))


def neck_isthmus(vertices, triangles, head: dict, shaft: dict, rounds: int = 15) -> dict:
    centre, radius = head["centre"], head["radius"]
    foot = shaft["point"] + ((centre - shaft["point"]) @ shaft["direction"] - 0.6 * radius) * shaft["direction"]
    direction = (foot - centre) / np.linalg.norm(foot - centre)          # 从头心指向骨干，略偏远端：颈轴的第一个猜测
    best, turned = None, float("inf")
    for _ in range(rounds):
        found = []
        for distance in np.arange(0.5 * radius, radius + 45.0, 1.0):
            origin = centre + distance * direction
            section = outer_section(vertices, triangles, origin, direction, near=origin)
            if section:
                found.append((section[0], distance, section[1], section[2]))
        if not found:
            break
        area, distance, centroid, loop = found[first_dip([row[0] for row in found])]
        pointing = (centroid - centre) / np.linalg.norm(centroid - centre)
        turned = math.degrees(math.acos(max(-1.0, min(1.0, float(pointing @ direction)))))
        best = {"centre": centroid, "area_mm2": float(area), "from_head_mm": float(distance), "loop": loop}
        direction = pointing
        if turned < 0.02:
            break
    if best is None:
        raise ValueError("找不到股骨颈的截面")
    return dict(best, last_turn_deg=turned, converged=turned < 0.02)


def lesser_trochanter(vertices, triangles, head: dict, shaft: dict, neck: dict, side: str) -> dict:
    axis = shaft["direction"]
    level_of_head = (head["centre"] - shaft["point"]) @ axis
    neck_axis = head["centre"] - neck["centre"]
    medial = neck_axis - (neck_axis @ axis) * axis
    medial /= np.linalg.norm(medial)
    posterior = np.cross(axis, medial) * (1.0 if side == "right" else -1.0)
    toward = (medial + posterior) / math.sqrt(2.0)
    levels, tops, points = [], [], []
    for below in np.arange(95.0, 25.0, -1.0):                              # 头心下 95 到 26 mm，每 1 mm 一个截面
        origin = shaft["point"] + (level_of_head - below) * axis
        section = outer_section(vertices, triangles, origin, axis, near=origin, within=60.0)
        if section is None:
            continue
        loop = section[2]
        reach = (loop - origin) @ toward
        levels.append(level_of_head - below), tops.append(float(reach.max())), points.append(loop[int(np.argmax(reach))])
    if len(levels) < 10:
        raise ValueError("头心下面 25 到 95 mm 这一段截不出像样的截面，找不到小转子")
    levels, tops = np.array(levels), np.array(tops)
    slope, intercept = np.polyfit(levels, tops, 1)                          # 走势：这一段的最小二乘直线
    bulge = tops - (slope * levels + intercept)
    peaks, about = find_peaks(bulge, prominence=0.0)                        # 这一段里面鼓出来的各个包；两头的不算
    if len(peaks):
        best, prominence = int(peaks[np.argmax(about["prominences"])]), float(about["prominences"].max())
    else:                                                                   # 一个包都没有：给最凸的点，突出量记 0，待检查清单会标出来
        best, prominence = int(np.argmax(bulge)), 0.0
    return {"point": points[best], "prominence_mm": prominence, "below_head_mm": float(level_of_head - levels[best])}


def find(mesh: dict, side: str) -> dict:
    """在皮质实体的表面上找齐五个标志点。返回标志点（骨模型格式里的写法）、量出来的几个数、和每一步的细节。"""
    vertices, triangles = mesh["vertices"], mesh["triangles"]
    shaft = shaft_axis(vertices, triangles, lengthwise(vertices))
    head = head_sphere(vertices, triangles, shaft)
    neck = neck_isthmus(vertices, triangles, head, shaft)
    trochanter = lesser_trochanter(vertices, triangles, head, shaft, neck, side)
    points = {"head_center": head["centre"], "neck_center": neck["centre"], "shaft_proximal": shaft["proximal"],
              "shaft_distal": shaft["distal"], "lesser_trochanter": trochanter["point"]}
    neck_axis = (head["centre"] - neck["centre"]) / np.linalg.norm(head["centre"] - neck["centre"])
    along = (head["centre"] - shaft["point"]) @ shaft["direction"]
    offset = float(np.linalg.norm(head["centre"] - shaft["point"] - along * shaft["direction"]))
    extent = vertices @ shaft["direction"]
    measures = {
        "head_radius_mm": head["radius"], "head_fit_rms_mm": head["rms_mm"], "head_fit_points": head["points"],
        "neck_shaft_angle_deg": 180.0 - math.degrees(math.acos(max(-1.0, min(1.0, float(neck_axis @ shaft["direction"]))))),
        "neck_isthmus_area_mm2": neck["area_mm2"], "neck_isthmus_from_head_mm": neck["from_head_mm"],
        "neck_axis_last_turn_deg": neck["last_turn_deg"], "head_offset_mm": offset,
        "shaft_centroid_spread_mm": shaft["spread_mm"], "length_mm": float(extent.max() - extent.min()),
        "lesser_trochanter_prominence_mm": trochanter["prominence_mm"], "lesser_trochanter_below_head_mm": trochanter["below_head_mm"],
    }
    listed = {name: {"xyz": [float(value) for value in point], "definition": DEFINITIONS[name]} for name, point in points.items()}
    return {"landmarks": listed, "measures": measures, "neck_axis": neck_axis.tolist(), "shaft_axis": shaft["direction"].tolist(),
            "neck_loop": neck["loop"], "neck_converged": bool(neck["converged"])}


def wall_thickness(mesh: dict, origin, normal, near) -> dict | None:
    """一个截面上皮质壳有多厚：最外圈上的每个点到里面那一圈的最近距离。截面上没有里面那一圈（实心的）就是 None。"""
    loops = []
    for loop in section_loops(mesh["vertices"], mesh["triangles"], origin, normal):
        area, centroid = loop_area_centroid(loop, normal)
        if np.linalg.norm(centroid - near) <= 40.0:
            loops.append((area, loop))
    if len(loops) < 2:
        return None
    loops.sort(key=lambda row: -row[0])
    outer, inner = loops[0][1], loops[1][1]
    gaps = np.sqrt(((outer[:, None, :] - inner[None, :, :]) ** 2).sum(2)).min(1)
    return {"min_mm": float(gaps.min()), "median_mm": float(np.median(gaps)), "max_mm": float(gaps.max())}
