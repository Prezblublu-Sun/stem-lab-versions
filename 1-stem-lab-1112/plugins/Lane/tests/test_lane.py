"""Lane 插件的测试。

每个测试用一个临时文件夹当 home，把 Lane 和 demo 两个插件复制进去，不碰正式的 experiments。
在仓库根上跑：

    PYTHONUTF8=1 python -m pytest plugins/Lane/tests -q -p no:cacheprovider
"""
import json
import shutil
import time
from pathlib import Path

import pytest

import stemlab
from stemlab.console import Desk, main
from stemlab.record import FINISHED, RUNNING, STOPPED, pid_alive, sha256_path

LANE = Path(__file__).resolve().parents[1]
REPO = Path(stemlab.__file__).resolve().parent.parent
EX = LANE / "examples"
GOOD = EX / "随机取可行点.py"
TASK = "选点"


@pytest.fixture
def home(tmp_path):
    shutil.copytree(LANE, tmp_path / "plugins" / "Lane", ignore=shutil.ignore_patterns("tests", "__pycache__"))
    shutil.copytree(REPO / "plugins" / "demo", tmp_path / "plugins" / "demo")
    return tmp_path


def strategy(tmp_path, name, code):
    path = tmp_path / "策略" / f"{name}.py"
    path.parent.mkdir(exist_ok=True)
    path.write_text(code, encoding="utf-8")
    return path


def make(desk, strat=GOOD, seed=7, n=5, **more):
    exp_id = desk.new("Lane")
    desk.set(exp_id, "策略", file=str(strat), source="测试")
    desk.set(exp_id, "目标和约束", file=str(EX / "目标和约束.json"), source="测试")
    desk.set(exp_id, "候选池", file=str(EX / "候选池.json"), source="测试")
    desk.set(exp_id, "选几个点", value=n, source="测试")
    desk.set(exp_id, "随机种子", value=seed, source="测试")
    for name, value in more.items():
        desk.set(exp_id, name, value=value, source="测试")
    return exp_id


def view(desk, exp_id):
    return desk.store.open(exp_id).view()


def wait(desk, *exp_ids, seconds=90):
    """一直叫刷新，直到这几个实验都不在运行中。"""
    deadline = time.time() + seconds
    while time.time() < deadline:
        if all(view(desk, e)["status"] != RUNNING for e in exp_ids):
            return
        desk.refresh()
        time.sleep(0.1)
    raise AssertionError("实验没有在预期的时间内结束")


def run(desk, exp_id):
    desk.start(exp_id)
    wait(desk, exp_id)
    return view(desk, exp_id)


def points_of(desk, exp_id):
    path, _ = desk.store.open(exp_id).output_path("一批点")
    return json.loads(path.read_text(encoding="utf-8"))


def has_points(desk, exp_id):
    return any(o["name"] == "一批点" for o in view(desk, exp_id)["outputs"])


def runner_pid(home, exp_id, run_no=1):
    return int((home / "experiments" / exp_id / "plugin_state" / f"run_{run_no:02d}" / "pid.txt").read_text())


def wait_gone(pid, seconds=10):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(0.1)
    return False


# ---- 插件报的四样 ---------------------------------------------------------


def test_plugin_reports_its_four_things(home):
    info = {p["name"]: p for p in Desk(home).plugin_info()}["Lane"]
    assert info["category"] == "优化"
    assert [(s["name"], s["required"]) for s in info["settings"]] == [
        ("策略", True), ("目标和约束", True), ("候选池", True), ("预测器", False),
        ("已有数据", False), ("选几个点", True), ("随机种子", True),
    ]
    assert [o["name"] for o in info["outputs"]] == ["一批点"]
    assert {"启动", "报任务状态", "停止", "重试"} <= set(info["hooks"])
    assert Desk(home).plugin_errors == []


# ---- 验收 1：操作台里新建、填设置、启动，得到一批点 -------------------------


