"""带代码的包：哈希不符不跑；自检不过不交出结果；包崩了不带倒值守。"""
from __future__ import annotations

import json
import os
import subprocess

import pytest

from stemlab import hooks
from stemlab.contract import Refused, layout, plugin_api
from stemlab.desk.core import actions, start, watch
from stemlab.experiments import view
from stemlab.hooks import entry, handle
from stemlab.registry import lookup, verify
from tests import helpers


def package(tmp_path, name="demo-strategy", kind="strategy", **how) -> dict:
    return actions.register(kind, name, source=helpers.make_package(tmp_path / name, kind, **how), note="测试用的包")


def experiment(tool: dict, **setting) -> str:
    made = helpers.experiment("demo.pack", value=setting)
    actions.fill(made, "tool", tool["id"])
    return made


def problems(made: str) -> list[str]:
    return [problem["error"] for problem in view.view(made).rounds[-1].problems]


class Markers:
    """这个包在这台机器的缓存里留下的自检记号。"""

    def __init__(self, tool: dict):
        self.pattern = f"{tool['hash'][:32]}-*.json"

    def found(self) -> list:
        folder = layout.cache_root() / "selftest"
        return sorted(folder.glob(self.pattern)) if folder.is_dir() else []

    def exists(self) -> bool:
        return bool(self.found())

    def read_bytes(self) -> bytes:
        return self.found()[0].read_bytes()

    def unlink(self) -> None:
        for path in self.found():
            path.unlink()


def marker(tool: dict) -> Markers:
    return Markers(tool)


def count_launches(monkeypatch) -> list:
    """数包的入口被起了几次。返回一个列表，每起一次多一项。"""
    launches, real = [], subprocess.Popen

    def counting(command, *args, **how):
        if list(command[1:2]) == ["code/main.py"]:
            launches.append(command)
        return real(command, *args, **how)

    monkeypatch.setattr(subprocess, "Popen", counting)
    return launches


# ---- 跑通 ----

@pytest.mark.parametrize("kind", ["kernel", "strategy", "derive_def", "predictor"])
def test_running_a_package_through_the_facade(lab, data, tmp_path, kind, monkeypatch):
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)    # 不许包往里写缓存，要靠核心自己设，不靠外面碰巧设了
    tool = package(tmp_path, kind=kind)
    made = experiment(tool, x=4)
    assert start.start(made).ok and start.poll(made).ok
    status = view.view(made)
    report = lookup.content(lookup.by_origin(made, 1)[0]["id"])
    assert json.loads((report / "summary.json").read_bytes())["result"] == {"y": 10.0, "name": "demo"}
    assert status.rounds[0].result == "done" and status.rounds[0].problems == []
    noted = [extra["info"] for extra in status.rounds[0].extra if extra["source"] == "package"]
    assert noted == [{"id": tool["id"], "hash": tool["hash"], "kind": kind, "name": tool["name"], "version": 1}], \
        "用了哪个包由核心记进来历"
    assert json.loads(marker(tool).read_bytes())["package"] == tool["id"], "在这台机器上过了自检，留了记号"
    assert verify.verify_item(tool["id"]) == tool["hash"], "跑过之后包里没有多出缓存之类的东西"
    assert not (lookup.content(tool["id"]) / "code" / "__pycache__").exists()
    assert (layout.work_dir(made) / "out-r1" / "log.txt").exists()


def test_the_selftest_runs_only_the_first_time_on_this_machine(lab, data, tmp_path, monkeypatch):
    tool = package(tmp_path)
    launches = count_launches(monkeypatch)
    first = experiment(tool, x=1)
    start.start(first), start.poll(first)
    second = experiment(tool, x=3)
    start.start(second), start.poll(second)
    assert len(launches) == 3, "第一次：自检一遍加真跑一遍；第二次：只真跑一遍"
    assert view.view(second).state == "ended"
    marker(tool).unlink()
    third = experiment(tool, x=3)
    start.start(third), start.poll(third)
    assert len(launches) == 5, "记号没了就重新自检"


