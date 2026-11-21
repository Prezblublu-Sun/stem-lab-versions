"""示范插件怎么算。相当于真插件里自由的那部分，可以整个重写。

行为由 setting 这样输入指挥，所以测试不用改插件就能演各种情形：
    tasks      任务名的列表。默认 ["only"]
    outcomes   任务 -> 它每一轮的结局的列表，最后一个往后沿用。默认都是 finished
    polls      轮询几次才做完。默认 1
    poll_raises  每一轮头几次轮询抛错，之后恢复正常
    check      "raise" 检查抛错；别的字符串就是检查不过的原因
    start      "raise" 启动抛错；"exit" 启动到一半进程退出；"finish" 启动里就说做完；"fail" 启动里就说做不下去
    start_seconds  启动里磨蹭多少秒
    start_output   true 就在启动里交一份报告
    error_text     轮询抛错时报错的文字
    poll       "raise" 轮询抛错；"fail" 说做不下去；"never" 永远做不完；"finish_then_raise" 说了做完又抛错
    stop       "raise" 停止抛错；"raise_once" 第一次抛错，再停一次能成
    bone_id    写进产物清单的骨标识
    second     true 就再交第二份报告
    seconds    demo.sleep 的那个进程睡多久
"""
import json
import os
import sys
import time

from stemlab import hooks

MANIFEST = "manifest.json"


