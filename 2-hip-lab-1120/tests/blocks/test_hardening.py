"""独立审查查出来的问题，一条一条钉住：每条测试对应一处当时确实会出事的地方。"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from stemlab.contract import Refused, hashing, layout, plugin_api
from stemlab.contract.formats import points
from stemlab.desk.core import actions, check, query, start, watch
from stemlab.experiments import log, reader, view
from stemlab.hooks import call, publish
from stemlab.registry import lookup
from tests import helpers
from tests.blocks.test_registry import make_junction


def problems(made: str) -> list[dict]:
    return view.view(made).rounds[-1].problems


# ---- 连着出现的报错是按轮数的 ----

def test_a_streak_of_errors_does_not_leak_into_the_next_round(lab, data):
    """上一轮连着出错的次数留在值守的进程里；换了一轮，同样的报错要重新记，不能闷着不记。"""
    made = helpers.experiment(value={"poll": "raise"})
    start.start(made)
    for _ in range(3):
        start.poll(made)
    assert len(problems(made)) == 1
    # 别的进程（比如你在命令行里）把这一轮停了，又启动了新的一轮；值守的进程不知道
    log.append(made, {"entry": "called", "round": 1, "action": "stop", "ok": True, "error": None})
    log.append(made, {"entry": "round_closed", "round": 1, "result": "stopped", "reason": "在别处停的"})
    assert start.start(made).ok
    assert not start.poll(made).ok
    found = problems(made)
    assert len(found) == 1 and found[0]["count"] == 1, "新的一轮里，这个报错记下了，而且是从头数的"
    assert view.view(made).rounds[0].problems[0]["count"] == 1


# ---- 给插件的是抄出来的一份 ----

def test_a_plugin_cannot_corrupt_what_the_core_keeps_in_memory(lab, data, monkeypatch):
    made = helpers.experiment(value={"poll": "never"})
    start.start(made)
    kind, plugin = call.find("demo.echo")

    def vandal(handle):
        handle.round.provenance.clear()
        handle.input_info("setting").origin.clear()
        handle.input("setting").clear()

    thief = plugin_api.Kind(name=kind.name, inputs=kind.inputs, outputs=kind.outputs, outcomes=kind.outcomes,
                            check=kind.check, start=kind.start, poll=vandal)
    real = call.find
    monkeypatch.setattr(call, "find", lambda type_name: (thief, plugin))
    assert call.call("demo.echo", "poll", made).ok
    monkeypatch.setattr(call, "find", real)
    status = view.view(made)
    assert status.rounds[0].provenance["plugin"] == "demo" and status.frozen["setting"][0]["origin"]["from"] == "external"
    assert start.poll(made).ok, "下一次调用照常"


# ---- 机器清单坏了 ----

def test_a_broken_machine_list_is_a_reason_or_a_problem_never_a_crash(own_lab, data):
    running = helpers.experiment(value={"poll": "never"})
    start.start(running)
    waiting = helpers.experiment()
    (own_lab / "machines.json").write_bytes(b"{ this is not json")
    before = helpers.snapshot(data)
    with pytest.raises(Refused, match="检查没过"):
        start.start(waiting)
    assert helpers.snapshot(data) == before
    result = start.poll(running)
    assert not result.ok and len(problems(running)) == 1, "正在跑的那个：记成它的一条问题"
    (own_lab / "machines.json").write_bytes(b'{"format": 1, "machines": []}')
    assert "desk" in start.poll(running).error, "清单读得出来但不合格，也是一样"


# ---- 交上来的文件夹里有交接点 ----

def test_an_output_with_a_junction_inside_is_refused_and_nothing_outside_is_touched(lab, data, tmp_path):
    made = helpers.experiment(value={"poll": "never"})
    start.start(made)
    shared = helpers.write_files(tmp_path / "shared", {"big.bin": b"lives outside data/"})
    folder = helpers.make_folder(layout.work_dir(made) / "linked", files={"a.txt": b"1"})
    make_junction(folder / "elsewhere", shared)
    assert publish.publish(made, 1, "report", folder) is None
    assert "链接或交接点" in problems(made)[0]["error"]
    assert folder.exists() and not layout.outputs_dir(made, 1).exists() and lookup.by_origin(made) == []
    assert os.access(shared / "big.bin", os.W_OK), "外面那个文件没有被设成只读"


# ---- 启动正在核对输入的时候，输入被换了 ----

def test_an_input_swapped_while_start_is_checking_stops_the_start(lab, data, monkeypatch):
    first, second = helpers.setting("first", {"tasks": ["a"]}), helpers.setting("second", {"tasks": ["b"]})
    made = actions.new("demo.echo")
    actions.fill(made, "setting", first["id"])
    real = call.call_check

    def sneaky(type_name, experiment, table, frozen, info):
        log.append(experiment, {"entry": "filled", "input": "setting", "items": [second["id"]]})    # 绕过 busy 的另一处
        return real(type_name, experiment, table, frozen, info)

    monkeypatch.setattr(call, "call_check", sneaky)
    with pytest.raises(Refused, match="又被填过"):
        start.start(made)
    status = view.view(made)
    assert status.frozen is None and status.rounds == [], "没有拿核对过的旧输入去存定、去开轮"
    monkeypatch.setattr(call, "call_check", real)
    assert start.start(made).ok and view.view(made).frozen["setting"][0]["id"] == second["id"]


def test_fill_waits_for_whoever_is_working_on_the_experiment(lab, data, monkeypatch):
    made = actions.new("demo.echo")
    item = helpers.setting("one")
    monkeypatch.setattr(actions, "WAIT", 0.3)
    holder = helpers.spawn_worker("hold", "busy", made)
    try:
        assert holder.stdout.readline().strip() == b"held"
        before = helpers.snapshot(data)
        with pytest.raises(Refused, match="拿不到锁"):
            actions.fill(made, "setting", item["id"])               # 别处正在动它（比如正在启动）：不插进去
        with pytest.raises(Refused, match="拿不到锁"):
            actions.fill_new(made, "setting", "setting", "fresh", value={}, note="n")
        assert helpers.snapshot(data)[f"experiments/{made}/record.jsonl"] == before[f"experiments/{made}/record.jsonl"]
    finally:
        helpers.kill_tree(holder)
    actions.fill(made, "setting", item["id"])
    assert view.view(made).filled == {"setting": [item["id"]]}


def test_call_itself_turns_away_a_process_holding_other_code_than_the_record_says(lab, data):
    """最后一道关在叫插件的那一处：这个进程里装着的不是这一轮记下的那一份，就不叫。"""
    from stemlab.hooks import load

    made = helpers.experiment(value={"poll": "never"})
    start.start(made)
    load._AT_IMPORT["demo"] = "f" * 64
    before = helpers.snapshot(data)
    with pytest.raises(load.Stale):
        call.call("demo.echo", "poll", made)
    assert helpers.snapshot(data) == before, "没有叫插件，也没有记成这个实验的问题：这是进程的事，不是实验的事"


# ---- 一个 case 下面有什么：直接用了的就是直接用了 ----

def test_an_experiment_using_the_case_directly_is_labelled_so_however_it_is_reached(lab, data, tmp_path):
    source = helpers.write_files(tmp_path / "ct", {"scan.dcm": b"ct"})
    case = actions.register("bone_source", "femur042-ct", source=source, note="CT", bone_id="femur042", new_bone=True)
    first = helpers.experiment(extra=[case["id"]])
    start.start(first), start.poll(first)
    product = lookup.by_origin(first, 1)[0]
    both = helpers.experiment(extra=[case["id"], product["id"]])       # 既直接用了这个 case，又用了它的产物
    start.start(both), start.poll(both)
    labels = {row["experiment"]: row["why"] for row in query.under_case(case["id"]) if "experiment" in row}
    assert labels == {first: "直接用了", both: "直接用了"}


# ---- 编号不对、没有这个实验 ----

@pytest.mark.parametrize("bad", ["E1", "../E0001", "", "R0001", "E0001/x"])
def test_a_malformed_experiment_id_is_refused(lab, data, bad):
    for action in (start.start, start.stop, start.poll, lambda e: actions.fill(e, "setting", [])):
        with pytest.raises(Refused, match="没有实验"):
            action(bad)


def test_an_unknown_experiment_leaves_no_folder_behind(lab, data):
    helpers.experiment()
    for action in (start.start, start.stop, start.poll, lambda e: actions.fill(e, "setting", [])):
        with pytest.raises(Refused, match="没有实验"):
            action("E9999")
    assert not layout.experiment_dir("E9999").exists(), "没有的实验不该凭空多出一个文件夹"
    assert sorted(p.name for p in (data / "experiments").iterdir() if p.is_dir()) == ["E0001"]


# ---- 手写的一批点写得不对 ----

@pytest.mark.parametrize("line", [
    b'{"name": "p1", "design": {"length": 1}, "reason": "no bone id"}',
    b'{"name": "p1", "bone_id": "femur042", "design": {"length": 1}, "conditions": null, "reason": "x"}',
    b'{"name": "p1", "bone_id": "femur042", "design": [1, 2], "reason": "x"}',
    b'"just a string"',
])
def test_badly_written_points_are_refused_not_crashed_on(lab, data, tmp_path, line):
    defaults = helpers.setting("defaults", {"load": "walk"})
    hand = tmp_path / "hand.jsonl"
    hand.write_bytes(line + b"\n")
    before = helpers.snapshot(data)
    with pytest.raises(Refused):
        actions.register("points", "hand", source=hand, defaults=defaults["id"], note="手写的")
    with pytest.raises(Refused):
        actions.register("points", "hand", source=None, defaults=defaults["id"], note="没给文件")
    assert helpers.snapshot(data) == before


def test_write_points_names_what_is_wrong_instead_of_crashing(tmp_path):
    good = {"name": "p1", "bone_id": "femur042", "design": {"length": 1}, "conditions": {"load": "walk"}, "reason": "x"}
    for bad in ([dict(good, design=[1, 2])], [dict(good, conditions="walk")], ["not a point"],
                [dict(good, design={"length": float("nan")})], [good, dict(good, name="p2", design={1: 2})]):
        with pytest.raises(ValueError):
            points.write_points(tmp_path / "pts", bad)
    assert not (tmp_path / "pts").exists()


# ---- 检查的入口 ----

def test_check_reports_a_broken_record_instead_of_dying_on_it(lab, data):
    broken, fine = helpers.experiment(value={"poll": "never"}), helpers.experiment(value={"poll": "never"})
    start.start(broken), start.start(fine)
    with open(layout.record_file(broken), "ab") as stream:
        stream.write(b"{ this line is not json\n")
    helpers.write_files(layout.experiment_dir("E0003"), {"record.jsonl": b""})      # 新建到一半断掉留下的空记录
    with open(layout.issued_file(), "rb") as stream:
        assert stream.read().count(b"\n") == 2
    assert check.reconcile_all() == [], "对账跳过读不出来的，不死在上面"
    found = check.verify_chains()
    assert len(found) == 1 and broken in found[0] and "JSON" in found[0]
    assert check.verify_all() == found


def test_check_runs_from_the_command_line_on_damaged_data(lab, data):
    made = helpers.experiment(value={"poll": "never"})
    start.start(made)
    record = layout.record_file(made)
    record.write_bytes(record.read_bytes().replace(b'"round":1', b'"round":9', 1))
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env.pop("PYTHONUTF8", None)
    done = subprocess.run([sys.executable, "-m", "stemlab.desk.core.check", "--no-tests"], cwd=helpers.REPO, env=env,
                          capture_output=True, timeout=300)
    out = done.stdout.decode("utf-8")
    assert done.returncode == 1 and "[不过] data/ 的各条链" in out and made in out and "Traceback" not in out
    assert "对账" not in out, "链有问题的时候不对账：不往有问题的账上再写东西"


def test_check_notices_when_the_two_books_disagree(lab, data):
    done_one, done_two = helpers.experiment(), helpers.experiment()
    for made in (done_one, done_two):
        start.start(made), start.poll(made)
    assert check.verify_all() == []

    stray = helpers.make_folder(layout.output_dir(done_one, 1, "second"), files={"a.txt": b"moved but never registered"})
    found = check.verify_all()
    assert len(found) == 1 and done_one in found[0] and "没登记的东西" in found[0] and "second" in found[0]
    import shutil
    shutil.rmtree(stray)

    product = lookup.by_origin(done_two, 1)[0]
    folder = lookup.content(product["id"])
    for path in sorted(folder.rglob("*"), reverse=True):
        os.chmod(path, 0o700)
        path.unlink() if path.is_file() else path.rmdir()
    folder.rmdir()
    found = check.verify_all()
    assert len(found) == 1 and product["id"] in found[0] and "内容不见了" in found[0], "不用重算哈希也看得出内容没了"


def test_check_notices_a_registered_product_the_record_never_listed(lab, data):
    from stemlab.registry import register

    made = helpers.experiment()
    start.start(made), start.poll(made)
    place = helpers.make_folder(layout.output_dir(made, 1, "second"))
    register.register_output("report", f"{made}.second", layout.inside(place), hashing.hash_tree(place),
                             {"from": "product", "experiment": made, "round": 1, "output": "second"}, None)
    found = check.verify_all()
    assert len(found) == 1 and "登记里的是" in found[0] and "second" in found[0]


# ---- 对不上账不拦着收尾 ----

def test_a_reconcile_that_is_refused_does_not_stop_the_round_from_closing(lab, data, monkeypatch):
    made = helpers.experiment()
    start.start(made)

    def refuses(experiment):
        raise Refused("示范：这样产物登记不上")

    monkeypatch.setattr(publish, "reconcile", refuses)
    assert start.poll(made).ok
    status = view.view(made)
    assert status.rounds[0].result == "done", "这一轮照常收尾"
    assert any("对账没做完" in problem["error"] for problem in status.rounds[0].problems), "对不上账记成了问题"


# ---- 打印的时候不死在编码上 ----

def test_the_watch_prints_errors_the_console_encoding_cannot_hold(lab, data):
    made = helpers.experiment(value={"poll": "raise", "error_text": "应力超过 500 N/mm² ✓ �"})
    start.start(made)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="")
    env.pop("PYTHONUTF8", None)                         # 不靠外面设好的编码
    done = subprocess.run([sys.executable, "-m", "stemlab.desk.core.watch", "--once"], cwd=helpers.REPO, env=env,
                          capture_output=True, timeout=300)
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    assert "N/mm² ✓" in done.stdout.decode("utf-8") and len(problems(made)) == 1


# ---- 后面的轮里没有要重排的任务 ----

def test_a_later_round_with_nothing_to_rerun_does_not_queue_finished_tasks_again(lab, data):
    """rerun 是空的不等于“这是第一轮”：上一轮做不下去了，但任务都有了结果，新的一轮不该把它们再派一遍。"""
    # b 失败了、结局属于待查：第二轮手动排它重来（做完的 a 不许重排）；第三轮没点名，它就不重排
    made = helpers.experiment(value={"tasks": ["a", "b"], "polls": 1, "outcomes": {"b": ["diverged"]}})
    start.start(made), start.poll(made)
    assert view.view(made).rounds[0].result == "done"
    log.append(made, {"entry": "round_opened", "round": 2, "provenance": view.view(made).rounds[0].provenance,
                      "rerun": ["b"]})
    log.append(made, {"entry": "called", "round": 2, "action": "start", "ok": False, "error": "示范：这一轮没起来"})
    log.append(made, {"entry": "round_closed", "round": 2, "result": "start_failed", "reason": "示范：这一轮没起来"})
    assert start.start(made).ok
    third = view.view(made).rounds[2]
    assert third.rerun == [] and third.tasks == {}, "已经有结果的任务没有被再派一遍"
    assert reader.verify(made) == []
    assert json.loads(json.dumps(view.summary(made)["tasks"])) == {"done": 1, "failed": 1}, "两个任务还是第一轮的结果"
