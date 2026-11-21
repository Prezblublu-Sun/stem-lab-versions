"""Freeze the 15 b28 picks: design point, entry offset, size and bone removed from the placement re-templating, and the predictions G42 checks. Local, read only.

    python -X utf8 freeze_rows.py

Writes prep/data/fam1_rows.json and prints the tuples for v2/stage_db.py (FAM1_ROWS) and experiments/b28_fam/gates.py (PRED).
"""
import csv
import json
import pathlib

import numpy as np

D = pathlib.Path(__file__).resolve().parent / "data"
U_COLS = ["u_L", "u_alpha", "u_h_cut", "u_m", "u_rho_tip", "u_q", "u_lam", "u_g_ml", "u_g_ap", "u_n_a", "u_n_p", "u_tau_a", "u_tau_p"]
ROLE = {"best": "b", "outer": "o", "explore": "x"}
picks = list(csv.DictReader(open(D / "picks.csv", encoding="utf-8")))
tol = {(t["src"], str(t["src_idx"]), round(float(t["e"]), 3)): t for t in json.load(open(D / "tol_ring.json", encoding="utf-8"))}
z = np.load(D / "scored_final.npz", allow_pickle=True)
out = []
for r in picks:
    u = np.array([float(r[c]) for c in U_COLS])
    e = float(r["e"])
    t = tol[(r["src"], str(r["src_idx"]), round(e, 3))]
    assert t["ok"]
    i = np.where(np.all(np.isclose(z["U"], u, atol=1e-9), axis=1) & np.isclose(z["e"], e))[0][0]
    lab = f"{r['fam']}{ROLE[r['role']]}"
    out.append({"label": lab, "fam": int(r["fam"]), "role": r["role"], "e": e, "A0": float(t["A0"]), "bone_mm3": float(t["bone_mm3"]), "h_cut": float(t["h_cut"]), "alpha": float(t["alpha"]),
                "u13": u.tolist(), "dist_A": float(z["dA"][i]), "pred_log_f1": float(z["pm"][i]), "pred_sd_cal": float(z["psc"][i]), "pred_F_mm": float(z["F"][i]),
                "pred_dF_mm": float(z["dF"][i]), "pred_dl": float(z["dl"][i]), "P_beat": float(z["P"][i]), "src": r["src"], "src_idx": int(r["src_idx"]), "design": t["design"]})
json.dump(out, open(D / "fam1_rows.json", "w", encoding="utf-8"), indent=1)
print("FAM1_ROWS = (")
for o in out:
    print(f"    ({o['label']!r}, {o['e']!r}, {round(o['A0'], 3)!r}, {round(o['bone_mm3'], 2)!r}, ({', '.join(repr(v) for v in o['u13'])})),")
print(")")
print("PRED = {" + ", ".join(f"{o['label']!r}: ({o['pred_log_f1']:.5f}, {o['pred_sd_cal']:.5f})" for o in out) + "}")
print("FAST_F = {" + ", ".join(f"{o['label']!r}: {o['pred_F_mm']:.2f}" for o in out) + "}")
