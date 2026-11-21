"""经过操作台的测试：新建、填设置、启动、值守式的刷新、停止、重试，后台进程真的起起来。

用假归档和临时 home。地基的文件一个都不改，只是照操作台的用法去叫它。
"""
import csv
import io
import json
import time

import pytest

import fae_synth as SY
from fae_helpers import new_experiment, plugin_module, run_to_end, wait_gone, worker_pids
from stemlab.console import Desk
from stemlab.record import FINISHED, PAUSED, RUNNING, STOPPED

GOOD = ["syn_fric_0001", "syn_bond_0002", "syn_fail_0003"]


@pytest.fixture
def arch(tmp_path):
    folder = tmp_path / "arch"
    SY.write_archive(folder, "syn_fric_0001", SY.job_files("fric", seed=1))
    SY.write_archive(folder, "syn_bond_0002", SY.job_files("bond", seed=2))
    SY.write_archive(folder, "syn_fail_0003", SY.job_files("failed", seed=3))
    return folder


def labels(home, exp):
    text = (home / "experiments" / exp / "outputs" / "标签" / "标签.csv").read_text(encoding="utf-8")
    return {r["job_id"]: r for r in csv.DictReader(io.StringIO(text))}


def test_plugin_reports_its_four_things(home):
    desk = Desk(home)
    assert desk.plugin_errors == []
    (info,) = desk.plugin_info()
    assert (info["name"], info["category"]) == ("fea-archive-export", "FEA") and info["version"]
    assert [(s["name"], s["required"]) for s in info["settings"]] == [("归档", True), ("作业", True), ("导出哪些量", False)]
    assert [o["name"] for o in info["outputs"]] == ["标签", "界面场", "整体场", "说明"]
    assert info["hooks"] == ["启动", "报任务状态", "停止", "暂停", "继续", "重试"]


def test_whole_run_one_task_per_job_and_four_outputs(home, arch):
    desk = Desk(home)
    exp = new_experiment(desk, arch, GOOD, note="三个作业")
    assert desk.start(exp) is True
    first = desk.store.open(exp).view()
    assert first["status"] == RUNNING and list(first["tasks"]) == GOOD  # 每个作业一个任务，启动时都排上
    view = run_to_end(desk, exp)
    assert view["status"] == FINISHED and view["problems"] == []
    assert {k: t["state"] for k, t in view["tasks"].items()} == dict.fromkeys(GOOD, "完成")
    assert all(t["history"][0]["state"] == "排队" for t in view["tasks"].values())
    assert [o["name"] for o in view["outputs"]] == ["标签", "界面场", "整体场", "说明"]
    assert all(o["inside"] and len(o["sha256"]) == 64 for o in view["outputs"])
    out = home / "experiments" / exp / "outputs"
    assert sorted(p.name for p in (out / "界面场").iterdir()) == ["syn_fric_0001.npz"]
    assert sorted(p.name for p in (out / "整体场").iterdir()) == ["syn_bond_0002.npz", "syn_fric_0001.npz"]
    rows = labels(home, exp)
    assert sorted(rows) == sorted(GOOD) and rows["syn_fail_0003"]["status"] == "FAILED"
    doc = json.loads((out / "说明" / "说明.json").read_text(encoding="utf-8"))
    assert doc["结局"] == {"完成": 3, "失败": 0} and len(doc["每个作业"]) == 3
    assert "归档里本来就没有的" in (out / "说明" / "说明.md").read_text(encoding="utf-8")
    old = json.loads((out / "标签" / "标签说明.json").read_text(encoding="utf-8"))["旧表的列"]
    assert old["n_old_columns"] == 300 and all(c["exported"] or c["why_not"] for c in old["columns"])
    # 设置存定了：归档只记位置和哈希，没有复制进实验文件夹
    s = view["settings"]["归档"]["content"]
    assert s["kind"] == "位置" and len(s["sha256"]) == 64 and not (home / "experiments" / exp / "settings").exists()
    assert view["provenance"]["归档导出"]["作业数"] == 3
    assert desk.store.open(exp).check() == []
    for pid in worker_pids(home):
        assert wait_gone(pid)  # 后台进程做完自己退出


