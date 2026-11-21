"""CT 重建的两段：照 CT 值分出皮质和内部、出两个表面（ct.py），再变成划得了网格的两个实体（solids.py）。
拿一根造出来的“骨”试：一段两头带球冠的圆管，外径、壁厚、CT 值都是定好的，所以该量出多少手上有数。

要 VTK、SimpleITK、MeshLab。这三个库装上了却加载不了的时候（比如安全软件还占着刚装的文件），这里的测试跳过并说明原因。
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from plugins.recon import ct, solids

RADIUS, HALF, WALL = 15.0, 60.0, 5.0            # 外半径、圆管半长（两头各加一个球冠）、壁厚，毫米
SPACING = 0.8


def libraries():
    """三个库都加载得了才往下走。"""
    try:
        import pymeshlab
        import SimpleITK

        vtk = ct.toolkit()
    except ImportError as error:
        pytest.skip(f"CT 重建要的库加载不了：{error}")
    return SimpleITK, vtk, pymeshlab


def capsule(radius: float, half: float, rings: int = 24, around: int = 48) -> tuple:
    """两头带半球的圆管的表面，轴沿 z。法向朝外。"""
    points = [(0.0, 0.0, half + radius)]
    for sign in (1.0, -1.0):
        angles = np.linspace(0.0, math.pi / 2, rings + 1)[1:] if sign > 0 else np.linspace(math.pi / 2, 0.0, rings + 1)[:-1]
        for angle in angles:
            for k in range(around):
                turn = 2 * math.pi * k / around
                points.append((radius * math.sin(angle) * math.cos(turn), radius * math.sin(angle) * math.sin(turn), sign * (half + radius * math.cos(angle))))
    points.append((0.0, 0.0, -half - radius))
    faces, last = [], len(points) - 1
    for k in range(around):
        faces.append((0, 1 + k, 1 + (k + 1) % around))
        faces.append((last, last - around + (k + 1) % around, last - around + k))
    for ring in range(2 * rings - 1):
        for k in range(around):
            a, b = 1 + ring * around + k, 1 + ring * around + (k + 1) % around
            faces += [(a, a + around, b), (b, a + around, b + around)]
    return np.array(points), np.array(faces, dtype=np.int64)


def source(folder, other_bone: bool = True):
    """一份造出来的 CT 骨源：ct.nrrd 和 outer.stl。壁是 1200 HU，里面 150，外面 0；旁边另有一块别的“骨”。"""
    sitk, _, _ = libraries()
    folder.mkdir(parents=True, exist_ok=True)
    solids.write_stl(folder / "outer.stl", *capsule(RADIUS, HALF))
    low = np.array([-RADIUS - 12.0, -RADIUS - 12.0, -HALF - RADIUS - 12.0])
    size = [int(math.ceil(2 * abs(v) / SPACING)) + 1 for v in low]
    z, y, x = np.meshgrid(*(low[k] + SPACING * np.arange(size[k]) for k in (2, 1, 0)), indexing="ij")
    away = np.sqrt(x ** 2 + y ** 2 + (z - np.clip(z, -HALF, HALF)) ** 2)              # 到轴上那一段的距离
    values = np.where(away <= RADIUS - WALL, 150.0, np.where(away <= RADIUS, 1200.0, 0.0))
    if other_bone:
        values[np.sqrt((x - RADIUS - 6.0) ** 2 + y ** 2 + z ** 2) <= 4.0] = 1500.0   # 紧挨着的另一块骨：不在外形里，不该被算进来
    image = sitk.GetImageFromArray(values.astype(np.float32))
    image.SetSpacing((SPACING,) * 3)
    image.SetOrigin(tuple(float(v) for v in low))
    sitk.WriteImage(image, str(folder / "ct.nrrd"), True)
    return folder


SETTING = {"side": "right", "source": {"outer": "outer.stl", "ct": "ct.nrrd"}, "ct": {"proximal": "high_z"}}
WHOLE = math.pi * RADIUS ** 2 * 2 * HALF + 4.0 / 3.0 * math.pi * RADIUS ** 3
HOLLOW = math.pi * (RADIUS - WALL) ** 2 * 2 * HALF + 4.0 / 3.0 * math.pi * (RADIUS - WALL) ** 3


def test_a_tube_of_known_size_is_split_into_cortex_and_interior(tmp_path):
    folder = source(tmp_path / "source")
    assert ct.problems(folder, SETTING) == []
    stages = []
    made = ct.run(folder, SETTING, tmp_path / "out", stages.append)
    seen = made["measures"]
    assert set(seen) <= set(ct.MEASURES), f"CT 这一步量的数要都在 ct.MEASURES 里（定稿照抄的就是这一份）：{sorted(set(seen) - set(ct.MEASURES))}"
    assert stages == ["ct-read", "ct-masks", "ct-surfaces"] and made["notes"] == []
    assert seen["ct_flip"] == [1, 1, 1] and seen["ct_overlap"] == 1.0 and seen["ct_file"] == "ct.nrrd" and seen["proximal_end"] == "high_z"
    assert abs(seen["femur_mask_mm3"] - WHOLE) < 0.01 * WHOLE, "外形围出的体积"
    assert seen["surface_on_bone_share"] > 0.45 and 1100 < seen["hu_inside_p95"] <= 1200
    assert seen["cortex_removed_by_depth_mm3"] > 0, "远端的壁比 3 mm 的上限厚：深处的那一层归了内部"
    assert 0.95 * HOLLOW < seen["interior_mask_mm3"] < 1.03 * HOLLOW, f"里面的体积：{seen['interior_mask_mm3']}，真值 {HOLLOW}"
    assert abs(seen["cortex_mask_mm3"] + seen["interior_mask_mm3"] - seen["femur_mask_mm3"]) < 1e-6, "皮质加内部正好是整根"
    assert abs(seen["wall_fine_median_mm"] - WALL) < 0.4, f"管壁 5 mm：{seen['wall_fine_median_mm']}"
    assert 3.3 < seen["wall_fine_min_mm"] < 4.4, f"远端限深 3 mm，那里的壁比 5 mm 薄：{seen['wall_fine_min_mm']}"
    assert abs(seen["isthmus_canal_diameter_mm"] - 2 * (RADIUS - WALL)) < 0.6 and abs(seen["isthmus_outer_diameter_mm"] - 2 * RADIUS) < 0.6
    assert abs(seen["isthmus_cortex_index"] - WALL / RADIUS) < 0.03
    for name in ("outer", "inner"):
        assert seen[f"{name}_fine_bad_edges"] == 0 and seen[f"{name}_fine_regions"] == 1, "两个表面各是一块、封闭"
        assert (tmp_path / "out" / f"{name}.stl").is_file()
    assert seen["outer_vs_reference_mean_mm"] < 0.15 and abs(seen["outer_fine_volume_mm3"] - WHOLE) < 0.02 * WHOLE
    assert [step["step"] for step in made["history"]] == ["ct-input", "ct-resample", "ct-cortex", "ct-interior", "ct-surfaces"]
    assert "500 HU" in made["history"][2]["what"] and "1.4 mm" in made["history"][3]["what"]

    free = ct.run(folder, dict(SETTING, ct={"proximal": "high_z", "depth_cap": None}), tmp_path / "free")["measures"]
    assert "cortex_removed_by_depth_mm3" not in free and abs(free["wall_fine_min_mm"] - WALL) < 0.6, "不限深：两头的壁也是 5 mm"
    assert free["interior_mask_mm3"] < seen["interior_mask_mm3"]
    thin = ct.run(folder, dict(SETTING, ct={"proximal": "high_z", "cortical_hu": 1300.0}), tmp_path / "thin")["measures"]
    assert thin["cortex_by_threshold_mm3"] == 0 and 1.0 < thin["wall_fine_median_mm"] < 1.9, "阈值高到一个体素都够不上：皮质全靠最小壁厚 1.4 mm 补出来"
    assert thin["cortex_added_by_rules_share"] == 1.0


def test_the_shape_and_the_ct_must_be_the_same_scan(tmp_path):
    folder = source(tmp_path / "source", other_bone=False)
    points, faces = capsule(RADIUS, HALF)
    solids.write_stl(folder / "elsewhere.stl", points + np.array([400.0, 0.0, 0.0]), faces)
    with pytest.raises(ValueError, match="没有一份 CT 装得下这个外形"):
        ct.run(folder, dict(SETTING, source={"outer": "elsewhere.stl", "ct": "ct.nrrd"}), tmp_path / "out")
    solids.write_stl(folder / "upside_down.stl", points * np.array([-1.0, 1.0, -1.0]), faces[:, ::-1])
    turned = ct.run(folder, dict(SETTING, source={"outer": "upside_down.stl"}), tmp_path / "turned")["measures"]
    assert turned["ct_flip"] in ([1, 1, 1], [-1, 1, -1]) and abs(turned["femur_mask_mm3"] - WHOLE) < 0.01 * WHOLE, "对称的外形，哪种坐标约定都装得下"


def test_two_surfaces_become_two_solids_that_can_be_meshed(tmp_path):
    libraries()
    folder = source(tmp_path / "source", other_bone=False)
    made = ct.run(folder, SETTING, tmp_path / "out")
    solid = solids.from_surfaces(made["outer"], made["inner"], tmp_path / "solids", SETTING)
    seen = solid["measures"]
    assert set(seen) == set(solids.REMESH_MEASURES), "重划这一步量的数就是 solids.REMESH_MEASURES 那一份（定稿照抄的）"
    assert seen["surfaces_open_edges"] == 0 and seen["remesh_deviation_p95_mm"] < 0.3
    assert seen["outer_triangle_quality_p01"] > 0.6 and seen["inner_triangle_quality_p01"] > 0.6, "重划之后没有细长的三角形"
    assert abs(seen["outer_volume_mm3"] - WHOLE) < 0.02 * WHOLE
    edges = np.linalg.norm(solid["surfaces"]["outer"][0][solid["surfaces"]["outer"][1][:, 0]] - solid["surfaces"]["outer"][0][solid["surfaces"]["outer"][1][:, 1]], axis=1)
    assert 2.0 < np.median(edges) < 3.0, "外表面的目标边长 2.5 mm"
    back = solids.surfaces_of(solid["files"])
    assert back is not None and len(back["outer"][1]) == seen["outer_triangles"] and len(back["inner"][1]) == seen["inner_triangles"]
    thick = solids.wall(back)
    assert abs(thick["wall_median_mm"] - WALL) < 0.5 and thick["wall_min_mm"] > 2.2
    tets = solids.tet_check(back, 2.5)
    assert tets["tet_inverted"] == 0 and tets["tet_gamma_min"] > 0.1 and tets["tet_count_cortical"] > 1000 and tets["tet_count_cancellous"] > 1000
    assert tets["tet_count"] == tets["tet_count_cortical"] + tets["tet_count_cancellous"]
    finer = solids.from_surfaces(made["outer"], made["inner"], tmp_path / "finer", dict(SETTING, ct={"edge_mm": 1.5}))["measures"]
    assert finer["outer_triangles"] > 2 * seen["outer_triangles"], "边长小了，三角形就多"
