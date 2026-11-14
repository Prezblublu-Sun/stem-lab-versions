"""并发和持锁测试用的工人：python -m tests.blocks.parallel <做什么> <参数...>

    register <前缀> <次数>        等发令枪，然后连着登记这么多个值
    append <实验> <名字> <次数>   等发令枪，然后往这个实验的记录里连着记这么多条备注
    create <名字> <次数>          等发令枪，然后连着新建这么多个实验
    hold <哪把锁> [<实验>]        拿住一把锁，打印 held，然后一直拿着，直到被结束
    start <实验>                  等发令枪，然后启动这个实验，打印 started 或 refused
    spawn <秒数> stay|leave       起一个脱离出去的子进程（睡这么多秒），打印它，然后留着或马上退出
"""
from __future__ import annotations

import json
import sys
import time

from stemlab.contract import Refused, layout
from stemlab.desk.core import locks, start
from stemlab.experiments import lock as record_lock
from stemlab.experiments import log
from stemlab.hooks import local
from stemlab.registry import lock as register_lock
from stemlab.registry import register
from tests.contract import samples


def wait_for_go() -> None:
    go = layout.data_root() / "go"
    while not go.exists():
        time.sleep(0.005)


def main(what: str, *args: str) -> int:
    if what == "register":
        prefix, count = args
        wait_for_go()
        for n in range(int(count)):
            register.register_external("setting", f"{prefix}-{n}", value={"n": n}, note="并发登记", by=prefix)
    elif what == "append":
        experiment, name, count = args
        wait_for_go()
        for n in range(int(count)):
            log.append(experiment, {"entry": "noted", "text": f"{name} {n}"})
    elif what == "create":
        name, count = args
        tables = {"inputs": samples.INPUTS, "outputs": samples.OUTPUTS, "outcomes": samples.OUTCOMES}
        wait_for_go()
        for n in range(int(count)):
            log.create("demo.echo", tables, note=f"{name} {n}")
    elif what == "hold":
        held = {"register": register_lock.writing, "issued": record_lock.issuing,
                "record": lambda: record_lock.writing(args[1]),
                "busy": lambda: locks.busy(args[1], "测试里拿着"), "watch": locks.watch_lock}[args[0]]
        with held():
            print("held", flush=True)
            time.sleep(600)
    elif what == "start":
        wait_for_go()
        try:
            start.start(args[0])
            print("started", flush=True)
        except Refused as error:
            print(f"refused {error}", flush=True)
    elif what == "spawn":
        child = local.spawn([sys.executable, "-c", "import time; time.sleep(float(%s))" % args[0]])
        print(json.dumps(child), flush=True)
        if args[1] == "stay":
            time.sleep(600)
    else:
        raise SystemExit(f"不认识的工种：{what}")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
