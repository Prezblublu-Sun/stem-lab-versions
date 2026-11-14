"""来路只认两种形状。"""
from __future__ import annotations

import pytest

from stemlab.contract.origin import check_origin, external, product


def test_the_two_shapes_pass():
    assert check_origin(external("手写的条件默认", "prez")) == []
    assert check_origin(product("E0007", 2, "data")) == []
    assert external("n", "b") == {"from": "external", "note": "n", "by": "b"}
    assert product("E0007", 2, "data") == {"from": "product", "experiment": "E0007", "round": 2, "output": "data"}


BAD = [
    None, "external", [], {},
    {"from": "copied", "note": "x", "by": "y"},
    {"from": "external", "note": "x"},
    {"from": "external", "note": "", "by": "y"},
    {"from": "external", "note": "x", "by": "   "},
    {"from": "external", "note": "x", "by": "y", "experiment": "E0001"},
    {"from": "external", "note": 5, "by": "y"},
    {"from": "product", "experiment": "E0007", "round": 2},
    {"from": "product", "experiment": "7", "round": 2, "output": "data"},
    {"from": "product", "experiment": "R0007", "round": 2, "output": "data"},
    {"from": "product", "experiment": "E0007", "round": 0, "output": "data"},
    {"from": "product", "experiment": "E0007", "round": "2", "output": "data"},
    {"from": "product", "experiment": "E0007", "round": True, "output": "data"},
    {"from": "product", "experiment": "E0007", "round": 2, "output": "Data Table"},
    {"from": "product", "experiment": "E0007", "round": 2, "output": "data", "note": "x"},
    {"from": "product", "experiment": "E0007", "round": 2, "output": "data", "by": "y", "note": "x"},
]


@pytest.mark.parametrize("origin", BAD)
def test_anything_else_is_refused(origin):
    problems = check_origin(origin)
    assert problems and all(isinstance(text, str) and text for text in problems)
