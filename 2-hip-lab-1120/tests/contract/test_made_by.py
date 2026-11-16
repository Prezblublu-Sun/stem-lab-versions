"""算出来的东西记着是怎么算出来的（清单里的 made_by，第 2 版）；不同的算法、设定、骨模型的版本算出来的数不放在一起用。
第 1 版的 made_by（只有内核和推导量定义）照样认，缺的几样当成不知道。"""
from __future__ import annotations

import pytest

from stemlab.contract.formats.manifest import (as_v2, check_format, common_maker, made_by, made_by_split, maker_clash,
                                               mixed_makers)
from stemlab.contract.formats.points import write_points
from stemlab.contract.hashing import hash_json
from tests.contract.test_data import make

MODEL = {"name": "M1-3406-v1", "code_hash": "6d7af243d0", "solver": "Abaqus/Standard 2025"}
K, D = "a" * 64, "b" * 64
GOOD = {"kernel": MODEL, "derive": {"package": D}}                      # 第 1 版
BONE = {"femur042": {"id": "C0001", "hash": "1" * 64}}
FEM = {"mu": 0.3, "element": "C3D10"}
NEW = made_by({"model": MODEL}, K, {"columns": []}, D, bones=BONE, settings={"fem": FEM})     # 第 2 版


def test_which_kernel_is_written_down():
    assert made_by({"model": MODEL, "modes": ["build"]}, K) == {
        "kernel": MODEL, "stem": None, "fem": None, "derive": None, "settings": None, "bones": None, "predictions": []}, \
        "内核的清单里写了 model，就记 model；没给骨模型和设定就是不知道"
    assert made_by({"modes": ["build"]}, K, {"columns": []}, D)["kernel"] == {"package": K}, "没写 model 就记包的哈希"
    assert made_by({"modes": ["build"]}, K, {"columns": []}, D)["derive"] == {"package": D}, "推导量定义记它的包的哈希"
    assert made_by({"model": {"code_hash": "x"}}, K)["kernel"] == {"package": K}, "model 里没有名字的不算"
    assert NEW["settings"] == {"placement": None, "fem": hash_json(FEM), "derive": None}, "设定记的是哈希，由契约来算"
    assert NEW["bones"] == BONE and NEW["predictions"] == []
    assert made_by({"model": MODEL}, K, settings={})["settings"] == {"placement": None, "fem": None, "derive": None}, \
        "给 {} 是知道：没用到设定"
    assert made_by({"model": MODEL}, K, predictions=["R0009", "R0003"])["predictions"] == ["R0003", "R0009"]


def test_after_the_kernel_is_split_the_two_packages_are_written_down(tmp_path):
    """拆内核以后（fea.run）：kernel 是 null，stem、fem 记柄空间包、有限元包的哈希；无植入物 stem 写 "none"。"""
    S, F = "c" * 64, "d" * 64
    split = made_by_split(S, F, D, bones=BONE, settings={"placement": {"entry": "rule"}, "fem": FEM})
    assert split == {"kernel": None, "stem": {"package": S}, "fem": {"package": F}, "derive": {"package": D},
                     "settings": {"placement": hash_json({"entry": "rule"}), "fem": hash_json(FEM), "derive": None},
                     "bones": BONE, "predictions": []}
    bare = made_by_split(None, F)
    assert (bare["stem"], bare["derive"], bare["settings"], bare["bones"]) == ("none", None, None, None), "无植入物写明“无”"
    for number, value in enumerate((split, bare)):
        assert check_format("data", make(tmp_path / f"d{number}", made_by=value)) == []
    assert any("不同内核" in text for text in mixed_makers([("参照包算的", NEW), ("拆开的两包算的", split)])), \
        "参照包和拆开的两个包算的数不放在一起"
    assert any("不同内核" in text for text in mixed_makers([("有植入物", split), ("无植入物", dict(split, stem="none"))]))
    assert any("placement设定不一样" in text for text in mixed_makers([("甲", split), ("乙", made_by_split(
        S, F, D, bones=BONE, settings={"placement": {"entry": "fixed"}, "fem": FEM}))])), "放置设定换了，不放在一起"


def test_the_first_version_is_read_as_the_second_with_what_it_lacks_unknown():
    assert as_v2(GOOD) == {"kernel": MODEL, "stem": None, "fem": None, "derive": {"package": D}, "settings": None,
                           "bones": None, "predictions": []}
    assert as_v2(NEW) is NEW and as_v2(None) is None


@pytest.mark.parametrize("kind", ["data", "prediction"])
def test_data_and_predictions_may_say_who_made_them(tmp_path, kind):
    assert check_format(kind, make(tmp_path / "x", kind=kind, made_by=GOOD)) == [], "第 1 版照样认"
    assert check_format(kind, make(tmp_path / "w", kind=kind, made_by=NEW)) == []
    assert check_format(kind, make(tmp_path / "y", kind=kind, made_by=dict(GOOD, derive=None))) == [], "没有推导量定义的写 null"
    assert check_format(kind, make(tmp_path / "z", kind=kind)) == [], "不写也合格：只是不知道是怎么算的"


