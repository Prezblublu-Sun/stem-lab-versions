"""操作台核心：你的每个动作、启动和停止、值守、追溯、检查、备份。

每个动作都是“查状态表、记、叫、记结果”，断在哪一步都留下读得懂的记录。
"""
import sys


def utf8_console() -> None:
    """把这个进程的标准输出和标准错误定成 UTF-8。每个命令行入口一开头都叫它。

    Windows 的控制台和管道默认不是 UTF-8：报错里只要有一个它写不出的字，进程就会在打印的时候死掉。
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
