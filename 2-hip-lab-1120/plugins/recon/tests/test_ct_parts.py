"""CT 重建里只用 numpy 和 scipy 的那几样：STL 的读写、两个实体怎么写怎么读回来、点到表面的距离、近远端的判断、设定的核对。
自由的测试：写法换了，这里跟着换。要 VTK、SimpleITK、MeshLab 的在 test_ct.py 里。
"""
from __future__ import annotations

import math

import numpy as np

from plugins.recon import ct, landmarks, review, solids, sources


def ball(radius: float, centre=(0.0, 0.0, 0.0), rounds: int = 3) -> tuple:
    """一个球的三角网：正二十面体细分 rounds 次，顶点推到球面上。法向朝外。"""
    t = (1.0 + math.sqrt(5.0)) / 2.0
    points = [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t), (0, -1, -t), (0, 1, -t), (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]
    faces = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6), (7, 1, 8),
             (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9), (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1)]
    points = [np.array(point, float) / np.linalg.norm(point) for point in points]
    for _ in range(rounds):
        middle, split = {}, []

        def between(a: int, b: int) -> int:
            key = (min(a, b), max(a, b))
            if key not in middle:
                made = points[a] + points[b]
                points.append(made / np.linalg.norm(made))
                middle[key] = len(points) - 1
            return middle[key]

        for a, b, c in faces:
            ab, bc, ca = between(a, b), between(b, c), between(c, a)
            split += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
        faces = split
    return np.array(points) * radius + np.array(centre, float), np.array(faces, dtype=np.int64)


def test_an_stl_written_here_reads_back_as_the_same_closed_surface(tmp_path):
    vertices, triangles = ball(10.0, (3.0, -2.0, 5.0))
    solids.write_stl(tmp_path / "ball.stl", vertices, triangles)
    back, faces = solids.read_stl(tmp_path / "ball.stl")
    assert len(back) == len(vertices) and len(faces) == len(triangles) and solids.open_edges(faces) == 0
    volume = 4.0 / 3.0 * math.pi * 1000.0
    assert 0.98 * volume < solids.signed_volume(back, faces) < volume, "法向朝外，体积是正的，比真球小一点（多面体在球里面）"
    assert solids.signed_volume(back, faces[:, ::-1]) < 0, "绕向反过来，体积变号"
    assert solids.quality(back, faces).min() > 0.7
    (tmp_path / "cut.stl").write_bytes((tmp_path / "ball.stl").read_bytes()[:-30])
    try:
        solids.read_stl(tmp_path / "cut.stl")
    except ValueError as error:
        assert "不是完整的" in str(error)
    else:
        raise AssertionError("截短了的 STL 该读不成")


def test_the_two_solids_are_written_so_that_they_read_back_as_the_two_surfaces(tmp_path):
    surfaces = {"outer": ball(20.0), "inner": ball(15.0, rounds=2)}
    files = solids.write(surfaces, tmp_path)
    shell, core = sources.read_solid(files["cortical"]), sources.read_solid(files["cancellous"])
    assert sources.watertight(shell) and sources.watertight(core) and shell["solids"] == 1 and core["solids"] == 1
    outer, inner = abs(solids.signed_volume(*surfaces["outer"])), abs(solids.signed_volume(*surfaces["inner"]))
    assert abs(shell["volume"] - (outer - inner)) < 1e-2 * outer and abs(core["volume"] - inner) < 1e-3 * inner, "皮质是外表面和内壁之间，松质是内壁以内"
    assert len(shell["triangles"]) == len(surfaces["outer"][1]) + len(surfaces["inner"][1])
    back = solids.surfaces_of(files)
    for name in ("outer", "inner"):
        assert len(back[name][1]) == len(surfaces[name][1]) and solids.signed_volume(*back[name]) > 0, "读回来的两个表面法向都朝外"
    thick = solids.wall(back)
    assert 4.5 < thick["wall_min_mm"] <= 5.0 + 1e-6 and 4.5 < thick["wall_max_mm"] < 5.3, f"两个球半径差 5 mm：{thick}"
    assert solids.surfaces_of({"cortical": tmp_path / "a.step", "cancellous": tmp_path / "b.step"}) is None, "CAD 的实体不是这种"
    solids.write_stl(files["cortical"], *surfaces["outer"])
    assert solids.surfaces_of(files) is None, "皮质里只有一块（没有内壁）的，也不是"


