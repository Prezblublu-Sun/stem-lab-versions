"""实验记录：实验的现状只由记录重放得出，没有第二份状态。"""
from __future__ import annotations

import shutil

import pytest

from stemlab.contract import Refused, chain, layout, versions
from stemlab.contract.entries import check_entry
from stemlab.experiments import lock, log, reader, view
from tests import helpers
from tests.contract import samples as s
from tests.contract.test_states import REFUSE_SITUATIONS, WRITE_TABLE, WRITES

TABLES = {"inputs": s.INPUTS, "outputs": s.OUTPUTS, "outcomes": s.OUTCOMES}


def new_experiment(**more) -> str:
    return log.create("demo.echo", TABLES, note="示范", tags=["示范"], **more)


def reach(situation: str) -> str:
    """新建一个实验，照样本一条一条记到这个情形。"""
    experiment = new_experiment()
    for body in s.HISTORIES[situation][1:]:
        log.append(experiment, body)
    return experiment


def record_bytes(experiment: str) -> bytes:
    return layout.record_file(experiment).read_bytes()


# ---- 新建和发号 ----

def test_create_issues_a_number_and_writes_the_first_entry(data):
    first, second = new_experiment(), new_experiment(clone_of="E0001")
    assert (first, second) == ("E0001", "E0002") and reader.all_ids() == ["E0001", "E0002"]
    entries = reader.read(first)
    assert len(entries) == 1 and check_entry(entries[0]) == []
    assert entries[0]["entry"] == "created" and entries[0]["type"] == "demo.echo" and entries[0]["inputs"] == s.INPUTS
    assert (entries[0]["seq"], entries[0]["prev"]) == (1, "0" * 64)
    assert reader.read(second)[0]["clone_of"] == "E0001"
    assert reader.head(first) == chain.Head(1, entries[0]["this"])
    assert reader.verify(first) == [] and reader.verify_issued() == []
    assert (data / "experiments" / "E0001" / "record.jsonl").is_file()


def test_numbers_are_never_reused_even_if_the_folder_is_deleted(data):
    new_experiment(), new_experiment()
    shutil.rmtree(layout.experiment_dir("E0002"))
    assert new_experiment() == "E0003"
    assert reader.all_ids() == ["E0001", "E0002", "E0003"]
    with pytest.raises(LookupError):
        view.view("E0002")
    with pytest.raises(LookupError):
        view.view("E0009")


def test_a_bad_first_entry_does_not_use_up_a_number(data):
    with pytest.raises(Refused, match="类型名"):
        log.create("demo", TABLES)
    with pytest.raises(Refused, match="结局"):
        log.create("demo.echo", dict(TABLES, outcomes=[]))
    assert reader.all_ids() == [] and new_experiment() == "E0001"


# ---- 1 状态表逐格：能做的记得上，不能做的记录里不多一条 ----

@pytest.mark.parametrize("write", list(WRITE_TABLE))
@pytest.mark.parametrize("column", [n for n, name in enumerate(REFUSE_SITUATIONS) if name != "none"])
def test_every_write_in_every_state(data, write, column):
    situation = REFUSE_SITUATIONS[column]
    experiment = reach(situation)
    before = record_bytes(experiment)
    if WRITE_TABLE[write][column]:
        entry = log.append(experiment, WRITES[write])
        assert record_bytes(experiment) == before + chain.dumps(entry), "能做的记得上"
        assert reader.read(experiment)[-1] == entry
    else:
        with pytest.raises(Refused):
            log.append(experiment, WRITES[write])
        assert record_bytes(experiment) == before, f"{write} 在 {situation}：不能做的，记录里不多一条"
    assert reader.verify(experiment) == []


def test_a_malformed_entry_is_refused_before_the_state_table_is_asked(data):
    experiment = reach("running")
    before = record_bytes(experiment)
    for body in ({"entry": "task", "round": 1, "task": "p1", "state": "done"},          # 缺项
                 dict(s.task(), state="paused"), dict(s.noted(), surprise=1), {"entry": "paused"},
                 dict(s.noted(), seq=5)):                                               # 链填的项不能自己带
        with pytest.raises((Refused, ValueError)):
            log.append(experiment, body)
    assert record_bytes(experiment) == before


def test_time_and_format_are_set_by_the_log_not_by_the_caller(data):
    experiment = new_experiment()
    entry = log.append(experiment, dict(s.noted(), time="1999-01-01T00:00:00.000Z", format=99))
    assert entry["format"] == versions.FORMATS["record"] and entry["time"] > "2026" and chain.is_time(entry["time"])


# ---- 2 同一样输入填两次 ----

