"""d_capab: geometry-only feasibility probe (templating only; NO meshing, NO FE, NO queue access).

Runs on Linux from ~/mobo_toy_v2/deck/plandb_tmp_d_capab/ against ~/mobo_toy_v2/code (read-only use).
Write guards: numpy.save/savez/savez_compressed, io.open/builtins.open in write/append modes, and pathlib
write_text/write_bytes/touch/unlink/rename/replace/mkdir (new dirs) all raise unless the target is inside TMP.
The femur_3406 cache already exists (femur_3406_521f28cddd.npz), so femur_3406.build only reads it; if it did
not exist the guard would make build() raise instead of writing a cache file.

Boxes (13 vars, order = PHASES[13]['vars']):
  cur      = PHASES[13] box (alpha 15-45, m 0.5-2.0, L 20-45, h_cut 16-32, ...)
  wide     = cur with alpha 15-55, m 0.25-2.0
  cornA    = corner inside current bounds: L 40-45, alpha 40-45, h_cut 16-17, m 0.5-0.75, rest = cur
  cornB    = corner beyond the bounds:      L 40-45, alpha 45-55, h_cut 16-17, m 0.25-0.5, rest = cur
Same scrambled Sobol points (seed 4242) mapped into every box (paired).
usage: python probe_widen.py <box> <n> [time_limit_s]
"""
import io
import json
import math
import os
import pathlib
import sys
import time

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

TMP = (pathlib.Path.home() / "mobo_toy_v2" / "deck" / "plandb_tmp_d_capab").resolve()
CODE = pathlib.Path.home() / "mobo_toy_v2" / "code"
sys.path.insert(0, str(CODE))
sys.path.insert(0, str(CODE / "v2"))

import builtins  # noqa: E402

import numpy as np  # noqa: E402

BLOCKED = []


def _inside_tmp(p) -> bool:
    try:
        q = pathlib.Path(p).resolve()
    except Exception:  # noqa: BLE001
        return False
    return q == TMP or TMP in q.parents


def _deny_np(*a, **k):
    BLOCKED.append(("numpy-save", str(a[0]) if a else "?"))
    raise RuntimeError("probe guard: numpy save blocked")


np.save = np.savez = np.savez_compressed = _deny_np

_open = io.open


def _guard_open(file, mode="r", *a, **k):
    if isinstance(file, (str, bytes, os.PathLike)) and any(c in mode for c in "wax+") and not _inside_tmp(file):
        BLOCKED.append(("open", str(file)))
        raise RuntimeError(f"probe guard: write blocked {file}")
    return _open(file, mode, *a, **k)


io.open = builtins.open = _guard_open

_P = pathlib.Path


def _wrap(name):
    orig = getattr(_P, name)

    def f(self, *a, **k):
        if name == "mkdir" and self.exists():
            return None
        if not _inside_tmp(self):
            BLOCKED.append((name, str(self)))
            raise RuntimeError(f"probe guard: {name} blocked {self}")
        return orig(self, *a, **k)
    setattr(_P, name, f)


for _n in ("write_text", "write_bytes", "touch", "unlink", "rename", "replace", "mkdir"):
    _wrap(_n)

os.chdir(TMP)

import geom3d as G  # noqa: E402
import jobs as J  # noqa: E402
import stage_neckopt as N  # noqa: E402
import stage_v2a as S  # noqa: E402
from scipy.stats import qmc  # noqa: E402

base = N.PHASES[13]["vars"]
BOXES = {
    "cur": dict(base),
    "wide": {**base, "alpha": (15.0, 55.0), "m": (0.25, 2.0)},
    "cornA": {**base, "L": (40.0, 45.0), "alpha": (40.0, 45.0), "h_cut": (16.0, 17.0), "m": (0.5, 0.75)},
    "cornB": {**base, "L": (40.0, 45.0), "alpha": (45.0, 55.0), "h_cut": (16.0, 17.0), "m": (0.25, 0.5)},
}
PH_NO = {"cur": 13, "wide": 913, "cornA": 914, "cornB": 915}
for k, p in PH_NO.items():
    if p != 13:
        N.PHASES[p] = {**N.PHASES[13], "vars": BOXES[k]}          # in-memory only; never saved