def test_replacing_one_of_the_two_solids_rewrites_the_other_to_fit(tmp_path):
    files = solids.write({"outer": ball(20.0), "inner": ball(15.0, rounds=2)}, tmp_path / "draft")
    assert solids.wall(solids.surfaces_of(files))["interface_gap_max_mm"] < 1e-6, "自动写出来的两个实体，界面是同一组顶点"
    assert solids.reconcile(files, set(), tmp_path / "none") == (files, None), "一个都没换：原样"
    assert solids.reconcile(files, {"cortical", "cancellous"}, tmp_path / "both") == (files, None), "两个都换了：人自己负责对上，原样"
    steps = {"cortical": tmp_path / "a.step", "cancellous": tmp_path / "b.step"}
    assert solids.reconcile(steps, {"cancellous"}, tmp_path / "cad") == (steps, None), "CAD 的实体不是这种"

    solids.write_stl(tmp_path / "inner.stl", *ball(12.0, rounds=2))                     # 人把内壁改小了：半径 15 变 12
    edited = dict(files, cancellous=tmp_path / "inner.stl")
    stale = solids.wall(solids.surfaces_of(edited))["interface_gap_max_mm"]
    assert 2.7 < stale < 3.5, f"不处理的话，皮质实体里留着的还是旧内壁，和新的差 3 mm：{stale}"
    fitted, said = solids.reconcile(edited, {"cancellous"}, tmp_path / "fitted")
    thick = solids.wall(solids.surfaces_of(fitted))
    assert "内壁" in said and thick["interface_gap_max_mm"] < 1e-6 and 7.5 < thick["wall_min_mm"] <= 8.0 + 1e-6
    shell = sources.read_solid(fitted["cortical"])
    whole, hollow = solids.signed_volume(*ball(20.0)), solids.signed_volume(*ball(12.0, rounds=2))
    assert abs(shell["volume"] - (whole - hollow)) < 1e-5 * whole and shell["solids"] == 1 and sources.watertight(shell)

    solids.write_stl(tmp_path / "outer.stl", *ball(21.0))                               # 换皮质，只给了一个新的外表面
    fitted, said = solids.reconcile(dict(files, cortical=tmp_path / "outer.stl"), {"cortical"}, tmp_path / "outer_only")
    thick = solids.wall(solids.surfaces_of(fitted))
    assert "只有外表面" in said and thick["interface_gap_max_mm"] < 1e-6 and 5.5 < thick["wall_min_mm"] <= 6.0 + 1e-6

    given = solids.write({"outer": ball(20.0), "inner": ball(13.0, rounds=2)}, tmp_path / "given")     # 换皮质，带着新的内壁
    fitted, said = solids.reconcile(dict(files, cortical=given["cortical"]), {"cortical"}, tmp_path / "with_inner")
    core = sources.read_solid(fitted["cancellous"])
    assert "带着新的内壁" in said and abs(core["volume"] - solids.signed_volume(*ball(13.0, rounds=2))) < 1e-5 * core["volume"]
    assert solids.wall(solids.surfaces_of(fitted))["interface_gap_max_mm"] < 1e-6


def test_the_distance_from_points_to_a_surface_is_the_true_distance():
    vertices, triangles = ball(10.0, rounds=4)
    rng = np.random.default_rng(1)
    directions = rng.standard_normal((200, 3))
    directions /= np.linalg.norm(directions, axis=1, keepdims=True)
    for radius in (4.0, 9.5, 12.0, 30.0):
        away = solids.distance(directions * radius, vertices, triangles)
        assert np.abs(away - abs(radius - 10.0)).max() < 0.06, f"离球心 {radius} 的点，离半径 10 的球面 {abs(radius - 10.0)}"


def test_one_surface_splits_into_its_connected_pieces_largest_first():
    big, small = ball(10.0), ball(2.0, (30.0, 0.0, 0.0), rounds=1)
    parts = solids.split(np.vstack([small[0], big[0]]), np.vstack([small[1], big[1] + len(small[0])]))
    assert [len(part[1]) for part in parts] == [len(big[1]), len(small[1])] and all(solids.open_edges(part[1]) == 0 for part in parts)


def femur_like(head_at_top: bool = True, condyles: bool = True) -> tuple:
    """一根像股骨的东西：一段骨干，一头是一个偏在一边的球（股骨头），另一头是并排的两个前后拉长的椭球（两个髁）。
    几块各自封闭，叠在一起。condyles 给 False 就没有髁：远端是骨干的断口。"""
    sign = 1.0 if head_at_top else -1.0
    pieces = [ball(22.0, (40.0, 0.0, sign * 200.0))]
    for x in ((-22.0, 22.0) if condyles else ()):
        points, faces = ball(20.0)
        pieces.append((points * np.array([1.0, 1.6, 1.0]) + np.array([x, 0.0, -sign * 200.0]), faces))
    rings = np.array([[14.0 * math.cos(a), 14.0 * math.sin(a), z] for z in np.linspace(-190.0, 190.0, 40) for a in np.linspace(0, 2 * math.pi, 24, endpoint=False)])
    faces = []
    for layer in range(39):
        for k in range(24):
            a, b = layer * 24 + k, layer * 24 + (k + 1) % 24
            faces += [(a, b, a + 24), (b, b + 24, a + 24)]
    pieces.append((rings, np.array(faces, dtype=np.int64)))
    shift, vertices, triangles = 0, [], []
    for points, part in pieces:
        vertices.append(points), triangles.append(part + shift)
        shift += len(points)
    return np.vstack(vertices), np.vstack(triangles)