def test_filling_twice_keeps_both_in_the_record_and_the_later_one_wins(data):
    experiment = new_experiment()
    log.append(experiment, s.filled(items=("R0007",)))
    log.append(experiment, s.filled(items=("R0001",)))
    assert view.view(experiment).filled == {"setting": ["R0001"]}, "现状以后一次为准"
    assert [e["items"] for e in reader.read(experiment) if e["entry"] == "filled"] == [["R0007"], ["R0001"]], "两次都留在记录里"
    log.append(experiment, s.frozen())
    with pytest.raises(Refused, match="存定"):
        log.append(experiment, s.filled(items=("R0008",)))
    assert view.view(experiment).filled == {"setting": ["R0001"]}


def test_what_is_frozen_must_be_what_is_filled(data):
    experiment = new_experiment()
    log.append(experiment, s.filled(items=("R0007",)))
    before = record_bytes(experiment)
    with pytest.raises(Refused, match="和现在填的不一样"):
        log.append(experiment, s.frozen())              # 样本里存定的是 R0001，现在填的是 R0007
    assert record_bytes(experiment) == before


# ---- 3 把插件拔掉：required 照样答得出 ----

def test_required_is_answered_from_the_record_alone(data, monkeypatch):
    monkeypatch.setenv("STEMLAB_PLUGINS", "no.such.package")       # 这一块根本不碰插件
    experiment = new_experiment()
    assert view.required(experiment) == ["setting"], "可选的 extra 不算缺"
    log.append(experiment, s.filled())
    assert view.required(experiment) == []
    log.append(experiment, s.filled(items=()))
    assert view.required(experiment) == ["setting"], "清掉之后又缺了"


# ---- 4 再启动：旧轮的条目一条不动，新条目都带新的轮号 ----

def test_a_new_round_leaves_the_old_round_untouched(data):
    experiment = reach("ended_done_retry")
    old = record_bytes(experiment)
    for body in (s.round_opened(number=2, rerun=["p1"]), s.called(number=2), s.task(number=2, state="running"),
                 s.output(number=2), s.task(number=2, state="done", outcome="finished"), s.round_closed(number=2)):
        log.append(experiment, body)
    assert record_bytes(experiment).startswith(old), "旧轮的条目一条不动"
    added = reader.read(experiment)[len(s.HISTORIES["ended_done_retry"]):]
    assert [entry["round"] for entry in added] == [2] * 6, "新条目都带新的轮号"
    with pytest.raises(Refused, match="轮号"):
        log.append(reach("running"), s.task(number=2))
    status = view.view(experiment)
    assert [one.number for one in view.rounds(experiment)] == [1, 2]
    assert status.rounds[0].tasks["p1"].state == "failed" and status.rounds[1].tasks["p1"].state == "done"
    assert status.rounds[0].outputs == {} and list(status.rounds[1].outputs) == ["report"]


# ---- 5 四个进程同时追加 ----

def test_four_processes_appending_at_once(data):
    experiment = new_experiment()
    helpers.release([helpers.spawn_worker("append", experiment, f"w{n}", "30") for n in range(4)])
    entries = reader.read(experiment)
    assert len(entries) == 121, "一条不少"
    assert sorted(e["text"] for e in entries[1:]) == sorted(f"w{w} {n}" for w in range(4) for n in range(30))
    assert [e["seq"] for e in entries] == list(range(1, 122))
    assert reader.verify(experiment) == [], "都接得上"
    assert len({e["text"].split()[0] for e in entries[1:41]}) > 1, "四个进程确实是交错着写的"
    for worker in range(4):
        own = [int(e["text"].split()[1]) for e in entries[1:] if e["text"].startswith(f"w{worker} ")]
        assert own == list(range(30)), "每个进程自己写的先后没有乱"


def test_four_processes_creating_at_once(data):
    helpers.release([helpers.spawn_worker("create", f"w{n}", "10") for n in range(4)])
    assert reader.all_ids() == [f"E{n:04d}" for n in range(1, 41)], "编号不重复，一个不少"
    assert reader.verify_issued() == []
    notes = [view.view(experiment).note for experiment in reader.all_ids()]
    assert sorted(notes) == sorted(f"w{w} {n}" for w in range(4) for n in range(10)), "每个编号各有各的实验"
    assert len({note.split()[0] for note in notes[:12]}) > 1, "四个进程确实是交错着建的"


# ---- 6 手改或手删一条 ----

def rewrite(experiment: str, change) -> None:
    path = layout.record_file(experiment)
    lines = path.read_bytes().split(b"\n")[:-1]
    path.write_bytes(b"".join(line + b"\n" for line in change(lines)))


