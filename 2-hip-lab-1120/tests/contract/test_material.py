"""材料的给法（柄的模型和骨模型共用）：七种给法各写得出；参数不合理的被拒，说出是哪一样；四篇文献里用到的都写得进去。"""
from __future__ import annotations

import pytest

from stemlab.contract.formats import material as m

TI = {"model": "elastic", "E": 110000, "nu": 0.3, "density": 4.43}
AXES = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
KEYAK = [{"from": 0, "to": 0.27, "a": 33900, "b": 2.2}, {"from": 0.27, "to": 0.6, "a": 5307, "b": 0.0},
         {"from": 0.6, "to": 2.0, "a": 10200, "b": 2.01}]


def samples() -> dict:
    return {
        "elastic": dict(TI),
        "engineering_constants": {"model": "engineering_constants", "E1": 17000, "E2": 11500, "E3": 11500, "nu12": 0.32,
                                  "nu13": 0.32, "nu23": 0.33, "G12": 3300, "G13": 3300, "G23": 3600, "axes": AXES},
        "neo_hooke": m.neo_hooke_from(13.6, 1359),
        "mooney_rivlin": {"model": "mooney_rivlin", "C10": 0.5, "C01": 0.1, "D1": 0.01},
        "piecewise": {"model": "piecewise", "along": "stem_axis",
                      "segments": [{"from": 20.0 * n, "to": 20.0 * (n + 1), "material": dict(TI, E=5000 + 1000 * n)}
                                   for n in range(7)]},
        "field": {"model": "field", "source": {"prediction": "R0042", "field": "density"},
                  "relation": [{"from": 0, "to": 1, "a": 110000, "b": 2.0}], "nu": 0.3},
        "density": {"model": "density", "ct": "C0001", "calibration": {"slope": 0.0008, "intercept": 0.002, "phantom": "QRM-BDC"},
                    "relation": KEYAK, "nu": 0.4, "bounds": {"min": 0.01, "max": 30000}, "bins": 100, "mapping": "按单元取平均"},
    }


@pytest.mark.parametrize("model", m.MODELS)
def test_every_model_can_be_written(model):
    assert m.check_material(samples()[model], axes={"stem_axis"}) == []


def test_neo_hooke_written_as_shear_and_bulk_moduli_is_converted_on_import():
    """Harris 2012 的软骨：G 13.6 MPa、K 1,359 MPa。Abaqus 要的是 C10 = G/2、D1 = 2/K。"""
    cartilage = m.neo_hooke_from(13.6, 1359)
    assert cartilage == {"model": "neo_hooke", "C10": 6.8, "D1": 2 / 1359}


@pytest.mark.parametrize("model,change,said", [
    ("elastic", {"E": 0}, "E 要是正数"),
    ("elastic", {"nu": 0.5}, "nu 要在 0 到 0.5 之间"),
    ("elastic", {"nu": -0.1}, "nu 要在 0 到 0.5 之间"),
    ("elastic", {"density": 0}, "density 要是正数"),
    ("elastic", {"colour": "grey"}, "多了 colour"),
    ("engineering_constants", {"G23": -1}, "G23 要是正数"),
    ("engineering_constants", {"nu12": "0.3"}, "nu12 要是一个数"),
    ("engineering_constants", {"axes": [[1, 0, 0], [1, 0, 0], [0, 0, 1]]}, "两两垂直"),
    ("neo_hooke", {"C10": 0}, "C10 要是正数"),
    ("neo_hooke", {"D1": -0.001}, "D1 不能是负数"),
    ("mooney_rivlin", {"C10": -0.5, "C01": 0.1}, "加起来为正"),
    ("mooney_rivlin", {"D1": -0.01}, "D1 不能是负数"),
    ("field", {"source": {"prediction": "not-an-id", "field": "density"}}, "source 要写成"),
    ("field", {"relation": []}, "至少一段"),
    ("field", {"nu": 0.5}, "nu 要在 0 到 0.5 之间"),
    ("density", {"calibration": {"slope": 0, "intercept": 0, "phantom": "QRM"}}, "calibration 要写成"),
    ("density", {"relation": KEYAK[:1] + KEYAK[2:]}, "要接着上一段"),
    ("density", {"bounds": {"min": 10, "max": 1}}, "bounds 要写成"),
    ("density", {"bins": 0}, "bins 要是正整数"),
    ("density", {"mapping": " "}, "mapping 要写"),
    ("density", {"ct": "femur042"}, "ct 要是"),
])
def test_unreasonable_parameters_are_refused_and_named(model, change, said):
    spec = dict(samples()[model], **change)
    problems = m.check_material(spec)
    assert problems and any(said in text for text in problems), problems


