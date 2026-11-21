"""远程执行。系统只用“操作台连 worker”这一个方向：worker 不主动连回来，也不往 data/ 里写。

操作台这一边，在插件的动作里用，都要给 handle 和机器清单里 worker 的名字：
    push(handle, 机器, 输入)       上传这一轮的代码快照和输入的副本
    start(handle, 机器, 模块)      在远端起一个脱离会话的 worker，立刻返回
    status(handle, 机器)           读远端的状态文件：阶段、心跳、环境、结局
    pull(handle, 机器)             把产物取回到插件的 work/，把远端的环境记进这一轮的来历
    stop(handle, 机器)             结束远端的 worker
worker 那一边，在远端跑，拿不到 handle：
    report(作业文件夹, 阶段, ...)  写状态文件

远端一轮一个作业文件夹 <作业根目录>/E0012/r1/：
    code/         这一轮上传的快照：stemlab/ 和本插件的文件夹
    inputs/       输入的副本
    outputs/      产物，等着被取回
    status.json   阶段、心跳、环境、结局
    log.txt       worker 的输出

直接调系统的 ssh 和 scp。连不上时退避重试；还是连不上就报 Unreachable：这不是任务失败，下一遍再试。
"""
from __future__ import annotations

import json
import os
import platform
import re
import shlex
import shutil
import socket
import subprocess
import tarfile
import threading
import time
from pathlib import Path

from stemlab.contract import Refused, hashing, layout, machines, states
from stemlab.experiments import log, view
from stemlab.hooks import load, local

RETRIES = (1.0, 4.0, 15.0)      # 连不上时隔多少秒再试
STOP_WAIT = 10                  # 停止时发了 TERM 之后等它自己收尾的秒数，过了还在就强杀
_QUIET = local.QUIET            # 不在桌面上弹出窗口


class Unreachable(Refused):
    """连不上远端。不是任务失败：这一遍先不动，下一遍再试。"""


# ---------------------------------------------------------------- ssh 和 scp

def _tool(machine: machines.Machine, name: str) -> str:
    return str(Path(machine.bin) / name) if machine.bin else name


def _run(command: list[str], timeout: float, where: str, again: bool = True) -> bytes:
    """跑一条 ssh 或 scp。连不上（退出码 255，或者到时间没有回应）时退避重试，还是不行就报 Unreachable。

    again=False 用在重做一遍会出事的命令上：连接断的时候它在远端可能已经开始了，所以只试一次。
    """
    for wait in (*RETRIES, None) if again else (None,):
        try:
            done = subprocess.run(command, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL,
                                  check=False, **_QUIET)
            code, said = done.returncode, done.stderr.decode("utf-8", "replace").strip()
        except subprocess.TimeoutExpired:
            code, said = 255, f"等了 {timeout} 秒没有回应"
        except OSError as error:
            raise Refused(f"起不了 {command[0]}：{error}") from None
        if code == 0:
            return done.stdout
        if code != 255:
            raise Refused(f"{where} 上的命令出错了（退出码 {code}）：{said[-600:]}")
        if wait is None:
            raise Unreachable(f"连不上 {where}：{said[-300:]}")
        time.sleep(wait)
    raise AssertionError("到不了这里")


def ssh(machine: machines.Machine, script: str, timeout: float = 120.0, again: bool = True) -> bytes:
    """在远端跑一段 shell，返回它的输出。重做一遍会出事的命令给 again=False。"""
    command = [_tool(machine, "ssh"), "-p", str(machine.port), *machine.options, machine.ssh, script]
    return _run(command, timeout, machine.name, again)


def _scp(machine: machines.Machine, source: str, target: str, timeout: float) -> None:
    command = [_tool(machine, "scp"), "-q", "-P", str(machine.port), *machine.options, source, target]
    _run(command, timeout, machine.name)


def upload(machine: machines.Machine, local, remote_path: str, timeout: float = 3600.0) -> None:
    """把本机的一个文件传到远端。"""
    _scp(machine, str(local), f"{machine.ssh}:{remote_path}", timeout)


def download(machine: machines.Machine, remote_path: str, local, timeout: float = 3600.0) -> None:
    """把远端的一个文件取回本机。"""
    _scp(machine, f"{machine.ssh}:{remote_path}", str(local), timeout)


def read_machines() -> tuple:
    """仓库根目录的机器清单。还没有这份清单就是空的。"""
    path = layout.repo_root() / "machines.json"
    if not path.is_file():
        return ()
    return machines.parse_machines(json.loads(path.read_bytes()))


def worker(name: str, listed=None) -> machines.Machine:
    """机器清单里叫这个名字的 worker。"""
    for machine in (read_machines() if listed is None else listed):
        if machine.name == name and machine.role == machines.WORKER:
            return machine
    raise Refused(f"机器清单里没有叫 {name} 的 worker")


