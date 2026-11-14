"""挂点：插件写得再糟，最坏的结果是这个实验多一条问题。"""
from __future__ import annotations

import json
import subprocess
import threading
import time

import pytest

from stemlab import hooks
from stemlab.contract import Refused, hashing, layout, plugin_api
from stemlab.desk.core import actions, start
from stemlab.experiments import log, reader, view
from stemlab.hooks import call, handle, load, local, publish
from stemlab.registry import lookup, register, verify
from tests import helpers
from tests.contract import samples


def record_bytes(made: str) -> bytes:
    return layout.record_file(made).read_bytes()


def problems(made: str) -> list[dict]:
    return view.view(made).rounds[-1].problems


# ---- 门面 ----

def test_the_facade_is_exactly_what_plugins_may_use():
    assert set(hooks.__all__) == {
        "Kind", "Input", "Output", "Outcome", "Chart", "TASK_STATES", "read_points", "write_points", "check_format",
        "fingerprint", "predict", "derive", "run_strategy", "run_kernel", "look", "rerun", "spawn", "alive", "kill", "remote"}
    assert all(hasattr(hooks, name) for name in hooks.__all__)
    assert hooks.TASK_STATES == ("queued", "running", "done", "failed", "stopped")
    assert hooks.Kind is plugin_api.Kind and hooks.spawn is local.spawn and hooks.kill is local.kill


# ---- 1 一个类型报的三张表和它写了哪几个动作，都读得出 ----

def test_types_tables_and_actions_can_be_read(lab):
    loaded = load.load()
    assert {"demo.echo", "demo.quiet", "demo.sleep", "bad.raises"} <= set(loaded.kinds)
    assert loaded.owners["demo.echo"] == "demo" and loaded.owners["bad.raises"] == "bad"
    echo = loaded.kinds["demo.echo"]
    tables = plugin_api.tables(echo)
    assert [row["name"] for row in tables["inputs"]] == ["setting", "extra"]
    assert tables["inputs"][1] == {"name": "extra", "kinds": ["report", "edits", "bone_source"], "many": True,
                                   "required": False, "label": "附带的"}
    assert [row["name"] for row in tables["outputs"]] == ["report", "second"]
    assert {row["name"]: row["category"] for row in tables["outcomes"]} == {
        "finished": "ok", "misfit": "conclusion", "env": "retryable", "diverged": "unclear"}
    assert plugin_api.actions(echo) == ("check", "start", "poll", "stop")
    assert plugin_api.actions(loaded.kinds["demo.quiet"]) == ("check", "start", "poll"), "这个类型没有写停止"
    assert call.find("demo.echo") == (echo, "demo")


# ---- 5 一个插件装不上：别的照常，它的旧实验照样能看 ----

def test_a_plugin_that_cannot_load_does_not_take_the_others_down(lab, data):
    loaded = load.load()
    assert set(loaded.errors) == {"broken"} and "RuntimeError" in loaded.errors["broken"]
    assert "示范：这个插件装不上" in loaded.errors["broken"]
    assert "demo.echo" in loaded.kinds, "别的照常"
    with pytest.raises(Refused, match="装不上"):
        call.find("broken.thing")
    with pytest.raises(Refused, match="没有找到插件"):
        call.find("nothing.thing")

    tables = {"inputs": samples.INPUTS, "outputs": samples.OUTPUTS, "outcomes": samples.OUTCOMES}
    old = log.create("broken.thing", tables, note="插件还好的时候建的")
    for body in samples.HISTORIES["running"][1:] + [samples.task(state="done", outcome="finished"), samples.output()]:
        log.append(old, body)
    status = view.view(old)
    assert status.state == "running" and status.tasks["p1"].outcome == "finished", "它的旧实验照样能看"
    assert view.required(old) == [] and view.summary(old)["outputs"] == ["report"]
    result = call.call("broken.thing", "poll", old)
    assert not result.ok and "用不了" in result.error and len(problems(old)) == 1, "叫不了它，记成这个实验的问题"


ODD = """\
from stemlab.hooks import Input, Kind, Outcome, Output
def nothing(handle):
    return None
def kind(name, accepts="setting"):
    return Kind(name=name, inputs=(Input("x", (accepts,)),), outputs=(), outcomes=(Outcome("ok", "ok"),),
                check=nothing, start=nothing, poll=nothing)
KINDS = %s
"""


