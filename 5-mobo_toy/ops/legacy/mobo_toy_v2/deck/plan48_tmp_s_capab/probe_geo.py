"""s_capab geometry-only probe (templating only: no gmsh meshing, no FE, no queue writes).

Run on Linux from ~/mobo_toy_v2/deck/plan48_tmp_s_capab/ with
  PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  nice -n 19 taskset -c 4-11 timeout 840 ~/mobo_toy_v2/.venv/bin/python -B probe_geo.py
Write guard: builtins.open / io.open in a write mode, os.replace/rename/remove/unlink/mkdir/makedirs and
numpy save/savez/savez_compressed raise unless the target is inside TMP. Any blocked write = loud failure (CLAUDE.md s11).
Parts
  P0  femur cache key check (femur_3406_<key>.npz must already exist -> build() only reads it)
  P1  reproduce production templating of the candidate designs (A0, e vs prep.json)
  P2  forced entry offset e in {-2,-1,0,+1,+2}: (a) re-sized at that e (spec key entry_offset semantics),
      (b) same production size A0 shifted to e: margin deficit and cortex penetration
  P3  widened-bounds feasibility: same scrambled-Sobol unit points mapped into the current box and the widened boxes
  P4  corner-design sweeps alpha 45..55 and m 0.5..0.25 for A (a105) and B (a78)
"""
from __future__ import annotations

import builtins
import io
import json
import math
import os
import pathlib
import sys
import time

T_START = time.time()
BUDGET_S = 780.0                                   # stop new work after 13 min (hard timeout 14 min outside)
HOME = pathlib.Path.home() / "mobo_toy_v2"
TMP = (HOME / "deck" / "plan48_tmp_s_capab").resolve()
CODE = HOME / "code"
sys.dont_write_bytecode = True
sys.path.insert(0, str(CODE))
sys.path.insert(0, str(CODE / "v2"))

# ------------------------------------------------------------------ write guard
_real_open = builtins.open
_real_os = {k: getattr(os, k) for k in ("replace", "rename", "remove", "unlink", "mkdir", "makedirs", "rmdir")}


def _inside_tmp(p) -> bool:
    try:
        q = pathlib.Path(os.fsdecode(p)).resolve()
    except TypeError:
        return False
    return q == TMP or TMP in q.parents


def _guard_open(file, mode="r", *a, **k):
    if isinstance(file, int):
        return _real_open(file, mode, *a, **k)
    if any(c in mode for c in "wax+") and not _inside_tmp(file):
        raise PermissionError(f"probe write blocked: open({file!r}, {mode!r})")
    return _real_open(file, mode, *a, **k)


builtins.open = _guard_open
io.open = _guard_open


def _guard_os(name):
    real = _real_os[name]

    def f(*args, **kw):
        tgt = args[1] if name in ("replace", "rename") and len(args) > 1 else (args[0] if args else None)
        if name in ("mkdir", "makedirs") and tgt is not None and pathlib.Path(os.fsdecode(tgt)).exists():
            if name == "makedirs" and kw.get("exist_ok"):
                return None
            raise FileExistsError(17, "File exists", os.fsdecode(tgt))
        if tgt is None or not _inside_tmp(tgt) or (name in ("replace", "rename") and not _inside_tmp(args[0])):
            raise PermissionError(f"probe write blocked: os.{name}{args!r}")
        return real(*args, **kw)
    return f


for _n in _real_os:
    setattr(os, _n, _guard_os(_n))

import numpy as np  # noqa: E402


def _blocked(*a, **k):
    raise PermissionError("probe write blocked: numpy save")


np.save = np.savez = np.savez_compressed = _blocked

# ------------------------------------------------------------------ project imports (read-only)
import jobs as J  # noqa: E402
import geom3d as G  # noqa: E402
import collar_rule as CR  # noqa: E402
import femur_3406 as F6  # noqa: E402
import stage_neckopt as SN  # noqa: E402
import stage_v2a as S  # noqa: E402

OUT = {"meta": {"t0": time.strftime("%Y-%m-%d %H:%M:%S"), "code_hash": J.code_hash(), "python": sys.version.split()[0]}}
LOG = []


def log(*a):
    s = " ".join(str(x) for x in a)
    LOG.append(s)
    print(s, flush=True)


def budget_left() -> float:
    return BUDGET_S - (time.time() - T_START)


