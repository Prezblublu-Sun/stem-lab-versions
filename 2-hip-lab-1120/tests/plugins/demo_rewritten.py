"""示范插件自由部分的另一份写法：接口不变，里面整个重写。

测试把它盖到 demo/free.py 上，看“把自由的部分整个换一份写法”之后，已有实验的核对和新的实验是不是都照过。
它只管默认的那条路：任务都算完、交一份报告、说做完。
"""
import json
import sys

from stemlab import hooks

REWRITTEN = True


def _report(handle, body: dict):
    folder = handle.work_dir / ("rewritten-%d" % handle.round.number)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "summary.json").write_text(json.dumps(body, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    (folder / "manifest.json").write_text(
        json.dumps({"format": 1, "kind": "report", "files": ["summary.json"]}, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")
    return folder


def sleep_check(handle):
    return None


def check(handle):
    return None if isinstance(handle.input("setting"), dict) else "设定不是一个表"


def start(handle):
    already = handle.tasks()
    fresh = [name for name in handle.input("setting").get("tasks", ["only"]) if name not in already]
    for name in [*handle.round.rerun, *fresh]:
        handle.task(name, "queued")


def poll(handle):
    mine = [task for task in handle.tasks().values() if task.round == handle.round.number]
    for task in mine:
        if task.state in ("queued", "running"):
            handle.task(task.name, "done", outcome="finished", stage="rewritten")
    handle.output("report", _report(handle, {"rewritten": True, "tasks": sorted(task.name for task in mine)}))
    handle.finish()


def stop(handle):
    for task in handle.tasks().values():
        if task.round == handle.round.number and task.state in ("queued", "running"):
            handle.task(task.name, "stopped")


def chart(handle, name):
    return {"columns": ["任务"], "rows": [[name] for name in handle.tasks()]}


def pack_start(handle):
    handle.task("job", "queued")


def pack_poll(handle):
    tool = handle.input_info("tool")
    source = handle.work_dir / "in"
    source.mkdir(exist_ok=True)
    (source / "x.json").write_text(json.dumps({"x": handle.input("setting").get("x", 1)}), encoding="utf-8")
    result = hooks.run_strategy(tool.id, source, handle.work_dir / "out")
    handle.task("job", "done", outcome="finished")
    handle.output("report", _report(handle, {"rewritten": True, "result": result}))
    handle.finish()


def remote_start(handle):
    setting = handle.input("setting")
    hooks.remote.push(handle, setting["machine"], {})
    hooks.remote.start(handle, setting["machine"], "tests.plugins.demo.worker", "1")
    handle.task("job", "running")


def remote_poll(handle):
    if hooks.remote.status(handle, handle.input("setting")["machine"]):
        handle.task("job", "done", outcome="finished")
        handle.finish()


def remote_stop(handle):
    hooks.remote.stop(handle, handle.input("setting")["machine"])


def sleep_start(handle):
    process = hooks.spawn([sys.executable, "-c", "pass"])
    (handle.work_dir / "process.json").write_text(json.dumps(process), encoding="utf-8")
    handle.task("job", "running")


def sleep_poll(handle):
    handle.task("job", "done", outcome="finished")
    handle.finish()


def sleep_stop(handle):
    hooks.kill(json.loads((handle.work_dir / "process.json").read_text(encoding="utf-8")))
