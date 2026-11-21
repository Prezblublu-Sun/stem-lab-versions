"""CT 骨源经真的重建插件走完“候选”和“定稿”。

骨是 tests/real.py 里那根造出来的假股骨：涂成一份 CT（整根外形以内是皮质 1200 HU，松质芯以内 150，外面 0），
外形用整根骨不挖内腔的表面。标志点的真值手上有（real.TRUTH），所以 CT 这条路找得准不准可以直接比。

要 VTK、SimpleITK、MeshLab。这三个库装上了却加载不了的时候（比如安全软件还占着刚装的文件），这里的测试跳过并说明原因。

5c 起重建的骨架叫重建方法包干活，插件里 CT 这条路不再经核心跑：这里先跳过，5e 把它搬进 CT 方法包时照方法包改写。
CT 那几步本身，plugins/recon/tests/ 里的几个测试直接试着。
"""
from __future__ import annotations

import json
import math

import numpy as np
import pytest

from stemlab.contract.formats import bone_model
from stemlab.contract.formats.manifest import check_format, read_manifest
from stemlab.desk.core import start
from stemlab.experiments import view
from tests import real
from tests_free.recon import shapes

pytestmark = pytest.mark.skip(reason="5c 起重建经重建方法包走，插件里的 CT 这条路不再经核心跑；等 5e 的 CT 方法包")

SPACING, MARGIN = 0.8, 10.0
GATE = real.GATE + [
    {"name": "closed", "value": "surfaces_open_edges", "max": 0, "what": "两个表面都封闭"},
    {"name": "remesh_close", "value": "remesh_deviation_p95_mm", "max": 0.3, "what": "重划之后离原来的表面不超过 0.3 mm（95% 分位）"},
    {"name": "wall", "value": "wall_min_mm", "min": 1.0, "what": "皮质处处不薄于 1 mm"},
]
FINAL = GATE + [
    {"name": "tets_fit", "value": "tet_gamma_min", "min": 0.1, "what": "四面体最差的 gamma 不低于 0.1"},
    {"name": "tets_upright", "value": "tet_inverted", "max": 0, "what": "没有翻转的四面体"},
    {"name": "landmarks_near", "value": "landmark_shift_max_mm", "max": 5.0, "what": "定稿的标志点离自动找的不超过 5 mm"},
]


def libraries():
    try:
        import pymeshlab  # noqa: F401
        import SimpleITK

        from plugins.recon import ct

        ct.toolkit()
    except ImportError as error:
        pytest.skip(f"CT 重建要的库加载不了：{error}")
    return SimpleITK


def ct_source(tmp) -> dict:
    """把假股骨涂成一份 CT，登记成骨源：ct.nrrd 和 outer.stl。"""
    from plugins.recon import ct, solids

    sitk = libraries()
    whole = shapes.whole_femur(tmp / "whole.step")
    for name, (points, faces) in (("outer", whole), ("core", shapes.core(tmp))):
        solids.write_stl(tmp / f"{name}.stl", points, faces)
    low = whole[0].min(0) - MARGIN
    size = [int(math.ceil((whole[0].max(0)[k] - low[k] + MARGIN) / SPACING)) for k in range(3)]
    inside = {name: sitk.GetArrayFromImage(ct.fill_solid(ct.rasterize(ct.read_shape(tmp / f"{name}.stl"), tuple(low), size, SPACING))) > 0
              for name in ("outer", "core")}
    values = np.where(inside["core"], 150.0, np.where(inside["outer"], 1200.0, 0.0)).astype(np.float32)
    image = sitk.GetImageFromArray(values)
    image.SetSpacing((SPACING,) * 3)
    image.SetOrigin(tuple(float(v) for v in low))
    sitk.WriteImage(image, str(tmp / "ct.nrrd"), True)
    return real.cad_source(tmp, files={"ct.nrrd": (tmp / "ct.nrrd").read_bytes(), "outer.stl": (tmp / "outer.stl").read_bytes()})


def setting(gate, **more) -> dict:
    # triangles 给得比细表面实际的多，也就是不减面。这根假股骨的骨干是一段完美的圆柱：减面会把它减成上百毫米长的细长三角形，
    # MeshLab 重划时在这一段翻面，四面体就划不成（真实的股骨没有这样的圆柱，默认的 12 万在 z061 上核过）。
    return real.recon_setting(gate, source={"outer": "outer.stl", "ct": "ct.nrrd"}, ct={"triangles": 5_000_000, **more})


