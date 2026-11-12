"""地基的测试。每个测试用一个临时文件夹当 home，不碰真的 experiments。"""
import json
import re
import shutil
from pathlib import Path

import pytest

from stemlab.console import Desk, main
from stemlab.record import FINISHED, NOT_STARTED, PAUSED, RUNNING, STOPPED, RecordError

REPO = Path(__file__).resolve().parent.parent

BOOM = '''
from stemlab.plugins import Plugin, Setting

class Boom(Plugin):
    name = "boom"
    version = "0"
    category = "会出错的"
    settings = []
    def start(self, ctx):
        raise RuntimeError("故意的")

PLUGIN = Boom()
'''


@pytest.fixture
def home(tmp_path):
    shutil.copytree(REPO / "plugins" / "demo", tmp_path / "plugins" / "demo")
    return tmp_path


def run_to_end(desk, exp_id, limit=10):
    for _ in range(limit):
        if desk.store.open(exp_id).view()["status"] != RUNNING:
            return
        desk.refresh(exp_id)
    raise AssertionError("示范插件没有在预期的次数内结束")


def test_ids_are_unique_and_never_reused(home):
    """编号不重复；文件夹被删了，编号也不再用。"""
    desk = Desk(home)
    a, b = desk.new("demo"), desk.new("demo")
    assert (a, b) == ("E0001", "E0002")
    shutil.rmtree(home / "experiments" / "E0002")
    assert desk.new("demo") == "E0003"


def test_record_only_grows_and_tampering_is_found(home):
    """记录只追加：每条带序号和上一条的哈希；改一行或删一行能查出来。"""
    desk = Desk(home)
    exp_id = desk.new("demo", note="原来的说明")
    desk.note(exp_id, "一条备注")
    exp = desk.store.open(exp_id)
    assert [e["seq"] for e in exp.events()] == [1, 2, 3]
    assert exp.check() == []

    original = exp.record_path.read_bytes()
    exp.record_path.write_bytes(original.replace("原来的说明".encode("utf-8"), "改过的说明".encode("utf-8")))
    assert any("接不上" in line for line in exp.check())

    lines = original.split(b"\n")
    exp.record_path.write_bytes(b"\n".join(lines[:1] + lines[2:]))
    assert exp.check() != []


def test_setting_changes_before_start_all_stay_in_record(home):
    """启动前可以改设置；改之前的那一次也留在记录里。"""
    desk = Desk(home)
    exp_id = desk.new("demo")
    desk.set(exp_id, "点", value=["a"], source="手填")
    desk.set(exp_id, "点", value=["a", "b"], source="手填")
    exp = desk.store.open(exp_id)
    filled = [e["data"]["content"]["value"] for e in exp.events() if e["type"] == "填设置"]
    assert filled == [["a"], ["a", "b"]]
    assert exp.view()["settings"]["点"]["content"]["value"] == ["a", "b"]


def test_start_stores_the_setting_actually_used(home, tmp_path):
    """启动时把原文复制进实验并算哈希；之后原文件改了，实验里那份不变。"""
    src = tmp_path / "我的点.json"
    src.write_text('["a", "b"]', encoding="utf-8")
    desk = Desk(home)
    exp_id = desk.new("demo")
    desk.set(exp_id, "点", file=str(src), source="自己写的", when="2026-11-12")
    desk.start(exp_id)

    src.write_text('["完全不同"]', encoding="utf-8")
    exp = desk.store.open(exp_id)
    s = exp.view()["settings"]["点"]
    stored = exp.folder / s["content"]["stored"]
    assert s["frozen"] is True
    assert json.loads(stored.read_text(encoding="utf-8")) == ["a", "b"]
    assert len(s["content"]["sha256"]) == 64
    assert s["source"] == {"kind": "其他来源", "from": "自己写的", "when": "2026-11-12"}
    assert set(exp.view()["tasks"]) == {"a", "b"}


def test_settings_cannot_change_after_start(home):
    """启动之后设置不能改，要改就新建一个实验。"""
    desk = Desk(home)
    exp_id = desk.new("demo")
    desk.set(exp_id, "点", value=["a"])
    desk.start(exp_id)
    with pytest.raises(RecordError, match="新建一个实验"):
        desk.set(exp_id, "点", value=["b"])
    assert desk.store.open(exp_id).view()["settings"]["点"]["content"]["value"] == ["a"]


def test_start_refused_while_a_required_setting_is_missing(home):
    """必填的设置没填就不能启动，并说出缺哪一项；可以不填的不拦。"""
    desk = Desk(home)
    exp_id = desk.new("demo")
    with pytest.raises(RecordError, match="点"):
        desk.start(exp_id)
    assert desk.store.open(exp_id).view()["status"] == NOT_STARTED
    desk.set(exp_id, "点", value=["a"])
    assert desk.start(exp_id) is True


def test_unknown_setting_name_is_refused(home):
    """插件没报过的设置名不收。"""
    desk = Desk(home)
    exp_id = desk.new("demo")
    with pytest.raises(RecordError, match="没有叫"):
        desk.set(exp_id, "不存在的设置", value=1)


