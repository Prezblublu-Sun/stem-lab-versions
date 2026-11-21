"""b28 prep step 3.5: the shortlisted designs at e -0.5 to +2.5 in steps of 0.5. Local, writes prep/data/ only.

    python -X utf8 egrid_inputs.py
"""
import csv
import json
import pathlib

import numpy as np

D = pathlib.Path(__file__).resolve().parent / "data"
U_COLS = ["u_L", "u_alpha", "u_h_cut", "u_m", "u_rho_tip", "u_q", "u_lam", "u_g_ml", "u_g_ap", "u_n_a", "u_n_p", "u_tau_a", "u_tau_p"]
E_GRID = (-0.5, 0.0, 0.5, 1.0, 1.5, 2.0, 2.5)
rows = list(csv.DictReader(open(D / "shortlist_e.csv", encoding="utf-8")))
P = np.array([[float(r[c]) for c in U_COLS] for r in rows])
U = np.repeat(P, len(E_GRID), axis=0)
E = np.tile(np.array(E_GRID), len(P))
np.save(D / "egrid_u13.npy", U)
np.save(D / "egrid_e.npy", E)
json.dump({"designs": len(P), "e_grid": E_GRID, "tasks": int(len(U))}, open(D / "egrid.json", "w", encoding="utf-8"), indent=1)
print(len(P), "designs,", len(U), "tasks")
