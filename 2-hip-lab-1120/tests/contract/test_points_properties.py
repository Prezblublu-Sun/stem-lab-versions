"""一批点的属性测试：补条件默认补两次和补一次一样，写了的不被改；点的哈希只由骨标识、设计、写全的条件定，
名字和理由不算，键的先后不算，5 和 5.0 算同一个值。属性测试是什么，见 tests/properties.py。"""
from __future__ import annotations

from hypothesis import assume, given
from hypothesis import strategies as st

from stemlab.contract.formats.points import fill_defaults, point_hash
from stemlab.contract.hashing import canonical
from tests import properties  # noqa: F401  载入 Hypothesis 的设置

NAMES = st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=8)
VALUES = st.one_of(st.integers(-10 ** 6, 10 ** 6), st.floats(-1e6, 1e6, allow_nan=False), st.booleans(), NAMES)
GROUP = st.dictionaries(NAMES, VALUES, max_size=5)
POINTS = st.fixed_dictionaries({"name": NAMES, "bone_id": st.sampled_from(["femur042", "femur043"]), "design": GROUP,
                                "conditions": GROUP, "reason": st.text(max_size=10)})


@given(st.lists(POINTS, max_size=5), GROUP)
def test_filling_defaults_twice_is_filling_once_and_keeps_what_is_written(points, defaults):
    once = fill_defaults(points, defaults)
    assert fill_defaults(once, defaults) == once
    for before, after in zip(points, once, strict=True):
        assert set(after["conditions"]) == set(before["conditions"]) | set(defaults)
        assert all(after["conditions"][key] == value for key, value in before["conditions"].items()), "写了的不改"
        assert after["hash"] == point_hash(after)


@given(POINTS, NAMES, st.text(max_size=10))
def test_name_and_reason_and_key_order_do_not_move_the_hash(point, name, reason):
    shuffled = dict(point, name=name, reason=reason, design=dict(reversed(list(point["design"].items()))),
                    conditions=dict(reversed(list(point["conditions"].items()))))
    assert point_hash(shuffled) == point_hash(point)
    whole = {key: float(value) if isinstance(value, int) and not isinstance(value, bool) else value
             for key, value in point["design"].items()}
    assert point_hash(dict(point, design=whole)) == point_hash(point), "5 和 5.0 是同一个值、同一个哈希"


@given(POINTS, st.sampled_from(["placement", "derive"]), GROUP)
def test_empty_placement_and_derive_leave_the_first_version_hash_and_values_move_it(point, group, values):
    """第 2 版：放置、推导量两组空着，哈希和第 1 版一样（账里已有的点对得上）；有值就是另一个点。"""
    assert point_hash(dict(point, placement={}, derive={})) == point_hash(point)
    if values:
        assert point_hash(dict(point, **{group: values})) != point_hash(point)


@given(POINTS, st.sampled_from(["design", "conditions", "placement", "derive"]), NAMES, VALUES)
def test_changing_the_bone_or_any_item_moves_the_hash(point, group, key, value):
    other = "femur043" if point["bone_id"] == "femur042" else "femur042"
    assert point_hash(dict(point, bone_id=other)) != point_hash(point)
    changed = dict(point, **{group: dict(point.get(group, {}), **{key: value})})       # 第 1 版的点没有放置、推导量两组
    assume(canonical(changed[group]) != canonical(point.get(group, {})))
    assert point_hash(changed) != point_hash(point)
