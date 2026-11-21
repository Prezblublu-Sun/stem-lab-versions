"""本机的脱离进程：spawn 起一个，alive 查在不在，kill 结束它。

一个进程用它的进程号和创建时间认：{"pid": ..., "created": ...}。这是个普通的 JSON 对象，
插件可以把它存进自己的 work/，下一次 poll 再拿出来问。

两条 Windows 上写错了不会报错、只会出事的写法都在这里：
    查进程在不在，不用 os 模块里发信号的那个函数：在 Windows 上它不是探测，会把进程杀掉。
    用 psutil，并比创建时间，防进程号被重用。
    起进程要脱离父进程：关掉终端、操作台退出，求解照样跑。两个系统写法不同。
"""
from __future__ import annotations

import os
import subprocess
import threading

# 起一个要等它结果的子进程（git、ssh、带代码的包）时带上它：操作台没有控制台时，不在桌面上弹出窗口
QUIET = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def _psutil():
    """psutil 只在真的起、查、杀进程的时候才用到。

    远端的 worker 只读输入、写产物和状态文件，用不到这里；所以它 import 挂点的门面时不要求装了 psutil。
    """
    import psutil
    return psutil


def spawn(command, cwd=None, env=None, log=None) -> dict:
    """起一个脱离父进程的本机进程，立刻返回它的进程号和创建时间。

    command 是参数的列表。log 给一个文件的位置，进程的输出就追加到那里；不给就丢掉。
    """
    options = {"cwd": cwd, "env": env, "stdin": subprocess.DEVNULL, "close_fds": True}
    if os.name == "nt":
        # 自己一个不显示的控制台、自己一个进程组：父进程的终端关了、按了 Ctrl+C 都轮不到它，
        # 它再起的子进程也不会在桌面上弹出窗口
        detached = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        attempts = [detached | subprocess.CREATE_BREAKAWAY_FROM_JOB, detached]     # 父进程在作业对象里时先试着脱出来
    else:
        options["start_new_session"] = True
        attempts = [0]
    output = open(log, "ab") if log else subprocess.DEVNULL
    try:
        for number, flags in enumerate(attempts):
            try:
                child = subprocess.Popen(list(command), stdout=output, stderr=subprocess.STDOUT,
                                         creationflags=flags, **options)
                break
            except PermissionError:
                if number == len(attempts) - 1:
                    raise
    finally:
        if log:
            output.close()
    created = _psutil().Process(child.pid).create_time()
    # 不等它：它是脱离出去的。旁边一个不拦着退出的线程等它结束、替它收尾，
    # 免得它在 Linux 上留成僵尸进程，也免得这边退出时报“子进程还在跑”
    threading.Thread(target=child.wait, name=f"reap-{child.pid}", daemon=True).start()
    return {"pid": child.pid, "created": created}


def _find(process):
    psutil = _psutil()
    try:
        found = psutil.Process(int(process["pid"]))
        if abs(found.create_time() - float(process["created"])) > 0.001:
            return None                                 # 进程号被别的进程重用了
        return None if found.status() == psutil.STATUS_ZOMBIE else found
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def alive(process) -> bool:
    """这个进程还在不在。进程号对、创建时间也对才算在。"""
    return _find(process) is not None


def kill(process) -> None:
    """结束这个进程和它起的子进程。已经不在了就什么都不做，所以可以重复叫。"""
    found = _find(process)
    if found is not None:
        end(found.pid)


def end(pid: int) -> None:
    """结束进程号是 pid 的进程，连同它起的所有进程。只用在我们自己刚起、还拿着的进程上。"""
    psutil = _psutil()
    try:
        root = psutil.Process(pid)
        family = root.children(recursive=True) + [root]
    except psutil.NoSuchProcess:
        return
    for member in family:
        try:
            member.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    psutil.wait_procs(family, timeout=10)
