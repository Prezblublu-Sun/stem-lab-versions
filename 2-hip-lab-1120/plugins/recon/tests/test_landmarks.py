"""找标志点的几样小工具，拿手算得出来的形状直接试。自由的测试：找法换了，这里跟着换。"""
from __future__ import annotations

import math

import numpy as np

from plugins.recon import landmarks, sources

CUBE = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]], float)
FACES = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5],
                  [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]])


def test_a_plane_through_a_cube_gives_one_square_loop():
    loops = landmarks.section_loops(CUBE, FACES, np.array([0.5, 0.5, 0.3]), [0, 0, 1])
    assert len(loops) == 1
    area, centroid = landmarks.loop_area_centroid(loops[0], [0, 0, 1])
    assert abs(area - 1.0) < 1e-9 and np.allclose(centroid, [0.5, 0.5, 0.3])
    assert landmarks.section_loops(CUBE, FACES, np.array([0.5, 0.5, 2.0]), [0, 0, 1]) == [], "平面没碰到实体"


def test_the_outer_section_is_the_largest_loop_near_the_given_point():
    far = CUBE * 3.0 + np.array([10.0, 0.0, 0.0])                       # 另一块更大的，离得远
    vertices, triangles = np.vstack([CUBE, far]), np.vstack([FACES, FACES + len(CUBE)])
    origin = np.array([0.5, 0.5, 0.5])
    assert abs(landmarks.outer_section(vertices, triangles, origin, [0, 0, 1])[0] - 9.0) < 1e-9, "不限远近：最大的那一圈"
    near = landmarks.outer_section(vertices, triangles, origin, [0, 0, 1], near=origin, within=2.0)
    assert abs(near[0] - 1.0) < 1e-9 and np.allclose(near[1], origin)


def test_the_cube_is_closed_and_encloses_its_volume():
    mesh = {"vertices": CUBE, "triangles": FACES}
    assert sources.watertight(mesh) and abs(sources.enclosed_volume(mesh) - 1.0) < 1e-12
    assert not sources.watertight({"vertices": CUBE, "triangles": FACES[:-1]}), "少一个三角形就不封闭"
    normals = landmarks.outward(CUBE, FACES)
    assert all((normal @ (corner - 0.5)) > 0 for normal, corner in zip(normals, CUBE)), "顶点法向朝外"
    assert abs(landmarks.vertex_areas(CUBE, FACES).sum() - 6.0) < 1e-12


def test_the_first_dip_is_the_neck_not_whatever_is_smallest_further_out():
    assert landmarks.first_dip([10, 8, 6, 7, 9, 3, 1]) == 2, "回升过 15% 之前最小的那个；后面再小也不算"
    assert landmarks.first_dip([10, 8, 6, 6.5, 5.9, 6.2, 7.0, 2.0]) == 4, "回升不到 15% 的小起伏不算回升"
    assert landmarks.first_dip([10, 9, 8]) == 2, "一直没有回升：取最小的"
    assert landmarks.first_dip([5, 6, 7]) == 0


def test_a_sphere_is_fitted_from_points_on_it():
    rng = np.random.default_rng(1)
    directions = rng.normal(size=(400, 3))
    directions /= np.linalg.norm(directions, axis=1, keepdims=True)
    centre, radius = landmarks._sphere(np.array([3.0, -2.0, 7.0]) + 22.0 * directions, np.ones(400))
    assert np.allclose(centre, [3.0, -2.0, 7.0]) and math.isclose(radius, 22.0, rel_tol=1e-9)


def test_which_end_is_proximal():
    rng = np.random.default_rng(2)
    shaft = np.c_[rng.normal(scale=5, size=(3000, 2)), rng.uniform(-300, 0, 3000)]
    head = np.c_[rng.normal(scale=25, size=(600, 2)), rng.uniform(0, 60, 600)]
    axis = landmarks.lengthwise(np.vstack([shaft, head]))
    assert axis[2] > 0.99, "有头的那一头是近端"


def test_triangle_quality_is_one_for_equilateral_and_small_for_slivers():
    mesh = {"vertices": CUBE, "triangles": FACES}
    assert np.allclose(sources.quality(mesh), 4 * math.sqrt(3) * 0.5 / 4.0), "立方体的每个面切成两个等腰直角三角形"
    found = sources.quality_histogram(mesh)
    assert found["edges"][0] == 0.0 and found["edges"][-1] == 1.0 and len(found["counts"]) == 10
    assert found["counts"][8] == 12 and sum(found["counts"]) == 12, "十二个三角形的质量都是 0.866，落在 0.8 到 0.9 那一段"
    flat = {"vertices": np.array([[0, 0, 0], [1, 0, 0], [0.5, math.sqrt(3) / 2, 0], [0.5, 1e-4, 0]], float),
            "triangles": np.array([[0, 1, 2], [0, 1, 3]])}
    good, sliver = sources.quality(flat)
    assert math.isclose(good, 1.0, rel_tol=1e-12) and sliver < 1e-3
