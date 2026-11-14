"""状态表：每种操作在每种状态下都有明确的答案，逐格试过。fold 重放两遍结果相同。"""
from __future__ import annotations

import copy
from dataclasses import asdict

import pytest

from stemlab.contract import states
from stemlab.contract.states import can, fold, refuse, rerunnable, why_not
from tests.contract import samples as s

SITUATIONS = ("none", "new", "new_frozen", "starting", "running",
              "ended_done", "ended_done_retry", "ended_failed", "ended_stopped", "ended_start_failed")

# 操作 -> 在上面每种情形下能不能做。写死在这里，不从实现里推
T, F = True, False
OPERATION_TABLE = {
    #               none new  frz  stg  run  done retry fail stop sfail
    "create":      (T,   F,   F,   F,   F,   F,   F,    F,   F,   F),
    "fill":        (F,   T,   F,   F,   F,   F,   F,    F,   F,   F),
    "start":       (F,   T,   T,   F,   F,   F,   T,    T,   T,   T),
    "start_ok":    (F,   F,   F,   T,   F,   F,   F,    F,   F,   F),
    "start_error": (F,   F,   F,   T,   F,   F,   F,    F,   F,   F),
    "stop":        (F,   F,   F,   F,   T,   F,   F,    F,   F,   F),
    "finish":      (F,   F,   F,   F,   T,   F,   F,    F,   F,   F),
    "fail":        (F,   F,   F,   F,   T,   F,   F,    F,   F,   F),
    "report":      (F,   F,   F,   T,   T,   F,   F,    F,   F,   F),
    "poll":        (F,   F,   F,   F,   T,   F,   F,    F,   F,   F),
    "clone":       (F,   T,   T,   T,   T,   T,   T,    T,   T,   T),
    "note":        (F,   T,   T,   T,   T,   T,   T,    T,   T,   T),
    "tag":         (F,   T,   T,   T,   T,   T,   T,    T,   T,   T),
}

EXPECTED_STATE = {
    "none": "none", "new": "new", "new_frozen": "new", "starting": "starting", "starting_erred": "starting",
    "running": "running", "running_stop_called": "running", "ended_done": "ended", "ended_done_retry": "ended",
    "ended_done_unclear": "ended", "ended_failed": "ended", "ended_stopped": "ended", "ended_start_failed": "ended",
}


def status_of(situation: str):
    return fold(s.HISTORIES[situation])


def test_the_table_covers_every_operation():
    assert set(OPERATION_TABLE) == set(states.OPERATIONS)


@pytest.mark.parametrize("situation", list(s.HISTORIES))
def test_fold_reaches_the_expected_state(situation):
    assert status_of(situation).state == EXPECTED_STATE[situation]


@pytest.mark.parametrize("op", list(OPERATION_TABLE))
@pytest.mark.parametrize("column", range(len(SITUATIONS)))
def test_every_operation_in_every_state(op, column):
    situation = SITUATIONS[column]
    status = status_of(situation)
    allowed = can(op, status, actions=("check", "start", "poll", "stop"))
    assert allowed is OPERATION_TABLE[op][column], f"{op} 在 {situation}：{why_not(op, status, ('stop',))}"
    assert (why_not(op, status, actions=("check", "start", "poll", "stop")) is None) is allowed


@pytest.mark.parametrize("situation", SITUATIONS)
def test_stop_needs_the_type_to_have_written_stop(situation):
    assert not can("stop", status_of(situation), actions=("check", "start", "poll"))


def test_unknown_operation_is_an_error():
    with pytest.raises(ValueError):
        can("pause", status_of("running"))


# ---- 条目层：每种写法在每种情形下能不能记 ----

WRITES = {
    "created": s.created(), "filled": s.filled(), "frozen": s.frozen(), "round_opened": s.round_opened(),
    "called:start:ok": s.called(), "called:start:error": s.called(ok=False),
    "round_closed:start_failed": s.round_closed(result="start_failed"),
    "called:stop:ok": s.called(action="stop"), "round_closed:stopped": s.round_closed(result="stopped"),
    "round_closed:done": s.round_closed(), "round_closed:failed": s.round_closed(result="failed"),
    "task": s.task(), "output": s.output(), "problem": s.problem(), "provenance": s.provenance(),
    "noted": s.noted(), "tagged": s.tagged(),
}
REFUSE_SITUATIONS = ("none", "new", "new_frozen", "starting", "starting_erred",
                     "running", "running_stop_called", "ended_done")
