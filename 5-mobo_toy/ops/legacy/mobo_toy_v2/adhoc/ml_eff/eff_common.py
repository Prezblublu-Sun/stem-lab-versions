"""Shared helpers for the efficiency study (runs on Linux, read-only on queue/results/code).

Outputs go to ~/mobo_toy_v2/deck/ml_eff/efficiency/.
"""
from __future__ import annotations

import csv
import json
import math
import pathlib
import sys

import numpy as np

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "code"))
sys.path.insert(0, str(HOME / "code" / "v2"))
OUT = HOME / "deck" / "ml_eff" / "efficiency"
OUT.mkdir(parents=True, exist_ok=True)
DATA = HOME / "deck" / "ml_eff" / "data" / "metrics_all.csv"

VARS10 = ["L", "alpha", "h_cut", "m", "rho_tip", "q", "lam", "g_ml", "g_ap", "n_a", "n_p", "tau_a", "tau_p"]
SPACE10 = {"L": (20.0, 60.0), "alpha": (15.0, 45.0), "h_cut": (25.0, 32.0), "m": (0.5, 2.0), "rho_tip": (0.10, 0.50),
           "q": (0.5, 3.0), "lam": (1.0, 2.2), "g_ml": (0.35, 0.65), "g_ap": (0.35, 0.65), "n_a": (2.0, 6.0),
           "n_p": (2.0, 6.0), "tau_a": (-0.30, 0.30), "tau_p": (-0.30, 0.30)}
SPACE9 = dict(SPACE10, m=(-0.25, 2.0))
MM_LIMIT, VM_LIMIT, SED_LIMIT, ROT_FLOOR = 150.0, 440.0, 30.0, 1e-3


def read_table(path=DATA):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def fnum(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else float("nan")
    except (TypeError, ValueError):
        return float("nan")


def tbool(v):
    return str(v).strip().lower() in ("true", "1", "yes")


def collarless_rows(rows):
    """current code, no overrides, collarless neck_in_shoulder (neck9 + neck10 + any deck variant without overrides)."""
    return [r for r in rows if tbool(r["current_code"]) and r["variant_class"] == "none" and r["collar_rule"] == "neck_in_shoulder"
            and fnum(r["collar_w"]) == 0.0]


def to_unit(r, space):
    return np.array([(fnum(r[k]) - space[k][0]) / (space[k][1] - space[k][0]) for k in VARS10])


def outputs(r):
    """phase-10 quantities: y_rot = log10 rotation, y_con = contact area (mm2), c_mm = log10 f1, c_vm, c_sed."""
    rot = fnum(r["rot_first_deg"])
    return {"y_rot": math.log10(max(rot, ROT_FLOOR)), "y_con": fnum(r["contact_area_load2_mm2"]),
            "c_mm": math.log10(max(fnum(r["f1_p95_um"]), 1e-3)), "c_vm": fnum(r["vm_p99"]), "c_sed": fnum(r["sed_chg_pct"])}


def combined_c(c_mm, c_vm, c_sed):
    """the optimiser's single normalised violation (stage_neckopt.objectives, metric v3, sed='abs')."""
    f1 = 10.0 ** np.asarray(c_mm)
    return np.maximum.reduce([(f1 - MM_LIMIT) / MM_LIMIT, (np.asarray(c_vm) - VM_LIMIT) / VM_LIMIT,
                              (np.abs(np.asarray(c_sed)) - SED_LIMIT) / SED_LIMIT])


def spearman(a, b):
    from scipy.stats import spearmanr
    a, b = np.asarray(a, float), np.asarray(b, float)
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 4:
        return float("nan"), int(ok.sum())
    return float(spearmanr(a[ok], b[ok]).statistic), int(ok.sum())


def dump(name, obj):
    p = OUT / name
    p.write_text(json.dumps(obj, indent=1, default=float))
    return p