def test_the_selftest_runs_again_when_the_environment_changes(own_lab, data, tmp_path, monkeypatch):
    """记号认的是“这个包、这台机器、这个环境”：锁文件变了，环境就可能不一样了，重新自检。"""
    tool = package(tmp_path)
    launches = count_launches(monkeypatch)
    first = experiment(tool)
    start.start(first), start.poll(first)
    assert len(launches) == 2 and len(marker(tool).found()) == 1
    lock = own_lab / "uv.lock"
    lock.write_bytes(lock.read_bytes() + b"\n# a dependency was upgraded\n")
    second = experiment(tool)
    start.start(second), start.poll(second)
    assert len(launches) == 4 and len(marker(tool).found()) == 2, "换了环境，自检重新跑了一遍"


def test_the_provenance_is_noted_once_per_round(lab, data, tmp_path):
    tool = package(tmp_path)
    made = experiment(tool, wait=False)
    start.start(made)
    start.poll(made)
    assert view.view(made).tasks["job"].stage == "in the package", "起了一个脱离出去的进程就返回"
    process = json.loads((layout.work_dir(made) / "process.json").read_bytes())
    helpers.wait_for(lambda: not hooks.alive(process))
    assert start.poll(made).ok
    status = view.view(made)
    assert status.rounds[0].result == "done"
    assert len([extra for extra in status.rounds[0].extra if extra["source"] == "package"]) == 1


# ---- 哈希不符不跑 ----

def test_a_package_whose_content_changed_is_not_run(lab, data, tmp_path):
    tool = package(tmp_path)
    made = experiment(tool)
    assert start.start(made).ok
    code = lookup.content(tool["id"]) / "code" / "main.py"
    os.chmod(code, 0o600)
    code.write_bytes(code.read_bytes() + b"\n# tampered after it was registered\n")
    result = start.poll(made)
    assert not result.ok and "不一致" in result.error and tool["id"] in result.error
    assert view.view(made).state == "running" and view.view(made).rounds[0].outputs == {}
    assert not (layout.work_dir(made) / "out-r1").exists() and not marker(tool).exists(), "一次都没跑"


# ---- 自检不过不交出结果 ----

def test_a_package_that_fails_its_selftest_gives_no_result(lab, data, tmp_path):
    tool = package(tmp_path, expected={"y": 5.1, "name": "demo"})
    made = experiment(tool)
    start.start(made)
    result = start.poll(made)
    assert not result.ok and "自检没过" in result.error and "small" in result.error and "result.y" in result.error
    assert view.view(made).rounds[0].outputs == {} and not marker(tool).exists()
    assert not (layout.work_dir(made) / "out-r1").exists(), "自检没过，真的那一遍就不跑"
    assert [e for e in view.view(made).rounds[0].extra if e["source"] == "package"] == [], "没用上，就不记进来历"


# ---- 包崩了不带倒值守 ----

def test_a_crashing_package_is_just_a_problem(lab, data, tmp_path):
    tool = package(tmp_path)
    crashing, fine = experiment(tool, crash=True), experiment(tool, x=2)
    start.start(crashing), start.start(fine)
    seen = watch.once()
    assert seen[crashing].startswith("插件出错") and seen[fine] == "看过了"
    text = problems(crashing)[0]
    assert "退出码 7" in text and "crashing on purpose" in text, "带着包输出的末尾"
    assert view.view(crashing).state == "running" and view.view(fine).state == "ended"


def test_a_package_that_takes_too_long_is_ended(lab, data, tmp_path):
    tool = package(tmp_path)
    made = experiment(tool)
    start.start(made)
    status = view.view(made)
    given = handle.Handle(made, plugin_api.RoundInfo(1, (), status.rounds[0].provenance), status.inputs, status.frozen)
    source = helpers.write_files(given.work_dir / "slow", {"x.json": b'{"x": 1, "sleep": 30}'})
    with pytest.raises(Refused, match="还没完"):
        entry.call_with(given, lambda h: entry.run(tool["id"], source, given.work_dir / "slow-out", timeout=1.5))
    assert entry.call_with(given, lambda h: hooks.run_strategy(tool["id"], helpers.write_files(
        given.work_dir / "quick", {"x.json": b'{"x": 2}'}), given.work_dir / "quick-out")) == {"y": 5.0, "name": "demo"}


