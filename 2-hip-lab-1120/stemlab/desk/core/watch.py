"""值守：每隔一段时间看一遍所有没结束的实验。

    once()        看一遍
    run(间隔)     一直值守
    status()      现在有没有在值守，是哪个进程

对每个实验：拿 busy，叫插件的轮询，插件借这次调用报任务、交产物、报问题、说做完；然后对一次账。
启动中而做启动的进程不在了的，记成启动失败。一个实验出什么事都不耽误别的实验。

run 分两层。外面一层只拿着值守的锁、看着里面那一层；里面一层才看实验、叫插件，所以它里面装着插件的代码。
插件的代码在它起来之后变了，它就退出，外面用新的代码重新起一个：值守从不拿旧代码接着跑。
一轮里不换代码：新起的那一层去轮询代码中途换了的那一轮，会被拒，记成那个实验的问题（见 hooks/call.py）。
里面那一层卡死了（插件的动作不返回），结束它就行，外面会重新起。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

import psutil

from stemlab.contract import Refused, layout, states
from stemlab.desk import core
from stemlab.desk.core import locks, start
from stemlab.experiments import reader, view
from stemlab.hooks import load, local

RESTART = 75        # 里面那一层用这个退出码说：插件的代码变了，请重新起我


def _pass() -> dict:
    """看一遍，不拿值守的锁。返回 {实验: 这一遍它怎么样了}，没什么可看的实验不在里面。"""
    seen = {}
    for experiment in reader.all_ids():
        try:
            status = view.view(experiment)
            if not (states.can("poll", status) or states.can("start_error", status)):
                continue
            result = start.poll(experiment, wait=False)
        except Refused as error:
            seen[experiment] = f"跳过：{error}"
        except LookupError:
            continue                                # 发了号却没有记录的空号
        except Exception as error:  # noqa: BLE001  一个实验出什么事都不耽误别的
            seen[experiment] = f"出错：{type(error).__name__}: {error}"
        else:
            seen[experiment] = "看过了" if result is None or result.ok else f"插件出错：{result.error}"
    return seen


def once() -> dict:
    """看一遍所有没结束的实验。已经有一处在值守就被拒。"""
    with locks.watch_lock():
        return _pass()


def _inner(interval: float, outer: dict) -> int:
    """里面那一层：一遍一遍地看，直到插件的代码变了，或者外面那一层不在了。"""
    while True:
        if not local.alive(outer):
            return 0                                # 外面那一层被结束了：值守的锁已经放掉，这里不再接着看
        if load.stale():
            return RESTART
        seen = _pass()
        if seen:
            print(time.strftime("%H:%M:%S"), " ".join(f"{name}：{what}" for name, what in seen.items()), flush=True)
        time.sleep(interval)


def run(interval: float = 10.0) -> None:
    """一直值守，直到被结束（Ctrl+C）。同一时刻只有一处在值守：已经有了就被拒。"""
    # 把自己的进程号和创建时间告诉里面那一层。不能让它去问“我的父进程”：
    # Windows 的虚拟环境里 python.exe 是个转发器，里面那一层的父进程是转发器，不是这里
    me = psutil.Process()
    command = [sys.executable, "-m", "stemlab.desk.core.watch", "--inner", str(interval),
               "--outer", str(me.pid), repr(me.create_time())]
    env = dict(os.environ, PYTHONUTF8="1")
    with locks.watch_lock():
        while True:
            code = subprocess.call(command, cwd=layout.repo_root(), env=env)
            if code != RESTART:
                print(f"值守里面那一层退出了（退出码 {code}），{interval} 秒后重新起", flush=True)
                time.sleep(interval)


def status() -> dict | None:
    """现在拿着值守锁的进程：pid、created、alive。没有在值守就是 None。"""
    return locks.holder(layout.watch_lock())


def main(argv=None) -> int:
    core.utf8_console()
    parser = argparse.ArgumentParser(prog="python -m stemlab.desk.core.watch", description="值守")
    parser.add_argument("--interval", type=float, default=10.0, help="每隔多少秒看一遍")
    parser.add_argument("--once", action="store_true", help="只看一遍")
    parser.add_argument("--inner", type=float, metavar="间隔", help="里面那一层，由 run 自己起，不是给人用的")
    parser.add_argument("--outer", nargs=2, metavar=("进程号", "创建时间"), help="外面那一层是谁，由 run 自己给")
    args = parser.parse_args(argv)
    try:
        if args.inner is not None:
            return _inner(args.inner, {"pid": int(args.outer[0]), "created": float(args.outer[1])})
        if args.once:
            for name, what in once().items():
                print(f"{name}：{what}")
            return 0
        run(args.interval)
    except Refused as error:
        print(f"被拒：{error}")
        return 1
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
