"""示范插件在远端跑的入口：python -m tests.plugins.demo.worker <作业文件夹> <秒数>

把 inputs/numbers.json 里的数加起来，磨蹭上那么多秒（一路写心跳），把结果写进 outputs/sum.json。
worker 只读 inputs/，只写 outputs/ 和状态文件，别的都不碰。它拿不到 handle。
"""
import json
import sys
import time
from pathlib import Path

from stemlab import hooks

LIBS = {"demo": "1.0"}


def main(job: str, seconds: str) -> int:
    folder = Path(job)
    numbers = json.loads((folder / "inputs" / "numbers.json").read_bytes())["numbers"]
    deadline = time.time() + float(seconds)
    while time.time() < deadline:
        hooks.remote.report(folder, "adding", libs=LIBS)
        time.sleep(0.2)
    (folder / "outputs" / "sum.json").write_text(json.dumps({"sum": sum(numbers)}), encoding="utf-8")
    hooks.remote.report(folder, "done", libs=LIBS, result="finished")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
