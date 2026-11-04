"""s_value plan48 probe: geometry-only templating (no meshing, no FE, no files written).
Reproduces production templating (collar_rule neck_in_shoulder + margin_check dense + A_BOUNDS 2000) for the bench
candidates and init29, then (a) fixes the entry offset e to off-grid / neighbouring values, (b) one-at-a-time steps around
A = sb13_a105 (alpha / m / L / h_cut, incl. beyond the current bounds), (c) moments of the head force about the stem axis,
the neck axis and the shaft axis for the stair and the two sit-to-stand loads. Prints JSON lines to stdout only.
Write protection: numpy save*/savez*, pathlib write_text/write_bytes and builtins.open in any write mode raise."""
import os
for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[k] = "1"
import sys
sys.dont_write_bytecode = True
import builtins
import copy
import json
import math
import pathlib
import time

import numpy as np


def _deny(*a, **k):
    raise RuntimeError("s_value probe: write attempted (read-only run)")


np.savez_compressed = _deny
np.savez = _deny
np.save = _deny
pathlib.Path.write_text = _deny
pathlib.Path.write_bytes = _deny
_open = builtins.open


def _ro_open(file, mode="r", *a, **k):
    if any(c in str(mode) for c in "wax+"):
        raise RuntimeError(f"s_value probe: open({file!r}, {mode!r}) denied (read-only run)")
    return _open(file, mode, *a, **k)


builtins.open = _ro_open

ROOT = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(ROOT / "code" / "v2"))
sys.path.insert(0, str(ROOT / "code"))
import femur_3406 as F6  # noqa: E402

cfg = F6.load_cfg("isthmus")
if not (F6.CACHE / f"femur_3406_{F6._cache_key(cfg)}.npz").exists():
    print(json.dumps({"error": "cache missing; stopping (would rebuild and write the cache)"}))
    sys.exit(0)
F6.install()                                    # G.A_BOUNDS -> (20, 2000) in this process only
FM0 = F6.build(neck_axis="isthmus")
import geom3d as G  # noqa: E402
import collar_rule as CR  # noqa: E402
import model3d_v2 as MV  # noqa: E402  (load_vector only: pure function)

JOBS = {"A": "sb13_a105_91e458e3", "B": "sb13_a78_b0f465da", "Bp": "sb13_a53_23a3f031", "C": "sb14_a29_6ad70033",
        "D": "sb14_a26_96c5ab9b", "init29": "sb13_init_2943f28a", "a83": "sb13_a83_af62e125"}
LOADS = {"stair2391": None,
         "sts1714": {"resultant_N": 1714.0, "alpha_front_deg": 24.0, "alpha_sagit_deg": 8.0},
         "sts3839": {"resultant_N": 3839.0, "alpha_front_deg": 24.0, "alpha_sagit_deg": 8.0}}


def fvec(over):
    c = copy.deepcopy(FM0.cfg)
    if over:
        c["load"].update(over)
    return MV.load_vector(c)


FV = {k: fvec(v) for k, v in LOADS.items()}


def run(dsg, h, min_A0, offsets=None):
    fm = FM0.with_cut(h)
    st = G.Stem3D(**{k: v for k, v in dsg.items() if k in G.Stem3D.__dataclass_fields__})
    t0 = time.time()
    kw = {} if offsets is None else {"offsets": np.array(offsets, float)}
    r = CR.template_neck_in_shoulder(st, fm, min_A0=min_A0, margin_check="dense", **kw)
    out = {"fit": bool(r.get("fit")), "t_s": round(time.time() - t0, 2)}
    if r.get("fit"):
        P0, ax, e_ml, e_ap = r["pose"]
        ax = ax / np.linalg.norm(ax)
        un = -np.asarray(fm.u3, float) / np.linalg.norm(fm.u3)
        z = np.array([0.0, 0.0, 1.0])
        out.update(A0=float(r["A0"]), e=float(r["e"]), s_bind=float(r["s_bind"]), vol=float(r["volume"]),
                   head_off_mm=float(np.linalg.norm((fm.H - P0) - ((fm.H - P0) @ ax) * ax)))
        for ln, F in FV.items():
            M = np.cross(fm.H - P0, F)                     # N*mm about the shoulder point P0
            out[f"{ln}_Mstem_Nm"] = round(float(M @ ax) / 1e3, 3)
            out[f"{ln}_Mneck_Nm"] = round(float(M @ un) / 1e3, 3)
            out[f"{ln}_Mshaft_Nm"] = round(float(M @ z) / 1e3, 3)
            out[f"{ln}_Mbend_Nm"] = round(float(np.linalg.norm(M - (M @ ax) * ax)) / 1e3, 3)
    else:
        out["reason"] = str(r.get("reason"))[:240]
    return out


def emit(code, job, var, val, res, ref=None):
    rec = {"code": code, "job": job, "var": var, "val": val, **res}
    if ref and res.get("fit") and ref.get("fit"):
        rec["dA0_pct"] = round(100.0 * (res["A0"] / ref["A0"] - 1.0), 2)
    print(json.dumps(rec, default=float), flush=True)


for code, job in JOBS.items():
    spec = json.loads((ROOT / "queue" / job / "spec.json").read_text())
    prep = json.loads((ROOT / "queue" / job / "prep.json").read_text()) if (ROOT / "queue" / job / "prep.json").exists() else {}
    tp = prep.get("templating") or {}
    base = dict(spec["design"])
    h0 = float(spec["h_cut"])
    mA = float(spec.get("min_A0", 0.0))
    ref = run(base, h0, mA)
    emit(code, job, "repro", None, {**ref, "prep_A0": tp.get("A0"), "prep_e": tp.get("e")})
    for e in (-2.0, -1.0, -0.5, 0.5, 1.0, 2.0):
        emit(code, job, "e_fixed", e, run(base, h0, mA, offsets=[e]), ref)
    if code in ("A", "B"):
        steps = {"alpha": [base["alpha"] - 1.0, base["alpha"] + 1.0, 46.0, 47.0, 48.0],
                 "m": [0.25, 0.35, 0.6],
                 "L": [base["L"] - 1.0, base["L"] + 1.0, base["L"] + 1.5, base["L"] + 2.0],
                 "h_cut": [16.5, 17.0, 18.0]}
        for var, vals in steps.items():
            for v in vals:
                d, h = dict(base), h0
                if var == "h_cut":
                    h = float(v)
                else:
                    d[var] = float(v)
                emit(code, job, var, round(float(v), 4), run(d, h, mA), ref)
print(json.dumps({"done": True}), flush=True)