def load_with_an_extra_plugin(own_lab, kinds: str):
    """在这次测试自己的仓库拷贝里多放一个插件 odd，它报的类型由 kinds 这段代码给。"""
    import sys

    import tests

    plugin = own_lab / "tests" / "plugins" / "odd"
    plugin.mkdir(exist_ok=True)
    (plugin / "__init__.py").write_bytes(b"")
    (plugin / "plugin.py").write_text(ODD % kinds, encoding="utf-8")
    original = list(tests.plugins.__path__)
    tests.plugins.__path__.append(str(own_lab / "tests" / "plugins"))       # 这个插件只在这份拷贝里有
    __import__("importlib").invalidate_caches()
    try:
        return load.load()
    finally:
        tests.plugins.__path__[:] = original
        sys.modules.pop("tests.plugins.odd", None), sys.modules.pop("tests.plugins.odd.plugin", None)


def test_bad_declarations_are_named(own_lab):
    loaded = load_with_an_extra_plugin(own_lab, '[kind("odd.fine"), kind("odd.wrong", accepts="nothing")]')
    assert "收的种类不对" in loaded.errors["odd"], "三张表写得不对，点名哪里不对"
    assert "odd.fine" not in loaded.kinds and "demo.echo" in loaded.kinds, "一个类型报得不对，整个插件不装；别的插件照常"

    loaded = load_with_an_extra_plugin(own_lab, '[kind("demo.stolen")]')
    assert "要以插件名 odd 开头" in loaded.errors["odd"] and "demo.stolen" not in loaded.kinds

    loaded = load_with_an_extra_plugin(own_lab, '[kind("odd.twice"), kind("odd.twice")]')
    assert "报了两次" in loaded.errors["odd"]

    loaded = load_with_an_extra_plugin(own_lab, '[kind("odd.fine")]')
    assert "odd" not in loaded.errors and loaded.owners["odd.fine"] == "odd"


def test_a_handle_kept_after_the_call_is_dead(lab, data, monkeypatch):
    """handle 只在一次调用里有效：插件把它留下来，过后再用，一样被拒。"""
    made = helpers.experiment(value={"poll": "never"})
    start.start(made)
    kept = []
    kind, plugin = call.find("demo.echo")
    thief = plugin_api.Kind(name=kind.name, inputs=kind.inputs, outputs=kind.outputs, outcomes=kind.outcomes,
                            check=kind.check, start=kind.start, poll=kept.append)
    monkeypatch.setattr(call, "find", lambda type_name: (thief, plugin))
    assert call.call("demo.echo", "poll", made).ok
    before = record_bytes(made)
    for use in (lambda: kept[0].task("only", "done", outcome="finished"), lambda: kept[0].input("setting"),
                kept[0].finish, lambda: kept[0].output("report", layout.work_dir(made))):
        with pytest.raises(Refused, match="已经结束"):
            use()
    assert record_bytes(made) == before


# ---- 2 检查里往记录写：被拒，记录里不多一条 ----

def test_writing_from_check_is_refused_and_leaves_no_trace(lab, data):
    loud = helpers.experiment("bad.check_writes")
    before = helpers.snapshot(data)
    with pytest.raises(Refused, match="只读"):
        start.start(loud)
    assert helpers.snapshot(data) == before, "记录里不多一条"

    quiet = helpers.experiment("bad.check_writes_quietly")
    assert start.start(quiet).ok, "插件把被拒吞掉了，检查算过"
    kinds_written = [entry["entry"] for entry in reader.read(quiet)]
    assert kinds_written == ["created", "filled", "frozen", "round_opened", "task", "called"], "检查里想写的六样一样都没写进去"
    assert not (layout.work_dir(quiet) / "sneaky").exists()


