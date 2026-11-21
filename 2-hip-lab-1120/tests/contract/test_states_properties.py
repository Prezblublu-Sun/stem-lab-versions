"""状态表的属性测试。属性测试是什么，见 tests/properties.py。

随机生成一串“想记的条目”：开轮、启动成了或出错、各个任务报各种状态（结局、机器、输入指纹随便配）、交产物、停止、
收一轮，轮号偶尔写错一轮。照实验记录真的追加那样，一条一条地问 check_entry 和状态表，只留下能记的；
再看下面几句话是不是对每一串都成立。

两条 @example 是这里查出来、2026-11-15 修好的两处的反例（《修改目标》03 和总目标第 2 句），留着防它们回来。
"""
from __future__ import annotations

import copy
from dataclasses import asdict

from hypothesis import example, given
from hypothesis import strategies as st

from stemlab.contract import entries, states
from tests import properties  # noqa: F401  载入 Hypothesis 的设置
from tests.contract import samples as s

TASKS = ("p1", "p2", "p3")
REPORTS = (("queued", None), ("running", None), ("done", "finished"), ("done", "misfit"), ("failed", "env"),
           ("failed", "diverged"), ("stopped", None), ("done", "nothing"), ("failed", "finished"))     # 后两种是记不上的
ENDS = (states.T_DONE, states.T_FAILED, states.T_STOPPED)
FIXED = ("state", "outcome", "fingerprint", "machine")      # 一个任务结束之后，这一轮里就不该再变的几样（修改目标 03）

ACTIONS = st.one_of(
    st.tuples(st.just("task"), st.sampled_from(TASKS), st.sampled_from(REPORTS), st.sampled_from((None, "win", "linux")),
              st.sampled_from((None, s.H1, s.H2)), st.sampled_from((None, "building", "solving"))),
    st.tuples(st.just("open"), st.lists(st.sampled_from(TASKS), unique=True, max_size=3)),
    st.sampled_from([("start_ok",), ("start_error",), ("start_failed",), ("stop",), ("stopped",), ("done",), ("failed",),
                     ("output",), ("problem",), ("note",)]),
)
SLIPS = st.sampled_from((0, 0, 0, 0, 1, -1))         # 轮号大多写对，偶尔写错一轮


def body(action, number: int) -> dict:
    kind = action[0]
    if kind == "task":
        _, name, (state, outcome), machine, fingerprint, stage = action
        return dict(s.task(number=number, name=name, state=state, outcome=outcome, stage=stage), machine=machine, fingerprint=fingerprint)
    if kind == "open":
        return s.round_opened(number=number, rerun=action[1])
    made = {"start_ok": lambda: s.called(number=number), "start_error": lambda: s.called(number=number, ok=False),
            "start_failed": lambda: s.round_closed(number=number, result="start_failed"),
            "stop": lambda: s.called(number=number, action="stop"), "stopped": lambda: s.round_closed(number=number, result="stopped"),
            "done": lambda: s.round_closed(number=number), "failed": lambda: s.round_closed(number=number, result="failed"),
            "output": lambda: s.output(number=number), "problem": lambda: s.problem(number=number), "note": s.noted}
    return made[kind]()


def recorded(tries) -> list[dict]:
    """照实验记录追加的规矩一条一条地试（先 check_entry，再问状态表），只留下能记的。"""
    history = [s.created(), s.filled(), s.frozen()]
    for action, slip in tries:
        status = states.fold(history)
        number = len(status.rounds) + 1 + slip if action[0] == "open" else max(len(status.rounds), 1) + slip
        entry = body(action, number)
        if not entries.check_entry(entry) and states.refuse(status, entry) is None:
            history.append(entry)
    return history


HISTORIES = st.lists(st.tuples(ACTIONS, SLIPS), max_size=40).map(recorded)


def tried(*actions) -> list[dict]:
    """写死的一串（轮号都写对），给下面的 @example 用：已知的反例写在这里，换了 Hypothesis 的版本也照样试到。"""
    return recorded([(action, 0) for action in actions])