WRITE_TABLE = {
    #                             none new  frz  stg  erred run  stopc done
    "created":                   (T,   F,   F,   F,   F,    F,   F,    F),
    "filled":                    (F,   T,   F,   F,   F,    F,   F,    F),
    "frozen":                    (F,   T,   F,   F,   F,    F,   F,    F),
    "round_opened":              (F,   F,   T,   F,   F,    F,   F,    F),
    "called:start:ok":           (F,   F,   F,   T,   F,    F,   F,    F),
    "called:start:error":        (F,   F,   F,   T,   F,    F,   F,    F),
    "round_closed:start_failed": (F,   F,   F,   F,   T,    F,   F,    F),
    "called:stop:ok":            (F,   F,   F,   F,   F,    T,   T,    F),
    "round_closed:stopped":      (F,   F,   F,   F,   F,    F,   T,    F),
    "round_closed:done":         (F,   F,   F,   F,   F,    T,   T,    F),
    "round_closed:failed":       (F,   F,   F,   F,   F,    T,   T,    F),
    "task":                      (F,   F,   F,   T,   T,    T,   T,    F),
    "output":                    (F,   F,   F,   T,   T,    T,   T,    F),
    "problem":                   (F,   F,   F,   T,   T,    T,   T,    F),
    "provenance":                (F,   F,   F,   T,   T,    T,   T,    F),
    "noted":                     (F,   T,   T,   T,   T,    T,   T,    T),
    "tagged":                    (F,   T,   T,   T,   T,    T,   T,    T),
}


def test_the_write_table_covers_every_rule():
    assert set(WRITE_TABLE) == {rule.write for rule in states.TABLE}
    assert {name: states.variant(body) for name, body in WRITES.items()} == {name: name for name in WRITES}


@pytest.mark.parametrize("write", list(WRITE_TABLE))
@pytest.mark.parametrize("column", range(len(REFUSE_SITUATIONS)))
def test_every_write_in_every_state(write, column):
    situation = REFUSE_SITUATIONS[column]
    reason = refuse(status_of(situation), WRITES[write])
    assert (reason is None) is WRITE_TABLE[write][column], f"{write} 在 {situation}：{reason}"


@pytest.mark.parametrize("situation", list(s.HISTORIES))
def test_what_is_not_in_the_table_is_refused(situation):
    status = status_of(situation)
    assert refuse(status, s.called(action="stop", ok=False)) is not None      # 没停成不记 called
    assert refuse(status, s.entry("paused", round=1)) is not None
    assert refuse(status, s.round_closed(result="paused")) is not None


def test_every_history_is_itself_legal():
    """样本里的每一串记录，按顺序一条一条记，每一条都是当时能记的。"""
    for name, history in s.HISTORIES.items():
        for index, body in enumerate(history):
            assert refuse(fold(history[:index]), body) is None, f"{name} 的第 {index + 1} 条"


# ---- 条目层的条件 ----

def test_wrong_round_number_is_refused():
    assert "轮号" in refuse(status_of("running"), s.task(number=2))
    assert "轮号" in refuse(status_of("new_frozen"), s.round_opened(number=2))


def test_fill_rules():
    new = status_of("new")
    assert "没有" in refuse(new, s.filled(name="nothing"))
    assert "只收一份" in refuse(new, s.filled(items=("R0001", "R0002")))
    assert refuse(new, s.filled(name="extra", items=("R0001", "R0002"))) is None
    assert "存定" in refuse(status_of("new_frozen"), s.filled())


def test_freeze_must_cover_the_inputs_table():
    body = s.frozen()
    del body["inputs"]["extra"]
    assert "对不上" in refuse(status_of("new"), body)


def test_freeze_must_be_what_is_filled_right_now():
    """核对输入和存定之间，输入又被填过：存定的就不是现在填的，记不上。"""
    refilled = fold([s.created(), s.filled(items=("R0001",)), s.filled(items=("R0002",))])
    assert "和现在填的不一样" in refuse(refilled, s.frozen())
    cleared = fold([s.created(), s.filled(), s.filled(items=())])
    assert "和现在填的不一样" in refuse(cleared, s.frozen())
    more = fold([s.created(), s.filled(), s.filled(name="extra", items=("R0005",))])
    assert "extra" in refuse(more, s.frozen()), "可选的输入后来填了，存定时没带上，也不行"
    assert refuse(fold([s.created(), s.filled(items=("R0002",)), s.filled()]), s.frozen()) is None


def test_recorded_code_follows_the_changes_noted_in_the_round():
    from stemlab.contract.states import recorded_code

    opened = fold(s.HISTORIES["running"])
    assert recorded_code(opened.rounds[-1]) == s.PROVENANCE["plugin_hash"]
    change = dict(s.provenance(), source="code", info={"plugin_hash": s.H2, "commit": "abc", "plugin_dirty": True})
    later = dict(change, info=dict(change["info"], plugin_hash="3" * 64))
    assert recorded_code(fold(s.HISTORIES["running"] + [s.provenance(), change]).rounds[-1]) == s.H2
    assert recorded_code(fold(s.HISTORIES["running"] + [change, later]).rounds[-1]) == "3" * 64


def test_task_outcome_must_be_declared_and_match_the_state():
    running = status_of("running")
    assert refuse(running, s.task(state="done", outcome="finished")) is None
    assert refuse(running, s.task(state="done", outcome="misfit")) is None
    assert refuse(running, s.task(state="failed", outcome="env")) is None
    assert "结局表里没有" in refuse(running, s.task(state="done", outcome="nothing"))
    assert "任务状态应该是" in refuse(running, s.task(state="failed", outcome="finished"))
    assert "任务状态应该是" in refuse(running, s.task(state="done", outcome="diverged"))