def test_a_missing_parameter_and_an_unknown_model_are_refused():
    spec = samples()["elastic"]
    del spec["E"]
    assert m.check_material(spec) == ["材料（elastic）：缺 E"]
    assert "model 要是" in m.check_material({"model": "plastic"})[0]
    assert "model 要是" in m.check_material("elastic")[0]


@pytest.mark.parametrize("change,said", [
    (lambda s: s.update(along="no_such_axis"), "这个模型里没有"),
    (lambda s: s["segments"][3].update({"from": 61.0}), "要接着上一段"),
    (lambda s: s["segments"][1].update({"from": 21.0}), "第 2 段要接着上一段"),
    (lambda s: s["segments"][0].update({"to": 0.0}), "from 小于 to"),
    (lambda s: s["segments"][1].update(material={"model": "field"}), "均匀的给法"),
    (lambda s: s["segments"][2]["material"].update(E=-5), "第 3 段"),
    (lambda s: s["segments"][0].pop("material"), "要写且只写"),
    (lambda s: s.update(segments=[]), "segments 要是段的列表"),
])
def test_piecewise_segments_are_contiguous_along_a_real_axis_and_each_uniform(change, said):
    spec = samples()["piecewise"]
    change(spec)
    problems = m.check_material(spec, axes={"stem_axis"})
    assert problems and any(said in text for text in problems), problems


def test_unit_axes():
    assert m.unit_axes(AXES)
    assert not m.unit_axes([[1, 0, 0], [0, 1, 0]])
    assert not m.unit_axes([[2, 0, 0], [0, 1, 0], [0, 0, 1]])
    assert not m.unit_axes([[1, 0, 0], [0, 1, 0], "z"])
    assert not m.unit_axes([[1, 0, 0], [0, 1, 0], [0, 0]])


@pytest.mark.parametrize("model,change", [
    ("elastic", {"nu": 0.0}),                                   # 泊松比可以是 0
    ("neo_hooke", {"D1": 0.0}),                                 # D1 是 0 就是不可压缩
    ("mooney_rivlin", {"D1": 0.0, "C10": 0.0, "C01": 0.1}),     # C10、C01 有一个是 0 也行，加起来为正就行
    ("density", {"bins": 1}),
])
def test_values_right_at_the_edge_that_are_allowed(model, change):
    assert m.check_material(dict(samples()[model], **change)) == []


@pytest.mark.parametrize("model,change,said", [
    ("mooney_rivlin", {"C10": 0.1, "C01": -0.1}, "加起来为正"),
    ("density", {"bounds": {"min": 5, "max": 5}}, "bounds 要写成"),
    ("field", {"relation": [{"from": 0, "to": 1, "a": 0, "b": 2.0}]}, "a 要是正数"),
    ("field", {"relation": [{"from": 0, "to": 1, "a": 1, "b": "2"}]}, "b 要是一个数"),
    ("field", {"relation": [{"from": -0.1, "to": 1, "a": 1, "b": 2}]}, "不是负的"),
    ("field", {"relation": [{"from": 1, "to": 1, "a": 1, "b": 2}]}, "从小到大"),
])
def test_values_right_at_the_edge_that_are_refused(model, change, said):
    problems = m.check_material(dict(samples()[model], **change))
    assert problems and any(said in text for text in problems), problems
