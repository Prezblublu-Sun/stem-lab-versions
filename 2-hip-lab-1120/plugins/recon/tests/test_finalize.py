"""定稿时，候选的数只照抄定稿不重做、也重做不了的那几样：CT 那一步的数；两个实体都没换过时，重划那一步的数。

壁厚、界面间隙、四面体这些说的是候选的几何。定稿这次没量成（换上的实体不是 STL、四面体没划成），就是没有数，
检查门照没有数判，不拿候选的数充数。读实体、找标志点、量这些重活换成了桩：这里只验带不带过来。
"""
from __future__ import annotations

import json

import pytest

from plugins.recon import ct, gate, rebuild, solids

CANDIDATE = {
    "ct_file": "ct.nrrd", "cortex_mask_mm3": 100.0, "interior_mask_mm3": 50.0, "isthmus_canal_diameter_mm": 12.0,   # CT 那一步的
    "remesh_deviation_p95_mm": 0.12, "surfaces_open_edges": 0, "outer_triangles": 9000,                            # 重划那一步的
    "tet_gamma_min": 0.31, "tet_inverted": 0, "tet_count": 50000,                                                  # 候选的几何
    "wall_min_mm": 1.2, "interface_gap_max_mm": 0.0,
    "cortical_volume_mm3": 100.0, "cancellous_volume_mm3": 50.0,
}
LINES = [{"name": "open", "value": "surfaces_open_edges", "max": 0}, {"name": "remesh", "value": "remesh_deviation_p95_mm", "max": 0.3},
         {"name": "tets", "value": "tet_gamma_min", "min": 0.1}, {"name": "inverted", "value": "tet_inverted", "max": 0},
         {"name": "seam", "value": "interface_gap_max_mm", "max": 0.01}]


@pytest.fixture
def finalize(tmp_path, monkeypatch):
    """给出一个函数：照给的人工修改定稿一根 CT 的候选，返回定稿的结果。"""
    draft = tmp_path / "draft"
    draft.mkdir()
    (draft / "manifest.json").write_text(json.dumps({
        "solids": {"cortical": {"file": "solids/cortical.stl"}, "cancellous": {"file": "solids/cancellous.stl"}},
        "landmarks": {}, "history": [], "measures": CANDIDATE}), encoding="utf-8")
    monkeypatch.setattr(rebuild, "_read", lambda files, setting: {"cortical": {"volume": 101.0}, "cancellous": {"volume": 49.0}})
    monkeypatch.setattr(rebuild.landmarks, "find", lambda mesh, side: {"landmarks": {"head_center": {"xyz": [0.0, 0.0, 0.0]}}})
    monkeypatch.setattr(rebuild, "measure", lambda meshes, found: {"cortical_volume_mm3": 101.0, "cancellous_volume_mm3": 49.0})
    monkeypatch.setattr(rebuild.sources, "quality_histogram", lambda mesh: {})

    def run(replace: str | None = None) -> dict:
        def apply(listed, source, edits):
            files = {name: source / listed["solids"][name]["file"] for name in rebuild.NAMES}
            if replace:
                files["cancellous"] = tmp_path / "edits" / replace
            return files, {"head_center": {"xyz": [0.0, 0.0, 0.0]}}, []

        monkeypatch.setattr(rebuild.review, "apply", apply)
        job = {"setting": {"side": "right", "ct": {"tet_check": True}}, "draft": str(draft),
               "edits": str(tmp_path / "edits") if replace else None, "out": str(tmp_path / "out")}
        return rebuild.finalize(job, lambda name: None)

    return run


def surfaces_measured(monkeypatch, tet):
    """两个实体是这里写出来的那种：壁厚、界面量得出来；四面体照 tet 给的划（抛错就是没划成）。"""
    monkeypatch.setattr(solids, "surfaces_of", lambda files: {"outer": (None, []), "inner": (None, []), "seam": (None, [])})
    monkeypatch.setattr(solids, "wall", lambda surfaces: {"wall_min_mm": 1.1, "interface_gap_max_mm": 0.0})
    monkeypatch.setattr(solids, "open_edges", lambda triangles: 0)
    monkeypatch.setattr(solids, "tet_check", tet)