def handle_for(made: str):
    status = view.view(made)
    return handle.Handle(made, plugin_api.RoundInfo(1, (), status.rounds[0].provenance), status.inputs, status.frozen)


def test_a_timeout_ends_what_the_package_started_too(lab, data, tmp_path):
    """超时的时候连同包起的进程一起结束：求解器不能留在后面接着跑、接着往输出里写。"""
    import psutil

    tool = package(tmp_path)
    made = experiment(tool)
    start.start(made)
    given = handle_for(made)
    source = helpers.write_files(given.work_dir / "solver", {"x.json": b'{"x": 1, "child": true, "sleep": 60}'})
    target = given.work_dir / "solver-out"
    with pytest.raises(Refused, match="都结束了"):
        entry.call_with(given, lambda h: entry.run(tool["id"], source, target, timeout=4.0))
    child = int((target / "child.pid").read_text())
    helpers.wait_for(lambda: not psutil.pid_exists(child), seconds=15)


def test_a_result_left_by_an_earlier_run_is_not_passed_off_as_this_one(lab, data, tmp_path):
    tool = package(tmp_path)
    made = experiment(tool)
    start.start(made)
    given = handle_for(made)
    target = given.work_dir / "out"
    first = helpers.write_files(given.work_dir / "first", {"x.json": b'{"x": 2}'})
    assert entry.call_with(given, lambda h: entry.run(tool["id"], first, target)) == {"y": 5.0, "name": "demo"}
    silent = helpers.write_files(given.work_dir / "silent", {"x.json": b'{"x": 3, "silent": true}'})
    with pytest.raises(Refused, match="没有留下读得出的"):
        entry.call_with(given, lambda h: entry.run(tool["id"], silent, target))
    assert not (target / "result.json").exists()


# ---- 只能跑这个实验存定的包，只能在调用里跑 ----

def test_only_frozen_inputs_can_be_run(lab, data, tmp_path):
    tool, other = package(tmp_path), package(tmp_path, name="another")
    made = experiment(tool, package=other["id"])
    start.start(made)
    assert "不是这个实验存定的输入" in start.poll(made).error

    wrong_kind = experiment(tool, **{"as": "kernel"})
    start.start(wrong_kind)
    assert "这里要的是kernel" in start.poll(wrong_kind).error

    not_a_package = experiment(tool)
    setting_id = view.view(not_a_package).filled["setting"][0]
    start.start(not_a_package)
    status = view.view(not_a_package)
    given = handle.Handle(not_a_package, plugin_api.RoundInfo(1, (), status.rounds[0].provenance), status.inputs, status.frozen)
    with pytest.raises(Refused, match="带代码的包"):
        entry.call_with(given, lambda h: entry.run(setting_id, tmp_path, tmp_path / "out"))


def test_packages_cannot_be_run_outside_a_call_or_from_a_read_only_one(lab, data, tmp_path):
    tool = package(tmp_path)
    made = experiment(tool)
    with pytest.raises(Refused, match="只能在"):
        hooks.run_strategy(tool["id"], tmp_path, tmp_path / "out")
    start.start(made)
    status = view.view(made)
    info = plugin_api.RoundInfo(1, (), status.rounds[0].provenance)
    read_only = handle.ReadOnly(made, info, status.inputs, status.frozen)
    with pytest.raises(Refused, match="只读"):
        entry.call_with(read_only, lambda h: hooks.run_strategy(tool["id"], tmp_path, tmp_path / "out"))
    assert entry.CURRENT.get() is None, "调用结束，就不在哪一次调用里了"


def test_a_registered_package_must_fit_the_format(lab, data, tmp_path):
    bad = helpers.make_package(tmp_path / "bad", "strategy", selftest=[])
    with pytest.raises(Refused, match="至少要有一个自检样本"):
        actions.register("strategy", "bad", source=bad, note="n")
    predictor = package(tmp_path, name="a-predictor", kind="predictor")
    assert lookup.get(predictor["id"])["kind"] == "predictor"
