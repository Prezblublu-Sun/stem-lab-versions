"""实验记录的锁，和发号的锁。

锁的是单独的 .lock 文件，不锁链文件本身：Windows 的文件锁是强制的，别的进程读写被锁的文件会失败，
锁了链文件，仪表盘就读不了它。锁是操作系统的文件锁，持锁的进程死了自动释放。

同一把锁不能在同一个进程里套着拿两次，所以两条链的锁不嵌套。
（登记那一块有一份同样的 hold：两块同层、互不相用，所以各写一份。）
"""
from __future__ import annotations

import contextlib
import os
import time

from stemlab.contract import Refused, layout

if os.name == "nt":
    import msvcrt
else:
    import fcntl

_FAR = 1 << 30      # 锁的是文件里很靠后的一个字节，所以文件开头写的东西别的进程照样能读


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
def hold(path, timeout: float = 30.0):
    """拿住 path 这把锁，出来时放掉。timeout 秒内拿不到就被拒；timeout=0 是只试一次。给出的是锁文件的描述符。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0))
    try:
        deadline = time.monotonic() + timeout
        while not _try_lock(fd):
            if time.monotonic() >= deadline:
                raise Refused(f"拿不到锁 {path.name}：别处正拿着它")
            time.sleep(0.02)
        try:
            yield fd
        finally:
            _unlock(fd)
    finally:
        os.close(fd)


def writing(experiment: str, timeout: float = 30.0):
    """这个实验记录的锁。往它的 record.jsonl 追加之前拿它。"""
    return hold(layout.record_lock(experiment), timeout)


def issuing(timeout: float = 30.0):
    """发号的锁。往 issued.jsonl 追加之前拿它。"""
    return hold(layout.issued_lock(), timeout)
