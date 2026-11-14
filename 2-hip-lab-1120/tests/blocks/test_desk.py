"""操作台核心：你的每个动作都是“查状态表、记、叫、记结果”，断在哪一步都留下读得懂的记录。"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time

import pytest

from stemlab.contract import Refused, chain, hashing, layout
from stemlab.contract.entries import ROUND_PROVENANCE
from stemlab.desk.core import actions, backup, check, locks, query, start, watch
from stemlab.experiments import reader, view
from stemlab.hooks import load
from stemlab.registry import lookup, verify
from tests import helpers
from tests.conftest import git


def record_bytes(made: str) -> bytes:
    return layout.record_file(made).read_bytes()


def run_to_the_end(made: str, passes: int = 5) -> None:
    start.start(made)
    for _ in range(passes):
        if start.poll(made) is None:
            break


# ---- 1 登记、新建、填、启动、值守、看：用示范插件走通一遍 ----

def test_walk_through_with_the_demo_plugin(lab, data):
    item = actions.register("setting", "echo-setting", value={"scale": 2, "tasks": ["a", "b"]}, note="示范设定")
    made = actions.new("demo.echo", note="走通一遍", tags=["示范"])
    assert (item["id"], made) == ("R0001", "E0001") and view.required(made) == ["setting"]
    actions.fill(made, "setting", "R0001")
    assert view.required(made) == [] and view.view(made).state == "new"

    result = start.start(made)
    assert result.ok and view.view(made).state == "running"
    assert {name: task.state for name, task in view.view(made).tasks.items()} == {"a": "queued", "b": "queued"}

    assert watch.once() == {"E0001": "看过了"}
    status = view.view(made)
    assert status.state == "ended" and status.rounds[0].result == "done"
    assert {name: (task.state, task.outcome) for name, task in status.tasks.items()} == {
        "a": ("done", "finished"), "b": ("done", "finished")}
    assert watch.once() == {}, "结束了的实验不用再看"

    produced = lookup.by_origin(made, 1)
    assert [p["name"] for p in produced] == ["E0001.report"] and produced[0]["id"] == "R0002"
    assert status.rounds[0].outputs == {"report": {"item": "R0002", "hash": produced[0]["hash"]}}
    folder = lookup.content("R0002")
    assert folder == data / "experiments" / "E0001" / "rounds" / "1" / "outputs" / "report"
    assert json.loads((folder / "summary.json").read_bytes())["scale"] == 2
    assert verify.verify_item("R0002") == produced[0]["hash"]
    with pytest.raises(PermissionError):
        (folder / "summary.json").write_bytes(b"x")         # 发布后的产物只读

    assert [e["entry"] for e in reader.read(made)] == [
        "created", "filled", "frozen", "round_opened", "task", "task", "called",
        "task", "task", "task", "task", "output", "provenance", "round_closed"]
    assert reader.verify(made) == [] and check.verify_all(contents=True) == []
    assert status.frozen["setting"] == [{k: item[k] for k in ("id", "kind", "name", "version", "hash", "origin", "bone_id")}]
    assert status.register_head == {"seq": 1, "this": item["this"]}, "存定时记下登记链当时的链头"

    provenance = status.rounds[0].provenance
    assert set(provenance) == set(ROUND_PROVENANCE)
    assert provenance["commit"] == git(lab, "rev-parse", "HEAD").strip() and provenance["clean"] is True
    assert (provenance["plugin"], provenance["plugin_dirty"], provenance["contract"]) == ("demo", False, 1)
    assert provenance["frozen"] == hashing.hash_file(lab / "FROZEN")
    assert provenance["lock"] == hashing.hash_file(lab / "uv.lock")
    assert not layout.plugin_diff(made, 1).exists(), "插件干净就没有差异要存"
    assert status.rounds[0].extra == [{"source": "plugin", "info": {"solver": "demo 1.0"}, "time": status.rounds[0].extra[0]["time"]}]


# ---- 2 启动被拒：说出原因，记录里什么都没多 ----

def refused(made: str, data, word: str, **how) -> str:
    before = helpers.snapshot(data)
    with pytest.raises(Refused) as caught:
        start.start(made, **how)
    assert word in str(caught.value), str(caught.value)
    assert helpers.snapshot(data) == before, "前五步只检查，什么都不写"
    return str(caught.value)


def test_start_is_refused_when_an_input_is_missing(lab, data):
    made = actions.new("demo.echo")
    assert "['setting']" in refused(made, data, "还缺")


def test_start_is_refused_when_an_input_is_of_the_wrong_kind(lab, data, tmp_path):
    from stemlab.experiments import log

    report = actions.register("report", "a-report", source=helpers.make_folder(tmp_path / "rep"), note="n")
    made = actions.new("demo.echo")
    with pytest.raises(Refused, match="收的是"):
        actions.fill(made, "setting", report["id"])                 # 填的时候就拦一次
    log.append(made, {"entry": "filled", "input": "setting", "items": [report["id"]]})     # 绕过去，启动时还要再拦
    assert report["id"] in refused(made, data, "收的是")


def test_start_is_refused_when_a_registered_thing_was_changed(lab, data, tmp_path):
    source = helpers.make_folder(tmp_path / "outside")
    ref = actions.register("report", "outside-report", source=source, storage="ref", note="只记位置")
    made = helpers.experiment(extra=[ref["id"]])
    (source / "summary.json").write_bytes(b'{"changed": true}\n')
    message = refused(made, data, "不一致")
    assert "extra" in message and ref["id"] in message and "outside-report" in message, "说出是哪一样"


def test_start_is_refused_when_the_plugin_check_fails(lab, data):
    assert "设定里少了 scale" in refused(helpers.experiment(value={"check": "设定里少了 scale"}), data, "检查没过")
    assert "ValueError" in refused(helpers.experiment(value={"check": "raise"}), data, "检查出错")


def test_start_is_refused_when_frozen_does_not_match(own_lab, data):
    made = helpers.experiment()
    path = own_lab / "stemlab" / "contract" / "kinds.py"
    path.write_bytes(path.read_bytes() + b"# touched\n")
    assert "stemlab/contract/kinds.py" in refused(made, data, "FROZEN 清单对不上"), "说出是哪个文件"
    git(own_lab, "commit", "-q", "-am", "改了固定的文件却没重新生成清单")
    refused(made, data, "FROZEN 清单对不上")

    frozen_plugin_file = own_lab / "tests" / "plugins" / "demo" / "plugin.py"
    git(own_lab, "checkout", "-q", "HEAD~1", "--", "stemlab/contract/kinds.py")
    frozen_plugin_file.write_bytes(frozen_plugin_file.read_bytes() + b"# touched\n")
    assert "tests/plugins/demo/plugin.py" in refused(made, data, "FROZEN 清单对不上"), "插件的冻结文件有改动也不行"


def test_start_is_refused_when_the_core_is_not_committed(own_lab, data, monkeypatch):
    from stemlab.desk.core import code_state

    made = helpers.experiment()
    path = own_lab / "stemlab" / "hooks" / "call.py"
    path.write_bytes(path.read_bytes() + b"# touched\n")
    code_state.freeze()                                             # 清单对得上了，但改动还没提交
    assert code_state.frozen_ok() == []
    message = refused(made, data, "没提交的改动")
    assert "stemlab/hooks/call.py" in message and "FROZEN" in message, "说出是哪个文件"
    git(own_lab, "commit", "-q", "-am", "照规矩：清单和它锁着的文件一起提交")
    assert start.start(made).ok


def test_start_is_refused_in_a_repo_without_commits(own_lab, data):
    made = helpers.experiment()
    shutil.rmtree(own_lab / ".git", onexc=lambda function, path, error: (__import__("os").chmod(path, 0o700), function(path)))
    refused(made, data, "git")


def test_start_is_refused_when_the_plugin_cannot_be_loaded_or_the_state_forbids(lab, data):
    from stemlab.experiments import log
    from tests.contract import samples

    made = log.create("broken.thing", {"inputs": samples.INPUTS, "outputs": samples.OUTPUTS, "outcomes": samples.OUTCOMES})
    assert "装不上" in refused(made, data, "用不了")
    with pytest.raises(Refused, match="没有实验"):
        start.start("E0099")
    running = helpers.experiment(value={"poll": "never"})
    start.start(running)
    refused(running, data, "运行中")
    with pytest.raises(Refused, match="用不了"):
        actions.new("nothing.at_all")


# ---- 3 插件不干净：能启动，来历里写着，差异存下了 ----

def test_a_dirty_plugin_can_start_and_its_diff_is_kept(own_lab, data):
    free = own_lab / "tests" / "plugins" / "demo" / "free.py"
    free.write_bytes(free.read_bytes() + b"\nEXPERIMENTAL = 42\n")
    (own_lab / "tests" / "plugins" / "demo" / "brand_new.py").write_bytes(b"NEW_FILE = 1\n")
    made = helpers.experiment()
    assert start.start(made).ok, "插件自由的部分带着没提交的改动可以启动"
    provenance = view.view(made).rounds[0].provenance
    assert provenance["plugin_dirty"] is True and provenance["clean"] is True, "来历里写明插件不干净；核心是干净的"
    diff = layout.plugin_diff(made, 1).read_bytes()
    assert b"+EXPERIMENTAL = 42" in diff and b"free.py" in diff, "改过的文件的差异存下了"
    assert b"+NEW_FILE = 1" in diff and b"brand_new.py" in diff, "新加的文件也在里面"

    clean = helpers.experiment()
    git(own_lab, "add", "-A")
    git(own_lab, "commit", "-q", "-m", "提交插件的改动")
    assert start.start(clean).ok
    later = view.view(clean).rounds[0].provenance
    assert later["plugin_dirty"] is False and not layout.plugin_diff(clean, 1).exists()
    assert later["plugin_hash"] == provenance["plugin_hash"], "文件夹的内容没变，哈希就一样"
    assert later["plugin_frozen"] == provenance["plugin_frozen"] and later["commit"] != provenance["commit"]


# ---- 4 存定的哈希就是核对时算的那一次，没有算第二次 ----

def test_the_frozen_hash_is_the_one_computed_while_verifying(lab, data, tmp_path, monkeypatch):
    report = actions.register("report", "a-report", source=helpers.make_folder(tmp_path / "rep"), note="n")
    made = helpers.experiment(extra=[report["id"]])
    real, calls = verify.verify_item, []

    def counting(item_id):
        calls.append(item_id)
        real(item_id)
        return ("a" if item_id == report["id"] else "b") * 64

    monkeypatch.setattr(verify, "verify_item", counting)
    assert start.start(made).ok
    frozen = view.view(made).frozen
    assert sorted(calls) == sorted([report["id"], frozen["setting"][0]["id"]]), "每样输入只核对一次、只算一次哈希"
    assert frozen["extra"][0]["hash"] == "a" * 64 and frozen["setting"][0]["hash"] == "b" * 64, "存定的就是核对时算出的那一个"


# ---- 6 两处同时启动同一个实验：插件的启动只被叫一次 ----

def test_two_processes_starting_the_same_experiment(lab, data):
    made = helpers.experiment(value={"tasks": ["a", "b", "c"], "poll": "never"})
    workers = [helpers.spawn_worker("start", made) for _ in range(2)]
    go = data / "go"
    time.sleep(1.0)
    go.write_bytes(b"")
    said = sorted(worker.communicate(timeout=120)[0].decode("utf-8").split()[0] for worker in workers)
    assert said == ["refused", "started"], "一处启动成了，另一处被拒"
    assert len(helpers.entries_of(made, "round_opened")) == 1 and len(helpers.entries_of(made, "frozen")) == 1
    assert len(helpers.entries_of(made, "called")) == 1
    assert [e["task"] for e in helpers.entries_of(made, "task")] == ["a", "b", "c"], "插件的启动只被叫了一次"
    assert reader.verify(made) == []


# ---- 7 停止没停成：状态还是运行中；再停一次能成 ----

def test_a_stop_that_fails_leaves_it_running_and_can_be_retried(lab, data):
    made = helpers.experiment(value={"tasks": ["a", "b"], "poll": "never", "stop": "raise_once"})
    start.start(made)
    start.poll(made)
    first = start.stop(made)
    status = view.view(made)
    assert not first.ok and "停止没停成" in first.error
    assert status.state == "running" and status.rounds[0].result is None, "状态只在结果上变：没停成就还是运行中"
    assert [p["error"] for p in status.rounds[0].problems] == ["RuntimeError: 示范：停止没停成"], "多一条问题"
    assert "Traceback" in status.rounds[0].problems[0]["raw"]
    assert helpers.entries_of(made, "called")[-1]["action"] == "start", "没停成不记 called"

    second = start.stop(made)
    status = view.view(made)
    assert second.ok and status.state == "ended" and status.rounds[0].result == "stopped"
    assert {task.state for task in status.tasks.values()} == {"stopped"}
    assert [e["entry"] for e in reader.read(made)][-2:] == ["called", "round_closed"]
    with pytest.raises(Refused):
        start.stop(made)                                            # 已经结束，不能再停


def test_a_type_without_stop_cannot_be_stopped(lab, data):
    made = helpers.experiment("demo.quiet", value={"poll": "never"})
    start.start(made)
    before = record_bytes(made)
    with pytest.raises(Refused, match="没有写停止"):
        start.stop(made)
    assert record_bytes(made) == before


def test_stop_and_restart_resumes_what_was_not_finished(lab, data):
    """没有暂停：停止之后再启动，新的一轮只重排没做完的任务，效果就是暂停再继续。"""
    made = helpers.experiment(value={"tasks": ["a", "b"], "polls": 2})
    start.start(made)
    start.poll(made)
    assert start.stop(made).ok
    assert start.start(made).ok
    assert view.view(made).rounds[1].rerun == ["a", "b"]
    start.poll(made), start.poll(made)
    status = view.view(made)
    assert status.rounds[1].result == "done" and {task.state for task in status.tasks.values()} == {"done"}


# ---- 8 再启动：只重排该重排的任务；一个都没有且结局是做完时被拒 ----

def test_restart_reruns_only_what_should_be_rerun(lab, data):
    # 每个任务在第 1、2、3、4 轮各是什么结局（示范插件按轮号取）
    outcomes = {"b": ["env", "finished"], "c": ["diverged", "diverged", "diverged", "finished"], "d": ["misfit"]}
    made = helpers.experiment(value={"tasks": ["a", "b", "c", "d"], "outcomes": outcomes})
    run_to_the_end(made)
    first = view.view(made)
    assert first.rounds[0].result == "done", "做完不等于每个任务都成功"
    assert {n: (t.state, t.outcome) for n, t in first.tasks.items()} == {
        "a": ("done", "finished"), "b": ("failed", "env"), "c": ("failed", "diverged"), "d": ("done", "misfit")}
    old_record, old_product = record_bytes(made), lookup.by_origin(made, 1)[0]

    run_to_the_end(made)                                            # 第 2 轮：只重排可重试的 b
    second = view.view(made)
    assert second.rounds[1].rerun == ["b"]
    assert sorted(second.rounds[1].tasks) == ["b"] and second.tasks["b"].outcome == "finished"
    assert second.tasks["a"].round == 1 and second.tasks["c"].round == 1, "别的任务留着第 1 轮的结果"
    assert record_bytes(made).startswith(old_record), "旧轮的记录一条不动"
    assert verify.verify_item(old_product["id"]) == old_product["hash"], "旧轮的产物一条不动"
    products = lookup.find(name=f"{made}.report")
    assert [(p["version"], p["origin"]["round"]) for p in products] == [(1, 1), (2, 2)], "新一轮的产物是新的一版"

    data_before = helpers.snapshot(data)
    with pytest.raises(Refused, match="已经做完"):
        start.start(made)                                           # 没有可以重排的了
    with pytest.raises(Refused, match="点名的任务不能重排"):
        start.start(made, named=["a"])                              # 已经算出来了的不能点名
    with pytest.raises(Refused, match="点名的任务不能重排"):
        start.start(made, named=["c", "nothing"])
    assert helpers.snapshot(data) == data_before

    start.start(made, named=["c"])                                  # 待查的，点了名才重排
    assert view.view(made).rounds[2].rerun == ["c"]
    start.poll(made)
    assert view.view(made).tasks["c"].outcome == "diverged", "这一轮它还是不收敛"
    start.start(made, named=["c"])
    start.poll(made)
    assert view.view(made).tasks["c"].outcome == "finished"
    assert [one.number for one in view.rounds(made)] == [1, 2, 3, 4] and reader.verify(made) == []


def test_restart_is_refused_when_frozen_changed_since_the_last_round(own_lab, data):
    from stemlab.desk.core import code_state

    made = helpers.experiment(value={"outcomes": {"only": ["env", "finished"]}})
    run_to_the_end(made)
    path = own_lab / "stemlab" / "hooks" / "call.py"
    path.write_bytes(path.read_bytes() + b"# a fixed file changed between rounds\n")
    code_state.freeze()
    git(own_lab, "commit", "-q", "-am", "固定的代码变了")
    refused(made, data, "和上一轮不一样")
    assert start.start(actions.clone(made)).ok, "克隆出来的新实验可以跑"


# ---- 9 克隆：新实验的输入逐样相同，旧实验一条不变 ----

def test_clone(lab, data, tmp_path):
    report = actions.register("report", "a-report", source=helpers.make_folder(tmp_path / "rep"), note="n")
    made = helpers.experiment(extra=[report["id"]])
    run_to_the_end(made)
    before = record_bytes(made)
    copy = actions.clone(made, note="克隆出来的")
    assert record_bytes(made) == before, "旧实验一条不变"
    original, cloned = view.view(made), view.view(copy)
    assert cloned.state == "new" and cloned.clone_of == made and cloned.type == original.type
    assert cloned.filled == original.filled and cloned.note == "克隆出来的" and cloned.frozen is None
    run_to_the_end(copy)
    assert view.view(copy).frozen == original.frozen, "输入逐样相同"
    assert actions.clone(actions.new("demo.echo")) == "E0004", "没启动过的也能克隆"


# ---- 10 往上追 ----

def test_upstream_goes_back_to_what_came_from_outside(lab, data):
    first = helpers.experiment(value={"scale": 1})
    run_to_the_end(first)
    first_report = lookup.by_origin(first, 1)[0]
    second = helpers.experiment(value={"scale": 2}, extra=[first_report["id"]])
    run_to_the_end(second)
    second_report = lookup.by_origin(second, 1)[0]

    node = query.upstream(second_report["id"])
    assert (node["item"]["id"], node["experiment"], node["round"], node["type"]) == (second_report["id"], second, 1, "demo.echo")
    assert node["provenance"]["plugin"] == "demo" and node["extra"][0]["info"] == {"solver": "demo 1.0"}
    setting = node["inputs"]["setting"][0]
    assert setting["item"]["origin"]["from"] == "external" and set(setting) == {"item"}, "追到“外面拿来的”为止"
    earlier = node["inputs"]["extra"][0]
    assert (earlier["item"]["id"], earlier["experiment"], earlier["round"]) == (first_report["id"], first, 1)
    assert earlier["inputs"]["setting"][0]["item"]["content"] == {"scale": 1}
    with pytest.raises(Refused):
        query.upstream("R0099")


def test_downstream_under_case_and_same_bone(lab, data, tmp_path):
    source = helpers.write_files(tmp_path / "ct", {"scan.dcm": b"ct"})
    case = actions.register("bone_source", "femur042-ct", source=source, note="CT", bone_id="femur042", new_bone=True)
    direct = helpers.experiment(value={"bone_id": "femur042"}, extra=[case["id"]])
    run_to_the_end(direct)
    product = lookup.by_origin(direct, 1)[0]
    assert product["bone_id"] == "femur042", "产物从它的清单里拿到骨标识"
    indirect = helpers.experiment(extra=[product["id"]])
    run_to_the_end(indirect)
    further = lookup.by_origin(indirect, 1)[0]
    unrelated = helpers.setting("unrelated")
    actions.attach(unrelated["id"], case["id"])

    users = query.downstream(case["id"])
    assert [(u["experiment"], u["as"]) for u in users] == [(direct, ["extra"])]
    assert users[0]["products"][0]["item"]["id"] == product["id"]
    assert users[0]["products"][0]["users"][0]["experiment"] == indirect

    under = query.under_case(case["id"])
    assert [(row.get("experiment") or row["item"]["id"], row["why"]) for row in under] == [
        (direct, "直接用了"), (product["id"], "是它的产物"), (indirect, "经别的产物用了"),
        (further["id"], "是它的产物"), (unrelated["id"], "手动挂的")]
    actions.detach(unrelated["id"], case["id"])
    assert len(query.under_case(case["id"])) == 4

    bone = query.same_bone("femur042")
    assert [item["id"] for item in bone["items"]] == [case["id"], product["id"]]
    assert bone["experiments"] == [direct, indirect]


# ---- 11 值守开着，不点任何东西，任务自己走完；同一时刻只有一处在值守 ----

def test_the_watch_finishes_tasks_on_its_own_and_is_alone(lab, data):
    made = helpers.experiment("demo.sleep", value={"seconds": 1.0})
    assert start.start(made).ok and view.view(made).tasks["job"].state == "running"
    command = [sys.executable, "-m", "stemlab.desk.core.watch", "--interval", "0.2"]
    watcher = subprocess.Popen(command, cwd=helpers.REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        holder = helpers.wait_for(watch.status)
        assert holder["alive"] and holder["pid"] in helpers.family(watcher) and holder["doing"] == "watch"
        with pytest.raises(Refused, match="拿不到锁"):
            watch.once()                                            # 同一时刻只有一处在值守
        second = subprocess.run(command, cwd=helpers.REPO, capture_output=True, timeout=60)
        assert second.returncode == 1 and "被拒" in second.stdout.decode("utf-8", "replace")
        helpers.wait_for(lambda: view.view(made).state == "ended")
    finally:
        helpers.kill_tree(watcher)
    status = view.view(made)
    assert status.rounds[0].result == "done" and status.tasks["job"].outcome == "finished"
    assert lookup.by_origin(made, 1)[0]["name"] == f"{made}.report"
    assert watch.once() == {}, "值守的进程不在了，锁就放了"
    assert watch.status() is None or watch.status()["alive"] is False


def test_the_watch_restarts_its_inner_layer_when_plugin_code_changes(own_lab, data):
    """值守从不拿旧代码接着跑：插件的代码变了，里面那一层退出，外面用新的代码重新起一个。"""
    import psutil

    made = helpers.experiment(value={"poll": "never"})
    start.start(made)
    command = [sys.executable, "-m", "stemlab.desk.core.watch", "--interval", "0.2"]
    watcher = subprocess.Popen(command, cwd=helpers.REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        outer = helpers.wait_for(watch.status)["pid"]
        helpers.wait_for(lambda: view.view(made).tasks["only"].state == "running")      # 里面那一层已经装上插件、看过一遍了
        first = helpers.wait_for(lambda: helpers.family(watcher) - {watcher.pid, outer})
        free = own_lab / "tests" / "plugins" / "demo" / "free.py"
        free.write_bytes(free.read_bytes() + b"\n# changed while the watch was running\n")
        helpers.wait_for(lambda: not (first & helpers.family(watcher)) and helpers.family(watcher) - {watcher.pid, outer})
        assert watch.status()["pid"] == outer, "外面那一层没换，值守的锁一直拿着"
        helpers.wait_for(lambda: [e for e in view.view(made).rounds[0].extra if e["source"] == "code"])

        inner = helpers.family(watcher) - {watcher.pid, outer}
        assert inner, "里面那一层在跑"
        psutil.Process(outer).kill()                                                    # 只结束外面那一层
        helpers.wait_for(lambda: not any(psutil.pid_exists(pid) for pid in inner))
    finally:
        helpers.kill_tree(watcher)
    load._AT_IMPORT.clear()                 # 这个测试进程自己装着的也是改之前的代码；装作重新起了一个
    assert watch.once() == {made: "看过了"}, "外面那一层没了，里面那一层也自己退出了，锁放了"


def test_a_pass_skips_what_is_busy_and_survives_what_goes_wrong(lab, data):
    busy = helpers.experiment(value={"poll": "never"})
    crashing = helpers.experiment("bad.raises")
    fine = helpers.experiment()
    for made in (busy, crashing, fine):
        start.start(made)
    worker = helpers.spawn_worker("hold", "busy", busy)
    try:
        assert worker.stdout.readline().strip() == b"held"
        holder = locks.holder(layout.busy_lock(busy))
        assert holder["alive"] and holder["pid"] in helpers.family(worker) and holder["doing"] == "测试里拿着"
        seen = watch.once()
    finally:
        helpers.kill_tree(worker)
    assert seen[busy].startswith("跳过") and seen[crashing].startswith("插件出错") and seen[fine] == "看过了"
    assert view.view(fine).state == "ended", "一个实验出什么事都不耽误别的"
    assert locks.holder(layout.busy_lock(busy))["alive"] is False, "持锁的进程被结束了，记录还在，但看得出它不在了"
    assert locks.holder(layout.busy_lock(fine)) is None, "正常放锁之后不留记录"


def test_a_start_in_progress_is_left_alone_by_the_watch(lab, data):
    """启动还在进行（做启动的进程拿着 busy）：值守跳过它，不把它当成启动失败。"""
    made = helpers.experiment(value={"start_seconds": 4, "poll": "never"})
    code = "import sys; from stemlab.desk.core import start; start.start(sys.argv[1])"
    starter = subprocess.Popen([sys.executable, "-c", code, made], cwd=helpers.REPO)
    try:
        helpers.wait_for(lambda: helpers.entries_of(made, "round_opened"))
        seen = watch.once()
        assert seen[made].startswith("跳过") and view.view(made).rounds[0].result is None
        with pytest.raises(Refused, match="拿不到锁"):
            start.poll(made, wait=False)
        assert starter.wait(timeout=60) == 0
    finally:
        helpers.kill_tree(starter)
    assert view.view(made).rounds[0].calls[0]["ok"] is True and watch.once() == {made: "看过了"}


def test_a_broken_record_does_not_stop_the_pass(lab, data):
    broken, fine = helpers.experiment(value={"poll": "never"}), helpers.experiment()
    start.start(broken), start.start(fine)
    with open(layout.record_file(broken), "ab") as stream:
        stream.write(b"this line is not json\n")
    seen = watch.once()
    assert seen[broken].startswith("出错") and seen[fine] == "看过了", "一个实验的记录坏了，不耽误看别的"
    assert view.view(fine).rounds[0].result == "done"
    assert any(broken in text for text in check.verify_all())


def test_saying_done_and_then_failing_does_not_close_the_round(lab, data):
    made = helpers.experiment(value={"poll": "finish_then_raise"})
    start.start(made)
    result = start.poll(made)
    assert not result.ok and view.view(made).rounds[0].result is None, "动作出错了，它说的做完不算数"
    assert len(view.view(made).rounds[0].problems) == 1


# ---- 12 删掉登记的最后两条：check_backup 报出来 ----

def test_check_backup_notices_a_deleted_tail(lab, data):
    made = helpers.experiment()
    run_to_the_end(made)
    for n in range(3):
        helpers.setting(f"later-{n}")
    assert check.check_backup() == [], "还没备份过，没有可比的"
    assert "还没备份过" in check.last_backup()
    layout.backup_file().write_bytes(hashing.canonical({"format": 1, "time": chain.stamp(__import__("datetime").datetime.now().astimezone()),
                                                        "machine": "linux", "heads": backup.heads()}) + b"\n")
    assert check.check_backup() == [] and "推到 linux" in check.last_backup()
    helpers.setting("after-the-backup")
    assert check.check_backup() == [], "备份之后又追加的不算问题"

    register = layout.register_file()
    lines = register.read_bytes().split(b"\n")[:-1]
    register.write_bytes(b"".join(line + b"\n" for line in lines[:-3]))        # 连同备份过的最后两条一起删掉
    assert verify.verify_register() == [], "哈希链自己查不出末尾被删"
    problems = check.check_backup()
    assert len(problems) == 1 and "登记链" in problems[0] and "延长" in problems[0]

    record = layout.record_file(made)
    kept = record.read_bytes().split(b"\n")[:-1]
    record.write_bytes(b"".join(line + b"\n" for line in kept[:-1]))
    assert any(made in text for text in check.check_backup())


# ---- 检查入口里数据这一边的几项 ----

def test_verify_all_and_reconcile_all(lab, data, tmp_path):
    source = helpers.make_folder(tmp_path / "outside")
    ref = actions.register("report", "outside", source=source, storage="ref", note="n")
    made = helpers.experiment(extra=[ref["id"]])
    run_to_the_end(made)
    assert check.verify_all() == [] and check.verify_all(contents=True) == [] and check.reconcile_all() == []
    (source / "summary.json").write_bytes(b"changed")
    assert len(check.verify_all()) == 1 and "outside" in check.verify_all()[0], "只记位置的每次都核"
    stored = lookup.content(lookup.by_origin(made, 1)[0]["id"]) / "summary.json"
    __import__("os").chmod(stored, 0o600)
    stored.write_bytes(b"tampered")
    assert len(check.verify_all()) == 1, "复制进来的和产物，要全核才重算"
    assert len(check.verify_all(contents=True)) == 2
    record = layout.record_file(made)
    record.write_bytes(record.read_bytes().replace(b'"round":1', b'"round":2', 1))
    assert any("被改过" in text for text in check.verify_all())


# ---- 不叫插件的那些动作 ----

def test_fill_rules(lab, data, tmp_path):
    report = actions.register("report", "a-report", source=helpers.make_folder(tmp_path / "rep"), note="n")
    one, two = helpers.setting("one"), helpers.setting("two")
    made = actions.new("demo.echo")
    before = record_bytes(made)
    for name, items, word in [("nothing", [one["id"]], "没有叫 nothing 的输入"), ("setting", [report["id"]], "收的是"),
                              ("setting", ["R0099"], "登记里没有"), ("setting", [one["id"], two["id"]], "只收一份")]:
        with pytest.raises(Refused, match=word):
            actions.fill(made, name, items)
    assert record_bytes(made) == before
    actions.fill(made, "setting", one["id"])
    actions.fill(made, "setting", [two["id"]])
    actions.fill(made, "extra", [report["id"]])
    assert view.view(made).filled == {"setting": [two["id"]], "extra": [report["id"]]}
    actions.fill(made, "extra", [])
    assert view.view(made).filled == {"setting": [two["id"]]}
    start.start(made)
    with pytest.raises(Refused, match="不能做 fill"):
        actions.fill(made, "setting", one["id"])


def test_fill_new_note_and_tag(lab, data):
    made = actions.new("demo.echo", tags=["a"])
    item = actions.fill_new(made, "setting", "setting", "fresh-setting", value={"scale": 3}, note="登记并填")
    assert view.view(made).filled == {"setting": [item["id"]]} and lookup.content(item["id"]) == {"scale": 3}
    with pytest.raises(Refused, match="不收 objective"):
        actions.fill_new(made, "setting", "objective", "x", value={}, note="n")
    assert len(lookup.find()) == 1, "被拒的时候没有白登记一样东西"
    actions.note(made, "先看看")
    actions.tag(made, add=["重要"], remove=["a"])
    status = view.view(made)
    assert [n["text"] for n in status.notes] == ["先看看"] and status.tags == ["重要"]
    run_to_the_end(made)
    actions.note(made, "结束之后也能备注")
    with pytest.raises(Refused):
        actions.note("E0099", "没有这个实验")


def test_hand_written_points_are_completed_with_defaults_before_they_are_stored(lab, data, tmp_path):
    from stemlab.contract.formats import points

    defaults = actions.register("setting", "load-default", value={"load": "walk", "bw": 700}, note="条件默认")
    hand = tmp_path / "hand.jsonl"
    hand.write_bytes(b'{"name": "p1", "bone_id": "femur042", "design": {"length": 120}, "reason": "hand"}\r\n'
                     b'{"name": "p2", "bone_id": "femur042", "design": {"length": 121}, "conditions": {"load": "stair"}, "reason": "hand"}\n')
    item = actions.register("points", "hand-points", source=hand, defaults=defaults["id"], note="手写的两个点")
    rows = points.read_points(lookup.content(item["id"]))
    assert [row["conditions"] for row in rows] == [{"load": "walk", "bw": 700}, {"load": "stair", "bw": 700}]
    assert all(row["hash"] == points.point_hash(row) for row in rows)
    assert defaults["id"] in item["origin"]["note"] and item["origin"]["from"] == "external"
    assert verify.verify_item(item["id"]) == item["hash"]
    with pytest.raises(Refused, match="不符合 points 的格式"):
        actions.register("points", "no-defaults", source=_points_folder(tmp_path, hand), note="没给条件默认")
    with pytest.raises(Refused, match="只有一批点"):
        actions.register("report", "x", source=tmp_path, defaults=defaults["id"], note="n")
    with pytest.raises(Refused, match="条件默认要是一份设定"):
        actions.register("points", "x", source=hand, defaults=item["id"], note="n")


def _points_folder(tmp_path, hand):
    """把手写的那两行原样放进一个带清单的文件夹：条件没补全，登记不上。"""
    from stemlab.contract.formats.manifest import make_manifest, write_manifest

    folder = tmp_path / "raw-points"
    folder.mkdir()
    (folder / "points.jsonl").write_bytes(hand.read_bytes().replace(b"\r\n", b"\n"))
    write_manifest(folder, make_manifest("points", ["points.jsonl"], count=2, design_keys=["length"], condition_keys=["bw", "load"]))
    return folder


def test_write_manifest_in_place_then_register_by_reference(lab, data, tmp_path):
    source = helpers.write_files(tmp_path / "big-ct", {"Series 1/IM 0001.dcm": b"slice"})
    with pytest.raises(Refused, match="不替你往原处写清单"):
        actions.register("bone_source", "big", source=source, storage="ref", note="n", bone_id="femur042", new_bone=True)
    written = actions.write_manifest(source, "bone_source", bone_id="femur042")
    assert written["files"] == ["Series 1/IM 0001.dcm"] and written["bone_id"] == "femur042"
    item = actions.register("bone_source", "big", source=source, storage="ref", note="n", new_bone=True)
    assert item["storage"] == "ref" and item["bone_id"] == "femur042" and not (data / "registry" / "store").exists()
    with pytest.raises(Refused):
        actions.write_manifest(source, "points")


def test_charts_come_from_the_plugin_and_never_touch_the_record(lab, data):
    made = helpers.experiment(value={"tasks": ["a", "b"]})
    assert query.charts(made) == [{"name": "tasks", "form": "table", "label": "各任务"}]
    run_to_the_end(made)
    before = helpers.snapshot(data)
    assert query.chart(made, "tasks")["rows"] == [["a", "done", "finished"], ["b", "done", "finished"]]
    with pytest.raises(Refused):
        query.chart(made, "nothing")
    assert helpers.snapshot(data) == before
    assert query.charts(helpers.experiment("demo.sleep")) == []


# ---- 这一轮中途插件的代码变了 ----

def new_process() -> None:
    """装作重新起了一个进程：它装上插件时看到的是盘上现在的代码。"""
    load._AT_IMPORT.clear()


def rewrite_free_code(repo) -> None:
    free = repo / "tests" / "plugins" / "demo" / "free.py"
    free.write_bytes(free.read_bytes() + b"\n# rewritten while a round was running\n")


def code_changes(made: str) -> list[dict]:
    return [extra["info"] for extra in view.view(made).rounds[-1].extra if extra["source"] == "code"]


def test_free_plugin_code_changing_mid_round_is_recorded(own_lab, data):
    made = helpers.experiment(value={"polls": 4})
    start.start(made)
    assert start.poll(made).ok
    rewrite_free_code(own_lab)

    # 这个进程里装着的还是旧代码，也就是这一轮记下的那一份：照旧跑，没有什么要记的
    assert start.poll(made).ok and code_changes(made) == []
    assert load.stale() == ["demo"], "值守这时会重启里面那一层"

    new_process()
    assert start.poll(made).ok and start.poll(made).ok
    status = view.view(made)
    changes = code_changes(made)
    assert len(changes) == 1, "变了一次就记一次，不是每次轮询都记"
    assert changes[0]["plugin_hash"] == load.plugin_hash("demo") != status.rounds[0].provenance["plugin_hash"]
    assert changes[0]["plugin_dirty"] is True and changes[0]["commit"] == status.rounds[0].provenance["commit"]
    diff = layout.plugin_diff(made, 1, changed_to=changes[0]["plugin_hash"]).read_bytes()
    assert b"+# rewritten while a round was running" in diff, "变成了什么样，差异存下了，找得回来"
    assert status.state == "ended", "自由的代码变了，记进来历，接着跑"


def test_a_process_holding_old_plugin_code_is_turned_away_and_nothing_is_recorded(own_lab, data):
    """记录说该跑的是新代码，这个进程里装着的却是旧的：不跑，什么都不记，由调用方重新起进程。"""
    made = helpers.experiment(value={"poll": "never"})
    start.start(made)
    old = load.imported("demo")
    rewrite_free_code(own_lab)
    new_process()
    assert start.poll(made).ok and len(code_changes(made)) == 1     # 另一个新起的进程看到了新代码，记下了变化
    load._AT_IMPORT["demo"] = old                                   # 而这个进程里装着的还是旧的
    before = helpers.snapshot(data)
    with pytest.raises(load.Stale):
        start.poll(made)
    with pytest.raises(load.Stale):
        start.stop(made)
    assert helpers.snapshot(data) == before
    assert watch.once()[made].startswith("跳过"), "值守这一遍跳过它，下一遍它先重启"


def test_start_is_refused_when_the_plugin_changed_after_this_process_loaded_it(own_lab, data):
    """记下的插件哈希必须是真正在跑的那一份：装上之后盘上又变了，就不启动。"""
    made = helpers.experiment()                                     # 到这里插件已经装上了
    rewrite_free_code(own_lab)
    assert "再启动一次" in refused(made, data, "又变了")
    new_process()
    assert start.start(made).ok
    assert view.view(made).rounds[0].provenance["plugin_hash"] == load.plugin_hash("demo") == load.imported("demo")


def test_a_stale_diff_from_a_start_that_died_does_not_survive_a_clean_start(lab, data):
    made = helpers.experiment()
    stale = layout.plugin_diff(made, 1)
    helpers.write_files(stale.parent, {"plugin.diff": b"left by a start that was killed before it opened the round"})
    assert start.start(made).ok
    assert view.view(made).rounds[0].provenance["plugin_dirty"] is False and not stale.exists()


def test_frozen_plugin_code_changing_mid_round_stops_the_round_from_going_on(own_lab, data):
    made = helpers.experiment(value={"polls": 2})
    start.start(made)
    frozen_file = own_lab / "tests" / "plugins" / "demo" / "plugin.py"
    original = frozen_file.read_bytes()
    frozen_file.write_bytes(original + b"\n# a frozen file changed while a round was running\n")
    result = start.poll(made)
    assert not result.ok and "冻结文件" in result.error
    assert view.view(made).state == "running" and len(view.view(made).rounds[0].problems) == 1
    assert not start.stop(made).ok, "停止也要叫插件，一样不行"
    frozen_file.write_bytes(original)
    assert start.poll(made).ok and start.poll(made).ok, "改回去就能接着跑"
    assert view.view(made).state == "ended"