def test_the_read_only_handle_refuses_every_write(lab, data):
    made = helpers.experiment()
    status = view.view(made)
    info = plugin_api.RoundInfo(1, (), {})
    frozen = {"setting": [{"id": "R0001", "kind": "setting", "name": "setting-x", "version": 1, "hash": "0" * 64,
                           "origin": samples.EXTERNAL, "bone_id": None}], "extra": []}
    given = handle.ReadOnly(made, info, status.inputs, frozen)
    assert given.input("setting") == {} and given.input("extra") == [] and given.input_info("setting").id == "R0001"
    assert given.input_info("extra") == [] and given.tasks() == {} and given.experiment == made
    assert given.work_dir == layout.work_dir(made) and not given.work_dir.exists(), "只读的那一份连 work/ 都不建"
    assert [machine.name for machine in given.machines] == ["here"]
    for write in (lambda: given.task("a", "queued"), lambda: given.output("report", given.work_dir),
                  lambda: given.problem("x"), lambda: given.provenance(a=1), given.finish, lambda: given.fail("x")):
        with pytest.raises(Refused, match="只读"):
            write()
    with pytest.raises(Refused, match="没有叫 nothing 的输入"):
        given.input("nothing")
    given.close()
    for use in (lambda: given.input("setting"), given.tasks, lambda: given.task("a", "queued")):
        with pytest.raises(Refused, match="已经结束"):
            use()


# ---- 3 动作抛错：记成问题，不往外抛，别的实验照常 ----

def test_an_action_that_raises_becomes_a_problem(lab, data):
    crashing, fine = helpers.experiment("bad.raises"), helpers.experiment()
    start.start(crashing), start.start(fine)
    result = start.poll(crashing)
    assert not result.ok and result.error == "RuntimeError: 坏插件：轮询里抛错", "不往外抛"
    found = problems(crashing)
    assert [p["error"] for p in found] == ["RuntimeError: 坏插件：轮询里抛错"] and found[0]["task"] is None
    assert "Traceback" in found[0]["raw"] and "poll_raises" in found[0]["raw"], "原始报错留着"
    assert view.view(crashing).state == "running", "状态不变"
    assert start.poll(fine).ok and view.view(fine).state == "ended", "别的实验照常"

    exiting = helpers.experiment("bad.exits_in_poll")
    start.start(exiting)
    result = start.poll(exiting)
    assert not result.ok and "SystemExit" in result.error, "插件想退出进程也接得住"


def test_a_start_that_raises_ends_the_round_as_start_failed(lab, data):
    made = helpers.experiment(value={"start": "raise"})
    result = start.start(made)
    status = view.view(made)
    assert not result.ok and result.error == "RuntimeError: 示范：启动抛错"
    assert status.state == "ended" and status.rounds[0].result == "start_failed"
    assert status.rounds[0].reason == "RuntimeError: 示范：启动抛错"
    assert status.rounds[0].calls == [{"action": "start", "ok": False, "error": "RuntimeError: 示范：启动抛错",
                                       "time": status.rounds[0].calls[0]["time"]}]
    assert "Traceback" in status.rounds[0].problems[0]["raw"]
    assert [e["entry"] for e in reader.read(made)][-3:] == ["problem", "called", "round_closed"]
    assert start.start(made).ok is False and len(view.view(made).rounds) == 2, "启动失败之后可以再启动，是新的一轮"


def test_what_the_plugin_says_takes_effect_after_the_call_returns(lab, data):
    finished = helpers.experiment(value={"start": "finish"})
    assert start.start(finished).ok
    assert [e["entry"] for e in reader.read(finished)][-3:] == ["task", "called", "round_closed"]
    assert view.view(finished).rounds[0].result == "done"

    failed = helpers.experiment(value={"start": "fail"})
    start.start(failed)
    assert (view.view(failed).rounds[0].result, view.view(failed).rounds[0].reason) == ("failed", "示范：启动里就做不下去")

    later = helpers.experiment(value={"poll": "fail"})
    start.start(later), start.poll(later)
    assert view.view(later).rounds[0].result == "failed" and view.view(later).rounds[0].reason == "示范：做不下去"


# ---- 4 同一个报错连着三次：只有一条问题，恢复时写明三次 ----

def test_the_same_error_three_times_is_one_problem_with_a_count(lab, data):
    made = helpers.experiment(value={"poll_raises": 3})
    start.start(made)
    for _ in range(3):
        assert not start.poll(made).ok
    assert len(helpers.entries_of(made, "problem")) == 1, "连着出现只记一次"
    assert problems(made)[0]["count"] == 1
    assert start.poll(made).ok
    entries = helpers.entries_of(made, "problem")
    assert len(entries) == 2 and entries[1]["count"] == 3 and entries[1]["error"] == entries[0]["error"]
    found = problems(made)
    assert len(found) == 1 and found[0]["count"] == 3, "看的时候只有一条问题，写明连着出现了三次"
    assert view.view(made).state == "ended"


