"""名字的规矩有两套：键名（输入名、产物名、结局名、图表名）只许小写；数据的列名、点的设计项和条件项可以带大写。

物理量的名字常带大写（L、E_canc_MPa、A0_mm2），所以列名放开；但同一张表里只差大小写的两个名字不许有。
"""
from __future__ import annotations

import pytest

from stemlab.contract import layout
from stemlab.contract.formats import data, points


def test_keys_are_lower_case_and_columns_may_have_capitals():
    for name in ("L", "E_canc_MPa", "A0_mm2", "load_x_N", "rotation"):
        assert layout.is_column(name), name
    for name in ("9lives", "load N", "", "_hidden", "长度", "a" * 41, None, 3):
        assert not layout.is_column(name), name
    assert layout.is_key("load") and not layout.is_key("L"), "键名的规矩没变"
    assert layout.same_but_case(["L", "alpha", "l", "Alpha"]) == ["l", "Alpha"]
    assert layout.same_but_case(["L", "alpha", "E_canc_MPa"]) == []


def test_a_batch_of_points_may_use_capital_names(tmp_path):
    point = {"name": "p1", "bone_id": "femur042", "design": {"L": 30.0, "alpha": 40.0}, "conditions": {"E_canc_MPa": 155.0}, "reason": "x"}
    listed = points.write_points(tmp_path / "ok", [point])
    assert (listed["design_keys"], listed["condition_keys"]) == (["L", "alpha"], ["E_canc_MPa"])
    assert points.check("points", listed, tmp_path / "ok") == []
    with pytest.raises(ValueError, match="大小写"):
        points.write_points(tmp_path / "clash", [dict(point, design={"L": 30.0, "l": 1.0})])
    with pytest.raises(ValueError, match="名字"):
        points.write_points(tmp_path / "odd", [dict(point, design={"stem length": 30.0})])


def test_data_columns_may_use_capital_names_but_not_differ_only_by_case():
    column = {"name": "L", "unit": "mm", "meaning": "stem length", "role": "design"}
    assert data.check_columns("data", {"columns": [column, dict(column, name="E_canc_MPa", role="condition")]}) == []
    assert any("大小写" in text for text in data.check_columns("data", {"columns": [column, dict(column, name="l")]}))
    assert any("列名" in text for text in data.check_columns("data", {"columns": [dict(column, name="stem length")]}))
