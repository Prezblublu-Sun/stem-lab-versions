"""判定的属性测试（修改目标 09）：代理的合格线、FEA 的判据。属性测试是什么，见 tests/properties.py。

随机造真值、预测、判据，看下面几句话是不是总成立：
    结论只有过、不过、不可判三种；不可判一定说出原因
    比不全（缺预测、给了两次、算不了）的那一部分，一律不可判
    一个可比的点都没有的时候，任何一条线都不判“过”
    同样的输入，结论唯一
重建的检查门缺了值算“不过”还是“不可判”还没定（修改目标 09 的“要你定”），这里不测它。
两条 @example 是这里查出来、2026-11-15 修好的两处（数点数的线和判据，在一个可比的点都没有时判过）的反例，留着防它们回来。
"""
from __future__ import annotations

from hypothesis import example, given
from hypothesis import strategies as st

from plugins.fea import judge as fea
from plugins.surrogate import report
from tests import properties  # noqa: F401  载入 Hypothesis 的设置

NUMBERS = st.floats(0.001, 1000.0, allow_nan=False)
# 一个点：真值（可能没有）、给了几次预测（0、1、2）、预测的值
POINTS = st.lists(st.tuples(st.none() | NUMBERS, st.sampled_from((0, 1, 1, 1, 2)), NUMBERS), max_size=8)
LINES = st.fixed_dictionaries({"id": st.just("a1"), "what": st.just("x"), "target": st.just("y"), "on": st.sampled_from(report.ON),
                               "metric": st.sampled_from(report.METRICS), "op": st.sampled_from(list(report.OPS)),
                               "limit": st.floats(-10.0, 10.0, allow_nan=False)})


def surrogate(points, line, scale: str = "linear") -> tuple[dict, dict]:
    """照这些点算误差，再拿这一条线判。返回（误差，判定）。"""
    truth = [{"point": f"{number:064x}", "values": {"y": actual}} for number, (actual, _, _) in enumerate(points)]
    predicted = [{"point": f"{number:064x}", "values": {"y": guess}, "lower": {"y": guess / 2}, "upper": {"y": guess * 2}}
                 for number, (_, times, guess) in enumerate(points) for _ in range(times)]
    found = report.errors(truth, predicted, "y", scale)
    return found, report.judge([line], {part: {"y": found} for part in report.ON})[0]


@given(POINTS, LINES, st.sampled_from(report.SCALES))
def test_a_surrogate_line_says_pass_fail_or_why_it_cannot_judge(points, line, scale):
    found, verdict = surrogate(points, line, scale)
    assert verdict["passed"] in (True, False, None)
    assert verdict["passed"] is not None or verdict["why"], "不可判一定说出原因"
    if report.gaps(found):
        assert verdict["passed"] is None, "比不全的那一部分一律不可判"
    assert surrogate(points, line, scale) == (found, verdict), "同样的输入，结论唯一"


@given(POINTS, LINES)
@example([], {"id": "a1", "what": "x", "target": "y", "on": "holdout", "metric": "n", "op": "<=", "limit": 10.0})   # 修好之前的反例
def test_a_surrogate_line_never_passes_without_a_single_comparable_point(points, line):
    found, verdict = surrogate(points, line)
    if found["n"] == 0:
        assert verdict["passed"] is not True, (found, verdict)


ROWS = st.lists(st.none() | NUMBERS, max_size=8)
CRITERIA = st.fixed_dictionaries({"id": st.just("g1"), "what": st.just("x"), "column": st.just("y"), "stat": st.sampled_from(list(fea.STATS)),
                                  "op": st.sampled_from(list(fea.OPS)), "limit": st.floats(-10.0, 10.0, allow_nan=False)},
                                 optional={"missing": st.sampled_from(fea.MISSING)})


def criterion(values, row, more: int = 0) -> dict:
    """一条判据，判这几个作业算出的数。more 是这批点里另有几个点连数据的行都没有（没算完、出错）。"""
    rows = {f"t{number}": {"values": {"y": value}} for number, value in enumerate(values)}
    return fea.judge({"criteria": [row]}, rows, len(values) + more)[0]


@given(ROWS, CRITERIA, st.integers(0, 3))
def test_a_fea_criterion_says_pass_fail_or_why_it_cannot_judge(values, row, more):
    verdict = criterion(values, row, more)
    assert verdict["passed"] in (True, False, None)
    assert verdict["passed"] is not None or verdict["why"], "不可判一定说出原因"
    if verdict["missing"] and row.get("missing", "na") == "na":
        assert verdict["passed"] is None, "缺了数、又没写只看有数的点，就不可判"
    assert verdict["used"] + verdict["missing"] == len(values) + more
    assert criterion(values, row, more) == verdict, "同样的输入，结论唯一"


@given(ROWS, CRITERIA, st.integers(0, 3))
@example([None, None], {"id": "g1", "what": "x", "column": "y", "stat": "count", "op": "<=", "limit": 10.0, "missing": "skip"}, 0)  # 修好之前的反例
def test_a_fea_criterion_never_passes_without_a_single_number(values, row, more):
    verdict = criterion(values, row, more)
    if not [value for value in values if value is not None]:
        assert verdict["passed"] is not True, verdict