def test_a_different_error_closes_the_streak(lab, data):
    made = helpers.experiment("bad.raises")
    start.start(made)
    start.poll(made), start.poll(made)
    call._failed(made, 1, "ValueError: 换了一个报错")
    start.poll(made)
    found = [(p["error"].split(":")[0], p["count"]) for p in problems(made)]
    assert found == [("RuntimeError", 2), ("ValueError", 1), ("RuntimeError", 1)]
    other = helpers.experiment("bad.raises")
    start.start(other), start.poll(other)
    assert len(problems(other)) == 1, "各个实验各数各的"


# ---- 6 发布：不该交的各被拒并记成问题，文件留在原地 ----

def test_rejected_outputs_become_problems_and_stay_where_they_were(lab, data):
    made = helpers.experiment("bad.wrong_output")
    start.start(made)
    assert start.poll(made).ok
    status = view.view(made)
    texts = [p["error"] for p in status.rounds[0].problems]
    assert len(texts) == 5 and all(text.startswith("产物 ") and "没有发布" in text for text in texts)
    assert "产物表里没有 'nothing'" in texts[0]
    assert "种类不符" in texts[1] and "edits" in texts[1]
    assert "清单列了但文件夹里没有：a.txt" in texts[2]
    assert "work/" in texts[3] and "work/" in texts[4]
    work = layout.work_dir(made)
    assert sorted(p.name for p in work.iterdir()) == ["no-such-file", "undeclared", "wrong-kind"], "文件留在原地"
    assert status.rounds[0].outputs == {} and lookup.by_origin(made) == []
    assert not layout.outputs_dir(made, 1).exists(), "什么都没移过去"
    assert status.state == "ended" and status.rounds[0].result == "done"


def test_an_output_can_only_be_published_once_per_round_and_only_in_the_round(lab, data):
    made = helpers.experiment(value={"second": True})
    start.start(made), start.poll(made)
    status = view.view(made)
    assert sorted(status.rounds[0].outputs) == ["report", "second"]
    with pytest.raises(Refused, match="不能交产物"):
        publish.publish(made, 1, "report", layout.work_dir(made))          # 这一轮已经结束了

    again = helpers.experiment(value={"poll": "never"})
    start.start(again)
    folder = helpers.make_folder(layout.work_dir(again) / "one", files={"a.txt": b"1"})
    first = publish.publish(again, 1, "report", folder)
    assert first == lookup.by_origin(again, 1)[0]["id"] and not folder.exists()
    twice = helpers.make_folder(layout.work_dir(again) / "two", files={"a.txt": b"2"})
    assert publish.publish(again, 1, "report", twice) is None and twice.exists()
    assert "已经交过" in problems(again)[0]["error"]
    with pytest.raises(Refused):
        publish.publish(again, 2, "second", twice)                          # 轮号不对


def test_the_bone_id_of_an_output_must_come_from_the_inputs(lab, data, tmp_path):
    source = helpers.write_files(tmp_path / "ct", {"scan.dcm": b"ct"})
    case = actions.register("bone_source", "femur042-ct", source=source, note="CT", bone_id="femur042", new_bone=True)
    stranger = helpers.experiment(value={"bone_id": "femur999"}, extra=[case["id"]])
    start.start(stranger), start.poll(stranger)
    assert "femur999" in problems(stranger)[0]["error"] and "继承" in problems(stranger)[0]["error"]
    assert problems(stranger)[0]["error"].startswith("产物 report 没有发布"), "在移动文件之前就拦下了"
    assert lookup.by_origin(stranger) == [] and not layout.outputs_dir(stranger, 1).exists()
    assert (layout.work_dir(stranger) / "report-r1" / "summary.json").exists(), "文件留在原地"

    inherited = helpers.experiment(value={"bone_id": "femur042"}, extra=[case["id"]])
    start.start(inherited), start.poll(inherited)
    assert lookup.by_origin(inherited)[0]["bone_id"] == "femur042" and problems(inherited) == []


# ---- 8 只记位置的输入在启动之后被改了：不交出内容，记成问题 ----

