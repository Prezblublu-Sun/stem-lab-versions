"""b28 prep: candidates in the ring 0.25 to 0.75 (unit distance from A), the band no FE row covers except "A with a larger m". Local, writes prep/data/ only.

    python -X utf8 ring_inputs.py

Random directions in the 13 unit coordinates (seed 56103), radius uniform in [0.25, 0.75], kept only inside the box with m >= 1 (u_m >= 1/3).
Each point at e 0, +1, +2. Writes ring_u13.npy, ring_e.npy, ring.json.
"""
import json
import pathlib

import numpy as np

D = pathlib.Path(__file__).resolve().parent / "data"
SEED, N_KEEP, R_LO, R_HI, E_LEVELS = 56103, 6000, 0.25, 0.75, (0.0, 1.0, 2.0)
UM1 = 1.0 / 3.0
uA = np.array(json.load(open(D / "inputs.json"))["uA"])
rng = np.random.default_rng(SEED)
kept, tried = [], 0
while len(kept) < N_KEEP:
    v = rng.standard_normal((20000, 13))
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    r = rng.uniform(R_LO, R_HI, 20000)
    p = uA + r[:, None] * v
    ok = np.all((p >= 0) & (p <= 1), axis=1) & (p[:, 3] >= UM1)
    tried += 20000
    kept += list(p[ok])
P = np.array(kept[:N_KEEP])
U = np.repeat(P, len(E_LEVELS), axis=0)
E = np.tile(np.array(E_LEVELS), len(P))
np.save(D / "ring_u13.npy", U)
np.save(D / "ring_e.npy", E)
info = {"seed": SEED, "tried": tried, "kept": len(P), "accept": round(len(kept) / tried, 4), "radius": [R_LO, R_HI], "e_levels": E_LEVELS, "tasks": int(len(U)),
        "dist_quartiles": np.quantile(np.linalg.norm(P - uA, axis=1), [0.25, 0.5, 0.75]).round(3).tolist()}
json.dump(info, open(D / "ring.json", "w", encoding="utf-8"), indent=1)
print(json.dumps(info))