def job_dir(given, machine: machines.Machine) -> str:
    """这个实验这一轮在远端的作业文件夹。"""
    return f"{machine.job_root.rstrip('/')}/{given.experiment}/r{given.round.number}"


# ---------------------------------------------------------------- 操作台这一边

def snapshot(given) -> Path:
    """打这一轮的代码快照：stemlab/ 和本插件的文件夹，打成一个 tar 放在 work/ 里。

    这一轮记的插件哈希必须就是打进去的这一份：开轮之后插件的代码变过，就被拒。
    """
    given._allow_write()
    plugin = given.round.provenance["plugin"]
    if load.plugin_hash(plugin) != states.recorded_code(view.view(given.experiment).rounds[-1]):
        raise Refused("盘上插件的代码不是这一轮记下的那一份，不能拿去远端跑。停掉，重新启动一轮")
    root, parts = layout.repo_root(), layout.plugins_package().split(".")
    target = given.work_dir / f"snapshot-r{given.round.number}.tar"
    with tarfile.open(target, "w") as tar:
        _add_tree(tar, root / "stemlab", "stemlab")
        for depth in range(1, len(parts) + 1):          # 插件所在的包一路上的 __init__.py
            init = root.joinpath(*parts[:depth], "__init__.py")
            if init.is_file():
                tar.add(init, arcname="/".join(parts[:depth]) + "/__init__.py")
        _add_tree(tar, load.plugins_dir() / plugin, "/".join([*parts, plugin]))
    return target


def _add_tree(tar: tarfile.TarFile, folder: Path, prefix: str) -> None:
    for rel in hashing.list_tree(folder, ignore=load.IGNORE):
        tar.add(folder / rel, arcname=f"{prefix}/{rel}")


def push(given, machine_name: str, inputs: dict) -> str:
    """上传这一轮的代码快照和输入的副本，返回远端的作业文件夹。

    inputs 是 名字 -> 本机的一个文件或文件夹；到了远端，它在 inputs/名字。重复上传会把上一次的盖掉。
    """
    machine, code = worker(machine_name, given.machines), snapshot(given)
    job = job_dir(given, machine)
    bundle = given.work_dir / f"inputs-r{given.round.number}.tar"
    with tarfile.open(bundle, "w") as tar:
        for name, source in inputs.items():
            if not layout.is_label(name):
                raise Refused(f"输入在远端的名字要用 ASCII 的字母、数字和 . _ -：{name!r}")
            tar.add(source, arcname=name)
    place = shlex.quote(job)
    ssh(machine, f"mkdir -p {place}")
    upload(machine, code, f"{job}/snapshot.tar")
    upload(machine, bundle, f"{job}/inputs.tar")
    # 解开这一步只试一次、等得久一点：连接断了它在远端可能还在解，再来一遍会和它撞在一起
    ssh(machine, f"cd {place} && rm -rf code inputs outputs status.json pid && mkdir -p code inputs outputs"
                 " && tar -xf snapshot.tar -C code && tar -xf inputs.tar -C inputs && rm -f snapshot.tar inputs.tar",
        timeout=3600.0, again=False)
    code.unlink(), bundle.unlink()
    return job


def _running(place: str) -> str:
    """一段 shell：作业文件夹的 pid 文件里记着的那个进程还在，而且确实是这个作业的 worker（防进程号被重用）。"""
    return f'p=$(cat {place}/pid 2>/dev/null) && grep -qa -- {place} "/proc/$p/cmdline" 2>/dev/null'


def start(given, machine_name: str, module: str, *arguments: str) -> None:
    """在远端起一个脱离会话的 worker，立刻返回：<那台机器的 python> -m 模块 作业文件夹 其余参数。

    它在作业文件夹的 code/ 里跑，输出进 log.txt。关掉这边的终端、断开 SSH，它照样跑。
    这个作业的 worker 已经在跑的话不再起第二个，所以连接断了重试、或者重复叫，都不会多出一个来。
    """
    given._allow_write()
    machine = worker(machine_name, given.machines)
    job = job_dir(given, machine)
    place = shlex.quote(job)
    command = " ".join(shlex.quote(part) for part in [machine.python, "-m", module, job, *arguments])
    ssh(machine, f"cd {place}/code && if {_running(place)}; then true; else"
                 f" (PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 setsid nohup {command}"
                 f" >> {place}/log.txt 2>&1 < /dev/null & echo $! > {place}/pid); fi")


def status(given, machine_name: str) -> dict | None:
    """读远端的状态文件。worker 还没写过就是 None。

    状态靠读状态文件，不靠查进程号。返回里另加 age：最后一次心跳到现在过了多少秒，按远端自己的钟算，
    所以两台机器的钟差多少都不要紧。
    """
    machine = worker(machine_name, given.machines)
    out = ssh(machine, f"cat {shlex.quote(job_dir(given, machine))}/status.json 2>/dev/null; echo; date -u +%s.%N")
    text, _, now = out.decode("utf-8").rstrip().rpartition("\n")
    if not text.strip():
        return None
    found = json.loads(text)
    return dict(found, age=float(now) - found["heartbeat"])


