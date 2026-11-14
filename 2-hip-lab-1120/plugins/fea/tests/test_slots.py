"""求解槽：整台机器共用，占槽的进程不在了槽就空出来；放槽只放还记在自己名下的。"""
import json
import subprocess
import sys

import psutil

from plugins.fea import run

A = {"experiment": "E0001", "task": "a"}
B = {"experiment": "E0002", "task": "b"}


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
