"""算出来的东西记着是哪个内核算的（清单里的 made_by）；不同内核算出来的数不放在一起用。"""
from __future__ import annotations

import pytest

from stemlab.contract.formats.manifest import check_format, made_by, maker_clash, mixed_makers
from stemlab.contract.formats.points import write_points
from tests.contract.test_data import make

MODEL = {"name": "M1-3406-v1", "code_hash": "6d7af243d0", "solver": "Abaqus/Standard 2025"}
K, D = "a" * 64, "b" * 64
GOOD = {"kernel": MODEL, "derive": {"package": D}}


def test_which_kernel_is_written_down():
    assert made_by({"model": MODEL, "modes": ["build"]}, K) == {"kernel": MODEL, "derive": None}, "内核的清单里写了 model，就记 model"
    assert made_by({"modes": ["build"]}, K, {"columns": []}, D) == {"kernel": {"package": K}, "derive": {"package": D}}, \
        "没写 model 就记包的哈希；推导量定义记它的包的哈希"
    assert made_by({"model": {"code_hash": "x"}}, K)["kernel"] == {"package": K}, "model 里没有名字的不算"


@pytest.mark.parametrize("kind", ["data", "prediction"])
def test_data_and_predictions_may_say_who_made_them(tmp_path, kind):
    assert check_format(kind, make(tmp_path / "x", kind=kind, made_by=GOOD)) == []
    assert check_format(kind, make(tmp_path / "y", kind=kind, made_by=dict(GOOD, derive=None))) == [], "没有推导量定义的写 null"
    assert check_format(kind, make(tmp_path / "z", kind=kind)) == [], "不写也合格：只是不知道是哪个内核算的"


BAD = [
    ("不是对象", "M1-3406-v1"),
    ("少了 derive", {"kernel": MODEL}),
    ("多了一项", dict(GOOD, solver="Abaqus")),
    ("kernel 是空的", dict(GOOD, kernel={})),
    ("kernel 不是对象", dict(GOOD, kernel="M1-3406-v1")),
    ("derive 是空的", dict(GOOD, derive={})),
    ("derive 是字符串", dict(GOOD, derive="bed_f")),
]


@pytest.mark.parametrize("why,value", BAD, ids=[row[0] for row in BAD])
def test_a_badly_written_maker_is_named(tmp_path, why, value):
    problems = check_format("data", make(tmp_path / "d", made_by=value))
    assert problems and any("made_by" in text for text in problems), f"{why}：{problems}"


def test_a_pool_is_written_with_its_maker(tmp_path):
    rows = [{"name": "c1", "bone_id": "femur042", "design": {"length": 30.0}, "feasible": True, "info": {}}]
    written = write_points(tmp_path / "pool", rows, kind="pool", made_by=dict(GOOD, derive=None))
    assert written["made_by"] == dict(GOOD, derive=None) and check_format("pool", tmp_path / "pool") == []
    with pytest.raises(ValueError, match="count"):
        write_points(tmp_path / "other", rows, kind="pool", count=9)          # 格式自己的项不能被盖掉


def test_what_may_be_used_together():
    first, same = ("第 1 份数据", GOOD), ("第 2 份数据", dict(GOOD))
    other = ("第 3 份数据", dict(GOOD, kernel={"name": "M2-3406-v1"}))
    assert mixed_makers([first]) == [] and mixed_makers([first, same]) == []
    said = mixed_makers([first, same, other])
    assert len(said) == 1 and "第 3 份数据" in said[0] and "M2-3406-v1" in said[0] and "M1-3406-v1" in said[0], "不同内核算的数不放在一起"
    assert any("没有记" in text for text in mixed_makers([first, ("第 2 份数据", None)])), "不知道是哪个内核算的，不能和别的放在一起"
    assert mixed_makers([("第 1 份数据", None)]) == [], "只有一份，不用比"
    older = ("旧库转来的数据", dict(GOOD, derive=None))
    assert mixed_makers([first, older]) == [], "没有推导量的（比如旧库转来的）不比推导量定义"
    redone = ("第 2 份数据", dict(GOOD, derive={"package": "c" * 64}))
    assert any("推导量" in text for text in mixed_makers([first, redone])), "推导量换了定义，也不放在一起"
    by_package = ("第 2 份数据", {"kernel": {"package": K}, "derive": None})
    assert any(K[:12] in text for text in mixed_makers([first, by_package])), "没写 model 的内核，说的是包的哈希"

    assert maker_clash(("预测", GOOD), ("数据", dict(GOOD))) is None
    clash = maker_clash(("预测", GOOD), ("数据", other[1]))
    assert clash and "预测" in clash and "M2-3406-v1" in clash
    assert maker_clash(("预测", None), ("数据", other[1])) is None, "有一边没记，就没法比，不拦"
    assert "推导量" in maker_clash(("预测", GOOD), ("数据", redone[1])), "两边都有推导量，得是同一份推导量定义算的"
    assert maker_clash(("预测器", GOOD), ("候选池", dict(GOOD, derive=None))) is None, "候选池没有推导量，只比内核"