BAD = [
    ("不是对象", "M1-3406-v1"),
    ("少了 derive", {"kernel": MODEL}),
    ("多了一项", dict(GOOD, solver="Abaqus")),
    ("kernel 是空的", dict(GOOD, kernel={})),
    ("kernel 不是对象", dict(GOOD, kernel="M1-3406-v1")),
    ("derive 是空的", dict(GOOD, derive={})),
    ("derive 是字符串", dict(GOOD, derive="bed_f")),
    ("第 2 版少了一样", {k: v for k, v in NEW.items() if k != "bones"}),
    ("内核和有限元包都没有", dict(NEW, kernel=None)),
    ("有限元包是空的", dict(NEW, fem={})),
    ("柄空间写错", dict(NEW, stem="nothing")),
    ("设定少了一份", dict(NEW, settings={"fem": "c" * 64})),
    ("设定不是哈希", dict(NEW, settings={"placement": None, "fem": "mu=0.3", "derive": None})),
    ("骨模型没写哈希", dict(NEW, bones={"femur042": {"id": "C0001"}})),
    ("骨模型的编号不对", dict(NEW, bones={"femur042": {"id": "femur042", "hash": "1" * 64}})),
    ("用到的预测没排序", dict(NEW, predictions=["R0009", "R0003"])),
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
    assert any("没有记" in text for text in mixed_makers([first, ("第 2 份数据", None)])), "不知道是怎么算的，不能和别的放在一起"
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


def bone(bone_id: str, item: str) -> dict:
    return {bone_id: {"id": item, "hash": item[-1] * 64}}


def test_bone_model_versions_are_compared_bone_by_bone():
    """同一根骨的版本一致才放在一起；不同的骨互不冲突（跨骨的代理照样能训练）。每两份都比得到。"""
    on = lambda bones: dict(NEW, bones=bones)  # noqa: E731
    a, b = ("第 1 份数据", on(bone("femur041", "C0001"))), ("第 2 份数据", on(bone("femur042", "C0002")))
    assert mixed_makers([a, b]) == [], "两根不同的骨"
    rebuilt = ("第 3 份数据", on(bone("femur042", "C0003")))
    said = mixed_makers([a, b, rebuilt])
    assert len(said) == 1 and "femur042" in said[0] and "C0002" in said[0] and "C0003" in said[0], \
        "第 3 份和第 1 份不冲突，和第 2 份用的 femur042 不是同一版：也要比出来"
    assert "femur042" in maker_clash(("预测", b[1]), ("数据", rebuilt[1])), "不合并、只是一起用的，同一根骨也得是同一版"


def test_settings_and_what_is_not_known():
    fem = dict(NEW, settings={"placement": None, "fem": "c" * 64, "derive": None})
    assert any("fem设定不一样" in text for text in mixed_makers([("甲", NEW), ("乙", fem)])), "有限元的设定换了，不放在一起"
    assert any("一份记了设定、一份没记" in text for text in mixed_makers([("甲", NEW), ("乙", dict(NEW, settings=None))]))
    assert any("一份记了骨模型的版本、一份没记" in text for text in mixed_makers([("甲", NEW), ("乙", dict(NEW, bones=None))]))
    assert mixed_makers([("甲", GOOD), ("乙", dict(GOOD))]) == [], "两份都是第 1 版，都不知道：照旧能放在一起"
    assert mixed_makers([("新", NEW), ("旧", GOOD)]) != [], "知道的和不知道的不放在一起"
    assert any("用到的预测不一样" in text for text in mixed_makers([("甲", NEW), ("乙", dict(NEW, predictions=["R0007"]))]))
    none = dict(NEW, settings={"placement": None, "fem": None, "derive": None})
    assert any("fem设定不一样" in text for text in mixed_makers([("甲", NEW), ("乙", none)])), \
        "合在一起用：一份用了有限元的设定、一份没用，不放在一起"
    derived = [dict(NEW, settings=dict(NEW["settings"], derive=digit * 64)) for digit in "de"]
    assert any("derive设定不一样" in text for text in mixed_makers([("甲", derived[0]), ("乙", derived[1])])), \
        "推导量的设定两边都记了，得一样"
    assert mixed_makers([("甲", NEW), ("乙", derived[0])]) == [], "推导量的设定只在两边都记了的时候比"
    pool = made_by({"model": MODEL}, K, bones=BONE, settings={})
    assert maker_clash(("数据", NEW), ("候选池", pool)) is None, "候选池不用有限元的设定：只比两边都记了的"
    assert maker_clash(("数据", NEW), ("候选池", as_v2(dict(GOOD, derive=None)))) is None, "有一边不知道，不合并的不拦"


def test_the_common_maker_of_data_put_together():
    one = dict(NEW, derive=None, bones=bone("femur041", "C0001"))
    two = dict(NEW, bones=bone("femur042", "C0002"))
    together = common_maker([one, two])
    assert together["derive"] == NEW["derive"] and together["bones"] == {**one["bones"], **two["bones"]}
    assert together["settings"] == NEW["settings"] and together["kernel"] == MODEL
    assert common_maker([NEW, None]) is None and common_maker([]) is None, "有一份不知道，合起来也不知道"
    assert common_maker([GOOD, dict(GOOD, derive=None)]) == as_v2(GOOD), "第 1 版的合起来是第 2 版的写法"