def _dump(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"


def _write_report(handle, name: str, summary: dict):
    """把一份报告写进 work/，返回文件夹。清单由这里写：真插件里这是冻结文件的事。"""
    setting = handle.input("setting")
    folder = handle.work_dir / f"{name}-r{handle.round.number}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "summary.json").write_bytes(_dump(summary))
    manifest = {"format": 1, "kind": "report", "files": ["summary.json"]}
    if setting.get("bone_id"):
        manifest["bone_id"] = setting["bone_id"]
    (folder / MANIFEST).write_bytes(_dump(manifest))
    return folder


def _outcome(setting: dict, task: str, number: int) -> str:
    planned = setting.get("outcomes", {}).get(task, ["finished"])
    return planned[min(number, len(planned)) - 1]


def _open_tasks(handle) -> list:
    return [name for name, task in handle.tasks().items()
            if task.round == handle.round.number and task.state in ("queued", "running")]


def _count(handle, name: str) -> int:
    """这个动作在这一轮里是第几次被叫。记在 work/ 里：插件在两次调用之间不留别的状态。"""
    path = handle.work_dir / f"{name}-r{handle.round.number}.count"
    count = int(path.read_text()) + 1 if path.exists() else 1
    path.write_text(str(count))
    return count


# ---------------------------------------------------------------- demo.echo

def check(handle):
    handle.input("extra")                                           # 检查里把输入都摸一遍
    return sleep_check(handle)


def start(handle):
    setting = handle.input("setting")
    how = setting.get("start")
    if how == "raise":
        raise RuntimeError("示范：启动抛错")
    if setting.get("start_output"):
        handle.output("report", _write_report(handle, "report", {"published": "inside start"}))
    # 该派的任务：这一轮要重排的，加上还从没报过的。rerun 是空的不等于“这是第一轮”
    known = handle.tasks()
    for task in list(handle.round.rerun) + [name for name in setting.get("tasks", ["only"]) if name not in known]:
        handle.task(task, "queued")
    time.sleep(setting.get("start_seconds", 0))
    if how == "exit":
        os._exit(3)                                                 # 启动到一半进程退出
    if how == "finish":
        handle.finish()
    if how == "fail":
        handle.fail("示范：启动里就做不下去")


def poll(handle):
    setting = handle.input("setting")
    extra = handle.input("extra")
    how = setting.get("poll")
    count = _count(handle, "poll")
    if how == "raise" or count <= setting.get("poll_raises", 0):
        raise RuntimeError(setting.get("error_text", "示范：轮询抛错"))
    if how == "fail":
        handle.fail("示范：做不下去")
        return
    if how == "finish_then_raise":
        handle.finish()
        raise RuntimeError("示范：说了做完，又抛了错")
    for task in _open_tasks(handle):
        handle.task(task, "running", stage="echo", machine="here")
    if how == "never" or count < setting.get("poll_raises", 0) + setting.get("polls", 1):
        return
    for task in _open_tasks(handle):
        outcome = _outcome(setting, task, handle.round.number)
        handle.task(task, "done" if outcome in ("finished", "misfit") else "failed", outcome=outcome)
    summary = {"scale": setting.get("scale"), "round": handle.round.number, "extra": len(extra),
               "tasks": {name: task.outcome for name, task in handle.tasks().items()}}
    handle.output("report", _write_report(handle, "report", summary))
    if setting.get("second"):
        handle.output("second", _write_report(handle, "second", {"second": True}))
    handle.provenance(solver="demo 1.0")
    handle.finish()


def stop(handle):
    how = handle.input("setting").get("stop")
    if how == "raise" or (how == "raise_once" and _count(handle, "stop") == 1):
        raise RuntimeError("示范：停止没停成")
    for task in _open_tasks(handle):
        handle.task(task, "stopped")


def chart(handle, name):
    return {"columns": ["任务", "状态", "结局"],
            "rows": [[task.name, task.state, task.outcome] for task in handle.tasks().values()]}


# ---------------------------------------------------------------- demo.pack

_RUNNERS = {"kernel": hooks.run_kernel, "strategy": hooks.run_strategy, "derive_def": hooks.derive,
            "predictor": hooks.predict}


def pack_start(handle):
    handle.task("job", "queued")


def pack_poll(handle):
    """把 setting 里的 x 交给包去算。setting 里 wait 是 false 的话，起一个脱离出去的进程，下一遍再来看。"""
    setting, tool = handle.input("setting"), handle.input_info("tool")
    source, target = handle.work_dir / "in", handle.work_dir / f"out-r{handle.round.number}"
    source.mkdir(exist_ok=True)
    (source / "x.json").write_bytes(_dump({"x": setting.get("x", 1), "crash": setting.get("crash", False)}))
    run = _RUNNERS[setting.get("as", tool.kind)]
    if setting.get("wait", True):
        result = run(setting.get("package", tool.id), source, target)
    elif not (target / "log.txt").exists():
        (handle.work_dir / "process.json").write_bytes(_dump(run(tool.id, source, target, wait=False)))
        handle.task("job", "running", stage="in the package")
        return
    elif hooks.alive(json.loads((handle.work_dir / "process.json").read_bytes())):
        return
    else:
        result = json.loads((target / "result.json").read_bytes())
    handle.task("job", "done", outcome="finished")
    handle.output("report", _write_report(handle, "report", {"result": result}))
    handle.finish()


# ---------------------------------------------------------------- demo.remote

def remote_start(handle):
    """打快照，上传快照和输入的副本，在远端起 worker，把任务报成运行。setting 里 machine 是 worker 的名字。"""
    setting = handle.input("setting")
    numbers = handle.work_dir / "numbers.json"
    numbers.write_bytes(_dump({"numbers": setting.get("numbers", [1, 2, 3])}))
    hooks.remote.push(handle, setting["machine"], {"numbers.json": numbers})
    hooks.remote.start(handle, setting["machine"], "tests.plugins.demo.worker", str(setting.get("seconds", 1)))
    handle.task("job", "running", stage="pushed", machine=setting["machine"])


def remote_poll(handle):
    """读远端的状态文件。没完就更新阶段；完了就取回、交报告、说做完。心跳停了太久算环境问题。"""
    setting = handle.input("setting")
    found = hooks.remote.status(handle, setting["machine"])
    if found is None:
        return
    if found["result"] is None:
        if found["age"] > setting.get("stale", 120):
            handle.task("job", "failed", outcome="env")
            handle.fail("示范：远端的心跳停了")
        elif handle.tasks()["job"].stage != found["stage"]:
            handle.task("job", "running", stage=found["stage"], machine=setting["machine"])
        return
    pulled = hooks.remote.pull(handle, setting["machine"])
    handle.task("job", "done", outcome=found["result"])
    summary = {"sum": json.loads((pulled / "sum.json").read_bytes())["sum"], "host": found["env"]["host"]}
    handle.output("report", _write_report(handle, "report", summary))
    handle.finish()


def remote_stop(handle):
    hooks.remote.stop(handle, handle.input("setting")["machine"])
    for task in _open_tasks(handle):
        handle.task(task, "stopped")


# ---------------------------------------------------------------- demo.sleep

_SLEEPER = "import pathlib, sys, time; time.sleep(float(sys.argv[1])); pathlib.Path(sys.argv[2]).write_text('done')"


def sleep_check(handle):
    setting = handle.input("setting")
    if setting.get("check") == "raise":
        raise ValueError("示范：检查抛错")
    return setting.get("check")


def sleep_start(handle):
    result = handle.work_dir / f"result-r{handle.round.number}.txt"
    process = hooks.spawn([sys.executable, "-c", _SLEEPER, str(handle.input("setting").get("seconds", 0.5)), str(result)])
    (handle.work_dir / "process.json").write_bytes(_dump(process))
    handle.task("job", "running", stage="sleeping", machine="here")


def sleep_poll(handle):
    result = handle.work_dir / f"result-r{handle.round.number}.txt"
    process = json.loads((handle.work_dir / "process.json").read_bytes())
    if result.exists():
        handle.task("job", "done", outcome="finished")
        handle.output("report", _write_report(handle, "report", {"slept": True}))
        handle.finish()
    elif not hooks.alive(process):
        handle.task("job", "failed", outcome="env")
        handle.fail("示范：进程没了，结果也没有")


def sleep_stop(handle):
    hooks.kill(json.loads((handle.work_dir / "process.json").read_bytes()))
    for task in _open_tasks(handle):
        handle.task(task, "stopped")
