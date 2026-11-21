"""b28 0 FE preparation, step 3.1 inputs. Local, read only on db3406.

    python -X utf8 make_inputs.py

Writes into prep/data/:
  base_jobs_v11.txt   stair baseline rows of db3406 v0.11 (training rows of the micromotion model; geometry recomputed on the new axis on Linux)
  new_u13.npy, new_e.npy   8192 scrambled Sobol points (seed 56101) in the m >= 1 sub-box (u_m from 1/3 to 1), unit distance >= 0.5 from A, each at e -1, 0, +1.5
  inputs.json         counts and the A point
"""
import csv
import json
import math
import pathlib

import numpy as np
from scipy.stats import qmc

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "data"
OUT.mkdir(exist_ok=True)
DB = pathlib.Path(r"H:/projects/Femoral implant generation/db3406/v0.11")
U_COLS = ["u_L", "u_alpha", "u_h_cut", "u_m", "u_rho_tip", "u_q", "u_lam", "u_g_ml", "u_g_ap", "u_n_a", "u_n_p", "u_tau_a", "u_tau_p"]
A_JOB = "db_ws_p13_a105_91e458e3_m1_2a79b613"
SEED, N, E_LEVELS, MIN_DIST = 56101, 8192, (-1.0, 0.0, 1.5), 0.5
UM1 = 1.0 / 3.0


def num(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else math.nan
    except (TypeError, ValueError):
        return math.nan


def base(r):
    return (r["status"] == "DONE" and num(r["delta_mm"]) == 0.1 and num(r["load_R_N"]) == 2391.0 and num(r["alpha_front_deg"]) == 20.0 and num(r["alpha_sagit_deg"]) == 18.0
            and num(r["mu"]) == 0.3 and num(r["cycles"]) == 2 and num(r["E_canc_MPa"]) == 155.0 and num(r["h_int_mm"]) == 2.0 and math.isfinite(num(r["f1_p95_um"]))
            and not r.get("torsion") and not r.get("pose"))


R = list(csv.DictReader(open(DB / "scalars.csv", encoding="utf-8")))
jobs = sorted(r["job_id"] for r in R if base(r))
(OUT / "base_jobs_v11.txt").write_text("\n".join(jobs) + "\n", encoding="utf-8", newline="\n")
uA = np.array([num(next(r for r in R if r["job_id"] == A_JOB)[c]) for c in U_COLS])
s = qmc.Sobol(d=13, scramble=True, seed=SEED).random(N)
s[:, 3] = UM1 + s[:, 3] * (1.0 - UM1)
far = np.linalg.norm(s - uA, axis=1) >= MIN_DIST
s = s[far]
U = np.repeat(s, len(E_LEVELS), axis=0)
E = np.tile(np.array(E_LEVELS), len(s))
np.save(OUT / "new_u13.npy", U)
np.save(OUT / "new_e.npy", E)
info = {"base_jobs": len(jobs), "sobol_seed": SEED, "sobol_n": N, "kept_far_from_A": int(far.sum()), "e_levels": E_LEVELS, "tasks": int(len(U)), "uA": uA.tolist(), "min_dist": MIN_DIST}
json.dump(info, open(OUT / "inputs.json", "w", encoding="utf-8"), indent=1)
print(json.dumps({k: v for k, v in info.items() if k != "uA"}))
