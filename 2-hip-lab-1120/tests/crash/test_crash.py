"""在启动和发布的每一步之后掐断，再对账：断在哪一步都留下读得懂的记录，都接得上。"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

from stemlab.contract import Refused, layout
from stemlab.desk.core import actions, check, start, watch
from stemlab.experiments import reader, view
from stemlab.hooks import publish
from stemlab.registry import lookup, verify
from stemlab.registry import reader as register_reader
from tests import helpers
from tests.crash.worker import DIED


def crash(what: str, where: str, target) -> None:
    """起一个子进程去做，它走到那一步之后立刻退出。"""
    env = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    done = subprocess.run([sys.executable, "-m", "tests.crash.worker", what, where, str(target)], cwd=helpers.REPO,
                          env=env, capture_output=True, timeout=300)
    assert done.returncode == DIED, f"它该断在 {where}，实际：\n" + (done.stdout + done.stderr).decode("utf-8", "replace")


def kinds_of(made: str) -> list[str]:
    return [entry["entry"] for entry in reader.read(made)]


# ---------------------------------------------------------------- 启动

def test_cut_after_frozen(lab, data):
    made = helpers.experiment(value={"tasks": ["a", "b"]})
    crash("start", "frozen", made)
    status = view.view(made)
    assert kinds_of(made) == ["created", "filled", "frozen"] and status.state == "new" and status.frozen is not None
    assert reader.verify(made) == [] and watch.once() == {}, "还没开轮，值守没什么可收的"
    with pytest.raises(Refused, match="存定"):
        actions.fill(made, "setting", status.filled["setting"])
    assert start.start(made).ok, "再启动一次就接上了"
    assert kinds_of(made).count("frozen") == 1 and view.view(made).rounds[0].number == 1


@pytest.mark.parametrize("where,written", [("round_opened", []), ("plugin_start", ["a", "b"])])
def test_cut_while_starting_is_closed_as_start_failed_by_the_next_pass(lab, data, where, written):
    made = helpers.experiment(value={"tasks": ["a", "b"]})
    crash("start", where, made)
    status = view.view(made)
    assert status.state == "starting" and list(status.tasks) == written and reader.verify(made) == []
    assert status.rounds[0].calls == [], "启动的结果还没记"

    assert watch.once() == {made: "看过了"}
    status = view.view(made)
    assert status.state == "ended" and status.rounds[0].result == "start_failed", "值守下一遍把它收成启动失败"
    assert "进程不在了" in status.rounds[0].reason and status.rounds[0].calls[0]["ok"] is False
    assert kinds_of(made)[-2:] == ["called", "round_closed"] and reader.verify(made) == [], "记录读得懂"
    assert watch.once() == {} and check.verify_all() == []

    assert start.start(made).ok and start.poll(made).ok
    status = view.view(made)
    assert status.rounds[1].rerun == written, "上一轮排了队没跑的，这一轮重排"
    assert status.rounds[1].result == "done" and {task.state for task in status.tasks.values()} == {"done"}


def test_cut_inside_the_plugin_start(lab, data):
    made = helpers.experiment(value={"tasks": ["a", "b"], "start": "exit"})
    env = dict(os.environ, PYTHONUTF8="1")
    code = "import sys; from stemlab.desk.core import start; start.start(sys.argv[1])"
    done = subprocess.run([sys.executable, "-c", code, made], cwd=helpers.REPO, env=env, capture_output=True, timeout=300)
    assert done.returncode == 3, "插件在启动里让进程退出了"
    assert view.view(made).state == "starting" and list(view.view(made).tasks) == ["a", "b"]
    assert watch.once() == {made: "看过了"} and view.view(made).rounds[0].result == "start_failed"
    assert reader.verify(made) == []


def test_cut_between_recording_the_start_error_and_closing_the_round(lab, data):
    made = helpers.experiment(value={"start": "raise"})
    crash("start", "called", made)
    status = view.view(made)
    assert status.state == "starting" and status.rounds[0].calls[0]["ok"] is False, "启动出错记下了，轮还没收"
    assert watch.once() == {made: "看过了"}
    status = view.view(made)
    assert status.rounds[0].result == "start_failed" and len(status.rounds[0].calls) == 1, "只补上收尾，不重复记启动的结果"
    assert status.rounds[0].reason == "启动到一半，做启动的进程不在了" and reader.verify(made) == []


def test_cut_after_called_just_carries_on(lab, data):
    made = helpers.experiment(value={"tasks": ["a", "b"]})
    crash("start", "called", made)
    assert view.view(made).state == "running" and kinds_of(made)[-1] == "called"
    assert watch.once() == {made: "看过了"}
    assert view.view(made).rounds[0].result == "done" and reader.verify(made) == []


def test_a_half_started_experiment_is_left_alone_while_its_starter_is_alive(lab, data):
    """启动中，但做启动的进程还拿着 busy：值守跳过它，不把它收成启动失败。"""
    made = helpers.experiment()
    crash("start", "round_opened", made)
    holder = helpers.spawn_worker("hold", "busy", made)
    try:
        assert holder.stdout.readline().strip() == b"held"
        assert watch.once()[made].startswith("跳过") and view.view(made).state == "starting"
    finally:
        helpers.kill_tree(holder)
    assert watch.once() == {made: "看过了"} and view.view(made).rounds[0].result == "start_failed"


# ---------------------------------------------------------------- 发布

STEPS = ("moved", "read_only", "registered", "output")


def cut_while_publishing(where: str) -> str:
    made = helpers.experiment(value={"tasks": ["a", "b"]})
    assert start.start(made).ok
    crash("poll", where, made)
    return made


def assert_nothing_is_half_done(made: str) -> None:
    """没有登记了一半的产物：登记里有的，记录里也有，内容也对得上。"""
    status = view.view(made)
    registered = lookup.by_origin(made, 1)
    assert len(registered) == 1, "登记了一次，不多不少"
    assert status.rounds[0].outputs == {"report": {"item": registered[0]["id"], "hash": registered[0]["hash"]}}
    assert verify.verify_item(registered[0]["id"]) == registered[0]["hash"]
    folder = lookup.content(registered[0]["id"])
    assert not os.access(folder / "summary.json", os.W_OK), "是只读的"
    assert sorted(p.name for p in layout.outputs_dir(made, 1).iterdir()) == ["report"]
    assert reader.verify(made) == [] and check.verify_all(contents=True) == []


@pytest.mark.parametrize("where", STEPS)
def test_what_a_cut_leaves_behind(lab, data, where):
    made = cut_while_publishing(where)
    status = view.view(made)
    target = layout.output_dir(made, 1, "report")
    assert status.state == "running" and reader.verify(made) == [] and register_reader.items()
    assert (target / "summary.json").exists() and not (layout.work_dir(made) / "report-r1").exists(), "文件已经移过去了"
    assert len(lookup.by_origin(made, 1)) == (1 if where in ("registered", "output") else 0)
    assert list(status.rounds[0].outputs) == (["report"] if where == "output" else [])
    assert os.access(target / "summary.json", os.W_OK) is (where == "moved")


@pytest.mark.parametrize("where", STEPS)
def test_reconcile_finishes_the_job_and_twice_is_the_same_as_once(lab, data, where):
    made = cut_while_publishing(where)
    done = publish.reconcile(made)
    assert done == ([] if where == "output" else ["report"])
    assert_nothing_is_half_done(made)
    once = helpers.snapshot(data)
    assert publish.reconcile(made) == [] and check.reconcile_all() == []
    assert helpers.snapshot(data) == once, "对账做两遍和做一遍结果相同"

    assert start.poll(made).ok, "插件把同一样产物又交了一次：内容一样，不算问题"
    status = view.view(made)
    assert status.rounds[0].result == "done" and status.rounds[0].problems == []
    assert_nothing_is_half_done(made)


@pytest.mark.parametrize("where", STEPS)
def test_the_next_pass_of_the_watch_picks_it_up_on_its_own(lab, data, where):
    made = cut_while_publishing(where)
    assert watch.once() == {made: "看过了"}
    status = view.view(made)
    assert status.state == "ended" and status.rounds[0].result == "done" and status.rounds[0].problems == []
    assert_nothing_is_half_done(made)
    assert watch.once() == {}


@pytest.mark.parametrize("where", STEPS[:3])
def test_a_pass_reconciles_even_if_the_plugin_does_not_resubmit(lab, data, where, monkeypatch):
    """轮询之后对一次账：插件这一遍什么都没交，断在半路的产物也接着做完了。"""
    from stemlab.hooks import call

    made = cut_while_publishing(where)
    monkeypatch.setattr(call, "call", lambda type_name, action, experiment: call.Result(True))
    assert start.poll(made).ok
    assert_nothing_is_half_done(made)
    assert view.view(made).state == "running"


@pytest.mark.parametrize("where", STEPS[:3])
def test_check_picks_it_up_too(lab, data, where):
    made = cut_while_publishing(where)
    assert check.reconcile_all() == [f"{made} 的 report"]
    assert_nothing_is_half_done(made)


def test_a_resubmitted_output_with_different_content_is_a_problem(lab, data):
    made = helpers.experiment(value={"poll": "never"})
    start.start(made)
    first = helpers.make_folder(layout.work_dir(made) / "first", files={"a.txt": b"1"})
    item = publish.publish(made, 1, "report", first)
    same = helpers.make_folder(layout.work_dir(made) / "same", files={"a.txt": b"1"})
    assert publish.publish(made, 1, "report", same) == item and view.view(made).rounds[0].problems == []
    different = helpers.make_folder(layout.work_dir(made) / "different", files={"a.txt": b"2"})
    assert publish.publish(made, 1, "report", different) is None
    assert "内容不一样" in view.view(made).rounds[0].problems[0]["error"]
    assert len(lookup.by_origin(made, 1)) == 1 and different.exists()


# ---------------------------------------------------------------- 登记

def test_cut_while_registering_a_copy(data, tmp_path):
    helpers.setting("before")
    source = helpers.make_folder(tmp_path / "rep")
    crash("register", "placed", source)
    assert [item["name"] for item in register_reader.items()] == ["before"], "链上没有登记了一半的东西"
    assert verify.verify_register() == [] and check.verify_chains() == []
    assert sorted(p.name for p in layout.store_root().iterdir()) == ["R0002"], "内容放到位了，但没上链"
    found = check.verify_all()
    assert len(found) == 1 and "registry/store/R0002 不在登记里" in found[0], "检查把留下的半截报出来"

    item = actions.register("report", "again", source=source, note="重新登记")
    assert item["id"] == "R0002" and verify.verify_item("R0002") == item["hash"], "这个编号照常发出去"
    names = sorted(p.name for p in layout.store_root().iterdir())
    assert len(names) == 2 and names[0].startswith(".orphan-R0002-") and names[1] == "R0002", "留下的半截挪到了一边，没有删"
    assert len(check.verify_all()) == 1 and ".orphan-R0002-" in check.verify_all()[0], "由人确认之后再删"
    import shutil
    shutil.rmtree(layout.store_root() / names[0])
    assert check.verify_all(contents=True) == []


# ---------------------------------------------------------------- 审查之后补的几处断点

def test_a_publish_cut_inside_the_plugin_start_is_finished_before_the_round_is_closed(lab, data):
    """插件在启动里交产物，交到一半进程没了：值守把这一轮收成启动失败之前，先把那样产物接着做完。"""
    for where, registered_before in (("moved", 0), ("registered", 1)):
        made = helpers.experiment(value={"start_output": True})
        crash("start", where, made)
        assert view.view(made).state == "starting" and len(lookup.by_origin(made, 1)) == registered_before
        assert watch.once() == {made: "看过了"}
        status = view.view(made)
        assert status.rounds[0].result == "start_failed"
        item = lookup.by_origin(made, 1)
        assert len(item) == 1 and status.rounds[0].outputs == {"report": {"item": item[0]["id"], "hash": item[0]["hash"]}}, \
            "登记里有的，记录里也有"
        assert reader.verify(made) == [] and check.verify_all(contents=True) == []


def test_cut_between_recording_the_stop_and_closing_the_round(lab, data):
    """插件已经停成了、called 也记了，收尾之前进程没了：下一遍只补上收尾，不再去叫插件。"""
    made = helpers.experiment("demo.sleep", value={"seconds": 60})
    assert start.start(made).ok
    crash("stop", "called", made)
    status = view.view(made)
    assert status.rounds[0].result is None and status.rounds[0].calls[-1] == dict(status.rounds[0].calls[-1], action="stop", ok=True)
    assert status.tasks["job"].state == "stopped"
    assert watch.once() == {made: "看过了"}
    status = view.view(made)
    assert status.rounds[0].result == "stopped" and status.tasks["job"].state == "stopped", "没有再叫插件，任务没被改成失败"
    assert kinds_of(made)[-2:] == ["called", "round_closed"] and reader.verify(made) == []


def test_a_resubmission_with_different_content_after_a_cut_is_a_problem(lab, data):
    made = cut_while_publishing("moved")
    different = helpers.make_folder(layout.work_dir(made) / "different", files={"a.txt": b"not what was handed in before"})
    assert publish.publish(made, 1, "report", different) is None, "这次交的没有收"
    status = view.view(made)
    assert "内容不一样" in status.rounds[0].problems[0]["error"] and different.exists()
    assert_nothing_is_half_done(made)                   # 上次交到一半的那一份接着发布了