# P0 femur cache must exist (so build() only np.load-s it)
cfg = F6.load_cfg("isthmus")
key = F6._cache_key(cfg)
cache_file = F6.CACHE / f"femur_3406_{key}.npz"
OUT["P0"] = {"cache_key": key, "cache_file": str(cache_file), "exists": cache_file.exists()}
log("P0 femur cache", key, cache_file.exists())
if not cache_file.exists():
    (TMP / "probe_out.json").write_text(json.dumps(OUT, indent=1))
    raise SystemExit("femur cache missing: build() would write; abort")
FM0 = J.femur_for({"femur_id": "sawbone3406", "neck_axis": "isthmus"})
log("A_BOUNDS after install", G.A_BOUNDS)

PH13 = SN.Phase(13)


def tpl(st, fm, offsets=None, a_max=2000.0):
    with J.a_bounds_cap(a_max):
        if offsets is None:
            return CR.template_neck_in_shoulder(st, fm, min_A0=S.MIN_A0, margin_check="dense")
        return CR.template_neck_in_shoulder(st, fm, offsets=np.asarray(offsets, float), min_A0=S.MIN_A0, margin_check="dense")


def slim(r):
    keys = ("fit", "reason", "alpha", "e", "A0", "s_bind", "volume", "margin", "neck_overhang_mm2", "contact")
    return {k: (float(r[k]) if isinstance(r.get(k), (int, float, np.floating)) and not isinstance(r.get(k), bool) else r.get(k))
            for k in keys if k in r}


# ------------------------------------------------------------------ P1 + P2 candidates
CANDS = {"A": "sb13_a105_91e458e3", "B": "sb13_a78_b0f465da", "Bp": "sb13_a53_23a3f031", "C": "sb14_a29_6ad70033",
         "D": "sb14_a26_96c5ab9b", "a62": "sb13_a62_1e4338ee", "init29": "sb13_init_2943f28a"}
OUT["P1"], OUT["P2"] = {}, {}
for code, job in CANDS.items():
    spec = json.loads((J.QROOT / job / "spec.json").read_text())
    prep = json.loads((J.QROOT / job / "prep.json").read_text())
    st = G.Stem3D(**spec["design"])
    fm = FM0.with_cut(float(spec["h_cut"]))
    t0 = time.time()
    r = tpl(st, fm)
    dt = time.time() - t0
    p_t = prep.get("templating") or {}
    OUT["P1"][code] = {"job": job, "repro": slim(r), "prep": {k: p_t.get(k) for k in ("alpha", "e", "A0", "s_bind", "volume")},
                       "dA0_rel": (r["A0"] - p_t["A0"]) / p_t["A0"] if r.get("fit") and p_t.get("A0") else None, "t_s": dt}
    log("P1", code, job, "repro A0", round(r.get("A0", float("nan")), 2), "e", r.get("e"), "prep A0", p_t.get("A0"), "e", p_t.get("e"), f"{dt:.1f}s")
    A0p, alpha, m = float(p_t["A0"]), float(spec["design"]["alpha"]), float(spec["design"]["m"])
    rows = []
    for e in (-2.0, -1.0, 0.0, 1.0, 2.0):
        ra = tpl(st, fm, offsets=[e])                                           # (a) entry_offset semantics: re-size at this e
        ps = fm.pose(alpha, e)                                                  # (b) same size, shifted entry
        pen_m = CR.penetration_dense(st, fm, A0p, ps, m)                        # margin deficit vs required m (0 = margin kept)
        pen_0 = CR.penetration_dense(st, fm, A0p, ps, 0.0)                      # depth outside the cancellous core (= into cortex / void)
        try:
            ov = CR.neck_overhang(st, fm, A0p, ps)
        except Exception as ex:                                                 # noqa: BLE001  report, do not swallow
            ov = f"error {type(ex).__name__}: {ex}"
        rows.append({"e": e, "resized": slim(ra), "fixed_size": {"A0": A0p, "margin_deficit_mm": float(pen_m), "outside_core_mm": float(pen_0),
                                                                    "neck_overhang_mm2": ov}})
        log("  P2", code, f"e {e:+.0f}", "resized fit", ra.get("fit"), "A0", round(ra.get("A0", float("nan")), 1),
            "| fixed A0: margin deficit", round(pen_m, 3), "outside core", round(pen_0, 3), "overhang", ov if isinstance(ov, str) else round(ov, 1))
    OUT["P2"][code] = rows

# ------------------------------------------------------------------ P3 widened-bounds feasibility
from scipy.stats import qmc  # noqa: E402