def probe(box: str, n: int, tlim: float):
    ph = N.Phase(PH_NO[box])
    assert list(ph.space) == list(base), "variable order changed"
    U = qmc.Sobol(len(ph.vars), scramble=True, seed=4242).random(n)
    fm0 = N.base_femur(ph)
    rows, t0 = [], time.time()
    for i, u in enumerate(U):
        if time.time() - t0 > tlim:
            break
        d, h = ph.design_of(u)
        t1 = time.time()
        try:
            fm = fm0.with_cut(h)
            with J.a_bounds_cap(ph.a_bounds_max):
                r = ph.template(G.Stem3D(**d), fm)
            ok = bool(r["fit"] and r["A0"] >= S.MIN_A0)
            loss = float(fm.resected_volume(ref_cut_mm=ph.ref_cut_mm) + r["volume"]) if ok else None
            row = {"i": i, "ok": ok, "fit": bool(r["fit"]), "A0": r.get("A0"), "e": r.get("e"), "reason": r.get("reason"),
                   "loss_mm3": loss}
        except Exception as e:  # noqa: BLE001  report, do not swallow
            row = {"i": i, "ok": False, "error": f"{type(e).__name__}: {e}"[:300]}
        row.update({"s": round(time.time() - t1, 3), "design": {k: d[k] for k in ph.vars if k in d}, "h_cut": h,
                    "in_cur_box": bool(all(base[k][0] - 1e-9 <= ({**d, "h_cut": h})[k] <= base[k][1] + 1e-9 for k in base))})
        rows.append(row)
    return rows, time.time() - t0


if __name__ == "__main__":
    box, n = sys.argv[1], int(sys.argv[2])
    tlim = float(sys.argv[3]) if len(sys.argv) > 3 else 1e9
    rows, wall = probe(box, n, tlim)
    ok = [r for r in rows if r["ok"]]
    out = {"box": box, "bounds": BOXES[box], "n_requested": n, "n_done": len(rows), "n_feasible": len(ok),
           "rate": len(ok) / max(1, len(rows)), "wall_s": wall, "s_per_point_median": float(np.median([r["s"] for r in rows])) if rows else None,
           "n_errors": sum(1 for r in rows if "error" in r), "blocked_writes": BLOCKED, "rows": rows}
    if box == "wide":
        ins = [r for r in rows if r["in_cur_box"]]
        outs = [r for r in rows if not r["in_cur_box"]]
        out["inside_cur"] = {"n": len(ins), "feasible": sum(r["ok"] for r in ins)}
        out["outside_cur"] = {"n": len(outs), "feasible": sum(r["ok"] for r in outs)}
        for lab, cond in (("alpha_gt45", lambda r: r["design"]["alpha"] > 45 and r["design"]["m"] >= 0.5),
                          ("m_lt0.5", lambda r: r["design"]["m"] < 0.5 and r["design"]["alpha"] <= 45),
                          ("both", lambda r: r["design"]["m"] < 0.5 and r["design"]["alpha"] > 45)):
            sub = [r for r in outs if cond(r)]
            out[lab] = {"n": len(sub), "feasible": sum(r["ok"] for r in sub)}
    reasons = {}
    for r in rows:
        if not r["ok"]:
            k = (r.get("reason") or r.get("error") or ("A0<min" if r.get("fit") else "?"))
            k = str(k)[:60]
            reasons[k] = reasons.get(k, 0) + 1
    out["fail_reasons"] = reasons
    (TMP / f"probe_{box}_n{n}.json").write_text(json.dumps(out, indent=1, default=float))
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, default=float))