def test_console_new_set_start_gives_points(home, capsys):
    """走的是命令行操作台。每条命令是一个新的操作台，和真的在命令行里打一样。"""
    h = ["--home", str(home)]
    assert main(h + ["new", "Lane", "--note", "示例策略走一遍"]) == 0
    exp_id = capsys.readouterr().out.strip()
    for name, kind, content in (
        ("策略", "--file", str(GOOD)),
        ("目标和约束", "--file", str(EX / "目标和约束.json")),
        ("候选池", "--file", str(EX / "候选池.json")),
        ("选几个点", "--value", "13"),  # 示例候选池 20 个里正好 13 个可行：不看约束的策略过不了下面的比较
        ("随机种子", "--value", "7"),
    ):
        assert main(h + ["set", exp_id, name, kind, content, "--source", "插件自带的示例"]) == 0
    assert main(h + ["start", exp_id]) == 0
    deadline = time.time() + 90
    while view(Desk(home), exp_id)["status"] == RUNNING and time.time() < deadline:
        assert main(h + ["refresh", exp_id]) == 0
        time.sleep(0.1)
    capsys.readouterr()

    v = view(Desk(home), exp_id)
    assert v["status"] == FINISHED and v["problems"] == []
    assert list(v["tasks"]) == [TASK] and v["tasks"][TASK]["state"] == "完成"
    assert [h["state"] for h in v["tasks"][TASK]["history"]] == ["排队", "运行", "完成"]

    points = points_of(Desk(home), exp_id)
    pool = {c["名字"]: c for c in json.loads((EX / "候选池.json").read_text(encoding="utf-8"))}
    assert isinstance(points, list) and len(points) == 13
    assert {p["名字"] for p in points} == {name for name, c in pool.items() if c["去骨量"] <= 6.0}
    for p in points:
        assert list(p)[:4] == ["名字", "设计", "条件", "理由"]
        assert p["设计"] == pool[p["名字"]]["设计"] and p["条件"] == {}
        assert pool[p["名字"]]["去骨量"] <= 6.0
        assert "随机抽中" in p["理由"]

    # 策略的原文存了一份，和插件自带的那份一样；跑过之后没有被动过
    stored = home / "experiments" / exp_id / v["settings"]["策略"]["content"]["stored"]
    assert stored.read_bytes() == GOOD.read_bytes()
    assert sha256_path(stored) == v["settings"]["策略"]["content"]["sha256"]
    assert not list(stored.parent.rglob("__pycache__"))

    assert main(h + ["show", exp_id]) == 0
    shown = capsys.readouterr().out
    assert "一批点" in shown and "13 个点" in shown


# ---- 验收 2：同设置同种子重跑相同，换种子不同 ------------------------------


def test_same_settings_same_seed_same_points_other_seed_differs(home):
    desk = Desk(home)
    a, b, c = make(desk, seed=7), make(desk, seed=7), make(desk, seed=8)
    for e in (a, b, c):
        assert run(desk, e)["problems"] == []
    pa, pb, pc = points_of(desk, a), points_of(desk, b), points_of(desk, c)
    assert len(pa) == len(pb) == len(pc) == 5
    for one, two in zip(pa, pb):
        assert one == two
    sha = {e: [o["sha256"] for o in view(desk, e)["outputs"] if o["name"] == "一批点"][0] for e in (a, b, c)}
    assert sha[a] == sha[b]
    assert [p["名字"] for p in pa] != [p["名字"] for p in pc]
    assert sha[a] != sha[c]


GLOBAL_RANDOM = '''
import random

def select(inputs):
    names = list({"甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸", "子", "丑"})  # 集合的顺序
    picks = random.sample(range(100000), 3)                                              # 没有自己设种子
    return [{"名字": f"{names[i]}{k}", "设计": {"k": k}, "理由": "用的是全局随机数"} for i, k in enumerate(picks)]
'''


def test_plugin_fixes_global_random_and_set_order(home, tmp_path):
    """策略没有自己设种子、还依赖集合的顺序：插件在跑之前都固定住了，重跑仍然相同。"""
    desk = Desk(home)
    strat = strategy(tmp_path, "全局随机", GLOBAL_RANDOM)
    a, b, c = make(desk, strat, seed=3, n=3), make(desk, strat, seed=3, n=3), make(desk, strat, seed=4, n=3)
    for e in (a, b, c):
        assert run(desk, e)["problems"] == []
    assert points_of(desk, a) == points_of(desk, b)
    assert points_of(desk, a) != points_of(desk, c)


NUMPY_RANDOM = '''
import numpy as np

def select(inputs):
    xs = np.random.rand(3)
    return [{"设计": {"x": x}, "理由": "numpy 的全局随机数", "分数": np.float64(x) * 2} for x in xs]
'''


