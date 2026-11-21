"""重建的科学验收：3406 这根骨，自动找的标志点和旧系统核过的参考值差多少；实体的体积、颈部皮质厚度在不在合理范围。

参考值和线在 lines.py。跑的是 plugins/recon 的自动重建本身（不经过核心），骨源是旧系统里那两个 STEP，只读。
"""
from __future__ import annotations

import math

import pytest

from plugins.recon import rebuild
from stemlab.contract.formats import bone_model
from tests.science import lines, tools

pytestmark = pytest.mark.science


def _angle(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b)) / math.sqrt(sum(x * x for x in a) * sum(y * y for y in b))
    return math.degrees(math.acos(max(-1.0, min(1.0, dot))))


def test_the_landmarks_of_3406_agree_with_the_checked_reference(source, tmp_path):
    setting = {"side": "right", "source": tools.STEPS, "tessellation_mm": 4.0}
    result = rebuild.draft({"setting": setting, "source": str(source), "out": str(tmp_path)}, lambda name: None)
    assert result["status"] == "ok", result
    marks, measures = result["landmarks"], result["measures"]
    reference, line, sane = lines.RECON_REFERENCE, lines.RECON, lines.RECON_SANE
    neck, shaft = bone_model.axes(marks)
    found = {
        "head_center_mm": math.dist(marks["head_center"]["xyz"], reference["head_center"]),
        "head_diameter_mm": 2 * abs(measures["head_radius_mm"] - reference["head_radius_mm"]),
        "neck_axis_deg": _angle(neck, reference["neck_axis"]),
        "shaft_axis_deg": _angle(shaft, reference["shaft_axis"]),
        "neck_shaft_angle_deg": abs(bone_model.neck_shaft_angle(marks) - reference["neck_shaft_angle_deg"]),
        "lesser_trochanter_mm": abs(measures["lesser_trochanter_below_head_mm"] - reference["lesser_trochanter_below_head_mm"]),
        "isthmus_area_rel": abs(measures["neck_isthmus_area_mm2"] - reference["neck_isthmus_area_mm2"]) / reference["neck_isthmus_area_mm2"],
        "isthmus_position_mm": abs(measures["neck_isthmus_from_head_mm"] - reference["neck_isthmus_from_head_mm"]),
    }
    for name, value in found.items():
        print(f"{name:24} 差 {value:.4f}（线 {line[name]}）")
    wrong = {name: value for name, value in found.items() if value > line[name]}
    assert not wrong, f"这几项和参考值差得超过了线：{wrong}"

    assert measures["neck_axis_converged"] is True
    low, high = sane["neck_wall_mm"]
    assert low <= measures["neck_wall_min_mm"] and measures["neck_wall_median_mm"] <= high, \
        f"颈最细处皮质厚 {measures['neck_wall_min_mm']:.2f} 到（中位）{measures['neck_wall_median_mm']:.2f} mm"
    low, high = sane["neck_shaft_angle_deg"]
    assert low <= measures["neck_shaft_angle_deg"] <= high
    for name in ("cortical", "cancellous"):
        assert measures[f"{name}_solids"] == 1 and measures[f"{name}_watertight"] is True, f"{name} 该是一个封闭的实体"
        assert measures[f"{name}_mesh_volume_error"] <= sane["mesh_volume_error"]
    volume = (measures["cortical_volume_mm3"] + measures["cancellous_volume_mm3"]) / 1000.0
    low, high = sane["bone_volume_cm3"]
    print(f"皮质 {measures['cortical_volume_mm3'] / 1000:.1f} cm3，松质 {measures['cancellous_volume_mm3'] / 1000:.1f} cm3")
    assert low <= volume <= high, f"皮质加松质一共 {volume:.0f} cm3"