def pull(given, machine_name: str, name: str = "pulled") -> Path:
    """把远端 outputs/ 里的东西取回到 work/ 下，返回取回来的文件夹。远端的环境由这里记进这一轮的来历。

    取回来放在 work/<name>-r<轮号>/；那里原来有东西就先清掉。name 只是一个名字，不能带路径。
    """
    given._allow_write()
    if not layout.is_label(name):
        raise Refused(f"取回来放的地方要用一个名字（ASCII 的字母、数字和 . _ -），不能是路径：{name!r}")
    machine = worker(machine_name, given.machines)
    job = job_dir(given, machine)
    ssh(machine, f"cd {shlex.quote(job)} && tar -cf outputs.tar -C outputs .", timeout=3600.0, again=False)
    bundle = given.work_dir / f"{name}-r{given.round.number}.tar"
    target = given.work_dir / f"{name}-r{given.round.number}"
    download(machine, f"{job}/outputs.tar", bundle)
    if target.exists():
        shutil.rmtree(target)
    with tarfile.open(bundle) as tar:
        tar.extractall(target, filter="data")
    bundle.unlink()

    found = status(given, machine_name)
    noted = any(extra["source"] == "remote" for extra in view.view(given.experiment).rounds[-1].extra)
    if found and found.get("env") and not noted:
        log.append(given.experiment, {"entry": "provenance", "round": given.round.number, "source": "remote",
                                      "info": found["env"]})
    return target


def stop(given, machine_name: str) -> None:
    """结束远端的 worker 和它起的进程，并确认停住了。已经不在了就什么都不做，所以可以重复叫。

    先对它那一组发 TERM，让它自己收尾；等 STOP_WAIT 秒还在，就发 KILL；再查一遍还在，就报错：
    插件的停止于是没停成，核心不记“停止”，实验还是运行中，可以再停一次。
    """
    given._allow_write()
    machine = worker(machine_name, given.machines)
    alive = _running(shlex.quote(job_dir(given, machine)))
    try:
        ssh(machine, f'if {alive}; then kill -TERM -- "-$p" 2>/dev/null;'
                     f' for i in $(seq {STOP_WAIT * 5}); do sleep 0.2; {alive} || exit 0; done;'
                     f' kill -KILL -- "-$p" 2>/dev/null; sleep 1;'
                     f' if {alive}; then echo "pid $p still running after TERM and KILL" >&2; exit 3; fi; fi; true',
            timeout=STOP_WAIT + 60.0)
    except Unreachable:
        raise
    except Refused as error:
        raise Refused(f"远端的 worker 没停住：{error}") from None


# ---------------------------------------------------------------- worker 那一边

_ENVIRONMENT: dict | None = None


def _environment() -> dict:
    """这台机器的环境：主机名、Python 版本、CUDA 和驱动、GPU 型号。没有 GPU 的那几项是 None。"""
    global _ENVIRONMENT
    if _ENVIRONMENT is None:
        gpu = driver = cuda = None
        try:
            asked = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
                                   capture_output=True, timeout=30, check=False, **_QUIET)
            first = asked.stdout.decode("utf-8", "replace").strip().splitlines()[:1]
            if asked.returncode == 0 and first:
                gpu, driver = (part.strip() for part in first[0].split(",")[:2])
                banner = subprocess.run(["nvidia-smi"], capture_output=True, timeout=30, check=False, **_QUIET)
                found = re.search(r"CUDA Version:\s*([0-9.]+)", banner.stdout.decode("utf-8", "replace"))
                cuda = found.group(1) if found else None
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass
        _ENVIRONMENT = {"host": socket.gethostname(), "python": platform.python_version(),
                        "cuda": cuda, "driver": driver, "gpu": gpu}
    return _ENVIRONMENT


def report(job, stage: str, libs: dict | None = None, result: str | None = None, **more) -> None:
    """worker 用它写状态文件：阶段、心跳、环境、结局。隔一阵叫一次，就是心跳。

    libs 写关键库的版本，比如 {"torch": torch.__version__}。result 在做完时给：一个结局名。
    先写到旁边再换过去，所以读的一方不会读到半截。worker 只碰自己的作业文件夹。
    """
    job = Path(job)
    body = {"stage": stage, "heartbeat": time.time(), "result": result, "env": dict(_environment(), libs=libs or {}),
            **more}
    scratch = job / f"status.json.{os.getpid()}.{threading.get_ident()}.tmp"     # 各线程各写各的，不互相踩
    scratch.write_bytes(hashing.canonical(body) + b"\n")
    os.replace(scratch, job / "status.json")