def test_broken_archives_become_problems_and_the_rest_go_on(home, arch):
    """一个归档被截断、一个作业根本没有归档：这两个记成问题，别的照常导出。"""
    SY.write_archive(arch, "syn_cut_0004", SY.job_files("fric", seed=4))
    p = arch / "syn_cut_0004.tar.xz"
    p.write_bytes(p.read_bytes()[: p.stat().st_size // 2])
    jobs = ["syn_cut_0004", "syn_fric_0001", "syn_gone_0005", "syn_bond_0002", "syn_fail_0003"]
    desk = Desk(home)
    exp = new_experiment(desk, arch, jobs)
    desk.start(exp)
    view = run_to_end(desk, exp)
    assert view["status"] == FINISHED
    states = {k: t["state"] for k, t in view["tasks"].items()}
    assert states == {"syn_cut_0004": "失败", "syn_fric_0001": "完成", "syn_gone_0005": "失败",
                      "syn_bond_0002": "完成", "syn_fail_0003": "完成"}
    problems = {p["task"]: p["error"] for p in view["problems"]}
    assert set(problems) == {"syn_cut_0004", "syn_gone_0005"}
    assert "哈希和清单对不上" in problems["syn_cut_0004"] and "不存在" in problems["syn_gone_0005"]
    assert all(p["raw"] for p in view["problems"])  # 原始报错也留着
    assert sorted(labels(home, exp)) == sorted(GOOD)
    out = home / "experiments" / exp / "outputs"
    assert sorted(p.name for p in (out / "整体场").iterdir()) == ["syn_bond_0002.npz", "syn_fric_0001.npz"]
    doc = json.loads((out / "说明" / "说明.json").read_text(encoding="utf-8"))
    assert [u["job_id"] for u in doc["归档读不了的作业"]] == ["syn_cut_0004", "syn_gone_0005"]
    assert doc["结局"] == {"完成": 3, "失败": 2}


def test_the_same_run_without_the_damage_has_no_problems(home, arch):
    """对照：同样的做法，归档不弄坏，就没有问题、没有失败。上一个测试里的问题确实是弄坏引起的。"""
    SY.write_archive(arch, "syn_cut_0004", SY.job_files("fric", seed=4))
    desk = Desk(home)
    exp = new_experiment(desk, arch, ["syn_cut_0004", "syn_fric_0001", "syn_bond_0002"])
    desk.start(exp)
    view = run_to_end(desk, exp)
    assert view["problems"] == [] and all(t["state"] == "完成" for t in view["tasks"].values())


def test_fix_the_archive_then_retry_redoes_only_the_failed_one(home, arch):
    desk = Desk(home)
    exp = new_experiment(desk, arch, ["syn_fric_0001", "syn_late_0006"])
    desk.start(exp)
    view = run_to_end(desk, exp)
    assert view["tasks"]["syn_late_0006"]["state"] == "失败"
    npz = home / "experiments" / exp / "outputs" / "整体场" / "syn_fric_0001.npz"
    stamp = npz.stat().st_mtime_ns
    SY.write_archive(arch, "syn_late_0006", SY.job_files("bond", seed=6))  # 归档后来补上了
    assert desk.retry(exp) is True
    view = run_to_end(desk, exp)
    assert view["status"] == FINISHED and all(t["state"] == "完成" for t in view["tasks"].values())
    assert [h["state"] for h in view["tasks"]["syn_late_0006"]["history"]][-2:] == ["排队", "完成"] or \
        [h["state"] for h in view["tasks"]["syn_late_0006"]["history"]][-3:] == ["排队", "运行", "完成"]
    assert npz.stat().st_mtime_ns == stamp  # 做完的没有重做
    assert sorted(labels(home, exp)) == ["syn_fric_0001", "syn_late_0006"]
    assert [o["name"] for o in view["outputs"]].count("标签") == 2  # 重试后产出重新登记了一次


def test_pause_holds_the_queue_and_resume_lets_it_finish(home, arch):
    desk = Desk(home)
    exp = new_experiment(desk, arch, GOOD)
    desk.start(exp)
    desk.pause(exp)
    time.sleep(2.0)  # 给后台进程足够的时间：它最多做完手上那一个
    assert desk.store.open(exp).view()["status"] == PAUSED
    assert not (home / "experiments" / exp / "plugin_state" / "done.json").exists()
    state_file = home / "experiments" / exp / "plugin_state" / "state.json"
    done_while_paused = len(json.loads(state_file.read_text(encoding="utf-8"))) if state_file.exists() else 0
    assert done_while_paused <= 1
    desk.resume(exp)
    view = run_to_end(desk, exp)
    assert view["status"] == FINISHED and all(t["state"] == "完成" for t in view["tasks"].values())


def test_stop_ends_the_background_process_and_retry_finishes_the_job(home, arch):
    pm = plugin_module()
    desk = Desk(home)
    exp = new_experiment(desk, arch, GOOD)
    desk.start(exp)
    desk.pause(exp)
    (pid,) = worker_pids(home)
    assert desk.stop(exp) is True
    assert not pm.pid_alive(pid)  # 停止之后后台进程确实不在了
    view = desk.store.open(exp).view()
    assert view["status"] == STOPPED and view["outputs"] == []
    states = [t["state"] for t in view["tasks"].values()]
    assert set(states) <= {"完成", "停止"} and "停止" in states
    assert desk.retry(exp) is True
    view = run_to_end(desk, exp)
    assert view["status"] == FINISHED and all(t["state"] == "完成" for t in view["tasks"].values())
    assert sorted(labels(home, exp)) == sorted(GOOD)


def test_background_process_that_dies_is_restarted_and_written_down(home, arch):
    pm = plugin_module()
    desk = Desk(home)
    exp = new_experiment(desk, arch, GOOD)
    desk.start(exp)
    (pid,) = worker_pids(home)
    pm.pid_kill(pid)  # 刚起来就被结束，一个作业都来不及做
    assert wait_gone(pid)
    view = run_to_end(desk, exp)
    assert view["status"] == FINISHED and all(t["state"] == "完成" for t in view["tasks"].values())
    assert [p["error"] for p in view["problems"]] == ["后台进程中途不在了，重新起一个（第 2 次起）"]


def test_background_process_that_keeps_dying_is_given_up_and_can_be_retried(home, arch):
    pm = plugin_module()
    desk = Desk(home)
    exp = new_experiment(desk, arch, GOOD)
    desk.start(exp)
    (pid,) = worker_pids(home)
    pm.pid_kill(pid)
    assert wait_gone(pid)
    plan = home / "experiments" / exp / "plugin_state" / "plan.json"
    good_plan = plan.read_text(encoding="utf-8")
    plan.write_text("这不是 json", encoding="utf-8")  # 之后每次起来都会马上出错退出
    view = run_to_end(desk, exp)
    assert view["status"] == FINISHED and view["outputs"] == []
    assert all(t["state"] == "失败" for t in view["tasks"].values())
    errors = [p["error"] for p in view["problems"]]
    assert len(errors) == 3 and errors[-1].startswith(f"后台进程起了 {pm.MAX_SPAWN} 次都中途退出")
    assert "JSONDecodeError" in view["problems"][-1]["raw"]  # 后台进程自己的报错留在原始报错里
    plan.write_text(good_plan, encoding="utf-8")
    desk.retry(exp)
    view = run_to_end(desk, exp)
    assert view["status"] == FINISHED and all(t["state"] == "完成" for t in view["tasks"].values())


def test_settings_that_cannot_be_used_end_the_experiment_with_a_problem(home, arch, tmp_path):
    desk = Desk(home)
    cases = [
        dict(archive=arch / "syn_fric_0001.tar.xz", jobs=GOOD, quantities=None, word="要是一个文件夹"),
        dict(archive=arch, jobs=GOOD, quantities=["标签", "温度场"], word="不认识的"),
        dict(archive=arch, jobs=["../x"], quantities=None, word="不像作业号"),
        dict(archive=arch, jobs=[], quantities=None, word="一个作业号都没有"),
    ]
    for case in cases:
        exp = new_experiment(desk, case["archive"], case["jobs"], case["quantities"])
        desk.start(exp)
        view = desk.store.open(exp).view()
        assert view["status"] == FINISHED and view["tasks"] == {} and view["outputs"] == []
        assert len(view["problems"]) == 1 and case["word"] in view["problems"][0]["error"]
    assert worker_pids(home) == []  # 没有起过后台进程


def test_jobs_can_be_a_list_file_or_everything_and_quantities_can_be_fewer(home, arch, tmp_path):
    desk = Desk(home)
    listing = tmp_path / "jobs.txt"
    listing.write_text("# 两个作业\nsyn_bond_0002\n\nsyn_fric_0001\n", encoding="utf-8")
    exp = desk.new("fea-archive-export")
    desk.set(exp, "归档", ref=str(arch), source="测试")
    desk.set(exp, "作业", file=str(listing), source="测试")
    desk.set(exp, "导出哪些量", value=["标签"], source="测试")
    desk.start(exp)
    view = run_to_end(desk, exp)
    assert list(view["tasks"]) == ["syn_bond_0002", "syn_fric_0001"]
    assert [o["name"] for o in view["outputs"]] == ["标签", "说明"]  # 没选的量不产出
    out = home / "experiments" / exp / "outputs"
    assert not (out / "界面场").exists() and not (out / "整体场").exists()

    exp2 = new_experiment(desk, arch, "全部", ["整体场"])
    desk.start(exp2)
    view = run_to_end(desk, exp2)
    assert sorted(view["tasks"]) == sorted(GOOD)
    assert [o["name"] for o in view["outputs"]] == ["整体场", "说明"]


def test_the_output_of_one_experiment_can_be_a_setting_of_another(home, arch):
    """产出登记在实验记录里，带位置和哈希：别的实验可以按「另一个实验的产出」拿它当设置。"""
    desk = Desk(home)
    exp = new_experiment(desk, arch, ["syn_fric_0001"])
    desk.start(exp)
    run_to_end(desk, exp)
    path, sha = desk.store.open(exp).output_path("整体场")
    assert path.is_dir() and (path / "syn_fric_0001.npz").exists() and len(sha) == 64