def finished(made: str, seconds: float = 600.0):
    assert start.start(made).ok
    real.run(made, seconds=seconds)
    return view.view(made)


def test_a_ct_source_goes_from_draft_to_a_bone_model(real_lab, tmp_path):
    source = ct_source(tmp_path)
    made = real.recon_draft(tmp_path, source, setting(GATE, tet_check=False))
    status = finished(made)
    assert real.tasks(made) == {"rebuild": ("done", "rebuilt")}, (status.rounds[-1].reason, status.rounds[-1].problems)
    folder = real.output(made, "draft")
    assert check_format("bone_draft", folder) == []
    listed = read_manifest(folder)
    assert listed["bone_id"] == real.BONE and {row["file"] for row in listed["solids"].values()} == {"solids/cortical.stl", "solids/cancellous.stl"}
    seen = listed["measures"]
    assert seen["ct_file"] == "ct.nrrd" and seen["ct_flip"] == [1, 1, 1] and seen["cortical_watertight"] and seen["cancellous_watertight"]
    assert seen["cortical_solids"] == 1 and seen["cancellous_solids"] == 1 and seen["surfaces_open_edges"] == 0 and "tet_gamma_min" not in seen
    assert seen["cortical_mesh_volume_error"] < 0.03 and seen["cancellous_mesh_volume_error"] < 0.03, "表面围出的体积和体素数出来的对得上"
    assert seen["outer_vs_reference_mean_mm"] < 0.2 and seen["wall_min_mm"] > 1.0
    steps = [step["step"] for step in listed["history"]]
    assert steps == ["ct-input", "ct-resample", "ct-cortex", "ct-interior", "ct-surfaces", "ct-remesh", "landmarks"], steps

    truth, marks = real.TRUTH, listed["landmarks"]
    assert math.dist(marks["head_center"]["xyz"], truth["head_center"]) < 1.0, marks["head_center"]
    assert abs(seen["head_radius_mm"] - truth["head_radius"]) < 0.6 and seen["head_fit_rms_mm"] < 0.5
    assert math.dist(marks["neck_center"]["xyz"], truth["neck_center"]) < 2.0, marks["neck_center"]
    assert abs(bone_model.neck_shaft_angle(marks) - truth["neck_shaft_angle"]) < 2.0
    assert math.dist(marks["lesser_trochanter"]["xyz"], truth["lesser_trochanter"]) < 3.0, marks["lesser_trochanter"]
    assert abs(seen["neck_wall_median_mm"] - truth["neck_wall"]) < 0.8, f"颈最细处的皮质 4 mm：{seen['neck_wall_median_mm']}"

    todo = json.loads((real.output(made, "todo") / "report.json").read_bytes())["todo"]
    assert any(row["doubt"] and "不是量出来的" in row["why"] for row in todo), "CT 的骨，两端的内壁每一根都请人看"

    final = real.recon_finalize(status.rounds[-1].outputs["draft"]["item"], setting(FINAL))
    status = finished(final)
    assert real.tasks(final) == {"finalize": ("done", "passed")}, (status.rounds[-1].reason, status.rounds[-1].problems)
    model = read_manifest(real.output(final, "model"))
    assert check_format("bone_model", real.output(final, "model")) == [] and all(check["passed"] for check in model["checks"])
    names = {check["name"] for check in model["checks"]}
    assert {"closed", "remesh_close", "wall", "tets_fit", "tets_upright"} <= names
    assert model["measures"]["tet_inverted"] == 0 and model["measures"]["tet_gamma_min"] >= 0.1 and model["measures"]["ct_file"] == "ct.nrrd"


def test_a_ct_source_written_wrong_is_refused_before_anything_runs(real_lab, tmp_path):
    from stemlab.contract import Refused

    source = real.cad_source(tmp_path, files={"ct.nrrd": b"NRRD0004", "outer.stl": b"solid"})        # 启动前的检查不打开体数据，不用那三个库
    for value, said in ((real.recon_setting(), "CT"), (real.recon_setting(source={"outer": "missing.stl"}), "外形文件"),
                        (real.recon_setting(source={"outer": "outer.stl"}, ct={"voxel_mm": 9}), "voxel_mm"),
                        (real.recon_setting(source={"outer": "outer.stl"}, ct={"edge_mm": 0.01}), "edge_mm")):
        with pytest.raises(Refused, match=said):
            start.start(real.recon_draft(tmp_path, source, value))