BOXES = {
    "C_current": {},
    "W1_a55_m025": {"alpha": (15.0, 55.0), "m": (0.25, 2.0)},
    "S_alpha45_55": {"alpha": (45.0, 55.0)},
    "S_m025_05": {"m": (0.25, 0.5)},
    "S_h12_16": {"h_cut": (12.0, 16.0)},
    "W2_a55_m025_h12": {"alpha": (15.0, 55.0), "m": (0.25, 2.0), "h_cut": (12.0, 32.0)},
}
N_PTS = {"C_current": 256, "W1_a55_m025": 256, "S_alpha45_55": 128, "S_m025_05": 128, "S_h12_16": 128, "W2_a55_m025_h12": 256}
for i, (name, over) in enumerate(BOXES.items()):
    SN.PHASES[900 + i] = {**SN.PHASES[13], "vars": {**SN.PHASES[13]["vars"], **over}}
PHS = {name: SN.Phase(900 + i) for i, name in enumerate(BOXES)}
U = qmc.Sobol(13, scramble=True, seed=480_2510).random(256)
res = {name: [] for name in BOXES}
order = [(j, name) for j in range(256) for name in BOXES if j < N_PTS[name]]
t3 = time.time()
stopped = None
for j, name in order:
    if budget_left() < 120:
        stopped = f"time budget: stopped at point {j} of box {name}"
        break
    ph = PHS[name]
    d, h = ph.design_of(U[j])
    fm = FM0.with_cut(h)
    r = tpl(G.Stem3D(**d), fm)
    ok = bool(r.get("fit") and r.get("A0", 0) >= S.MIN_A0)
    loss = float(fm.resected_volume(ref_cut_mm=ph.ref_cut_mm) + r["volume"]) if ok else None
    res[name].append({"j": j, "ok": ok, "alpha": d["alpha"], "m": d["m"], "h_cut": h, "L": d["L"], "A0": r.get("A0") if ok else None,
                      "e": r.get("e") if ok else None, "loss_mm3": loss, "reason": None if ok else str(r.get("reason"))[:160]})
OUT["P3"] = {"stopped": stopped, "elapsed_s": time.time() - t3, "boxes": {}}
for name, rows in res.items():
    n, k = len(rows), sum(r["ok"] for r in rows)
    newreg = [r for r in rows if r["alpha"] > 45.0 or r["m"] < 0.5 or r["h_cut"] < 16.0]
    reasons = {}
    for r in rows:
        if not r["ok"]:
            key_ = (r["reason"] or "").split(":")[0][:60]
            reasons[key_] = reasons.get(key_, 0) + 1
    feas = [r for r in rows if r["ok"]]
    OUT["P3"]["boxes"][name] = {"bounds_override": BOXES[name], "n": n, "feasible": k, "rate": k / n if n else None,
                               "new_region_n": len(newreg), "new_region_feasible": sum(r["ok"] for r in newreg),
                               "feasible_alpha_range": [min(r["alpha"] for r in feas), max(r["alpha"] for r in feas)] if feas else None,
                               "feasible_m_min": min(r["m"] for r in feas) if feas else None,
                               "feasible_h_min": min(r["h_cut"] for r in feas) if feas else None,
                               "feasible_A0_median": float(np.median([r["A0"] for r in feas])) if feas else None,
                               "fail_reasons_top": sorted(reasons.items(), key=lambda kv: -kv[1])[:6], "rows": rows}
    log("P3", name, f"{k}/{n} feasible", "new-region", f"{sum(r['ok'] for r in newreg)}/{len(newreg)}")

# ------------------------------------------------------------------ P4 corner sweeps
OUT["P4"] = {}
for code in ("A", "B"):
    if budget_left() < 40:
        OUT["P4"]["stopped"] = "time budget"
        break
    job = CANDS[code]
    spec = json.loads((J.QROOT / job / "spec.json").read_text())
    fm = FM0.with_cut(float(spec["h_cut"]))
    rows = []
    for k_, vals in (("alpha", (47.5, 50.0, 52.5, 55.0)), ("m", (0.4, 0.3, 0.25))):
        for v in vals:
            if budget_left() < 25:
                break
            dd = {**spec["design"], k_: float(v)}
            r = tpl(G.Stem3D(**dd), fm)
            rows.append({"var": k_, "value": v, **slim(r)})
            log("P4", code, k_, v, "fit", r.get("fit"), "A0", round(r.get("A0", float("nan")), 1), "e", r.get("e"))
    OUT["P4"][code] = rows

OUT["meta"]["elapsed_s"] = time.time() - T_START
OUT["log"] = LOG
(TMP / "probe_out.json").write_text(json.dumps(OUT, indent=1, default=float))
log("done", round(time.time() - T_START, 1), "s")
