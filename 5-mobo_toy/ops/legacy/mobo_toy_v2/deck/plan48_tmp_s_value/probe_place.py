"""s_value plan48 probe 2: same-size placement tolerance (geometry only; no meshing, no FE, no files written).
For each candidate the production size (A0 from prep.json, re-templated here and compared) is kept fixed and the pose is
perturbed: entry offset e (in the cut plane, along n3), insertion angle alpha, and seating depth ds along the stem axis
(+ = deeper). Reported: the minimum distance from the stem surface below the cut to the cortex (canal_sdf, dense rings
as in production; positive = clearance, negative = the stem would cut into the cortex). Nominal ~= m (0.5 mm) - tol.
Write protection as in probe_tpl.py."""
import os
for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[k] = "1"
import sys
sys.dont_write_bytecode = True
import builtins
import json
import pathlib

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
    print(json.dumps({"error": "cache missing; stopping"}))
    sys.exit(0)
F6.install()
FM0 = F6.build(neck_axis="isthmus")
import geom3d as G  # noqa: E402
import collar_rule as CR  # noqa: E402

BIG = 5.0
JOBS = {"A": "sb13_a105_91e458e3", "B": "sb13_a78_b0f465da", "Bp": "sb13_a53_23a3f031", "C": "sb14_a29_6ad70033",
        "D": "sb14_a26_96c5ab9b", "init29": "sb13_init_2943f28a", "a83": "sb13_a83_af62e125"}


def clearance(st, fm, A0, pose):
    v = CR.penetration_dense(st, fm, A0, pose, margin=BIG)    # = max(sdf + BIG, 0) over the dense + sparse points below the cut
    return BIG - float(v)


for code, job in JOBS.items():
    spec = json.loads((ROOT / "queue" / job / "spec.json").read_text())
    prep = json.loads((ROOT / "queue" / job / "prep.json").read_text())
    tp = prep["templating"]
    d = dict(spec["design"])
    fm = FM0.with_cut(float(spec["h_cut"]))
    st = G.Stem3D(**{k: v for k, v in d.items() if k in G.Stem3D.__dataclass_fields__})
    A0, e0, a0 = float(tp["A0"]), float(tp["e"]), float(tp["alpha"])
    nom = fm.pose(a0, e0)
    rows = {"nominal": clearance(st, fm, A0, nom)}
    for de in (-1.0, -0.5, -0.25, 0.25, 0.5, 1.0):
        rows[f"e{de:+g}"] = clearance(st, fm, A0, fm.pose(a0, e0 + de))
    for da in (-2.0, -1.0, -0.5, 0.5, 1.0, 2.0):
        rows[f"a{da:+g}"] = clearance(st, fm, A0, fm.pose(a0 + da, e0))
    for ds in (-1.0, -0.5, 0.5, 1.0):
        P0, ax, e_ml, e_ap = nom
        rows[f"s{ds:+g}"] = clearance(st, fm, A0, (P0 + ds * ax / np.linalg.norm(ax), ax, e_ml, e_ap))
    print(json.dumps({"code": code, "job": job, "A0": A0, "e": e0, "alpha": a0, "m": d["m"],
                      "clear_mm": {k: round(v, 3) for k, v in rows.items()}}), flush=True)
print(json.dumps({"done": True}), flush=True)
