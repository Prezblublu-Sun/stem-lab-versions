"""【自由】经 run_kernel 建模，经 spawn 起求解进程，按求解槽数排队；看每个作业走到哪：排队、建模、求解、后处理。

接口见 plugin.py 开头：begin、advance、halt、release。接口不变，这个文件可以整个重写。

一个作业在 work/jobs/<任务>/r<轮>/ 下有自己的文件夹：
    state.json            它走到哪了。只有这个文件读写它
    ask-build/、build/    交给内核建模的 job.json，和内核建模的输出
    solve/                求解用的文件夹：内核把求解器的输入写在这里，求解器在这里跑
    ask-post/、post/      后处理
推导量不在这里算：作业结束后由冻结的 export.py 去叫推导量定义。

建模、求解、后处理都是脱离出去的进程，动作里不等它们：这一遍看它们还在不在，不在了就读结果、起下一步。
槽是整台机器共用的：槽文件夹里一个文件一个槽，里面写着占它的进程；那个进程不在了，槽就空出来。
所以两个实验同时跑，合起来也不会超过求解槽数。看槽、占槽、交接、放槽都在槽文件夹的一把锁里做。
槽文件夹默认在 %LOCALAPPDATA%/stemlab/slots（别的系统是 ~/.local/state/stemlab/slots），
不放在临时文件夹里：系统清临时文件时会把它删掉，求了一半的槽就像空了。STEMLAB_SLOTS 可以另指。

起进程时先记“正要起”，起来了再记进程。断在这两步之间，下一遍把已经起来的那个收掉再算这个作业崩了：
求解带着环境变量 STEMLAB_JOB（这个作业的文件夹），建模、后处理的命令行最后两个参数是这个作业的 ask-<步>/ 和 <步>/，
认得准，不会碰别的进程。

导出设定里和这里有关的项（都可以不写）：
    build_slots        同时建模、后处理的作业最多几个，默认 2
    build_timeout_s    一次建模或后处理最多跑多久，默认 3600
    solve_timeout_s    一次求解最多跑多久，默认 21600；内核在 solve 里给了 timeout_s 的以内核的为准
"""
from __future__ import annotations

import contextlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

import psutil

from stemlab import hooks

if os.name == "nt":
    import msvcrt
else:
    import fcntl

STATE, JOB, RESULT = "state.json", "job.json", "result.json"
DIRS = ("build", "solve", "post")
MARK = "STEMLAB_JOB"            # 求解进程带着的环境变量：它是哪个作业的
LOCK = "slots.lck"              # 不叫 .lock：那是账本的几把锁的名字，插件不碰
_FAR = 1 << 30                  # 锁的是锁文件里很靠后的一个字节


# ---------------------------------------------------------------- 一个作业自己的文件夹

def folder_of(handle, task: str) -> Path:
    return handle.work_dir / "jobs" / task / f"r{handle.round.number}"


def _read(path: Path):
    try:
        return json.loads(path.read_bytes())
    except (OSError, ValueError):
        return None


