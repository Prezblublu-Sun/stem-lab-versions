"""床支撑 F 照定义另算一遍，给测试对照用（tests_free/derive_bed_f、tests_free/fem_abaqus）。

和包（external/derive_bed_f_named/main.py）走的不是一条路：包把位置换到骨模型的坐标里、整批节点一起算；
这里把位置留在柄自己的坐标系里、一个节点一个节点地算，不用包里的任何代码。
"""
from __future__ import annotations

import math

import numpy as np


def truth(nodes, where: dict, how: dict) -> dict:
    """照定义算床支撑。nodes 和 where 在同一个坐标系里：
    nodes 是 [{"x": [x, y, z], "area", "thickness", "collar"}]；where 是参照点 ref、深度轴的方向 depth、量角的轴 axis 和它过的点 centre、
    0 度的方向 zero；how 是 zeta_max_mm、theta_max_deg、t_floor_mm。"""
    depth, axis = (np.asarray(where[key], float) / np.linalg.norm(where[key]) for key in ("depth", "axis"))
    zero = np.asarray(where["zero"], float)
    zero = zero - (zero @ axis) * axis
    zero /= np.linalg.norm(zero)
    side = np.cross(axis, zero)
    total = area = floored = 0.0
    count, thinnest = 0, None
    for one in nodes:
        if one["collar"]:
            continue
        x = np.asarray(one["x"], float)
        zeta = -float((x - np.asarray(where["ref"], float)) @ depth)
        out = x - np.asarray(where["centre"], float)
        theta = math.degrees(math.atan2(float(out @ side), float(out @ zero)))
        if zeta <= how["zeta_max_mm"] and abs(theta) <= how["theta_max_deg"]:
            count += 1
            area += one["area"]
            total += one["area"] / max(one["thickness"], how["t_floor_mm"])
            floored += one["area"] if one["thickness"] < how["t_floor_mm"] else 0.0
            thinnest = one["thickness"] if thinnest is None else min(thinnest, one["thickness"])
    return {"F_mm": total, "F_area_mm2": area, "F_n_nodes": count, "F_t_min_mm": thinnest, "F_frac_floor": floored / area if area else None}


def in_stem_frame(model: dict, points) -> np.ndarray:
    """骨模型坐标里的点，换到柄自己的坐标系里。model 是柄的模型的清单。"""
    frame = {key: np.asarray(value, float) for key, value in model["placement"]["frame"].items()}
    away = np.atleast_2d(np.asarray(points, float)) - frame["origin"]
    return np.column_stack([away @ frame["x"], away @ frame["y"], away @ frame["z"]])


def located(values: dict, model: dict, landmarks: dict) -> dict:
    """照名字把位置找出来，放在柄自己的坐标系里。values 是一个点上推导量设定的取值，model 是柄的模型的清单，
    landmarks 是骨模型清单里的标志点（骨模型的坐标）。"""
    def point(value) -> np.ndarray:
        source, _, name = value["ref"].split(".")
        return np.asarray(model["features"][name], float) if source == "stem" else in_stem_frame(model, landmarks[name]["xyz"])[0]

    def axis(value) -> dict:
        return model["axes"][value["ref"].split(".")[2]]

    depth = np.asarray(axis(values["depth_axis"])["direction"], float)
    around = axis(values["angle_axis"])
    return {"ref": point(values["zone_from"]) - values["zone_offset_mm"] * depth, "depth": depth, "centre": around["point"],
            "axis": around["direction"], "zero": axis(values["angle_from"])["direction"]}


def of_cloud(cloud, values: dict, model: dict, landmarks: dict) -> dict:
    """一份界面点云（骨模型的坐标里：X、area、d_canal、collar）照这份设定该算出的床支撑。"""
    local = in_stem_frame(model, np.asarray(cloud["X"], float))
    nodes = [{"x": x, "area": float(area), "thickness": -float(canal), "collar": bool(collar)}
             for x, area, canal, collar in zip(local, cloud["area"], cloud["d_canal"], cloud["collar"])]
    return truth(nodes, located(values, model, landmarks), values)
