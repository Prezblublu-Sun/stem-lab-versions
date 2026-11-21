"""Does tpl_record.main()'s os.environ.setdefault('OPENBLAS_NUM_THREADS', '1') make the --workers 1 (in-process) path single-threaded?
Run WITHOUT the *_NUM_THREADS env vars set."""
import os
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
print("env before:", {k: os.environ.get(k) for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")})
import tpl_record as T  # noqa: E402  (imports numpy, as the CLI does before main() runs)
for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(k, "1")                    # exactly what tpl_record.main() does
import threadpoolctl  # noqa: E402
print("after main()-style setdefault:", [(i["internal_api"], i["num_threads"]) for i in threadpoolctl.threadpool_info()])
print("affinity CPUs:", len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None)