def test_a_ref_input_changed_after_start_is_not_handed_out(lab, data, tmp_path):
    source = helpers.make_folder(tmp_path / "outside")
    ref = actions.register("report", "outside-report", source=source, storage="ref", note="只记位置")
    made = helpers.experiment(value={"polls": 2}, extra=[ref["id"]])
    assert start.start(made).ok and start.poll(made).ok
    (source / "summary.json").write_bytes(b'{"changed": "after start"}\n')
    result = start.poll(made)
    assert not result.ok and "不一致" in result.error and ref["id"] in result.error
    assert "outside-report" in problems(made)[0]["error"], "记成问题，说出是哪一样"
    assert view.view(made).state == "running" and view.view(made).rounds[0].outputs == {}, "内容没交出去，产物没出来"


def test_handle_inputs_follow_the_inputs_table(lab, data, tmp_path):
    reports = [actions.register("report", f"r{n}", source=helpers.make_folder(tmp_path / f"r{n}"), note="n")
               for n in range(2)]
    made = helpers.experiment(value={"poll": "never", "scale": 7}, extra=[item["id"] for item in reports])
    start.start(made)
    status = view.view(made)
    info = plugin_api.RoundInfo(1, (), status.rounds[0].provenance)
    given = handle.Handle(made, info, status.inputs, status.frozen)
    assert given.input("setting") == {"poll": "never", "scale": 7}
    assert given.input("extra") == [lookup.content(item["id"]) for item in reports], "收多份的返回列表"
    assert [one.id for one in given.input_info("extra")] == [item["id"] for item in reports]
    single = given.input_info("setting")
    assert (single.kind, single.version, single.hash) == ("setting", 1, lookup.get(single.id)["hash"])
    assert given.round.provenance["plugin"] == "demo" and len(given.round.provenance["plugin_frozen"]) == 64
    assert given.work_dir.is_dir() and list(given.tasks()) == ["only"]
    given.task("only", "running", stage="手动报的")
    assert given.tasks()["only"].stage == "手动报的"
    with pytest.raises(Refused, match="结局表里没有"):
        given.task("only", "done", outcome="nothing")
    given.close()


# ---- 本机的脱离进程 ----

def test_spawn_alive_and_kill(tmp_path):
    log_file = tmp_path / "out.log"
    child = local.spawn([__import__("sys").executable, "-c", "import time; print('started', flush=True); time.sleep(60)"],
                        log=log_file)
    try:
        assert set(child) == {"pid", "created"} and json.loads(json.dumps(child)) == child, "是个普通的 JSON 对象"
        assert local.alive(child)
        assert not local.alive(dict(child, created=child["created"] + 5)), "进程号对、创建时间不对：是被重用的进程号"
        assert not local.alive({"pid": 4_000_000, "created": 0.0})
        helpers.wait_for(lambda: b"started" in log_file.read_bytes())
    finally:
        local.kill(child)
    assert not local.alive(child)
    local.kill(child)                           # 已经不在了：可以重复叫


def test_a_spawned_process_outlives_the_process_that_spawned_it():
    """关掉终端、操作台退出，求解照样跑。"""
    leaving = helpers.spawn_worker("spawn", "60", "leave")
    out, _ = leaving.communicate(timeout=60)
    child = json.loads(out)
    try:
        assert leaving.returncode == 0
        time.sleep(1.0)
        assert local.alive(child), "起它的进程正常退出了，它还在"
    finally:
        local.kill(child)

    staying = helpers.spawn_worker("spawn", "60", "stay")
    child = json.loads(staying.stdout.readline())
    spawner = helpers.family(staying) - {child["pid"]} - _descendants(child["pid"])
    try:
        staying.kill()                          # 起它的进程被强行结束（Windows 上连同转发器的作业对象一起）
        staying.wait(timeout=30)
        helpers.wait_for(lambda: not any(map(_exists, spawner)))
        time.sleep(0.5)
        assert local.alive(child), "起它的进程被结束了，它还在"
    finally:
        local.kill(child)
    assert not local.alive(child)


def _exists(pid: int) -> bool:
    import psutil

    return psutil.pid_exists(pid)


def _descendants(pid: int) -> set[int]:
    import psutil

    try:
        return {child.pid for child in psutil.Process(pid).children(recursive=True)}
    except psutil.NoSuchProcess:
        return set()


