"""在内存上限（外层 ulimit -v）下单独出模两个疑似把建模服务撑爆内存的作业，看哪一个失控、失控在哪一步。
成功的会像正常 prep 一样写 READY；失控的在 ulimit 下应抛 MemoryError → FAILED.json（而不是被 OOM killer 杀掉整个进程池）。"""
import pathlib
import resource
import sys
import time

CODE = pathlib.Path.home() / "mobo_toy_v2" / "code"
sys.path.insert(0, str(CODE)); sys.path.insert(0, str(CODE / "v2"))
import jobs as J  # noqa: E402

JOBS = ["collar_neck_circ_L25_w4_f5e42375", "collar_neck_asym_L25_w4_bccbecec"]
print("RLIMIT_AS", resource.getrlimit(resource.RLIMIT_AS), flush=True)
for j in JOBS:
    t0 = time.time()
    try:
        r = J.prep(j)
    except Exception as e:                                           # noqa: BLE001
        r = f"EXC {type(e).__name__}: {str(e)[:300]}"
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6
    print(f"{j}: {r}  ({time.time() - t0:.0f} s, max RSS so far {rss:.1f} GB)", flush=True)
    f = J.QROOT / j / "FAILED.json"
    if f.exists():
        print("  FAILED.json:", f.read_text()[:600], flush=True)
