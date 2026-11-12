"""定时值守和「一个实验一次只让一处动」的测试。用临时文件夹当 home。"""
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from stemlab.console import Desk, main
from stemlab.record import FINISHED, NOT_STARTED, PAUSED, RUNNING, RecordError
from stemlab.watch import Watch

REPO = Path(__file__).resolve().parent.parent

SLOW = '''
import time
from stemlab.plugins import Plugin

class Slow(Plugin):
    name = "slow"
    version = "0"
    category = "慢的"
    settings = []
    def start(self, ctx):
        time.sleep(0.4)
        ctx.private_dir.mkdir(parents=True, exist_ok=True)
        with open(ctx.private_dir / "started.txt", "a") as f:
            f.write("x")
        ctx.task("t", "排队")
    def poll(self, ctx):
        raise RuntimeError("看任务的时候出错")

PLUGIN = Slow()
'''


@pytest.fixture
def home(tmp_path):
    shutil.copytree(REPO / "plugins" / "demo", tmp_path / "plugins" / "demo")
    return tmp_path


def add_plugin(home, name, code):
    (home / "plugins" / name).mkdir(parents=True)
    (home / "plugins" / name / "plugin.py").write_text(code, encoding="utf-8")


def started(desk, points=("a", "b"), **settings):
    exp_id = desk.new("demo")
    desk.set(exp_id, "点", value=list(points))
    for name, value in settings.items():
        desk.set(exp_id, name, value=value)
    desk.start(exp_id)
    return exp_id


def wait_for(check, seconds=15):
    end = time.time() + seconds
    while time.time() < end:
        value = check()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("等不到")


def status(desk, exp_id):
    return desk.store.open(exp_id).view()["status"]


# ---- 一个实验一次只让一处动 ---------------------------------------------


