"""整条链在真东西上走一遍：3406 的 CAD 骨源 → recon.draft → recon.finalize（带内核冒烟）→ fea.run（真内核、真求解）→ 数据。

别的测试里内核和求解都是假的；这一条用登记进系统的真内核包和真的 Abaqus，经操作台核心和插件走下来，
看出来的数和旧数据库同一个设计的那一行对不对得上。一次求解要十几分钟，所以要设 STEMLAB_SCIENCE_SLOW=1 才跑。
"""
from __future__ import annotations

import math
import os
import subprocess
import sys

import pytest

from stemlab.contract.formats.manifest import check_format, read_manifest
from stemlab.contract.formats.points import read_points
from stemlab.desk.core import start
from stemlab.experiments import view
from stemlab.registry import register
from tests import helpers, real
from tests.science import lines, tools
from tests.science.test_fea import CONDITIONS, A

pytestmark = pytest.mark.science

FRAME = {"origin": "the origin of the CAD files", "x": "medial", "y": "posterior", "z": "proximal"}
MATERIALS = {"cortical": {"model": "linear_elastic", "E_MPa": 16700.0, "nu": 0.3},
             "cancellous": {"model": "linear_elastic", "E_MPa": 155.0, "nu": 0.3}}
GATE = [
    {"name": "cortical_closed", "value": "cortical_watertight", "equals": True, "what": "皮质实体的表面封闭"},
    {"name": "cancellous_closed", "value": "cancellous_watertight", "equals": True, "what": "松质实体的表面封闭"},
    {"name": "head_fit", "value": "head_fit_rms_mm", "max": 1.0, "what": "股骨头球拟合的残差不超过 1 mm"},
    {"name": "neck_wall", "value": "neck_wall_min_mm", "min": lines.RECON_SANE["neck_wall_mm"][0], "what": "股骨颈处皮质最薄不小于 0.3 mm"},
    {"name": "neck_shaft_angle", "value": "neck_shaft_angle_deg", "min": 110.0, "max": 145.0, "what": "颈干角在成人的范围里"},
]
FINAL = GATE + [
    {"name": "volume_kept", "value": "cortical_volume_change", "max": 0.005, "what": "皮质实体的体积和候选时相差不超过 0.5%"},
    {"name": "landmarks_near", "value": "landmark_shift_max_mm", "max": 5.0, "what": "定稿的标志点离自动找的不超过 5 mm"},
    {"name": "kernel_fits", "value": "kernel_smoke", "equals": True, "what": "内核在这根骨上模板化得了基线设计"},
]


def finished(made: str, seconds: float):
    assert start.start(made).ok
    real.run(made, seconds=seconds)
    return view.view(made)


def test_one_point_from_the_cad_source_to_the_data(package, source, abaqus, real_lab, data, tmp_path):
    if os.environ.get("STEMLAB_SCIENCE_SLOW") != "1":
        pytest.skip("整条链要真算一次（十几分钟到半小时）：设 STEMLAB_SCIENCE_SLOW=1 才跑")
    old = tools.legacy_rows(lines.LEGACY_JOB)[0]
    files = {name: (source / name).read_bytes() for name in tools.STEPS.values()}
    origin = register.register_external("bone_source", "sawbone3406-cad", note="3406 的两个 STEP", by="tester", bone_id=tools.BONE_ID,
                                        new_bone=True, source=helpers.make_folder(tmp_path / "source", "bone_source", files, bone_id=tools.BONE_ID))
    kernel = register.register_external("kernel", "kernel-m1-3406", source=package, note="M1-3406-v1 的内核包", by="tester")
    built = subprocess.run([sys.executable, str(helpers.REPO / "external" / "derive_bed_f" / "build.py"), str(tmp_path / "derive")],
                           capture_output=True, env=dict(os.environ, **tools.ENV))
    assert built.returncode == 0, built.stderr.decode("utf-8", "replace")[-1500:]
    derive = register.register_external("derive_def", "derive-bed-f", source=tmp_path / "derive", note="骨床支撑量", by="tester")

    base = {"side": "right", "frame": FRAME, "materials": MATERIALS, "source": tools.STEPS, "tessellation_mm": 4.0}
    draft = finished(real.recon_draft(tmp_path, origin, real.setting(dict(base, gate=GATE))), 900)
    assert draft.rounds[-1].result == "done", (draft.rounds[-1].reason, draft.rounds[-1].problems)
    asked = real.recon_finalize(draft.rounds[-1].outputs["draft"]["item"], kernel=kernel,
                                value=real.setting(dict(base, gate=FINAL, smoke={"mode": "template", "design": A})))
    final = finished(asked, 1800)
    assert real.tasks(asked) == {"finalize": ("done", "passed")}, (final.rounds[-1].reason, final.rounds[-1].problems)
    model = final.rounds[-1].outputs["model"]["item"]
    assert check_format("bone_model", real.output(asked, "model")) == [] and read_manifest(real.output(asked, "model"))["bone_id"] == tools.BONE_ID

    point = {"name": "A", "bone_id": tools.BONE_ID, "design": A, "conditions": CONDITIONS, "reason": "和旧数据库 v0.14 同一个设计"}
    made = real.fea(tmp_path, [point], export={"solve_timeout_s": 7200}, kernel=kernel, derive=derive, bone={"id": model})
    status = finished(made, 5400)
    assert real.tasks(made) == {"A": ("done", "finished")}, (status.rounds[-1].reason, status.rounds[-1].problems)
    assert check_format("data", real.output(made, "data")) == [] and check_format("archive", real.output(made, "archive")) == []
    values = read_points(real.output(made, "data") / "rows.jsonl")[0]["values"]
    for name, limit in lines.VS_LEGACY_DEX.items():
        apart = abs(math.log10(values[name] / float(old[name])))
        print(f"{name:18} 新 {values[name]:.6g}  旧 {float(old[name]):.6g}  差 {apart:.4f} dex（线 {limit}）")
        assert apart <= limit, f"{name} 和旧系统差 {apart:.4f} dex"
    assert abs(values["bone_total_mm3"] - float(old["bone_total_mm3"])) / float(old["bone_total_mm3"]) <= lines.VS_LEGACY_REL["bone_total_mm3"]
    assert values["iface_force_err_load"] <= lines.FORCE_BALANCE and values["F_mm"] is not None, "推导量（骨床支撑量）经 derive 算出来了"
    print(f"骨床支撑量 F = {values['F_mm']:.3f} mm；归档里留了 {read_manifest(real.output(made, 'archive'))['count']} 个文件")
