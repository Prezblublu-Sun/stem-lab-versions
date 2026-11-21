"""A4 驱动：把 a4_rotfit_linux.py 与 joblist.json 放到 Linux 的 ~/mobo_toy_v2/adhoc/ml_eff/a4/（只写这个目录），
在 CPU 4–11、nice 19、≤ 4 进程下运行，再把结果取回研究日志的 plan/a4/。

不调用 remote.sync_code / put / launch；不碰 queue/results/code/data。
用法：
  python v2/a4_rotfit/a4_remote.py push
  python v2/a4_rotfit/a4_remote.py run --limit 2 --procs 1 --out probe.jsonl
  python v2/a4_rotfit/a4_remote.py run --procs 4
  python v2/a4_rotfit/a4_remote.py fetch
"""
from __future__ import annotations

import argparse
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import remote as R  # noqa: E402

RDIR = "~/mobo_toy_v2/adhoc/ml_eff/a4"
LOCAL_PLAN = pathlib.Path(r"H:/projects/application/research-log/neck_implant_2026-10-02/ml_efficiency_2026-10-22/plan")
LOCAL_OUT = LOCAL_PLAN / "a4"            # remote.fetch 解出的成员名以 a4/ 开头，所以解到 plan/ 下
PY = "~/mobo_toy_v2/.venv/bin/python"


def push():
    for f in ("a4_rotfit_linux.py", "joblist.json"):
        data = (HERE / f).read_bytes()
        R.sh(f"mkdir -p {RDIR} && cat > {RDIR}/{f}", stdin=data, timeout=60)
    print(R.sh(f"ls -la {RDIR}"))


def run(limit: int, procs: int, out: str, timeout: float):
    procs = min(max(procs, 1), 4)
    cmd = (f"cd {RDIR} && PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 "
           f"taskset -c 4-11 nice -n 19 {PY} a4_rotfit_linux.py --jobs joblist.json --out {out} --procs {procs}"
           + (f" --limit {limit}" if limit else "") + f" 2>&1 | tee -a {RDIR}/{pathlib.Path(out).stem}.log")
    print(R.sh(cmd, timeout=timeout))


def fetch():
    names = R.fetch("adhoc/ml_eff/a4", LOCAL_PLAN, timeout=600)
    print(f"fetched {len(names)} entries into {LOCAL_OUT}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["push", "run", "fetch", "ls"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--out", default="rotfit_rows.jsonl")
    ap.add_argument("--timeout", type=float, default=2400)
    a = ap.parse_args()
    if a.what == "push":
        push()
    elif a.what == "run":
        run(a.limit, a.procs, a.out, a.timeout)
    elif a.what == "fetch":
        fetch()
    else:
        print(R.sh(f"ls -la {RDIR}; tail -n 5 {RDIR}/*.log 2>/dev/null"))
