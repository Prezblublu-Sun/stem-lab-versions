"""【自由】建模、后处理经包的入口跑，求解经 spawn 起进程，按求解槽数排队；看每个作业走到哪：排队、出柄的模型、建模、求解、后处理。

接口见 plugin.py 开头：begin、advance、halt、release。接口不变，这个文件可以整个重写。
两种作业走同一套：参照包那条（fea.reference）建模、后处理都交给内核（run_kernel）；
fea.run 的作业（jobs.py 在作业里写了 "split": True）先叫柄空间包出柄的模型（run_stem，无植入物跳过这一步），
建模、后处理交给有限元包（run_fem），交给它们的 job.json 照冻结的 given.ask 拼。

一个作业在 work/jobs/<任务>/r<轮>/ 下有自己的文件夹：
    state.json            它走到哪了。只有这个文件读写它
    ask-stem/、stem/      fea.run 有植入物的：交给柄空间包的 job.json，和它的输出（柄的模型在 stem/model/）
    ask-build/、build/    交给内核（或有限元包）建模的 job.json，和建模的输出
    solve/                求解用的文件夹：建模把求解器的输入写在这里，求解器在这里跑
    ask-post/、post/      后处理
推导量不在这里算：作业结束后由冻结的 export.py 去叫推导量定义。

建模、求解、后处理都是脱离出去的进程，动作里不等它们：这一遍看它们还在不在，不在了就读结果、起下一步。

槽是整台机器共用的：槽文件夹里一个文件一个槽，两种槽：
    build-<n>.json   出柄的模型、建模和后处理共用，数目是 build_slots
    solve-<n>.json   求解，数目是机器清单里这台的 slots
所以两个实验同时跑，合起来也不会超过槽数。看槽、占槽、交接、放槽都在槽文件夹的一把锁里做。
槽文件里写着占它的进程，和“谁占的”：实验、任务、作业文件夹（带着轮号，认得出是哪一次执行）、占它做哪一步。
一个槽算空着，要两样都不在：槽文件里记的进程，和认得出是那个作业那一步起的进程（见 _strays）。
后一样是为了断在“起了进程、还没交接”的时候：槽文件里记的还是断掉的操作台，进程却在跑。
求解器自己结束了、它起的子进程（比如 Abaqus）还在算，也照“还占着”算：子进程带着作业的标记。
放槽只放还记在自己名下的，认的是作业文件夹：同一个任务以前那一次执行放不掉这一次的槽。
槽文件夹默认在 %LOCALAPPDATA%/stemlab/slots（别的系统是 ~/.local/state/stemlab/slots），
不放在临时文件夹里：系统清临时文件时会把它删掉，求了一半的槽就像空了。STEMLAB_SLOTS 可以另指。

起进程时先记“正要起”，起来了再记进程。断在这两步之间，下一遍把已经起来的那个收掉再算这个作业崩了：
求解带着环境变量 STEMLAB_JOB（这个作业的文件夹），建模、后处理的命令行最后两个参数是这个作业的 ask-<步>/ 和 <步>/，
认得准，不会碰别的进程。

收进程（超时、停止、断在半路）都要确认真的不在了才放槽。收不掉的不放槽：那个进程还占着它，
等它自己结束，槽就空出来。收不掉要说出来：记成这个实验的一条问题。

和这里有关的设定项。fea.run 照运行设定（声明在 running.py，都写全）；参照包那条照导出设定，都可以不写：
    build_slots        同时出柄的模型、建模、后处理的作业最多几个，默认 2
    build_timeout_s    一次出柄的模型、建模或后处理最多跑多久，默认 3600
    solve_timeout_s    一次求解最多跑多久，默认 21600；建模在 solve 里给了 timeout_s 的以它给的为准
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

from plugins.fea import given
from stemlab import hooks

if os.name == "nt":
    import msvcrt
else:
    import fcntl

STATE, JOB, RESULT = "state.json", "job.json", "result.json"
DIRS = ("stem", "build", "solve", "post")
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


def _implant(handle, job: dict) -> bool:
    """fea.run 的作业有没有植入物：填了柄空间包就有。"""
    return bool(job.get("split")) and handle.input_info("stem") is not None


def _job_for(handle, job: dict, folder: Path, step: str, setting: dict) -> dict:
    """交给包的 job.json。fea.run 的照冻结的 given.ask 拼；参照包那条照原来的写法。"""
    if not job.get("split"):
        return {"mode": step, **_common(handle, job, folder, setting)}
    if step == "stem":
        return given.ask(handle, job, "model")
    return given.ask(handle, job, step, stem=folder / "stem" if _implant(handle, job) else None, solve=folder / "solve")


def _launch(handle, job: dict, step: str, ask: Path, out: Path):
    """起这一步的包，不等它跑完。"""
    if not job.get("split"):
        return hooks.run_kernel(handle.input_info("kernel").id, ask, out, wait=False)
    if step == "stem":
        return hooks.run_stem(handle.input_info("stem").id, ask, out, wait=False)
    return hooks.run_fem(handle.input_info("fem").id, ask, out, wait=False)


def _setting(handle, jobs: list[dict]) -> dict:
    """排队、超时、归档用的那几项：fea.run 是运行设定的取值，参照包那条是导出设定。"""
    if any(job.get("split") for job in jobs):
        return handle.input("run")["values"]
    return handle.input("export")


def _desk(handle):
    return next(machine for machine in handle.machines if machine.role == "desk")


def _note(handle, job: dict, folder: Path, step: str | None = None) -> dict:
    """“谁占的”：实验、任务、作业文件夹（带着轮号，就是这一次执行），占槽时再写占它做哪一步。"""
    note = {"experiment": handle.experiment, "task": job["task"], "folder": str(folder)}
    return dict(note, stage=step) if step else note


def _say(handle, job: dict, text: str) -> None:
    """收不掉的进程要说出来：记成这个实验的一条问题。"""
    handle.problem(f"作业 {job['task']}：{text}", task=job["task"])


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


def _taken(path: Path) -> bool:
    """这个槽还占着没有：槽文件里记的进程在，或者它起的、认得出是那个作业那一步的进程还在。"""
    held = _read(path)
    try:
        if hooks.alive(held["process"]):
            return True
    except (TypeError, KeyError, ValueError):
        return time.time() - path.stat().st_mtime < 30     # 读不出来：刚写坏的先当它占着
    folder, step = held.get("folder"), held.get("stage")
    return bool(folder and step and _strays(Path(folder), step, held["process"]))


def _claim(kind: str, count: int, note: dict) -> str | None:
    """占一个槽。占到了返回槽文件的位置，没有空槽返回 None。"""
    with _locked() as base:
        for number in range(max(1, int(count))):
            path = base / f"{kind}-{number}.json"
            if path.exists() and _taken(path):
                continue
            _write(path, {"process": _me(), **note})                    # 空的，或者占它的进程都不在了
            return str(path)
    return None


def _hold(slot: str, process: dict, note: dict) -> None:
    """槽由刚起来的那个进程接着占：这个进程在，槽就不空。"""
    with _locked():
        _write(Path(slot), {"process": process, **note})


def _mine(held, note: dict) -> bool:
    """槽文件里记的是不是这一次执行。都写了作业文件夹的照文件夹认；没写的旧槽照实验和任务认。"""
    if not isinstance(held, dict):
        return False
    if held.get("folder") is not None and note.get("folder") is not None:
        return held["folder"] == note["folder"]
    return (held.get("experiment"), held.get("task")) == (note["experiment"], note["task"])


def _free(slot, note: dict) -> None:
    """放掉一个槽。只放还记在自己名下的：占槽的进程一结束，别的作业就可能已经把它占走了，那就不是自己的了。"""
    if slot:
        with _locked():
            if _mine(_read(Path(slot)), note):
                try:
                    Path(slot).unlink()
                except OSError:
                    pass


# ---------------------------------------------------------------- 进程

def _strays(folder: Path, stage: str, root=None) -> list:
    """认得出是这个作业这一步起的进程，连同它们起的子进程。

    求解认环境变量 STEMLAB_JOB，求解器再起的子进程也带着它；建模、后处理认命令行的最后两个参数
    （这个作业的 ask-<步>/ 和 <步>/）。
    root 是起它们的那个进程（起进程的操作台，或者这一步的进程自己），知道的话只在它和它的后代里认。
    Windows 上读别的进程的命令行、环境变量很慢（2026-11-16 在操作台这台上量过：扫一遍全机要三四秒），
    顺着父进程号往下找只要十几毫秒；Windows 上父进程没了，子进程记着的父进程号也不变。
    别的系统上父进程没了，子进程会被过继出去，顺着找不到，所以照旧扫全机，在那里读命令行、环境变量很快。
    """
    asked = [str(folder / f"ask-{stage}"), str(folder / stage)]
    found = []
    for process in (_family(root) if root and os.name == "nt" else psutil.process_iter()):
        if process.pid == os.getpid():
            continue
        try:
            if (process.cmdline() or [])[-2:] == asked or (stage == "solve" and process.environ().get(MARK) == str(folder)):
                found.append(process)
                found += process.children(recursive=True)
        except (psutil.Error, OSError):
            continue
    return list({process.pid: process for process in found}.values())


def _family(root: dict) -> list:
    """root 和它起的进程，一层层往下，只认不比 root 早起来的（进程号会被重用）。root 已经不在了也找得到它的后代。"""
    children: dict[int, list[int]] = {}
    for pid, parent in _parents().items():
        children.setdefault(parent, []).append(pid)
    pids, frontier = [int(root["pid"])], [int(root["pid"])]
    while frontier:
        frontier = [child for pid in frontier for child in children.get(pid, []) if child not in pids]
        pids += frontier
    found = []
    for pid in pids:
        try:
            process = psutil.Process(pid)
            if process.create_time() >= float(root["created"]) - 0.001:
                found.append(process)
        except (psutil.Error, OSError):
            continue
    return found


def _parents() -> dict[int, int]:
    """全机的进程号 -> 父进程号。psutil 在 Windows 上有一次快照拿到全部的办法，不在它公开的接口里；
    没有就退回逐个问（Windows 上要一两秒）。"""
    quick = getattr(getattr(psutil, "_psplatform", None), "ppid_map", None)
    if quick is not None:
        return dict(quick())
    return {process.pid: process.info["ppid"] for process in psutil.process_iter(["ppid"])}


def _end_strays(folder: Path, stage: str, root=None) -> bool:
    """收掉这个作业这一步起的进程。都确认不在了返回 True，还有收不掉的返回 False。"""
    found = _strays(folder, stage, root)
    for process in found:
        try:
            process.kill()
        except psutil.Error:
            pass
    psutil.wait_procs(found, timeout=10)
    return not _strays(folder, stage, root)


def _quiet(folder: Path, stage: str, process) -> bool:
    """这一步起的进程都不在了：它自己，和它起的、认得出是这个作业这一步的那些。"""
    return not hooks.alive(process) and not _strays(folder, stage, process)


def _stopped(folder: Path, stage: str, process, launcher=None) -> bool:
    """收掉这一步起的进程：它自己（记下了的话），和认得出是这个作业这一步起的那些。都确认不在了返回 True。

    还没记下进程（断在起进程的半路）的，launcher 是起它的那个操作台，在它的后代里找。
    """
    if process:
        hooks.kill(process)
    return _end_strays(folder, stage, process or launcher) and not (process and hooks.alive(process))


def _launcher(state: dict, note: dict):
    """断在起进程的半路时，起它的那个操作台：占槽时写进槽文件的进程。槽已经不是这一次执行的了就不知道（None）。"""
    held = _read(Path(state["slot"])) if state.get("slot") else None
    return held["process"] if _mine(held, note) and isinstance(held.get("process"), dict) else None


def _gone(process: dict) -> str:
    """进程没了又没留下结果：机器重启过就是环境的事，不然就是它自己崩了。"""
    return "restart" if psutil.boot_time() > process["created"] else "crashed"


# ---------------------------------------------------------------- 一步一步往前推

def _end(state: dict, lost: str | None = None) -> dict:
    return dict(state, stage="end", process=None, slot=None, lost=lost, launching=None, step=None)


def _overdue(state: dict, seconds) -> bool:
    return time.time() - state["since"] > float(seconds)


def _timed_out(handle, job, folder: Path, state: dict, stage: str) -> dict:
    """超过时限：收掉这一步的进程。确认收掉了才放槽；收不掉，槽不放，说出来。"""
    if _stopped(folder, stage, state["process"]):
        _free(state["slot"], _note(handle, job, folder))
    else:
        _say(handle, job, f"{stage} 超过时限，进程收不掉，还在跑；它占的槽没有放，等它自己结束")
    return _end(state, lost="timeout")


def _started(folder: Path, state: dict, stage: str, slot, launch, note: dict) -> dict:
    """起一个进程并记下来。先记“正要起”，起来了再记进程：断在中间，下一遍看得出来，不会起第二个。"""
    _save(folder, dict(state, launching=stage, slot=slot))
    try:
        process = launch()
    except Exception as error:  # noqa: BLE001  包的哈希不符、自检没过、命令起不来，都是这个作业的事
        _free(slot, note)
        return _end(state, lost=f"{stage} 起不来：{type(error).__name__}: {error}")
    return dict(state, stage=stage, process=process, slot=slot, since=time.time(), launching=None)


def _launched(folder: Path, state: dict, stage: str, slot, launch, note: dict) -> dict:
    """起这一步的进程，起来了就把槽交给它。"""
    state = _started(folder, state, stage, slot, launch, note)
    if state["stage"] == stage:
        _hold(slot, state["process"], note)
    return state


def _in_build_slot(handle, job, folder, state, setting, step: str) -> dict:
    """占一个建模槽，起这一步（stem、build 或 post）的包。没有空槽就还是原样，下一遍再来。"""
    note = _note(handle, job, folder, step)
    slot = _claim("build", setting.get("build_slots", 2), note)
    if slot is None:
        return state
    ask = _ask(folder, step, _job_for(handle, job, folder, step, setting))
    return _launched(folder, state, step, slot, lambda: _launch(handle, job, step, ask, folder / step), note)


def _queued(handle, job, folder, state, setting) -> dict:
    return _in_build_slot(handle, job, folder, state, setting, "stem" if _implant(handle, job) else "build")


def _stem(handle, job, folder, state, setting) -> dict:
    """柄空间包在出柄的模型。出好了、看着对，就等一个建模槽去建模；放不进去、出错、交出的不对，这个作业就结束了。"""
    if not _quiet(folder, "stem", state["process"]):
        if _overdue(state, setting.get("build_timeout_s", 3600)):
            return _timed_out(handle, job, folder, state, "stem")
        return state
    _free(state["slot"], _note(handle, job, folder))
    result = _read(folder / "stem" / RESULT)
    if result is None:
        return _end(state, lost=_gone(state["process"]))
    if result.get("status") != "ok" or given.stem_wrong(handle, job, folder / "stem"):
        return _end(state)              # 归哪个结局、为什么，由冻结的代码去看
    return dict(state, stage="modeled", process=None, slot=None, since=time.time())


def _modeled(handle, job, folder, state, setting) -> dict:
    return _in_build_slot(handle, job, folder, state, setting, "build")


def _build(handle, job, folder, state, setting) -> dict:
    if not _quiet(folder, "build", state["process"]):
        if _overdue(state, setting.get("build_timeout_s", 3600)):
            return _timed_out(handle, job, folder, state, "build")
        return state
    _free(state["slot"], _note(handle, job, folder))
    result = _read(folder / "build" / RESULT)
    if result is None:
        return _end(state, lost=_gone(state["process"]))
    if result.get("status") != "built":
        return _end(state)
    return dict(state, stage="ready", process=None, slot=None, since=time.time())


def _ready(handle, job, folder, state, setting) -> dict:
    note = _note(handle, job, folder, "solve")
    slot = _claim("solve", _desk(handle).slots, note)
    if slot is None:
        return state
    solve = folder / "solve"
    solve.mkdir(parents=True, exist_ok=True)
    built = _read(folder / "build" / RESULT)

    def launch():
        command = [sys.executable if part == "{python}" else part for part in built["solve"]["command"]]
        return hooks.spawn(command, cwd=solve, env=dict(os.environ, **{MARK: str(folder)}), log=solve / "solver-output.txt")

    return _launched(folder, state, "solve", slot, launch, note)


def _solve(handle, job, folder, state, setting) -> dict:
    if not _quiet(folder, "solve", state["process"]):     # 求解器自己，或者它起的子进程，还在算
        built = _read(folder / "build" / RESULT) or {}
        limit = (built.get("solve") or {}).get("timeout_s") or setting.get("solve_timeout_s", 21600)
        if _overdue(state, limit):
            return _timed_out(handle, job, folder, state, "solve")
        return state
    _free(state["slot"], _note(handle, job, folder))      # 求解都结束了。成没成，由内核的后处理去看
    return dict(state, stage="post", process=None, slot=None, since=time.time())     # 排队等建模槽去做后处理


def _post(handle, job, folder, state, setting) -> dict:
    """后处理和建模共用建模槽。还没起进程的，先占一个建模槽再起。"""
    if state.get("process") is None:
        return _in_build_slot(handle, job, folder, state, setting, "post")
    if not _quiet(folder, "post", state["process"]):
        if _overdue(state, setting.get("build_timeout_s", 3600)):
            return _timed_out(handle, job, folder, state, "post")
        return state
    _free(state["slot"], _note(handle, job, folder))
    if _read(folder / "post" / RESULT) is None:
        return _end(state, lost=_gone(state["process"]))
    return _end(state)                  # 后处理说了什么、推导量是多少，由冻结的代码去看、去算


_STEPS = {"queued": _queued, "stem": _stem, "modeled": _modeled, "build": _build, "ready": _ready, "solve": _solve, "post": _post}


def _step(handle, job, folder: Path, state: dict, setting: dict) -> dict:
    """一步一步往前推，推不动了就停。状态一变就落盘：后处理起了进程，阶段还是 post，也要存下来。"""
    while state["stage"] in _STEPS:
        if state.get("launching"):      # 上一遍断在“正要起进程”和“记下进程”之间：起来了的收掉，槽放掉，不再起第二个
            note = _note(handle, job, folder)
            if _stopped(folder, state["launching"], None, _launcher(state, note)):
                _free(state.get("slot"), note)
            else:
                _say(handle, job, f"{state['launching']} 起到一半操作台断了，起来的进程收不掉，还在跑；它占的槽没有放")
            state = _end(state, lost="crashed")
            _save(folder, state)
            continue
        before = state
        state = _STEPS[before["stage"]](handle, job, folder, state, setting)
        if state != before:
            _save(folder, state)
        if state["stage"] == before["stage"]:
            break
    return state


def _result(folder: Path, state: dict, job: dict) -> dict:
    made = {"build": _read(folder / "build" / RESULT), "post": _read(folder / "post" / RESULT), "lost": state.get("lost"),
            "dirs": {name: str(folder / name) for name in DIRS if (folder / name).is_dir()}}
    return dict(made, stem=_read(folder / "stem" / RESULT)) if job.get("split") else made


def _running_step(state: dict) -> str | None:
    """这个作业可能还有进程在跑的那一步：起到一半的、正在跑的，或者上次停止时没收掉的。"""
    if state.get("launching"):
        return state["launching"]
    if state.get("process"):
        return state.get("step") or state["stage"]
    return None


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
    if not jobs:
        return {}
    setting = _setting(handle, jobs)
    machine = _desk(handle).name
    views = {}
    for job in jobs:
        folder = folder_of(handle, job["task"])
        state = _read(folder / STATE) or {"stage": "queued", "since": time.time()}
        state = _step(handle, job, folder, state, setting)
        ended = state["stage"] == "end"
        views[job["task"]] = {"stage": state["stage"], "machine": machine, "result": _result(folder, state, job) if ended else None}
    return views


def halt(handle, jobs: list[dict]) -> None:
    """把在跑的停掉，槽放掉。可以重复叫。

    确认收掉了才放槽。收不掉的不放它的槽，第一次碰到时记一条问题；再叫一次会再收一次。
    """
    for job in jobs:
        folder = folder_of(handle, job["task"])
        state = _read(folder / STATE)
        if not state:
            continue
        step, note = _running_step(state), _note(handle, job, folder)
        if step is None or _stopped(folder, step, state.get("process"), _launcher(state, note)):
            _free(state.get("slot"), note)
            _save(folder, dict(state, stage="stopped", process=None, slot=None, launching=None, step=None, stuck=False))
            continue
        if not state.get("stuck"):
            _say(handle, job, f"停不下来：{step} 的进程收不掉，还在跑；它占的槽没有放。再停一次会再试")
        _save(folder, dict(state, stage="stopped", step=step, stuck=True))


def release(handle, job: dict) -> None:
    """这个作业该留的都留好了：把它占的地方清掉。清不掉（文件还被占着）就留着，不碍事。"""
    shutil.rmtree(folder_of(handle, job["task"]), ignore_errors=True)