def test_the_proximal_end_is_the_one_whose_cut_is_one_round_blob():
    for head_at_top in (True, False):
        vertices, triangles = femur_like(head_at_top)
        top, bottom = landmarks.end_roundness(vertices, triangles, np.array([0.0, 0.0, 1.0]))
        head, condyles = (top, bottom) if head_at_top else (bottom, top)
        assert head > 0.97 and condyles < 0.94, f"头的顶截出来是一个圆，髁截出来不圆：{head:.3f}、{condyles:.3f}"
        pointing = landmarks.lengthwise(vertices, triangles)
        assert (pointing[2] > 0) == head_at_top, "长方向指向有股骨头的那一头"
        old_way = landmarks.lengthwise(vertices)
        assert (old_way[2] > 0) != head_at_top, "只看“哪一头的点离长轴更远”，这根会判反：髁比头宽"
    stump = femur_like(condyles=False)
    top, bottom = landmarks.end_roundness(stump[0], stump[1], np.array([0.0, 0.0, 1.0]))
    assert abs(top - bottom) < 0.03 and landmarks.lengthwise(*stump)[2] > 0, "两头差不多圆（远端是骨干的断口）时，看哪一头的点离长轴更远"


def test_ct_settings_written_wrong_are_said_one_by_one(tmp_path):
    (tmp_path / "scan.nrrd").write_bytes(b"NRRD")
    (tmp_path / "femur.stl").write_bytes(b"stl")
    good = {"source": {"outer": "femur.stl", "ct": "scan.nrrd"}}
    assert ct.problems(tmp_path, good) == [] and solids.problems(good) == []
    assert ct.problems(tmp_path, {"source": {"outer": "femur.stl"}}) == [], "ct 不写：骨源里的体数据文件都算候选"
    assert [path.name for path in ct.volumes(tmp_path)] == ["scan.nrrd"]
    assert "CT" in ct.problems(tmp_path, {"source": {"cortical": "a.step", "cancellous": "b.step"}})[0], "CAD 的写法用在 CT 骨源上"
    assert "外形文件" in ct.problems(tmp_path, {"source": {"outer": "missing.stl"}})[0]
    assert "没有这几个 CT 文件" in ct.problems(tmp_path, {"source": {"outer": "femur.stl", "ct": ["other.nrrd"]}})[0]
    assert "只有这几项" in ct.problems(tmp_path, dict(good, ct={"cortical": 500}))[0]
    wrong = ct.problems(tmp_path, dict(good, ct={"voxel_mm": 3, "cortical_hu": "high", "depth_cap": [[0.2, 3], [1, 5]], "min_wall_voxels": 0,
                                                 "inner_sigma_mm": 0, "proximal": "top"}))
    assert len(wrong) == 6 and all(name in " ".join(wrong) for name in ("voxel_mm", "cortical_hu", "depth_cap", "min_wall_voxels", "inner_sigma_mm", "proximal")), wrong
    assert ct.problems(tmp_path, dict(good, ct={"depth_cap": None, "proximal": "low_z"})) == [], "不限深、近端明写，都可以"
    assert ct.problems(tmp_path, dict(good, ct={"edge_mm": 2.3, "tet_check": False})) == [], "变成实体的那几项也写在 ct 里"
    assert ct.options(good)["cortical_hu"] == 500.0 and ct.options(dict(good, ct={"cortical_hu": 600}))["cortical_hu"] == 600
    assert len(solids.problems(dict(good, ct={"edge_mm": 0.1, "inner_factor": 9, "remesh_iterations": 0, "tet_check": "yes"}))) == 4
    assert solids.options(dict(good, ct={"edge_mm": 2.3, "cortical_hu": 600})) == {"edge_mm": 2.3, "inner_factor": 0.8, "remesh_iterations": 8, "tet_check": True}


def test_a_ct_bone_always_asks_for_a_look_at_the_inner_wall_at_both_ends():
    quiet = {"surface_on_bone_share": 0.6, "hu_inside_p95": 1577.0, "outer_vs_reference_p95_mm": 0.13, "cortex_added_by_rules_share": 0.21}
    doubts = review.ct_doubts(quiet, [])
    assert len(doubts) == 1 and doubts[0][0] == "solids" and "不是量出来的" in doubts[0][1] and "21%" in doubts[0][1]
    loud = review.ct_doubts({"surface_on_bone_share": 0.2, "hu_inside_p95": 3050.0, "outer_vs_reference_p95_mm": 0.9, "cortex_added_by_rules_share": 0.3}, ["请核对骨的方向"])
    assert [item for item, _ in loud] == ["source", "source", "source", "solids", "solids"]
    assert "骨的方向" in loud[0][1] and "对齐" in loud[1][1] and "金属" in loud[2][1] and "0.90 mm" in loud[3][1]
    assert review.ct_doubts({"head_fit_rms_mm": 0.1}, []) == [], "CAD 的骨没有这些"
    broken = review.ct_doubts(dict(quiet, tet_check_problem="Exception: PLC Error", interface_gap_max_mm=3.0), [])
    assert [item for item, _ in broken] == ["solids"] * 3 and "没有划成" in broken[0][1] and "3.00 mm" in broken[1][1]
