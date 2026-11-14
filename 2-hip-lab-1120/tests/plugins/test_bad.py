"""坏插件的七样，核心每一样都扛得住。"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import pytest

from stemlab.contract import Refused, layout
from stemlab.desk.core import check, start, watch
from stemlab.experiments import reader, view
from stemlab.registry import lookup
from tests import helpers
from tests.guard import scan

BAD = helpers.REPO / "tests" / "plugins" / "bad"


# ---- 1 检查里往记录写：被拒，记录里不多一条 ----

def test_1_writing_from_check_is_refused(lab, data):
    made = helpers.experiment("bad.check_writes")
    before = helpers.snapshot(data)
    with pytest.raises(Refused, match="只读"):
        start.start(made)
    assert helpers.snapshot(data) == before and view.view(made).state == "new"


# ---- 2 交一样产物表里没有的产物，或者种类不符：发布的第 1 步拒绝，记成问题 ----

def test_2_undeclared_or_wrong_kind_outputs_are_refused_at_step_1(lab, data):
    made = helpers.experiment("bad.wrong_output")
    start.start(made), start.poll(made)
    texts = [problem["error"] for problem in view.view(made).rounds[0].problems]
    assert "产物表里没有 'nothing'" in texts[0] and "种类不符" in texts[1]
    assert lookup.by_origin(made) == [] and (layout.work_dir(made) / "undeclared" / "a.txt").exists()


# ---- 3 交一批条件没写全的点：发布的第 2 步拒绝，说出缺哪一项 ----

def test_3_incomplete_points_are_refused_at_step_2_naming_what_is_missing(lab, data):
    made = helpers.experiment("bad.incomplete_points")
    start.start(made), start.poll(made)
    status = view.view(made)
    text = status.rounds[0].problems[0]["error"]
    assert "不符合 points 的格式" in text and "第 2 个点（'p2'）" in text and "['bw']" in text, text
    assert status.rounds[0].outputs == {} and lookup.find("points") == []
    assert (layout.work_dir(made) / "points" / "points.jsonl").exists(), "文件留在原地"


# ---- 4 动作里抛错：记成问题，不往外抛，别的实验照常 ----

def test_4_an_action_that_raises_is_a_problem_and_nothing_more(lab, data):
    crashing, fine = helpers.experiment("bad.raises"), helpers.experiment()
    start.start(crashing), start.start(fine)
    seen = watch.once()
    assert seen[crashing].startswith("插件出错") and seen[fine] == "看过了"
    assert view.view(crashing).state == "running" and len(view.view(crashing).rounds[0].problems) == 1
    assert view.view(fine).state == "ended"


# ---- 5 启动到一半进程退出：实验停在启动中；值守下一遍记成启动失败 ----

def test_5_a_start_that_dies_halfway_is_closed_as_start_failed_by_the_watch(lab, data):
    made = helpers.experiment("bad.exits")
    worker = helpers.spawn_worker("start", made)
    (data / "go").write_bytes(b"")
    worker.communicate(timeout=120)
    assert worker.returncode == 3, "做启动的进程在插件的启动里退出了"
    status = view.view(made)
    assert status.state == "starting" and status.tasks["only"].state == "queued", "实验停在启动中"
    assert reader.verify(made) == []

    assert watch.once() == {made: "看过了"}
    status = view.view(made)
    assert status.state == "ended" and status.rounds[0].result == "start_failed"
    assert status.rounds[0].calls[0]["ok"] is False and "进程不在了" in status.rounds[0].calls[0]["error"]
    assert [e["entry"] for e in reader.read(made)][-2:] == ["called", "round_closed"] and reader.verify(made) == []
    assert watch.once() == {}


# ---- 6 源码里直接打开 data/ 下的文件，或 import 挂点的子模块：报出是哪个文件哪一行 ----

def test_6_source_scans_report_file_and_line():
    hits = scan.scan(BAD, helpers.REPO, scan.strings_matching(scan.DATA_WORDS))
    assert sorted({(hit.file, hit.line) for hit in hits}) == [
        ("tests/plugins/bad/oversteps.py", 11), ("tests/plugins/bad/oversteps.py", 13)]
    hits = scan.scan(BAD, helpers.REPO, scan.mentions("register_output"))
    assert [(hit.file, hit.line) for hit in hits] == [("tests/plugins/bad/oversteps.py", 17)]


RULES_FOR_TEST_PLUGINS = """\
[importlinter]
root_packages =
    stemlab
    tests

[importlinter:contract:2]
name = 2 插件只经挂点
type = forbidden
source_modules =
    {source}