@pytest.mark.parametrize("position", [1, 4, 7])
def test_a_hand_edited_entry_is_pointed_out(data, position):
    experiment = reach("ended_done")
    assert len(reader.read(experiment)) == 7
    target = "示范".encode() if position == 1 else b'"round":1'
    replacement = "示犯".encode() if position == 1 else b'"round":7'
    rewrite(experiment, lambda lines: [line.replace(target, replacement) if n == position else line
                                       for n, line in enumerate(lines, start=1)])
    problems = reader.verify(experiment)
    assert len(problems) == 1 and f"第 {position} 条" in problems[0] and "被改过" in problems[0]


@pytest.mark.parametrize("position", [2, 5])
def test_a_hand_deleted_entry_is_pointed_out(data, position):
    experiment = reach("ended_done")
    rewrite(experiment, lambda lines: lines[:position - 1] + lines[position:])
    problems = reader.verify(experiment)
    assert len(problems) == 1 and f"第 {position} 条" in problems[0] and "接不上" in problems[0]


def test_a_well_chained_record_that_breaks_the_state_table_is_pointed_out(data):
    """有人照着链的规矩重算了哈希，但记下了当时不该记的东西。"""
    experiment = new_experiment()
    forged = s.chained([s.created(), s.filled(), s.round_closed()])
    layout.record_file(experiment).write_bytes(b"".join(chain.dumps(entry) for entry in forged))
    problems = reader.verify(experiment)
    assert len(problems) == 1 and "第 3 条" in problems[0] and "当时不该记下" in problems[0]

    malformed = s.chained([s.created(), dict(s.filled(), items=["not-an-id"])])
    layout.record_file(experiment).write_bytes(b"".join(chain.dumps(entry) for entry in malformed))
    assert "第 2 条" in reader.verify(experiment)[0]


# ---- 末尾留着半行；比自己新的格式 ----

def test_a_half_written_tail_is_ignored_then_cut_off(data):
    experiment = reach("running")
    whole = record_bytes(experiment)
    with open(layout.record_file(experiment), "ab") as stream:
        stream.write(b'{"entry":"task","fingerprint":nu')
    assert len(reader.read(experiment)) == len(s.HISTORIES["running"]) and reader.verify(experiment) == []
    assert view.view(experiment).state == "running"
    entry = log.append(experiment, s.noted())
    assert record_bytes(experiment) == whole + chain.dumps(entry)


def test_a_newer_format_is_said_out_loud(data):
    experiment = new_experiment()
    newer = s.chained([dict(s.created(), format=2)])
    layout.record_file(experiment).write_bytes(chain.dumps(newer[0]))
    with pytest.raises(versions.NewerFormat, match="第 2 版"):
        reader.read(experiment)
    with pytest.raises(versions.NewerFormat):
        log.append(experiment, s.noted())


# ---- 现状和摘要 ----

def test_view_and_summary(data):
    experiment = reach("running")
    for body in (s.task(name="a", state="done", outcome="finished"), s.task(name="b", state="failed", outcome="env"),
                 s.task(name="c", state="running", stage="solving"), s.problem(), s.output()):
        log.append(experiment, body)
    status = view.view(experiment)
    assert status.state == "running" and status.type == "demo.echo" and status.tasks["c"].stage == "solving"
    summary = view.summary(experiment)
    assert summary == {
        "id": "E0001", "type": "demo.echo", "state": "running", "label": "运行中", "round": 1, "result": None,
        "tasks": {"done": 1, "failed": 1, "running": 1}, "problems": 1, "outputs": ["report"], "bones": [],
        "created": status.created, "note": "示范", "tags": ["示范"],
    }
    fresh = view.summary(new_experiment())
    assert (fresh["state"], fresh["round"], fresh["result"], fresh["tasks"]) == ("new", 0, None, {})


def test_view_does_not_write_anything(data):
    experiment = reach("ended_done")
    before = helpers.snapshot(data)
    view.view(experiment), view.summary(experiment), view.required(experiment), view.rounds(experiment)
    reader.verify(experiment), reader.all_ids(), reader.head(experiment)
    assert helpers.snapshot(data) == before, "看不往盘上写任何东西，也不存缓存"


# ---- 锁 ----

def test_record_locks_are_per_experiment(data):
    first, second = new_experiment(), new_experiment()
    worker = helpers.spawn_worker("hold", "record", first)
    try:
        assert worker.stdout.readline().strip() == b"held"
        with pytest.raises(Refused, match="拿不到锁"):
            with lock.writing(first, timeout=0.2):
                pass
        log.append(second, s.noted())                   # 别的实验不受影响
        assert len(reader.read(first)) == 1             # 被锁着的实验照样能读
        assert new_experiment() == "E0003"              # 发号是另一把锁
    finally:
        helpers.kill_tree(worker)
    log.append(first, s.noted())                        # 持锁的进程死了，锁自动释放