def test_two_starts_at_once_call_the_plugin_only_once(home):
    """两处同时启动同一个实验：只有一处做成，插件只被叫一次，另一处被拒绝。"""
    add_plugin(home, "slow", SLOW)
    exp_id = Desk(home).new("slow")
    results = []

    def go():
        try:
            results.append(Desk(home).start(exp_id))
        except RecordError as err:
            results.append(str(err))

    threads = [threading.Thread(target=go) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert sorted(map(str, results)) == sorted(["True", f"{exp_id} 现在是「{RUNNING}」，不能启动。"])
    exp = Desk(home).store.open(exp_id)
    assert (exp.folder / "plugin_state" / "started.txt").read_text() == "x"
    assert [o["op"] for o in exp.view()["operations"]] == ["新建", "启动"]
    assert exp.check() == []


def test_refresh_skips_an_experiment_someone_else_is_working_on(home):
    """别处正在动一个实验时，刷新跳过它，不等也不重复叫插件；那一处放手后再看。"""
    desk = Desk(home)
    exp_id = started(desk)
    exp = desk.store.open(exp_id)
    with exp.busy():
        assert desk.refresh() == []
        assert exp.view()["tasks"]["a"]["state"] == "排队"
    assert desk.refresh() == [exp_id]
    assert exp.view()["tasks"]["a"]["state"] == "运行"


def test_lock_left_by_a_process_that_died_does_not_block(home):
    """拿着锁的进程不在了：锁当作没人要，操作照常做。"""
    desk = Desk(home)
    exp_id = started(desk)
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    exp = desk.store.open(exp_id)
    (exp.folder / ".busy").write_text(str(gone.pid), encoding="ascii")
    began = time.time()
    assert desk.pause(exp_id) is True
    assert time.time() - began < 5
    assert status(desk, exp_id) == PAUSED


def test_lock_is_never_left_behind_when_many_want_it(home):
    """几处抢同一把锁：同一时刻只有一处进得去，谁都不会一直等不到，用完之后锁文件不留下。"""
    desk = Desk(home)
    exp = desk.store.open(desk.new("demo"))
    inside, worst, errors = [0], [0], []

    def go():
        try:
            for _ in range(150):
                with exp.busy(wait=20):
                    inside[0] += 1
                    worst[0] = max(worst[0], inside[0])
                    inside[0] -= 1
        except Exception as err:
            errors.append(repr(err))

    threads = [threading.Thread(target=go) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(120)
    assert errors == [] and worst[0] == 1
    assert not (exp.folder / ".busy").exists()


def test_record_stays_whole_when_many_write_at_once(home):
    """几处同时往一个实验的记录里追加：一条不少，序号和哈希都接得上。"""
    desk = Desk(home)
    exp_id = desk.new("demo")
    errors = []

    def go(n):
        try:
            for i in range(40):
                Desk(home).note(exp_id, f"{n}-{i}")
        except Exception as err:
            errors.append(repr(err))

    threads = [threading.Thread(target=go, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(120)
    exp = desk.store.open(exp_id)
    assert errors == [] and len(exp.view()["notes"]) == 160 and exp.check() == []
    assert not (exp.folder / ".lock").exists()


# ---- 定时值守 -----------------------------------------------------------


def test_watch_moves_running_experiments_forward_by_itself(home):
    """值守开着，不用人叫刷新，任务自己走到结束；停掉之后值守锁放开。"""
    desk = Desk(home)
    one, two = started(desk), started(desk, points=["x"])
    watch = Watch(lambda: desk, every=0.05)
    watch.start()
    try:
        wait_for(lambda: status(desk, one) == FINISHED and status(desk, two) == FINISHED)
        st = wait_for(lambda: (s := watch.status())["rounds"] >= 3 and s)
        assert st["on"] and st["holding"] and st["last_time"] and st["last_error"] == ""
        assert (home / "experiments" / ".watch").read_text() == str(os.getpid())
    finally:
        watch.stop()
    assert not (home / "experiments" / ".watch").exists()
    assert watch.status()["on"] is False
    v = desk.store.open(one).view()
    assert [h["state"] for h in v["tasks"]["a"]["history"]] == ["排队", "运行", "完成"]
    assert v["outputs"][0]["name"] == "点清单" and desk.store.open(one).check() == []


def test_watch_only_touches_running_experiments(home):
    """值守只看运行中的：没启动的、暂停的不动。"""
    desk = Desk(home)
    idle = desk.new("demo")
    paused = started(desk)
    desk.pause(paused)
    before = {e: len(desk.store.open(e).events()) for e in (idle, paused)}
    watch = Watch(lambda: desk, every=0.05)
    for _ in range(3):
        assert watch.round() == []
    watch.stop()
    assert {e: len(desk.store.open(e).events()) for e in (idle, paused)} == before
    assert status(desk, idle) == NOT_STARTED and status(desk, paused) == PAUSED


def test_only_one_watch_per_home(home):
    """一个 home 同一时刻只有一处在值守；那一处停了，另一处自己接上。"""
    desk = Desk(home)
    exp_id = started(desk)
    first, second = Watch(lambda: desk, every=1), Watch(lambda: Desk(home), every=1)
    assert first.round() == [exp_id]
    assert second.round() is None
    assert second.status()["holding"] is False and second.status()["elsewhere"] == os.getpid()
    assert desk.store.open(exp_id).view()["tasks"]["a"]["state"] == "运行"  # 只往前走了一格
    first.stop()
    assert second.round() == [exp_id]
    assert second.status()["holding"] is True and second.status()["elsewhere"] is None
    second.stop()


def test_watch_goes_on_when_one_experiment_has_trouble(home):
    """一个实验的插件看任务时出错、另一个实验的记录读不了：都记下，别的实验照常走完。"""
    add_plugin(home, "slow", SLOW)
    desk = Desk(home)
    bad = desk.new("slow")
    desk.start(bad)
    broken = started(desk)
    good = started(desk)
    with open(home / "experiments" / broken / "record.jsonl", "ab") as f:
        f.write(b'{"seq": 99, "ti\n')

    watch = Watch(lambda: desk, every=0.05)
    for _ in range(3):
        watch.round()
    st = watch.status()
    watch.stop()
    assert status(desk, good) == FINISHED
    assert list(st["unreadable"]) == [broken] and st["last_error"] == ""
    problems = desk.store.open(bad).view()["problems"]
    assert len(problems) == 3 and "看任务的时候出错" in problems[0]["error"]


def test_watch_before_any_experiment_exists_writes_nothing(tmp_path):
    """还没有任何实验时，值守什么都不做，也不建文件夹。"""
    desk = Desk(tmp_path)
    watch = Watch(lambda: desk, every=0.05)
    assert watch.round() is None
    watch.stop()
    assert list(tmp_path.iterdir()) == []


def test_command_line_watch(home, capsys):
    """命令行的值守：中文命令能用，做满次数自己停，实验走到结束。"""
    desk = Desk(home)
    exp_id = started(desk)
    assert main(["--home", str(home), "值守", "--every", "0.05", "--rounds", "4"]) == 0
    out = capsys.readouterr().out
    assert "值守开始" in out and f"看过：{exp_id}" in out and "值守停了" in out
    assert status(desk, exp_id) == FINISHED
    assert not (home / "experiments" / ".watch").exists()