forbidden_modules =
    stemlab.contract
    stemlab.registry
    stemlab.experiments
    stemlab.desk
    stemlab.board
allow_indirect_imports = True

[importlinter:contract:3]
name = 3 插件只用挂点的门面
type = forbidden
source_modules =
    {source}
forbidden_modules =
    stemlab.hooks.handle
    stemlab.hooks.call
    stemlab.hooks.publish
    stemlab.hooks.load
    stemlab.hooks.entry
    stemlab.hooks.local
    stemlab.hooks.remote
allow_indirect_imports = True
"""


def test_6_import_rules_report_file_and_line(tmp_path):
    config = tmp_path / "bad.importlinter"
    config.write_text(RULES_FOR_TEST_PLUGINS.format(source="tests.plugins.bad"), encoding="utf-8")
    ok, output = check.lint_imports(str(config))
    assert not ok and "2 插件只经挂点 BROKEN" in output and "3 插件只用挂点的门面 BROKEN" in output
    assert "tests.plugins.bad.oversteps -> stemlab.hooks.handle (l.5)" in output
    assert "tests.plugins.bad.oversteps -> stemlab.hooks.publish (l.6)" in output
    assert "tests.plugins.bad.oversteps -> stemlab.registry.register (l.7)" in output

    config.write_text(RULES_FOR_TEST_PLUGINS.format(source="tests.plugins.demo"), encoding="utf-8")
    ok, output = check.lint_imports(str(config))
    assert ok, "示范插件照规矩来，同样两条规则是过的：\n" + output


# ---- 7 把自由的部分整个换一份写法，接口不变：已有实验的核对和新的实验全部照过 ----

RUN = """\
import json, sys
from stemlab.desk.core import actions, check, code_state, start
from stemlab.experiments import view
from stemlab.registry import lookup
item = actions.register("setting", sys.argv[1], value={"tasks": ["a", "b"]}, note="换写法的测试")
made = actions.new("demo.echo")
actions.fill(made, "setting", item["id"])
assert start.start(made).ok
start.poll(made)
status = view.view(made)
print(json.dumps({"experiment": made, "state": status.state, "result": status.rounds[0].result,
                  "provenance": status.rounds[0].provenance, "problems": status.rounds[0].problems,
                  "summary": json.loads((lookup.content(lookup.by_origin(made, 1)[0]["id"]) / "summary.json").read_bytes()),
                  "verify": check.verify_all(contents=True), "frozen_ok": code_state.frozen_ok() == []}))
"""


def run_in(repo, data, name: str) -> dict:
    """在仓库拷贝里起一个新进程跑一个实验：跑的就是拷贝里的代码。"""
    env = {key: value for key, value in os.environ.items() if key != "STEMLAB_REPO"}
    env.update(STEMLAB_DATA=str(data), STEMLAB_PLUGINS="tests.plugins", PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    done = subprocess.run([sys.executable, "-c", RUN, name], cwd=repo, env=env, capture_output=True, timeout=300)
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    return json.loads(done.stdout.decode("utf-8").strip().splitlines()[-1])


def test_7_rewriting_the_free_part_changes_nothing_that_others_depend_on(own_lab, data):
    before = run_in(own_lab, data, "before-rewrite")
    assert (before["state"], before["result"], before["verify"]) == ("ended", "done", [])
    assert before["provenance"]["plugin_dirty"] is False and "rewritten" not in before["summary"]

    shutil.copy(helpers.REPO / "tests" / "plugins" / "demo_rewritten.py", own_lab / "tests" / "plugins" / "demo" / "free.py")
    after = run_in(own_lab, data, "after-rewrite")
    assert (after["state"], after["result"], after["problems"]) == ("ended", "done", [])
    assert after["summary"] == {"rewritten": True, "tasks": ["a", "b"]}, "跑的确实是换过的那一份"
    assert after["verify"] == [], "已有实验的核对照过"
    assert after["frozen_ok"] is True, "冻结的文件一个没动"
    assert after["provenance"]["plugin_dirty"] is True, "来历里写明插件不干净"
    assert after["provenance"]["plugin_hash"] != before["provenance"]["plugin_hash"]
    assert after["provenance"]["plugin_frozen"] == before["provenance"]["plugin_frozen"], "冻结文件的哈希没变"
    assert after["provenance"]["frozen"] == before["provenance"]["frozen"]
    assert reader.verify(before["experiment"]) == [] and reader.verify(after["experiment"]) == []
    assert b"REWRITTEN = True" in layout.plugin_diff(after["experiment"], 1).read_bytes()
