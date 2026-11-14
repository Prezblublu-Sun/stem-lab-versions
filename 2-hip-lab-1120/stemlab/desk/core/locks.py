"""busy(实验)：同一个实验同一时刻只有一处在动；watch_lock()：同一时刻只有一处在值守。

两把都是操作系统的文件锁，持锁的进程死了自动释放。启动、停止、值守都先拿 busy。
锁文件里记着持锁进程的进程号、创建时间和它在做什么，给人看：启动卡死的时候，照着它去结束进程。

顺序固定：busy 在最外；两条链的锁不嵌套；叫插件代码的时候不拿链的锁。
"""
from __future__ import annotations

import contextlib
import json
import os

import psutil

from stemlab.contract import Refused, layout
from stemlab.experiments import lock
from stemlab.hooks import local

_WIDTH = 256        # 锁文件里那一行记录定长，放锁时用空格盖掉，所以从不用截短文件


@contextlib.contextmanager
def _held(path, doing: str, timeout: float):
    with lock.hold(path, timeout) as fd:
        me = psutil.Process()
        note = json.dumps({"pid": me.pid, "created": me.create_time(), "doing": doing}).encode("ascii")
        _note(fd, note)
        try:
            yield
        finally:
            _note(fd, b"")


def _note(fd: int, note: bytes) -> None:
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, note.ljust(_WIDTH))


def busy(experiment: str, doing: str, timeout: float = 30.0):
    """拿住这个实验的 busy。timeout=0 是只试一次：拿不到就说明别处正在动它。

    没有这个实验就被拒：先看有没有，再去拿锁，不给不存在的实验凭空建一个文件夹。
    """
    if not layout.is_experiment_id(experiment) or not layout.record_file(experiment).exists():
        raise Refused(f"没有实验 {experiment!r}")
    return _held(layout.busy_lock(experiment), doing, timeout)


def watch_lock(timeout: float = 0.0):
    """拿住值守的锁。默认只试一次：已经有一处在值守，就不再起第二处。"""
    return _held(layout.watch_lock(), "watch", timeout)


def holder(path) -> dict | None:
    """锁文件里记着的持锁进程，另加它现在还在不在（alive）。没人拿着就是 None。

    持锁的进程是被结束的话，记录会留在文件里，这时 alive 是 False。
    """
    try:
        text = path.read_bytes().strip()
        note = json.loads(text) if text else None
    except (OSError, ValueError):
        return None
    return dict(note, alive=local.alive(note)) if note else None