def test_a_spawned_process_ignores_ctrl_break_sent_to_its_parent():
    import signal

    if not hasattr(signal, "CTRL_BREAK_EVENT"):
        pytest.skip("只在 Windows 上有这回事")
    parent = subprocess.Popen(
        [__import__("sys").executable, "-m", "tests.blocks.parallel", "spawn", "60", "stay"], cwd=helpers.REPO,
        stdout=subprocess.PIPE, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    child = json.loads(parent.stdout.readline())
    try:
        parent.send_signal(signal.CTRL_BREAK_EVENT)
        parent.wait(timeout=30)
        time.sleep(0.5)
        assert local.alive(child), "按了 Ctrl+Break，父进程走了，它还在"
    finally:
        local.kill(child)
        helpers.kill_tree(parent)


# ---- Windows 上移动文件夹：正被读着的时候等一下再试 ----

def test_rename_retries_while_a_reader_still_has_a_file_open(tmp_path):
    source = helpers.write_files(tmp_path / "source", {"a.txt": b"x"})
    reader_handle = open(source / "a.txt", "rb")
    threading.Timer(0.4, reader_handle.close).start()
    started = time.monotonic()
    register.rename(source, tmp_path / "target")
    assert (tmp_path / "target" / "a.txt").read_bytes() == b"x" and not source.exists()
    if __import__("os").name == "nt":
        assert time.monotonic() - started > 0.3, "Windows 上打开着的文件不能改名：是等读的一方关了才成的"


def test_rename_gives_up_when_the_reader_never_lets_go(tmp_path):
    if __import__("os").name != "nt":
        pytest.skip("只在 Windows 上打开着的文件不能改名")
    source = helpers.write_files(tmp_path / "source", {"a.txt": b"x"})
    with open(source / "a.txt", "rb"):
        with pytest.raises(PermissionError):
            register.rename(source, tmp_path / "target", tries=3)
    assert source.exists() and not (tmp_path / "target").exists()


# ---- 插件文件夹的哈希 ----

def test_plugin_hashes_follow_the_files(own_lab):
    whole, frozen = load.plugin_hash("demo"), load.frozen_hash("demo")
    assert whole == hashing.hash_tree(own_lab / "tests" / "plugins" / "demo")
    free = own_lab / "tests" / "plugins" / "demo" / "free.py"
    free.write_bytes(free.read_bytes() + b"# x\n")
    assert load.plugin_hash("demo") != whole and load.frozen_hash("demo") == frozen
    assert load.stale() == [] or load.stale() == ["demo"]
    load.load()
    assert load.stale() == [], "刚 import 的就是现在的代码"
    free.write_bytes(free.read_bytes() + b"# y\n")
    assert load.stale() == ["demo"], "import 之后代码又变了：值守该重启了"


def test_verify_item_is_called_again_for_ref_inputs_only(lab, data, tmp_path, monkeypatch):
    source = helpers.make_folder(tmp_path / "outside")
    ref = actions.register("report", "outside", source=source, storage="ref", note="n")
    copy = actions.register("report", "inside", source=helpers.make_folder(tmp_path / "inside"), note="n")
    made = helpers.experiment(value={"poll": "never"}, extra=[ref["id"], copy["id"]])
    start.start(made)
    real, calls = verify.verify_item, []
    monkeypatch.setattr(verify, "verify_item", lambda item_id: calls.append(item_id) or real(item_id))
    start.poll(made)
    assert calls == [ref["id"]], "每次调用里，只记位置的先再核一次；复制进来的不用"


# ---- 一样输入是什么时候登记的、这一轮是什么时候开的，插件都看得到 ----

def test_a_plugin_can_see_when_an_input_was_registered_and_when_the_round_opened(lab, data, monkeypatch):
    """判据这类输入要在看到结果之前写定：冻结文件拿登记的时间和这一轮开的时间比。"""
    import dataclasses

    made = helpers.experiment()
    start.start(made)
    kind, plugin = call.find("demo.echo")
    seen = {}

    def peek(given):
        seen.update(registered=given.input_info("setting").time, opened=given.round.opened)

    monkeypatch.setattr(call, "find", lambda type_name: (dataclasses.replace(kind, poll=peek), plugin))
    assert call.call("demo.echo", "poll", made).ok
    status = view.view(made)
    assert seen == {"registered": lookup.get(status.frozen["setting"][0]["id"])["time"], "opened": status.rounds[-1].opened}
    assert seen["registered"] <= seen["opened"], "输入一定是在这一轮开之前登记的"
