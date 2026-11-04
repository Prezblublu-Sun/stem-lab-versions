"""db3406 0-FE pool: 65536 scrambled-Sobol points in the phase-11/13 13-D unit cube, seed 51100 (= 50000 + 100*11 + 0),
the same generator as stage_neckopt.gated_pool, so rows 0..16383 equal the existing pool draw neckopt_p11_n16384_s0_115ae6b5.
Writes U65536_s51100.npy and checks the prefix against the feasible rows of the existing pool file."""
import json
import pathlib
import sys

import numpy as np
from scipy.stats import qmc

HOME = pathlib.Path.home() / "mobo_toy_v2"
out = HOME / "results" / "db_pool"
out.mkdir(parents=True, exist_ok=True)
U = qmc.Sobol(13, scramble=True, seed=51_100).random(65_536)
U16 = qmc.Sobol(13, scramble=True, seed=51_100).random(16_384)
if not np.array_equal(U[:16_384], U16):
    sys.exit("prefix of the 65536 draw differs from the 16384 draw")
pool = np.load(HOME / "results" / "pools" / "neckopt_p11_n16384_s0_115ae6b5.npz")
P = pool["U"]
idx = {tuple(np.round(r, 12)) for r in U16}
missing = sum(tuple(np.round(r, 12)) not in idx for r in P)
if missing:
    sys.exit(f"{missing} feasible pool rows are not in the regenerated 16384 draw")
f = out / "U65536_s51100.npy"
if f.exists():
    sys.exit(f"{f} exists")
np.save(f, U)
(out / "U65536_s51100.json").write_text(json.dumps({"generator": "scipy.stats.qmc.Sobol(13, scramble=True, seed=51100).random(65536)",
                                                    "prefix_equals_pool_draw_16384": True, "pool_feasible_rows_found": int(len(P))}))
print(f"wrote {f}; {len(P)} feasible pool rows all found in the prefix")
