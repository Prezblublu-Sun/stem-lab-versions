"""在指定的那一步之后立刻退出的工人：python -m tests.crash.worker <做什么> <断在哪> <参数>

    start <断在哪> <实验>       启动这个实验，断在：
        frozen          记下 frozen 之后（第 6 步之后）
        round_opened    记下 round_opened 之后（第 7 步之后）
        plugin_start    插件的启动返回之后、记 called 之前（第 8 步之后）
        called          记下 called 之后（第 9 步之后）
    stop called <实验>          停止这个实验，断在记下 called（停成了）之后、收尾之前
    start 也可以用下面发布的四个断点：插件在启动里交产物的时候断
    poll <断在哪> <实验>        叫一次轮询，在发布产物时断在：
        moved           文件夹移进 outputs/ 之后（第 3 步之后）
        read_only       设成只读之后（第 4 步之后）
        registered      登记之后（第 5 步之后）
        output          记下 output 之后（第 6 步之后）
    register placed <文件夹>    复制着登记一个文件夹，断在内容放到位之后、上链之前

退出用 os._exit：不跑 finally，不放锁，和进程被杀、机器断电一样。退出码是 9。
"""
from __future__ import annotations

import os
import sys

from stemlab.desk.core import start
from stemlab.experiments import log
from stemlab.hooks import call
from stemlab.registry import register

DIED = 9


def die_after(module, name: str, when=lambda result: True) -> None:
    """把 module.name 换成：照原样做完，然后（when 说是的话）立刻退出。"""
    original = getattr(module, name)

    def wrapped(*args, **kwargs):
        result = original(*args, **kwargs)
        if when(result):
            os._exit(DIED)
        return result

    setattr(module, name, wrapped)


def die_after_entry(name: str) -> None:
    die_after(log, "append", lambda entry: entry["entry"] == name)


def main(what: str, where: str, target: str) -> int:
    if what == "register":
        die_after(register, "rename")
        register.register_external("report", "interrupted", source=target, note="登记到一半断掉", by="crash")
        return 0
    if where in ("frozen", "round_opened", "called", "output"):
        die_after_entry(where)
    elif where == "plugin_start":
        die_after(call, "call")
    elif where == "moved":
        die_after(register, "rename")
    elif where == "read_only":
        die_after(register, "read_only")
    elif where == "registered":
        die_after(register, "register_output")
    else:
        raise SystemExit(f"不认识的断点：{where}")
    {"start": start.start, "stop": start.stop, "poll": start.poll}[what](target)
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
