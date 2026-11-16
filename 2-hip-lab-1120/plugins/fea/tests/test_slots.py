"""求解槽：整台机器共用，占槽的进程不在了槽就空出来；放槽只放还记在自己名下的。几处同时来占，一个槽只给一处。
起进程断在半路：起来了的那个收掉，槽放掉。"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import psutil

from plugins.fea import run

A = {"experiment": "E0001", "task": "a"}
B = {"experiment": "E0002", "task": "b"}
REPO = Path(__file__).resolve().parents[3]


def dead_process() -> dict:
    """一个已经结束了的进程的进程号和创建时间。"""
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    created = psutil.Process(child.pid).create_time()
    child.wait()
    return {"pid": child.pid, "created": created}


def test_a_slot_is_taken_once_and_freed_by_its_owner(tmp_path, monkeypatch):
    monkeypatch.setenv("STEMLAB_SLOTS", str(tmp_path))
    first = run._claim("solve", 2, A)
    second = run._claim("solve", 2, B)
    assert first and second and first != second
    assert run._claim("solve", 2, {"experiment": "E0003", "task": "c"}) is None, "两个槽都占着"
    run._free(first, A)
    assert run._claim("solve", 2, {"experiment": "E0003", "task": "c"}) == first


def test_a_slot_whose_process_is_gone_can_be_taken_over(tmp_path, monkeypatch):
    monkeypatch.setenv("STEMLAB_SLOTS", str(tmp_path))
    slot = run._claim("solve", 1, A)
    run._hold(slot, dead_process(), A)
    assert run._claim("solve", 1, B) == slot, "占槽的进程不在了，槽空出来"
    assert json.loads(open(slot, "rb").read())["task"] == "b"


def test_freeing_does_not_take_a_slot_away_from_whoever_took_it_over(tmp_path, monkeypatch):
    """甲的求解刚结束、还没来得及放槽，乙已经把这个槽占走了：甲这时再放，不能把乙的槽放掉。"""
    monkeypatch.setenv("STEMLAB_SLOTS", str(tmp_path))
    slot = run._claim("solve", 1, A)
    run._hold(slot, dead_process(), A)
    assert run._claim("solve", 1, B) == slot
    run._free(slot, A)
    assert run._claim("solve", 1, {"experiment": "E0003", "task": "c"}) is None, "槽还是乙的"
    run._free(slot, B)
    assert run._claim("solve", 1, {"experiment": "E0003", "task": "c"}) == slot


def test_an_earlier_run_of_the_same_task_cannot_free_this_runs_slot(tmp_path, monkeypatch):
    """放槽认的是这一次执行（作业文件夹带着轮号），不只是实验和任务：上一轮那一次放不掉这一轮的槽。"""
    monkeypatch.setenv("STEMLAB_SLOTS", str(tmp_path / "slots"))
    earlier = dict(A, folder=str(tmp_path / "jobs" / "a" / "r1"))
    this = dict(A, folder=str(tmp_path / "jobs" / "a" / "r2"))
    slot = run._claim("solve", 1, dict(this, stage="solve"))
    run._free(slot, earlier)
    assert run._claim("solve", 1, B) is None, "槽还是这一轮这一次执行的"
    run._free(slot, this)
    assert run._claim("solve", 1, B) == slot


RACE = """
import json, sys, time
from pathlib import Path
from plugins.fea import run
go, done, name = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
while not go.exists():
    time.sleep(0.002)
print(json.dumps(run._claim("solve", 1, {"experiment": name, "task": "t"})), flush=True)
while not done.exists():
    time.sleep(0.02)
"""


def test_several_desks_taking_over_one_freed_slot_get_it_once(tmp_path, monkeypatch):
    """一个槽空出来了（占它的进程不在了），几处同时来占：看、改写都在锁里，只有一处占得到。
    占到的那一处一直活着，所以后来的也占不到。"""
    monkeypatch.setenv("STEMLAB_SLOTS", str(tmp_path / "slots"))
    run._hold(run._claim("solve", 1, A), dead_process(), A)
    go, done = tmp_path / "go", tmp_path / "done"
    env = dict(os.environ, PYTHONPATH=str(REPO), PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    racers = [subprocess.Popen([sys.executable, "-c", RACE, str(go), str(done), f"E{n:04d}"], cwd=REPO, env=env,
                               stdout=subprocess.PIPE) for n in range(8)]
    try:
        time.sleep(2.0)                                 # 等它们都起来、都等在门口
        go.touch()
        said = [json.loads(racer.stdout.readline()) for racer in racers]
    finally:
        done.touch()
        for racer in racers:
            racer.wait(timeout=60)
    assert len([one for one in said if one]) == 1, said


def test_a_launch_cut_short_ends_what_it_started_and_frees_the_slot(tmp_path, monkeypatch):
    """断在“正要起进程”和“记下进程”之间：下一遍把已经起来的那个收掉、槽放掉，这个作业算崩了，不再起第二个。
    建模认命令行最后两个参数，求解认环境变量。命令行里只是带着这个作业文件夹的别的进程（比如开着它的编辑器）不碰。"""
    monkeypatch.setenv("STEMLAB_SLOTS", str(tmp_path / "slots"))
    folder = tmp_path / "jobs" / "a" / "r1"
    handle, job = SimpleNamespace(experiment=A["experiment"]), {"task": A["task"]}
    sleeper = "import time; time.sleep(120)"
    build = subprocess.Popen([sys.executable, "-c", sleeper, str(folder / "ask-build"), str(folder / "build")])
    bystander = subprocess.Popen([sys.executable, "-c", sleeper, str(folder / "build")])
    solve = subprocess.Popen([sys.executable, "-c", sleeper], env=dict(os.environ, **{run.MARK: str(folder)}))
    try:
        for stage, started, before in (("build", build, "queued"), ("solve", solve, "ready")):
            slot = run._claim(stage, 1, A)
            cut = {"stage": before, "since": time.time(), "launching": stage, "slot": slot}
            state = run._step(handle, job, folder, cut, {})
            assert (state["stage"], state["lost"], state["slot"], state["launching"]) == ("end", "crashed", None, None)
            assert started.wait(timeout=30) is not None, f"{stage} 那个已经起来了的进程被收掉了"
            assert run._claim(stage, 1, B) == slot, "它占的槽放掉了"
        assert bystander.poll() is None, "命令行里只是带着这个作业文件夹的别的进程，不碰"
    finally:
        for process in (build, bystander, solve):
            process.kill()


def test_slots_are_not_kept_in_the_temp_folder_by_default(monkeypatch):
    """系统清临时文件时会删掉临时文件夹里的东西：槽要是放在那里，求了一半的槽就像空了。"""
    monkeypatch.delenv("STEMLAB_SLOTS", raising=False)
    where = run._slots()
    assert Path(tempfile.gettempdir()).resolve() not in where.resolve().parents and where.parts[-2:] == ("stemlab", "slots")
