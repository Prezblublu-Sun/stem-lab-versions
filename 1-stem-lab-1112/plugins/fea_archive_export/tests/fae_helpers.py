"""测试里共用的几个小函数。"""
import importlib.util
import json
import sys
import time
from pathlib import Path

TESTS = Path(__file__).resolve().parent
PLUGIN = TESTS.parent
REPO = PLUGIN.parent.parent


def plugin_module():
    """把 plugin.py 当普通模块读进来（名字起得不会和别的插件撞）。"""
    name = "fae_plugin_under_test"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, PLUGIN / "plugin.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def worker_pids(home: Path) -> list[int]:
    pids = []
    for f in Path(home).rglob("worker.json"):
        try:
            pids.append(int(json.loads(f.read_text(encoding="utf-8"))["pid"]))
        except (OSError, ValueError, KeyError):
            pass
    return pids


def kill_workers(home: Path) -> None:
    pm = plugin_module()
    for pid in worker_pids(home):
        if pm.pid_alive(pid):
            pm.pid_kill(pid)
            wait_gone(pid)


def wait_gone(pid: int, limit_s: float = 10.0) -> bool:
    pm = plugin_module()
    deadline = time.time() + limit_s
    while pm.pid_alive(pid) and time.time() < deadline:
        time.sleep(0.05)
    return not pm.pid_alive(pid)


def run_to_end(desk, exp_id, limit_s: float = 120.0) -> dict:
    """隔一会儿叫一次刷新，直到实验不在运行中。返回最后的九项。"""
    deadline = time.time() + limit_s
    while time.time() < deadline:
        desk.refresh(exp_id)
        view = desk.store.open(exp_id).view()
        if view["status"] != "运行中":
            return view
        time.sleep(0.2)
    raise AssertionError(f"{exp_id} 在 {limit_s:g} 秒内没有结束")


def new_experiment(desk, archive: Path, jobs, quantities=None, note: str = "") -> str:
    exp = desk.new("fea-archive-export", note=note)
    desk.set(exp, "归档", ref=str(archive), source="测试用的归档")
    desk.set(exp, "作业", value=jobs, source="测试")
    if quantities is not None:
        desk.set(exp, "导出哪些量", value=quantities, source="测试")
    return exp
