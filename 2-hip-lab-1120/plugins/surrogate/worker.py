"""【自由】在 Linux 上跑的入口：读输入、训练、打包、写状态文件。

    python -m plugins.surrogate.worker <作业文件夹>

作业文件夹里 inputs/job/ 是插件交过来的输入，产出写进 outputs/，状态写在 status.json（隔几秒一次心跳）。
派到 Linux 上是它，在操作台本机起进程也是它：两边走的是同一条路。
"""
from __future__ import annotations

import json
import os
import sys
import threading
import traceback
from pathlib import Path

import numpy as np

from plugins.surrogate import models, train
from stemlab import hooks

BEAT = 10.0


def main(argv=None) -> int:
    base = Path((argv or sys.argv[1:])[0])
    out = base / "outputs"
    out.mkdir(parents=True, exist_ok=True)
    libs, stage, over = {"numpy": np.__version__}, ["reading"], threading.Event()

    def report(name: str, result: str | None = None) -> None:
        stage[0] = name
        hooks.remote.report(base, name, libs, result)

    def beat() -> None:
        while not over.wait(BEAT):
            hooks.remote.report(base, stage[0], libs)

    report("reading")
    threading.Thread(target=beat, daemon=True).start()
    try:
        said = train.run(base / "inputs" / "job", out, report)
    except models.Diverged as error:
        said = {"status": "diverged", "reason": str(error)}
    except MemoryError as error:
        said = {"status": "env", "reason": f"内存不够：{error}"}
    except Exception as error:  # noqa: BLE001  训练出什么错都说出来
        said = {"status": "error", "reason": f"{type(error).__name__}: {error}", "trace": traceback.format_exc()[-1500:]}
    over.set()
    spare = out / "result.json.new"
    spare.write_bytes(json.dumps(said, ensure_ascii=False, default=float).encode("utf-8"))
    os.replace(spare, out / "result.json")
    report("done", said["status"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
