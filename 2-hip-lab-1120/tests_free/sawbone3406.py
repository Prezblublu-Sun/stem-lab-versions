"""Sawbones 3406 的骨模型，测试用。拆内核 4d、4e 的测试共用（tests_free/fem_abaqus、tests_free/derive_bed_f）。

两个实体是旧系统用的那两个 STEP，标志点照旧系统自己找出的那一套放。旧系统只读：这里只从它那里读文件、复制文件。
"""
from __future__ import annotations

import shutil
from pathlib import Path

from stemlab.contract import hashing
from stemlab.contract.formats.manifest import make_manifest, write_manifest
from tests import real
from tests.science import tools

SUMMARY = "v2/out/femur_3406_summary.json"     # 旧系统自己找出的 3406 的标志点和坐标系（只读）
# 骨模型的材料：Sawbones 3406 的皮质和 PCF 20 泡沫（和旧系统的配置、real.BONE_EXTRA 一样）
MATERIALS = {"cortical": {"model": "linear_elastic", "E_MPa": 16800.0, "nu": 0.3},
             "cancellous": {"model": "linear_elastic", "E_MPa": 155.0, "nu": 0.3}}


def landmarks(summary: dict) -> dict:
    """3406 的五个标志点，照旧系统自己找出的那一套放（femur_real.landmarks，记在 v2/out/femur_3406_summary.json）：
    干轴上的两个点就在旧系统的干轴上，小转子放在干轴上它那一层的高度（有限元包只用它的高度），颈中心在颈轴上。
    这样拆出的包截断的地方就是旧模型的 z = −150 mm；载荷的冠状面改用颈轴定，和旧模型差一个前倾角。"""
    origin, shaft_c, head = (summary[key] for key in ("origin", "shaft_c", "head_c"))
    neck = summary["neck_axis"]["u_baked"]
    on_axis = "on the legacy shaft axis (femur_real.landmarks: line fitted to the outer section centroids 150-330 mm below the top)"
    return {"head_center": {"xyz": list(head), "definition": "centre of the sphere fitted to the head by the legacy code"},
            "neck_center": {"xyz": [h - 23.3 * u for h, u in zip(head, neck)],
                            "definition": "on the legacy isthmus neck axis, 23.3 mm from the head centre"},
            "shaft_proximal": {"xyz": list(origin), "definition": f"{on_axis}, at the level of the lesser trochanter"},
            "shaft_distal": {"xyz": list(shaft_c), "definition": f"{on_axis}, centroid of the fitted sections"},
            "lesser_trochanter": {"xyz": list(origin), "definition": "the level of the most prominent point of the lesser "
                                  "trochanter, put on the shaft axis (the legacy model origin); only its level is used"}}


def bone_folder(folder: Path, legacy: Path, summary: dict, bone_id: str = tools.BONE_ID) -> Path:
    """3406 的骨模型：两个实体是旧系统用的那两个 STEP，标志点照旧系统找出的，材料是 3406 的。"""
    source = legacy / "v2" / "data" / "femur_3406"
    (folder / "solids").mkdir(parents=True)
    for name, file in tools.STEPS.items():
        shutil.copyfile(source / file, folder / "solids" / f"{name}.step")
    frame = {"origin": "the origin of the baked 3406R CAD files", "x": "medial", "y": "posterior", "z": "proximal"}
    write_manifest(folder, make_manifest("bone_model", hashing.list_tree(folder), bone_id=bone_id,
                                         **{**real.BONE_EXTRA, "landmarks": landmarks(summary), "frame": frame, "materials": MATERIALS}))
    return folder


def model_frame(summary: dict):
    """旧系统的“模型坐标”在骨模型文件的坐标里：（Rm，原点）。照 femur_real.landmarks 的写法从那份摘要里重算：
    原点在骨干轴上小转子那一层，z 沿干轴指向近端，x 是内外后髁连线投到垂直干轴的面上、指向内侧，y = z × x（后方）。
    Rm 的三行是模型坐标的三个轴。文件坐标换到模型坐标：x_m = (X − 原点) @ Rm.T；换回来：X = x_m @ Rm + 原点。"""
    import numpy as np

    ez = np.asarray(summary["shaft_d"], float)
    ez /= np.linalg.norm(ez)
    across = np.asarray(summary["p_med_condyle"], float) - np.asarray(summary["p_lat_condyle"], float)
    ex = across - (across @ ez) * ez
    ex /= np.linalg.norm(ex)
    return np.vstack([ex, np.cross(ez, ex), ez]), np.asarray(summary["origin"], float)