def test_plugin_fixes_numpy_global_random(home, tmp_path):
    pytest.importorskip("numpy")
    desk = Desk(home)
    strat = strategy(tmp_path, "numpy随机", NUMPY_RANDOM)
    a, b, c = make(desk, strat, seed=3, n=3), make(desk, strat, seed=3, n=3), make(desk, strat, seed=4, n=3)
    for e in (a, b, c):
        assert run(desk, e)["problems"] == []
    pa = points_of(desk, a)
    assert pa == points_of(desk, b) and pa != points_of(desk, c)
    # 策略没给名字，插件按顺序给；策略另给的字段原样留着；numpy 的数存成了普通的数
    assert [p["名字"] for p in pa] == ["p01", "p02", "p03"]
    assert all(isinstance(p["分数"], float) and p["分数"] == p["设计"]["x"] * 2 for p in pa)


UNSEEDED = '''
import os

def select(inputs):
    return [{"设计": {"x": 1}, "理由": "绕开种子：" + os.urandom(8).hex()}]
'''

SEED_BLIND = '''
import json

def select(inputs):
    pool = json.loads(inputs["候选池"].read_text(encoding="utf-8"))
    return [{"名字": c["名字"], "设计": c["设计"], "理由": "取前几个"} for c in pool[: inputs["选几个点"]]]
'''


def test_the_two_comparisons_can_tell(home, tmp_path):
    """上面两条比较不是摆设：绕开种子的策略重跑会不同；不看种子的策略换种子也相同。"""
    desk = Desk(home)
    unseeded = strategy(tmp_path, "绕开种子", UNSEEDED)
    a, b = make(desk, unseeded, seed=7), make(desk, unseeded, seed=7)
    run(desk, a), run(desk, b)
    assert points_of(desk, a) != points_of(desk, b)

    blind = strategy(tmp_path, "不看种子", SEED_BLIND)
    c, d = make(desk, blind, seed=7), make(desk, blind, seed=8)
    run(desk, c), run(desk, d)
    assert points_of(desk, c) == points_of(desk, d)


# ---- 验收 3：策略写错了，记下问题，不影响别的实验 ----------------------------


BAD = {
    "运行时出错": ("def select(inputs):\n    return 1 / 0\n", "ZeroDivisionError"),
    "语法错": ("def select(inputs:\n    return []\n", "SyntaxError"),
    "没有 select": ("x = 1\n", "没有叫 select 的函数"),
    "自己退出": ("import sys\n\ndef select(inputs):\n    sys.exit(5)\n", "SystemExit"),
    "进程直接没了": ("import os\n\ndef select(inputs):\n    os._exit(7)\n", "没有留下结果"),
    "返回的不是列表": ("def select(inputs):\n    return {'设计': {}}\n", "列表"),
    "一个都没有": ("def select(inputs):\n    return []\n", "一个点都没有"),
    "缺理由": ("def select(inputs):\n    return [{'设计': {'x': 1}}]\n", "理由"),
    "缺设计": ("def select(inputs):\n    return [{'理由': '好'}]\n", "设计"),
    "重名": ("def select(inputs):\n    return [{'名字': 'a', '设计': 1, '理由': '好'}] * 2\n", "重"),
    "给多了": ("def select(inputs):\n    return [{'设计': i, '理由': '好'} for i in range(6)]\n", "6 个"),
    "有非数": ("def select(inputs):\n    return [{'设计': {'x': float('nan')}, '理由': '好'}]\n", "JSON"),
}


@pytest.mark.parametrize("case", list(BAD))
def test_bad_strategy_becomes_a_problem(home, tmp_path, case):
    code, expect = BAD[case]
    desk = Desk(home)
    exp_id = make(desk, strategy(tmp_path, "坏策略", code))
    v = run(desk, exp_id)
    assert v["status"] == FINISHED
    assert v["tasks"][TASK]["state"] == "失败"
    assert not has_points(desk, exp_id)
    assert len(v["problems"]) == 1
    problem = v["problems"][0]
    assert problem["task"] == TASK
    assert expect in problem["error"] + problem["raw"]
    assert desk.check(exp_id).endswith("记录完好")


