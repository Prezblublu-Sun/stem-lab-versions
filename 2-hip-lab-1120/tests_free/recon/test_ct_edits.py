"""CT 那种实体（两个 STL：皮质 = 外表面加内壁，松质 = 内壁）定稿时用上人工修改。

人在系统外改的通常只是内壁。只换松质实体的话，皮质实体里留着的还是旧内壁，两个实体在界面上对不上。
这里验：定稿时皮质实体会照新的内壁重写，重建记录里写着，量出来的界面间隙是 0。

骨是 tests/real.py 里那根假股骨。只用 gmsh、numpy、scipy，不用 CT 重建那三个库。

5c 起重建的骨架叫重建方法包干活，插件里 CT 这条路不再经核心跑：这里先跳过，5e 把它搬进 CT 方法包时照方法包改写。
换实体、重写另一个实体那一段本身，plugins/recon/tests/test_ct_parts.py 和 test_finalize.py 直接试着。
"""
from __future__ import annotations

import pytest

from stemlab.contract.formats.manifest import check_format, make_manifest, read_manifest, write_manifest
from stemlab.desk.core import start
from stemlab.experiments import view
from stemlab.registry import register
from tests import helpers, real
from tests_free.recon import shapes

pytestmark = pytest.mark.skip(reason="5c 起重建经重建方法包走，插件里的 CT 这条路不再经核心跑；等 5e 的 CT 方法包")

SEAM = {"name": "seam", "value": "interface_gap_max_mm", "max": 0.01, "what": "两个实体在界面上对得上"}


def ct_style_draft(tmp) -> tuple:
    """登记一个候选骨模型，实体是 CT 重建写出来的那种。返回（登记的候选，外表面，内壁）。"""
    from plugins.recon import solids

    outer, inner = shapes.whole_femur(tmp / "whole.step"), shapes.core(tmp)
    made = solids.write({"outer": outer, "inner": inner}, tmp / "made")
    files = {f"solids/{name}.stl": path.read_bytes() for name, path in made.items()}
    folder = helpers.write_files(tmp / "draft", files)
    whole, hollow = abs(solids.signed_volume(*outer)), abs(solids.signed_volume(*inner))
    extra = dict(real.BONE_EXTRA, solids={name: {"file": f"solids/{name}.stl"} for name in made}, checks=[],
                 measures={"cortical_volume_mm3": whole - hollow, "cancellous_volume_mm3": hollow},
                 history=[{"step": "ct-input", "what": "测试：照 CT 重建的写法写出来的两个实体"}])
    write_manifest(folder, {**make_manifest("bone_draft", list(files), bone_id=real.BONE, **extra), "format": 1})    # 第 1 版的内容，明写第 1 版
    assert check_format("bone_draft", folder) == []
    draft = register.register_external("bone_draft", f"{real.BONE}-ct-draft", note="测试：CT 那种实体的候选", by="tester", bone_id=real.BONE,
                                       source=folder, new_bone=True)
    return draft, outer, inner


def finished(made: str, seconds: float = 300.0):
    assert start.start(made).ok
    real.run(made, seconds=seconds)
    return view.view(made)


def test_replacing_the_inner_wall_by_hand_rewrites_the_cortical_solid_to_fit(real_lab, tmp_path):
    from plugins.recon import solids

    draft, outer, inner = ct_style_draft(tmp_path)
    centre = inner[0].mean(0)
    solids.write_stl(tmp_path / "inner_smaller.stl", (inner[0] - centre) * 0.95 + centre, inner[1])        # 人把内壁往里收了一点
    edit = real.edits(tmp_path, {"by": "wei", "solids": {"cancellous": {"file": "inner_smaller.stl", "why": "头颈部的内壁往里收"}}},
                      files={"inner_smaller.stl": (tmp_path / "inner_smaller.stl").read_bytes()})
    setting = real.recon_setting(real.GATE + [SEAM], ct={"tet_check": False})
    final = real.recon_finalize(draft["id"], setting, edits=edit)
    status = finished(final)
    assert real.tasks(final) == {"finalize": ("done", "passed")}, (status.rounds[-1].reason, status.rounds[-1].problems)
    folder = real.output(final, "model")
    model = read_manifest(folder)
    said = [step["what"] for step in model["history"]]
    assert any("实体 cancellous 换成 inner_smaller.stl" in what for what in said), said
    assert any("皮质实体照新的内壁重写了" in what for what in said), said
    seen = model["measures"]
    assert seen["interface_gap_max_mm"] < 1e-6 and seen["surfaces_open_edges"] == 0 and "tet_gamma_min" not in seen
    whole, hollow = abs(solids.signed_volume(*outer)), abs(solids.signed_volume(*inner)) * 0.95 ** 3
    assert abs(seen["cancellous_volume_mm3"] - hollow) < 1e-3 * hollow, "松质就是新的内壁以内"
    assert abs(seen["cortical_volume_mm3"] - (whole - hollow)) < 1e-3 * whole, "皮质 = 原来的外表面和新的内壁之间"
    back = solids.surfaces_of({name: folder / model["solids"][name]["file"] for name in ("cortical", "cancellous")})
    assert back is not None and len(back["seam"][1]) == len(back["inner"][1]) == len(inner[1])
    assert seen["cortical_volume_change"] > 0.01, "和候选时比，皮质实体变了，量得出来"


def test_without_an_edit_the_candidate_is_finalized_as_it_is(real_lab, tmp_path):
    draft, _, _ = ct_style_draft(tmp_path)
    final = real.recon_finalize(draft["id"], real.recon_setting(real.GATE + [SEAM], ct={"tet_check": False}))
    status = finished(final)
    assert real.tasks(final) == {"finalize": ("done", "passed")}, (status.rounds[-1].reason, status.rounds[-1].problems)
    model = read_manifest(real.output(final, "model"))
    assert model["measures"]["interface_gap_max_mm"] < 1e-6 and model["measures"]["cortical_volume_change"] < 1e-5
    assert [step["step"] for step in model["history"]] == ["ct-input", "review"]