def test_demo_goes_through_and_all_nine_items_are_recorded(home):
    """走通一遍：新建、填设置、启动、任务状态变化、产出，九项都在。"""
    desk = Desk(home)
    exp_id = desk.new("demo", note="走通一遍", tags=["试"])
    desk.set(exp_id, "点", value=["a", "b"], source="手填")
    desk.start(exp_id)
    run_to_end(desk, exp_id)

    exp = desk.store.open(exp_id)
    v = exp.view()
    assert v["id"] == exp_id
    assert v["plugin"]["name"] == "demo" and v["plugin"]["category"] == "示范"
    assert len(v["plugin"]["files_sha256"]) == 64
    assert v["note"] == "走通一遍" and v["tags"] == ["试"]
    assert v["frozen"] and v["settings"]["点"]["content"]["value"] == ["a", "b"]
    assert [o["op"] for o in v["operations"]] == ["新建", "启动"]
    assert [h["state"] for h in v["tasks"]["a"]["history"]] == ["排队", "运行", "完成"]
    assert v["tasks"]["a"]["machine"]
    out = v["outputs"][0]
    assert out["name"] == "点清单" and len(out["sha256"]) == 64
    assert json.loads((exp.folder / out["path"]).read_text(encoding="utf-8")) == ["a", "b"]
    assert v["problems"] == []
    assert v["provenance"]["machine"] and v["provenance"]["plugin_at_start"]["name"] == "demo"
    assert "示范插件说" in v["provenance"]
    assert v["status"] == FINISHED
    assert exp.check() == []

    text = desk.show(exp_id)
    for label in ("1 编号", "2 插件", "3 说明", "4 标签", "5 实际设置", "6 操作", "7 任务", "8 产出", "9 问题"):
        assert label in text


def test_a_failed_task_is_recorded_and_the_others_go_on(home):
    """一个任务失败：记成问题，别的任务照常完成。"""
    desk = Desk(home)
    exp_id = desk.new("demo")
    desk.set(exp_id, "点", value=["a", "b", "c"])
    desk.set(exp_id, "出错的点", value=["b"])
    desk.start(exp_id)
    run_to_end(desk, exp_id)
    v = desk.store.open(exp_id).view()
    assert {k: t["state"] for k, t in v["tasks"].items()} == {"a": "完成", "b": "失败", "c": "完成"}
    assert [p["task"] for p in v["problems"]] == ["b"]
    assert v["problems"][0]["raw"]


def test_plugin_crash_becomes_a_problem_and_other_experiments_go_on(home):
    """插件自己出错：记成那个实验的问题，操作台不崩，别的实验照常走。"""
    (home / "plugins" / "boom").mkdir()
    (home / "plugins" / "boom" / "plugin.py").write_text(BOOM, encoding="utf-8")
    desk = Desk(home)
    bad = desk.new("boom")
    good = desk.new("demo")
    desk.set(good, "点", value=["a"])
    assert desk.start(bad) is False
    assert desk.start(good) is True
    desk.refresh()
    desk.refresh()
    problems = desk.store.open(bad).view()["problems"]
    assert "故意的" in problems[0]["error"] and "Traceback" in problems[0]["raw"]
    assert desk.store.open(good).view()["status"] == FINISHED


def test_plugin_reporting_an_unknown_task_state_becomes_a_problem(home):
    """插件报了五种以外的任务状态：不收，记成问题。"""
    code = BOOM.replace('raise RuntimeError("故意的")', 'ctx.task("x", "乱写的状态")')
    (home / "plugins" / "boom").mkdir()
    (home / "plugins" / "boom" / "plugin.py").write_text(code, encoding="utf-8")
    desk = Desk(home)
    exp_id = desk.new("boom")
    assert desk.start(exp_id) is False
    v = desk.store.open(exp_id).view()
    assert v["tasks"] == {} and "任务状态只能是" in v["problems"][0]["error"]


def test_a_plugin_that_fails_to_load_does_not_block_the_others(home):
    """一个插件装不上：报出来，别的插件照常能用。"""
    (home / "plugins" / "broken").mkdir()
    (home / "plugins" / "broken" / "plugin.py").write_text("这不是 Python (", encoding="utf-8")
    desk = Desk(home)
    assert list(desk.plugins) == ["demo"]
    assert len(desk.plugin_errors) == 1 and "broken" in desk.plugin_errors[0]
    assert "装不上" in desk.list_plugins()


def test_output_of_one_experiment_can_be_the_setting_of_another(home):
    """一个实验的产出给另一个当设置：来路记的是那个实验的编号。"""
    desk = Desk(home)
    first = desk.new("demo")
    desk.set(first, "点", value=["a", "b", "c"])
    desk.set(first, "出错的点", value=["c"])
    desk.start(first)
    run_to_end(desk, first)

    second = desk.new("demo")
    desk.set(second, "点", from_exp=first, output="点清单")
    desk.start(second)
    run_to_end(desk, second)
    v = desk.store.open(second).view()
    assert v["settings"]["点"]["source"] == {"kind": "实验产出", "experiment": first, "output": "点清单"}
    assert v["settings"]["点"]["content"]["sha256"] == desk.store.open(first).view()["outputs"][0]["sha256"]
    assert set(v["tasks"]) == {"a", "b"}
    assert f"实验 {first} 的产出" in desk.show(second)


