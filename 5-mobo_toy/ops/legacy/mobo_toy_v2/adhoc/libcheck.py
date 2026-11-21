import importlib
import os
import pathlib

import botorch
import gpytorch
import scipy
import torch

print(botorch.__version__, gpytorch.__version__, torch.__version__, scipy.__version__, "cpus", os.cpu_count())
for m in ("sklearn", "lightgbm", "xgboost"):
    try:
        importlib.import_module(m)
        print(m, "yes")
    except Exception:  # noqa: BLE001
        print(m, "no")
try:
    from botorch.sampling.pathwise import draw_matheron_paths  # noqa: F401
    print("pathwise ok")
except Exception as e:  # noqa: BLE001
    print("pathwise no", e)
print(sorted(p.name for p in (pathlib.Path.home() / "mobo_toy_v2/results/pools").glob("neckopt_p*")))