def test_broken_strategy_is_recorded_and_other_experiments_go_on(home, tmp_path):
    desk = Desk(home)
    before = make(desk, seed=1)
    bad = make(desk, strategy(tmp_path, "坏策略", BAD["运行时出错"][0]))
    after = make(desk, seed=2)
    for e in (before, bad, after):
        assert desk.start(e) is True
    wait(desk, before, bad, after)
    assert desk.refresh_errors == {}

    v = view(desk, bad)
    assert v["status"] == FINISHED and v["tasks"][TASK]["state"] == "失败" and not has_points(desk, bad)
    problem = v["problems"][0]
    assert "ZeroDivisionError" in problem["error"]
    # 原始报错：策略自己的出错位置在里面，并且另存了一份文件
    assert "Traceback" in problem["raw"] and "坏策略.py" in problem["raw"] and "return 1 / 0" in problem["raw"]
    saved = home / "experiments" / bad / "plugin_state" / "run_01" / "原始报错.txt"
    assert "ZeroDivisionError" in saved.read_text(encoding="utf-8")

    for e in (before, after):
        ok = view(desk, e)
        assert ok["status"] == FINISHED and ok["problems"] == [] and len(points_of(desk, e)) == 5
    # 坏实验之后还能照常新建、跑完
    assert run(desk, make(desk, seed=3))["tasks"][TASK]["state"] == "完成"


def test_fewer_points_than_asked_is_a_problem_but_points_are_kept(home):
    desk = Desk(home)
    exp_id = make(desk, n=40)  # 示例候选池里只有 13 个可行的
    v = run(desk, exp_id)
    assert v["tasks"][TASK]["state"] == "完成"
    assert len(points_of(desk, exp_id)) == 13
    assert len(v["problems"]) == 1 and "40" in v["problems"][0]["error"] and "13" in v["problems"][0]["error"]


@pytest.mark.parametrize("name,value,expect", [
    ("选几个点", "五", "选几个点"),
    ("选几个点", 0, "选几个点"),
    ("随机种子", 1.5, "随机种子"),
    ("随机种子", -1, "随机种子"),
])
def test_bad_setting_becomes_a_problem(home, name, value, expect):
    desk = Desk(home)
    exp_id = make(desk, **{name: value})
    v = run(desk, exp_id)
    assert v["status"] == FINISHED and v["tasks"][TASK]["state"] == "失败"
    assert expect in v["problems"][0]["error"] and not has_points(desk, exp_id)


def test_strategy_given_as_a_value_becomes_a_problem(home):
    desk = Desk(home)
    exp_id = desk.new("Lane")
    for name, value in (("策略", "随机"), ("目标和约束", {}), ("候选池", []), ("选几个点", 1), ("随机种子", 0)):
        desk.set(exp_id, name, value=value, source="测试")
    v = run(desk, exp_id)
    assert v["tasks"][TASK]["state"] == "失败" and "策略" in v["problems"][0]["error"]


def test_strategy_can_be_a_folder_and_settings_can_be_values(home, tmp_path):
    """策略是一个文件夹：入口 strategy.py，可以带自己的辅助文件。候选池等也可以直接填值。"""
    folder = tmp_path / "我的策略"
    folder.mkdir()
    (folder / "helper.py").write_text("def score(c):\n    return -c['去骨量']\n", encoding="utf-8")
    (folder / "strategy.py").write_text(
        "from helper import score\n\n"
        "def select(inputs):\n"
        "    assert inputs['预测器'] is None and inputs['已有数据'] == ['c01']\n"
        "    pool = [c for c in inputs['候选池'] if c['名字'] not in inputs['已有数据']]\n"
        "    best = sorted(pool, key=score, reverse=True)[: inputs['选几个点']]\n"
        "    return [{'名字': c['名字'], '设计': c['设计'], '条件': {'载荷': '上楼'},\n"
        "             '理由': f\"去骨量最小的几个之一：{c['去骨量']}\"} for c in best]\n",
        encoding="utf-8",
    )
    pool = json.loads((EX / "候选池.json").read_text(encoding="utf-8"))
    desk = Desk(home)
    exp_id = desk.new("Lane")
    desk.set(exp_id, "策略", file=str(folder), source="测试")
    desk.set(exp_id, "目标和约束", value={"目标": "去骨量越小越好"}, source="测试")
    desk.set(exp_id, "候选池", value=pool, source="测试")
    desk.set(exp_id, "已有数据", value=["c01"], source="测试")
    desk.set(exp_id, "选几个点", value=2, source="测试")
    desk.set(exp_id, "随机种子", value=0, source="测试")
    v = run(desk, exp_id)
    assert v["problems"] == []
    points = points_of(desk, exp_id)
    assert [p["名字"] for p in points] == ["c11", "c02"]
    assert points[0]["条件"] == {"载荷": "上楼"}