def _save(folder: Path, state: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    spare = folder / (STATE + ".new")
    spare.write_bytes(json.dumps(state).encode("utf-8"))
    os.replace(spare, folder / STATE)


def _ask(folder: Path, what: str, job: dict) -> Path:
    where = folder / f"ask-{what}"
    where.mkdir(parents=True, exist_ok=True)
    (where / JOB).write_bytes(json.dumps(job, ensure_ascii=False).encode("utf-8"))
    return where


def _common(handle, job: dict, folder: Path, setting: dict) -> dict:
    point = job["point"]
    return {"bone_model": str(handle.input("bone")), "bone_id": point["bone_id"], "settings": setting,
            "point": {"name": point["name"], "design": point["design"], "conditions": point["conditions"]},
            "job": str(folder / "solve")}


def _desk(handle):
    return next(machine for machine in handle.machines if machine.role == "desk")


# ---------------------------------------------------------------- 槽

def _slots() -> Path:
    given = os.environ.get("STEMLAB_SLOTS")
    if given:
        return Path(given)
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "stemlab" / "slots"
    return Path.home() / ".local" / "state" / "stemlab" / "slots"


def _try_lock(fd: int) -> bool:
    try:
        if os.name == "nt":
            os.lseek(fd, _FAR, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(fd: int) -> None:
    if os.name == "nt":
        os.lseek(fd, _FAR, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)


@contextlib.contextmanager
def _locked(timeout: float = 30.0):
    """槽文件夹的锁，给出槽文件夹。看旧槽、改写、交接、放掉都在锁里：两处同时来，不会把同一个槽各占一次，
    也不会把别处刚占下的槽当成空的删掉。是操作系统的文件锁，拿着它的进程死了自动放开。"""
    base = _slots()
    base.mkdir(parents=True, exist_ok=True)
    fd = os.open(base / LOCK, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0))
    try:
        deadline = time.monotonic() + timeout
        while not _try_lock(fd):
            if time.monotonic() >= deadline:
                raise TimeoutError(f"{timeout:.0f} 秒拿不到求解槽的锁（{base / LOCK}）：别处一直拿着")
            time.sleep(0.02)
        try:
            yield base
        finally:
            _unlock(fd)
    finally:
        os.close(fd)


def _write(path: Path, body: dict) -> None:
    spare = path.with_name(path.name + ".new")
    spare.write_bytes(json.dumps(body).encode("utf-8"))
    os.replace(spare, path)


def _me() -> dict:
    return {"pid": os.getpid(), "created": psutil.Process().create_time()}


def _claim(kind: str, count: int, note: dict) -> str | None:
    """占一个槽。占到了返回槽文件的位置，没有空槽返回 None。"""
    with _locked() as base:
        for number in range(max(1, int(count))):
            path = base / f"{kind}-{number}.json"
            if path.exists():
                held = _read(path)
                try:
                    taken = hooks.alive(held["process"])
                except (TypeError, KeyError, ValueError):
                    taken = time.time() - path.stat().st_mtime < 30     # 读不出来：刚写坏的先当它占着
                if taken:
                    continue
            _write(path, {"process": _me(), **note})                    # 空的，或者占它的进程不在了
            return str(path)
    return None


def _hold(slot: str, process: dict, note: dict) -> None:
    """槽由刚起来的那个进程接着占：这个进程在，槽就不空。"""
    with _locked():
        _write(Path(slot), {"process": process, **note})


def _free(slot, note: dict) -> None:
    """放掉一个槽。只放还记在自己名下的：占槽的进程一结束，别的作业就可能已经把它占走了，那就不是自己的了。"""
    if slot:
        with _locked():
            held = _read(Path(slot)) or {}
            if (held.get("experiment"), held.get("task")) == (note["experiment"], note["task"]):
                try:
                    Path(slot).unlink()
                except OSError:
                    pass


# ---------------------------------------------------------------- 一步一步往前推

def _end(state: dict, lost: str | None = None) -> dict:
    return dict(state, stage="end", process=None, slot=None, lost=lost, launching=None)


def _strays(folder: Path, stage: str) -> list:
    """断在“正要起进程”和“记下进程”之间时，已经起来了的那个进程，连同它起的子进程。

    求解认环境变量 STEMLAB_JOB；建模、后处理认命令行的最后两个参数（这个作业的 ask-<步>/ 和 <步>/）。
    """
    asked = [str(folder / f"ask-{stage}"), str(folder / stage)]
    found = []
    for process in psutil.process_iter(["cmdline"]):
        if process.pid == os.getpid():
            continue
        try:
            if (process.info["cmdline"] or [])[-2:] == asked or (stage == "solve" and process.environ().get(MARK) == str(folder)):
                found.append(process)
                found += process.children(recursive=True)
        except (psutil.Error, OSError):
            continue
    return list({process.pid: process for process in found}.values())


def _end_strays(folder: Path, stage: str) -> None:
    found = _strays(folder, stage)
    for process in found:
        try:
            process.kill()
        except psutil.Error:
            pass
    psutil.wait_procs(found, timeout=10)


def _gone(process: dict) -> str:
    """进程没了又没留下结果：机器重启过就是环境的事，不然就是它自己崩了。"""
    return "restart" if psutil.boot_time() > process["created"] else "crashed"


def _overdue(state: dict, seconds) -> bool:
    return time.time() - state["since"] > float(seconds)


def _started(folder: Path, state: dict, stage: str, slot, launch, note: dict) -> dict:
    """起一个进程并记下来。先记“正要起”，起来了再记进程：断在中间，下一遍看得出来，不会起第二个。"""
    _save(folder, dict(state, launching=stage, slot=slot))
    try:
        process = launch()
    except Exception as error:  # noqa: BLE001  包的哈希不符、自检没过、命令起不来，都是这个作业的事
        _free(slot, note)
        return _end(state, lost=f"{stage} 起不来：{type(error).__name__}: {error}")
    return dict(state, stage=stage, process=process, slot=slot, since=time.time(), launching=None)


def _queued(handle, job, folder, state, setting) -> dict:
    note = {"experiment": handle.experiment, "task": job["task"]}
    slot = _claim("build", setting.get("build_slots", 2), note)
    if slot is None:
        return state
    ask = _ask(folder, "build", {"mode": "build", **_common(handle, job, folder, setting)})
    state = _started(folder, state, "build", slot,
                     lambda: hooks.run_kernel(handle.input_info("kernel").id, ask, folder / "build", wait=False), note)
    if state["stage"] == "build":
        _hold(slot, state["process"], note)
    return state


def _build(handle, job, folder, state, setting) -> dict:
    note = {"experiment": handle.experiment, "task": job["task"]}
    if hooks.alive(state["process"]):
        if _overdue(state, setting.get("build_timeout_s", 3600)):
            hooks.kill(state["process"])
            _free(state["slot"], note)
            return _end(state, lost="timeout")
        return state
    _free(state["slot"], note)
    result = _read(folder / "build" / RESULT)
    if result is None:
        return _end(state, lost=_gone(state["process"]))
    if result.get("status") != "built":
        return _end(state)
    return dict(state, stage="ready", process=None, slot=None, since=time.time())


def _ready(handle, job, folder, state, setting) -> dict:
    note = {"experiment": handle.experiment, "task": job["task"]}
    slot = _claim("solve", _desk(handle).slots, note)
    if slot is None:
        return state
    solve = folder / "solve"
    solve.mkdir(parents=True, exist_ok=True)
    built = _read(folder / "build" / RESULT)

    def launch():
        command = [sys.executable if part == "{python}" else part for part in built["solve"]["command"]]
        return hooks.spawn(command, cwd=solve, env=dict(os.environ, **{MARK: str(folder)}), log=solve / "solver-output.txt")

    state = _started(folder, state, "solve", slot, launch, note)
    if state["stage"] == "solve":
        _hold(slot, state["process"], note)
    return state


def _solve(handle, job, folder, state, setting) -> dict:
    note = {"experiment": handle.experiment, "task": job["task"]}
    if hooks.alive(state["process"]):
        built = _read(folder / "build" / RESULT) or {}
        limit = (built.get("solve") or {}).get("timeout_s") or setting.get("solve_timeout_s", 21600)
        if _overdue(state, limit):
            hooks.kill(state["process"])
            _free(state["slot"], note)
            return _end(state, lost="timeout")
        return state
    _free(state["slot"], note)          # 求解器不在了。它成没成，由内核的后处理去看
    ask = _ask(folder, "post", {"mode": "post", **_common(handle, job, folder, setting)})
    return _started(folder, dict(state, slot=None), "post", None,
                    lambda: hooks.run_kernel(handle.input_info("kernel").id, ask, folder / "post", wait=False), note)


def _post(handle, job, folder, state, setting) -> dict:
    if hooks.alive(state["process"]):
        if _overdue(state, setting.get("build_timeout_s", 3600)):
            hooks.kill(state["process"])
            return _end(state, lost="timeout")
        return state
    if _read(folder / "post" / RESULT) is None:
        return _end(state, lost=_gone(state["process"]))
    return _end(state)                  # 后处理说了什么、推导量是多少，由冻结的代码去看、去算


_STEPS = {"queued": _queued, "build": _build, "ready": _ready, "solve": _solve, "post": _post}


def _step(handle, job, folder: Path, state: dict, setting: dict) -> dict:
    while state["stage"] in _STEPS:
        if state.get("launching"):      # 上一遍断在“正要起进程”和“记下进程”之间：起来了的收掉，槽放掉，不再起第二个
            _end_strays(folder, state["launching"])
            _free(state.get("slot"), {"experiment": handle.experiment, "task": job["task"]})
            state = _end(state, lost="crashed")
        else:
            before = state["stage"]
            state = _STEPS[before](handle, job, folder, state, setting)
            if state["stage"] == before:
                break
        _save(folder, state)
    return state


def _result(folder: Path, state: dict) -> dict:
    return {"build": _read(folder / "build" / RESULT), "post": _read(folder / "post" / RESULT), "lost": state.get("lost"),
            "dirs": {name: str(folder / name) for name in DIRS if (folder / name).is_dir()}}


# ---------------------------------------------------------------- 接口

def begin(handle, jobs: list[dict]) -> None:
    """一轮开头：给这一轮要跑的作业各建一个干净的文件夹。"""
    for job in jobs:
        folder = folder_of(handle, job["task"])
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)
        _save(folder, {"stage": "queued", "since": time.time()})