def test_output_must_be_declared_and_only_once_per_round():
    running = status_of("running")
    assert "产物表里没有" in refuse(running, s.output(name="nothing"))
    assert "已经交过" in refuse(fold(s.HISTORIES["running"] + [s.output()]), s.output())


def test_restart_needs_something_to_do():
    done = status_of("ended_done")
    assert "已经做完" in refuse(done, s.round_opened(number=2))
    assert refuse(done, s.round_opened(number=2, rerun=["p1"])) is None
    assert refuse(status_of("ended_failed"), s.round_opened(number=2)) is None
    assert "还没存定" in refuse(status_of("new"), s.round_opened())


# ---- 重排 ----

def test_rerunnable_follows_the_outcome_categories():
    history = s.HISTORIES["running"] + [
        s.task(name="ok", state="done", outcome="finished"),
        s.task(name="conclusion", state="done", outcome="misfit"),
        s.task(name="retry", state="failed", outcome="env"),
        s.task(name="unclear", state="failed", outcome="diverged"),
        s.task(name="queued", state="queued"),
        s.task(name="running", state="running"),
        s.task(name="stopped", state="stopped"),
        s.round_closed(),
    ]
    status = fold(history)
    assert rerunnable(status, s.OUTCOMES) == ["retry", "queued", "running", "stopped"]
    assert rerunnable(status, s.OUTCOMES, named=("unclear",)) == ["retry", "unclear", "queued", "running", "stopped"]
    assert "ok" not in rerunnable(status, s.OUTCOMES, named=("ok", "conclusion"))


def test_start_after_done_depends_on_what_can_be_rerun():
    assert not can("start", status_of("ended_done"))
    assert can("start", status_of("ended_done_retry"))
    unclear = status_of("ended_done_unclear")
    assert not can("start", unclear)
    assert can("start", unclear, named=("p1",))


# ---- fold ----

@pytest.mark.parametrize("situation", list(s.HISTORIES))
def test_fold_twice_gives_the_same_result(situation):
    history = s.HISTORIES[situation]
    before = copy.deepcopy(history)
    assert asdict(fold(history)) == asdict(fold(history))
    assert history == before, "fold 不该改动条目"


def test_fold_collects_what_view_needs():
    history = s.HISTORIES["running"] + [
        s.task(state="running", stage="solving"), s.output(), s.problem(), s.provenance(),
        s.task(state="done", outcome="finished"), s.noted(), s.tagged(), s.round_closed(),
    ]
    status = fold(history)
    assert status.type == "demo.echo" and status.note == "示范" and status.tags == ["示范", "重要"]
    assert status.filled == {"setting": ["R0001"]} and status.frozen["setting"][0]["id"] == "R0001"
    assert status.register_head == {"seq": 1, "this": s.H1}
    only = status.rounds[0]
    assert (only.number, only.result, only.closed) == (1, "done", s.T0)
    assert only.outputs == {"report": {"item": "R0002", "hash": s.H2}}
    assert [p["error"] for p in only.problems] == ["ValueError: 坏了"]
    assert only.extra[0]["info"] == {"solver": "demo 1.0"}
    assert only.calls == [{"action": "start", "ok": True, "error": None, "time": s.T0}]
    assert status.tasks["p1"].state == "done" and status.tasks["p1"].outcome == "finished"
    assert status.notes == [{"text": "一条备注", "time": s.T0}]
    assert status.count == len(history)


def test_filling_twice_keeps_the_later_one_and_empty_clears():
    status = fold([s.created(), s.filled(items=("R0001",)), s.filled(items=("R0007",))])
    assert status.filled == {"setting": ["R0007"]}
    assert fold([s.created(), s.filled(), s.filled(items=())]).filled == {}


def test_tags_are_added_once_and_removed():
    history = [s.created(tags=["a", "b"]), s.entry("tagged", add=["b", "c"], remove=["a"]),
               s.entry("tagged", add=[], remove=["nothing"])]
    assert fold(history).tags == ["b", "c"]
    assert fold(history + [s.entry("tagged", add=["a"], remove=["b", "c"])]).tags == ["a"]


def test_tasks_keep_the_latest_across_rounds():
    history = s.HISTORIES["ended_done_retry"] + [
        s.round_opened(number=2, rerun=["p1"]), s.called(number=2), s.task(number=2, state="done", outcome="finished"),
    ]
    status = fold(history)
    assert status.tasks["p1"].round == 2 and status.tasks["p1"].state == "done"
    assert status.rounds[0].tasks["p1"].state == "failed", "旧轮的记录不动"
    assert status.rounds[1].rerun == ["p1"]


def test_repeated_problem_is_counted_on_the_first_one():
    history = s.HISTORIES["running"] + [s.problem(), s.problem(count=3)]
    assert fold(history).rounds[0].problems == [
        {"error": "ValueError: 坏了", "task": None, "raw": None, "count": 3, "time": s.T0}]


def test_fold_refuses_a_record_outside_the_table():
    with pytest.raises(ValueError):
        fold([s.created(), s.entry("paused")])
    with pytest.raises(ValueError):
        fold([s.created(), s.task()])