def test_a_replaced_solid_that_is_not_stl_leaves_the_mesh_numbers_empty(finalize):
    """换上的松质是 .step：另一个没重写，网格那几项量不了。候选的数不带过来，检查门里拿它们比的线不过。"""
    result = finalize("cancellous_fixed.step")
    got = result["measures"]
    for name in ("tet_gamma_min", "tet_inverted", "tet_count", "wall_min_mm", "interface_gap_max_mm"):
        assert name not in got, f"{name} 说的是候选的几何，不该带过来"
    for name in ("remesh_deviation_p95_mm", "surfaces_open_edges", "outer_triangles"):
        assert name not in got, f"{name} 说的是重划之后的候选表面；实体换过了，不再是定稿的"
    assert {name: got[name] for name in ("ct_file", "cortex_mask_mm3", "isthmus_canal_diameter_mm")} == \
        {name: CANDIDATE[name] for name in ("ct_file", "cortex_mask_mm3", "isthmus_canal_diameter_mm")}, "CT 那一步的数照抄"
    checks = {row["name"]: row for row in gate.checks(got, LINES)}
    assert not gate.passed(list(checks.values())) and all(row["value"] is None and row["passed"] is False for row in checks.values())
    said = " ".join(step["what"] for step in result["history"])
    assert "不是 STL" in said and "没有照它重写" in said, "没重写要说出来"
    assert "不沿用候选的数" in said and "tet_gamma_min" in said


def test_a_tet_check_that_fails_at_finalize_does_not_borrow_the_candidates_tets(finalize, monkeypatch):
    """实体没换过，四面体这次没划成（比如库一时加载不了）：四面体那几项没有数，不拿候选的；重划那一步的数照抄。"""
    def broken(surfaces, edge):
        raise ImportError("DLL load failed while importing gmsh")

    surfaces_measured(monkeypatch, broken)
    got = finalize()["measures"]
    assert "tet_gamma_min" not in got and "tet_inverted" not in got and "ImportError" in got["tet_check_problem"]
    assert got["wall_min_mm"] == 1.1 and got["surfaces_open_edges"] == 0, "量得出来的照这次量的"
    assert got["remesh_deviation_p95_mm"] == CANDIDATE["remesh_deviation_p95_mm"], "实体没换过：重划那一步的数还是这两个实体的"
    failed = [row["name"] for row in gate.checks(got, LINES) if not row["passed"]]
    assert failed == ["tets", "inverted"]


def test_when_everything_is_measured_again_nothing_is_borrowed_but_the_ct_and_remesh_steps(finalize, monkeypatch):
    surfaces_measured(monkeypatch, lambda surfaces, edge: {"tet_count": 48000, "tet_gamma_min": 0.29, "tet_inverted": 0})
    result = finalize()
    got = result["measures"]
    assert (got["tet_gamma_min"], got["tet_count"], got["wall_min_mm"]) == (0.29, 48000, 1.1), "用这次量的，不用候选的"
    assert gate.passed(gate.checks(got, LINES))
    assert not any("不沿用" in step["what"] for step in result["history"]), "什么都量到了，就没有要说的"
    assert set(CANDIDATE) <= set(got)


def test_the_two_lists_of_borrowed_numbers_name_steps_finalize_does_not_redo():
    """照抄的只有这两份清单里的；清单里不该有定稿自己会量的数（壁厚、界面、四面体、实体的体积）。"""
    borrowed = set(ct.MEASURES) | set(solids.REMESH_MEASURES)
    assert not borrowed & {"wall_min_mm", "wall_p05_mm", "wall_median_mm", "wall_max_mm", "interface_gap_max_mm", "tet_gamma_min",
                           "tet_inverted", "tet_count", "cortical_volume_mm3", "cancellous_volume_mm3"}
    assert len(set(ct.MEASURES)) == len(ct.MEASURES) and len(set(solids.REMESH_MEASURES)) == len(solids.REMESH_MEASURES)