def advance(handle, jobs: list[dict]) -> dict:
    """把还没结束的作业各往前推，返回每个作业现在的样子。"""
    setting = handle.input("export")
    machine = _desk(handle).name
    views = {}
    for job in jobs:
        folder = folder_of(handle, job["task"])
        state = _read(folder / STATE) or {"stage": "queued", "since": time.time()}
        state = _step(handle, job, folder, state, setting)
        ended = state["stage"] == "end"
        views[job["task"]] = {"stage": state["stage"], "machine": machine, "result": _result(folder, state) if ended else None}
    return views


def halt(handle, jobs: list[dict]) -> None:
    """把在跑的停掉，槽放掉。可以重复叫。"""
    for job in jobs:
        folder = folder_of(handle, job["task"])
        state = _read(folder / STATE)
        if not state:
            continue
        if state.get("process"):
            hooks.kill(state["process"])
        _free(state.get("slot"), {"experiment": handle.experiment, "task": job["task"]})
        _save(folder, dict(state, stage="stopped", process=None, slot=None))


def release(handle, job: dict) -> None:
    """这个作业该留的都留好了：把它占的地方清掉。清不掉（文件还被占着）就留着，不碍事。"""
    shutil.rmtree(folder_of(handle, job["task"]), ignore_errors=True)
