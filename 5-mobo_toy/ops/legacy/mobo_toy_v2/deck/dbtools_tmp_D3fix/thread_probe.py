"""Does running tpl_record.py as a script (the CLI) give single-threaded BLAS when no *_NUM_THREADS variable is set?
Runs the CLI with --help only (imports everything, computes nothing), then reports the BLAS thread pools of this process.
Usage: python thread_probe.py <path/to/tpl_record.py>"""
import os
import runpy
import sys

KEYS = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")
for k in KEYS:
    os.environ.pop(k, None)
print("numpy imported before the CLI:", "numpy" in sys.modules, "| env before:", {k: os.environ.get(k) for k in KEYS}, flush=True)
path = sys.argv[1]
sys.argv = [path, "--help"]
try:
    runpy.run_path(path, run_name="__main__")
except SystemExit as e:
    print("CLI exited with", e.code, flush=True)
import threadpoolctl  # noqa: E402

print("env after:", {k: os.environ.get(k) for k in KEYS}, flush=True)
print("BLAS pools:", [(i["internal_api"], i["num_threads"]) for i in threadpoolctl.threadpool_info()], flush=True)
print("affinity CPUs:", len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count(), flush=True)