# ---- 验收 4：产出的一批点能给 demo 插件当设置 -------------------------------


def test_demo_reads_the_points_as_a_setting_from_another_experiment(home):
    desk = Desk(home)
    lane = make(desk)
    run(desk, lane)
    points = points_of(desk, lane)

    demo = desk.new("demo")
    desk.set(demo, "点", from_exp=lane, output="一批点")
    v = run(desk, demo)
    assert v["status"] == FINISHED and v["problems"] == []
    assert v["settings"]["点"]["source"] == {"kind": "实验产出", "experiment": lane, "output": "一批点"}
    assert len(v["tasks"]) == len(points) == 5
    for task_name, point in zip(v["tasks"], points):
        assert f"'名字': '{point['名字']}'" in task_name
        assert v["tasks"][task_name]["state"] == "完成"
    done_path, _ = desk.store.open(demo).output_path("点清单")
    assert len(json.loads(done_path.read_text(encoding="utf-8"))) == 5


# ---- 停止、重试 -----------------------------------------------------------


SLOW = '''
import time

def select(inputs):
    time.sleep(120)
    return []
'''


@pytest.mark.parametrize("same_desk", [True, False])
def test_stop_ends_the_strategy_process_and_retry_runs_it_again(home, tmp_path, same_desk):
    """same_desk=False：停止来自另一个操作台（比如另一条命令），它手里没有那个进程。"""
    desk = Desk(home)
    exp_id = make(desk, strategy(tmp_path, "慢策略", SLOW))
    desk.start(exp_id)
    desk.refresh(exp_id)
    assert view(desk, exp_id)["tasks"][TASK]["state"] == "运行"
    pid = runner_pid(home, exp_id)
    assert pid_alive(pid)

    other = desk if same_desk else Desk(home)
    other.stop(exp_id)
    v = view(other, exp_id)
    assert v["status"] == STOPPED and v["tasks"][TASK]["state"] == "停止"
    assert wait_gone(pid)

    other.retry(exp_id)
    v = view(other, exp_id)
    assert v["status"] == RUNNING and v["tasks"][TASK]["state"] == "运行"
    pid2 = runner_pid(home, exp_id, run_no=2)
    assert pid2 != pid and pid_alive(pid2)
    other.stop(exp_id)
    assert wait_gone(pid2)


NEEDS_ENV = '''
import os

def select(inputs):
    if os.environ.get("LANE_TEST_FAIL"):
        raise RuntimeError("这一次环境不对")
    return [{"设计": {"x": 1}, "理由": "环境好了"}]
'''


def test_retry_after_failure_runs_again_with_the_same_settings(home, tmp_path, monkeypatch):
    desk = Desk(home)
    exp_id = make(desk, strategy(tmp_path, "看环境", NEEDS_ENV), n=1)
    monkeypatch.setenv("LANE_TEST_FAIL", "1")
    v = run(desk, exp_id)
    assert v["tasks"][TASK]["state"] == "失败" and "这一次环境不对" in v["problems"][0]["error"]

    monkeypatch.delenv("LANE_TEST_FAIL")
    desk.retry(exp_id)
    wait(desk, exp_id)
    v = view(desk, exp_id)
    assert v["status"] == FINISHED and v["tasks"][TASK]["state"] == "完成"
    assert [h["state"] for h in v["tasks"][TASK]["history"]] == ["排队", "运行", "失败", "排队", "运行", "完成"]
    assert len(points_of(desk, exp_id)) == 1 and len(v["problems"]) == 1

    # 已经有一批点了再点重试：没有要重做的，实验回到已结束，产出不重复
    desk.retry(exp_id)
    v = view(desk, exp_id)
    assert v["status"] == FINISHED and len([o for o in v["outputs"] if o["name"] == "一批点"]) == 1