DONE_P1 = ("task", "p1", ("done", "finished"), "win", s.H1, None)


def reports_by_task(history) -> dict:
    """同一轮里同一个任务报过的各条，按记录的先后：(轮号, 任务) -> [条目]。"""
    found: dict = {}
    for entry in history:
        if entry["entry"] == "task":
            found.setdefault((entry["round"], entry["task"]), []).append(entry)
    return found


def after_the_end(reports) -> list[dict]:
    """一个任务在这一轮里第一次报结束的那一条，和它之后的各条。没结束过就是空的。"""
    ended = next((index for index, entry in enumerate(reports) if entry["state"] in ENDS), None)
    return [] if ended is None else reports[ended:]


@given(HISTORIES)
def test_replaying_twice_gives_the_same_status_and_leaves_the_entries_alone(history):
    before = copy.deepcopy(history)
    assert asdict(states.fold(history)) == asdict(states.fold(history))
    assert history == before


@given(HISTORIES)
def test_the_state_is_what_the_last_round_says_and_rounds_count_up_from_one(history):
    status = states.fold(history)
    open_round = bool(status.rounds) and status.rounds[-1].result is None
    assert (status.state in (states.STARTING, states.RUNNING)) == open_round
    assert (status.state == states.ENDED) == (bool(status.rounds) and not open_round)
    assert [one.number for one in status.rounds] == list(range(1, len(status.rounds) + 1))


@given(HISTORIES)
def test_every_kept_entry_carries_the_round_it_was_written_in(history):
    current = 0
    for entry in history:
        if entry["entry"] == "round_opened":
            current = entry["round"]
        elif "round" in entry:
            assert entry["round"] == current, entry


@given(HISTORIES)
def test_a_task_that_ended_keeps_its_state_and_outcome_for_the_rest_of_the_round(history):
    for reports in reports_by_task(history).values():
        assert len({(entry["state"], entry["outcome"]) for entry in after_the_end(reports)}) <= 1


@given(HISTORIES)
@example(tried(("open", []), ("start_ok",), DONE_P1, ("task", "p1", ("done", "finished"), "linux", s.H2, None)))   # 修改目标 03 修好之前的反例
def test_a_task_that_ended_keeps_everything_that_identifies_it_for_the_rest_of_the_round(history):
    for reports in reports_by_task(history).values():
        assert len({tuple(entry[key] for key in FIXED) for entry in after_the_end(reports)}) <= 1


@given(HISTORIES)
def test_a_task_from_an_earlier_round_comes_back_only_through_the_rerun_list(history):
    first_round, rerun = {}, {}
    for entry in history:
        if entry["entry"] == "round_opened":
            rerun[entry["round"]] = set(entry["rerun"])
        elif entry["entry"] == "task" and first_round.setdefault(entry["task"], entry["round"]) < entry["round"]:
            assert entry["task"] in rerun[entry["round"]], entry


@given(HISTORIES)
@example(tried(("open", []), ("start_ok",), DONE_P1, ("failed",), ("open", ["p1"])))     # 总目标第 2 句修好之前的反例
def test_a_task_that_is_done_is_never_put_back_into_a_later_round(history):
    latest: dict = {}
    for entry in history:
        if entry["entry"] == "round_opened":
            done = {name for name, last in latest.items() if last["state"] == states.T_DONE}
            assert not set(entry["rerun"]) & done, entry
        elif entry["entry"] == "task":
            latest[entry["task"]] = entry


@given(HISTORIES)
def test_what_can_be_rerun_never_includes_work_that_is_done(history):
    status = states.fold(history)
    for name in states.rerunnable(status, s.OUTCOMES, named=TASKS):
        assert status.tasks[name].state != states.T_DONE


@given(HISTORIES)
def test_an_output_is_handed_in_at_most_once_per_round(history):
    handed = [(entry["round"], entry["output"]) for entry in history if entry["entry"] == "output"]
    assert len(handed) == len(set(handed))