def test_start_refused_when_an_upstream_output_was_changed(home):
    """用作设置的产出，文件后来被改了：哈希对不上，不启动。"""
    desk = Desk(home)
    first = desk.new("demo")
    desk.set(first, "点", value=["a"])
    desk.start(first)
    run_to_end(desk, first)
    path, _ = desk.store.open(first).output_path("点清单")

    second = desk.new("demo")
    desk.set(second, "点", from_exp=first, output="点清单")
    path.write_text('["被人改了"]', encoding="utf-8")
    with pytest.raises(RecordError, match="对不上"):
        desk.start(second)
    assert desk.store.open(second).view()["status"] == NOT_STARTED


def test_experiments_stay_readable_after_their_plugin_is_removed(home):
    """拔掉插件：旧实验照样能看、能列，只是不能操作。"""
    desk = Desk(home)
    exp_id = desk.new("demo", note="拔插件之前建的")
    desk.set(exp_id, "点", value=["a"])
    desk.start(exp_id)
    shutil.rmtree(home / "plugins" / "demo")

    desk = Desk(home)
    assert desk.plugins == {}
    assert "拔插件之前建的" in desk.show(exp_id)
    assert exp_id in desk.list()
    assert desk.refresh() == []
    with pytest.raises(RecordError, match="只能看"):
        desk.stop(exp_id)


def test_pause_resume_stop_retry_are_each_recorded(home):
    """暂停、继续、停止、重试各记一条操作；暂停时任务不往前走；重试后做完。"""
    desk = Desk(home)
    exp_id = desk.new("demo")
    desk.set(exp_id, "点", value=["a", "b"])
    desk.start(exp_id)
    desk.refresh(exp_id)

    desk.pause(exp_id)
    assert desk.store.open(exp_id).view()["status"] == PAUSED
    assert desk.refresh(exp_id) == []
    assert desk.store.open(exp_id).view()["tasks"]["a"]["state"] == "运行"
    with pytest.raises(RecordError, match="不能暂停"):
        desk.pause(exp_id)

    desk.resume(exp_id)
    desk.stop(exp_id)
    v = desk.store.open(exp_id).view()
    assert v["status"] == STOPPED and v["tasks"]["a"]["state"] == "停止"

    desk.retry(exp_id)
    run_to_end(desk, exp_id)
    v = desk.store.open(exp_id).view()
    assert [o["op"] for o in v["operations"]] == ["新建", "启动", "暂停", "继续", "停止", "重试"]
    assert all(o["time"] for o in v["operations"])
    assert v["status"] == FINISHED and v["tasks"]["a"]["state"] == "完成"


def test_notes_and_tags_can_be_added_any_time(home):
    """说明之外的备注和标签随时能加，启动之后也能。"""
    desk = Desk(home)
    exp_id = desk.new("demo", tags=["甲"])
    desk.set(exp_id, "点", value=["a"])
    desk.start(exp_id)
    desk.note(exp_id, "启动之后写的")
    desk.tag(exp_id, add=["乙"], remove=["甲"])
    v = desk.store.open(exp_id).view()
    assert v["notes"][0]["text"] == "启动之后写的" and v["tags"] == ["乙"]


def test_base_code_names_no_plugin_and_no_category():
    """地基不认识具体的操作：三个地基文件里没有任何类别的词，也没有插件的名字。"""
    words = re.compile("重建|FEA|代理|优化|有限元|demo|示范", re.IGNORECASE)
    for file in sorted((REPO / "stemlab").glob("*.py")):
        hits = [line for line in file.read_text(encoding="utf-8").splitlines() if words.search(line)]
        assert hits == [], f"{file.name} 里出现了：{hits}"


def test_command_line_walkthrough(home, capsys):
    """命令行走一遍，中文命令和英文命令都能用。"""
    h = ["--home", str(home)]
    assert main(h + ["new", "demo", "--note", "命令行走一遍", "--tag", "试"]) == 0
    exp_id = capsys.readouterr().out.strip()
    assert exp_id == "E0001"
    assert main(h + ["设置", exp_id, "点", "--value", '["a", "b"]', "--source", "手填"]) == 0
    assert main(h + ["启动", exp_id]) == 0
    assert main(h + ["set", exp_id, "点", "--value", "[1]"]) == 2
    assert "新建一个实验" in capsys.readouterr().err
    for _ in range(3):
        assert main(h + ["refresh"]) == 0
    capsys.readouterr()
    assert main(h + ["看", exp_id]) == 0
    shown = capsys.readouterr().out
    assert "状态：已结束" in shown and "来路：其他来源，手填" in shown and "点清单" in shown
    assert main(h + ["list"]) == 0 and exp_id in capsys.readouterr().out
    assert main(h + ["check"]) == 0 and "记录完好" in capsys.readouterr().out
    assert main(h + ["plugins"]) == 0 and "必填" in capsys.readouterr().out
    assert main(h + ["看", "E9999"]) == 2
