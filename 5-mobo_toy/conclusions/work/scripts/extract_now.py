"""Read-only snapshot of every finished row newer than the local export, through the production stability module. Runs on Linux from stdin, writes nothing there.

    ssh ... 'cd ~/mobo_toy_v2/code/v2 && OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 timeout 590 taskset -c 4-7 nice -n 19 ../../run.sh -' < extract_now.py > now.txt

The last line of stdout is the JSON payload after the marker. pack_data.py reads it.
"""
import csv
import datetime
import glob
import json
import math
import pathlib
import sys

import numpy as np

sys.path[:0] = [".", ".."]
import stability as S  # noqa: E402
import stage_neckopt as SN  # noqa: E402

H = pathlib.Path.home()
ROOT = H / "mobo_toy_v2"
Q = ROOT / "queue"
RES = ROOT / "results"
EXPORT = H / "ml3406/data/v0.6/scalars.csv"
BATCHES = ("b8", "b12", "b15", "b16", "b17", "b18", "b19", "b7m", "b9p", "b11p", "b20")
RESULT_KEYS = ("f1_p95_um", "cpress_release_p95", "vm_p99", "sed_chg_pct", "f2_g7_loss_pct")
DEFAULT_STEPS = S.STEPS
PHASE = SN.Phase(13)

GAUGES = {"M1": (0.0, 27.0, 5.5), "MX1": (16.0, 20.3, 2.8), "M2": (31.75, 18.0, 0.1), "MX2": (47.75, 16.9, 0.5), "M3": (63.5, 16.6, 2.1),
          "M4": (95.25, 16.6, 2.6), "L1": (0.0, -17.3, 5.6), "L2": (31.75, -17.8, 2.5), "L3": (63.5, -17.3, 0.2), "L4": (95.25, -16.2, 0.3)}


def scalars(d):
    return {k: float(v) for k, v in d.items() if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))}


def in_box(design):
    return all(PHASE.space[k][0] - 1e-9 <= float(design[k]) <= PHASE.space[k][1] + 1e-9 for k in PHASE.vars if k in design)


def steps_of(n):
    out = ["RELEASE", "LOAD", "UNLOAD", "LOAD2"]
    for k in range(2, n):
        out += [f"UNLOAD{k}", f"LOAD{k+1}"]
    return tuple(out)


def fit(L, a, b):
    p, rel, X = L["p"], L["rel"], L["X"]
    body = ~p["pair_collar"]
    tr, om, c, rms = S.rigid_fit(X[body], (rel[b] - rel[a])[body], p["pair_area"][body])
    t0 = tr + np.cross(om, L["P0"] - c)
    return {"rot": math.degrees(np.linalg.norm(om)), "sub_um": float(t0 @ L["ax"] * 1e3)}


def per_cycle(d, n):
    S.STEPS = steps_of(n)
    try:
        L = S._load(d)
        peak, resid, rev, sub = [], [], [], []
        for k in range(1, n):
            lk, uk, lk1 = ("LOAD", "UNLOAD", "LOAD2") if k == 1 else (f"LOAD{k}", f"UNLOAD{k}", f"LOAD{k+1}")
            pk, re_, rv = fit(L, "RELEASE", lk), fit(L, "RELEASE", uk), fit(L, uk, lk1)
            peak.append(pk["rot"]); resid.append(re_["rot"]); rev.append(rv["rot"]); sub.append(re_["sub_um"])
        peak.append(fit(L, "RELEASE", f"LOAD{n}")["rot"])
        return {"peak": peak, "resid": resid, "rev": rev, "sub_um": sub}
    finally:
        S.STEPS = DEFAULT_STEPS


def row_of(job, m):
    d = Q / job
    spec = json.load(open(d / "spec.json"))
    design = spec.get("design") or {}
    r = {"job_id": job, "batch": m["batch"], "key": m["key"], "layer": m["layer"], "source": m["source"], "condition_id": m["condition_id"], "source_job": m["source_job"], "design_code": m.get("design_code"),
         "kind": spec.get("kind"), "stage": spec.get("stage"), "tag": spec.get("tag"), "design": design, "h_cut": spec.get("h_cut"), "delta": spec.get("delta"), "h_int": spec.get("h_int"), "entry_offset": spec.get("entry_offset"),
         "cycles": spec.get("cycles", 2), "cfg": spec.get("cfg"), "mu": spec.get("mu"), "in_box": in_box(design) if design else None}
    if spec.get("kind") == "intact":
        return r
    st = S.stability(d)
    prep = json.load(open(d / "prep.json"))
    res = json.load(open(d / "result.json"))
    t = prep["templating"]
    r.update(stability=scalars(st), tpl={k: t.get(k) for k in ("A0", "e", "alpha", "margin")}, bone_mm3=prep["bone_loss"]["total_mm3"], result={k: res.get(k) for k in RESULT_KEYS})
    if int(r["cycles"]) > 2:
        r["per_cycle"] = per_cycle(d, int(r["cycles"]))
    return r


def val_load(j):
    d = Q / j
    z = np.load(d / "mesh3d.npz", allow_pickle=True)
    labs, nodes = z["node_labels"].astype(int), z["nodes"]
    idx = np.zeros(labs.max() + 1, dtype=int)
    idx[labs] = np.arange(len(labs))
    conn = z["cortex_conn"][:, :4].astype(int)
    P = nodes[idx[conn]]
    cen = P.mean(1)
    vol = np.abs(np.einsum("ij,ij->i", P[:, 1] - P[:, 0], np.cross(P[:, 2] - P[:, 0], P[:, 3] - P[:, 0]))) / 6
    A = np.loadtxt(d / "intact_csv/LOAD_S.csv", delimiter=",", skiprows=1, usecols=(0, 1))
    m = np.full(int(A[:, 0].max()) + 1, np.nan)
    m[A[:, 0].astype(int)] = A[:, 1]
    return dict(cen=cen, vol=vol, mises=m[z["cortex_elab"].astype(int)], nodes=nodes)


def val_at(M, p, r=4.0):
    d = np.linalg.norm(M["cen"] - p, axis=1)
    s = d <= r
    if not s.any():
        return float(M["mises"][int(d.argmin())])
    return float((M["mises"][s] * M["vol"][s]).sum() / M["vol"][s].sum())


def val_turned(M, z, x, y, deg):
    q = M["nodes"][np.abs(M["nodes"][:, 2] - z) < 2.5]
    c = (q[:, :2].max(0) + q[:, :2].min(0)) / 2
    v = np.array([x, y]) - c
    a = math.radians(deg)
    u = np.array([math.cos(a) * v[0] - math.sin(a) * v[1], math.sin(a) * v[0] + math.cos(a) * v[1]])
    u /= np.linalg.norm(u)
    rel = q[:, :2] - c
    sel = q[np.abs(rel[:, 0] * u[1] - rel[:, 1] * u[0]) < 4.0]
    return sel[int(((sel[:, :2] - c) @ u).argmax())]


def val_rows(j):
    M = val_load(j)
    out = {}
    for g, (dep, x, y) in GAUGES.items():
        out[g] = {"p0": val_at(M, np.array([x, y, -dep])), "p15": val_at(M, val_turned(M, -dep, x, y, 15)), "m15": val_at(M, val_turned(M, -dep, x, y, -15))}
    return out


def manifest(batch):
    m = json.load(open(RES / f"db_manifest_{batch}.json"))
    return [dict(v, batch=batch) for v in m["rows"].values()]


known = {r["job_id"] for r in csv.DictReader(open(EXPORT, encoding="utf-8"))}
out = {"snapshot_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "export_on_linux": str(EXPORT), "rows": [], "not_done": [], "failed": [], "errors": []}
for b in BATCHES:
    for m in manifest(b):
        job = m.get("id") or m.get("expected_id")
        if job in known:
            continue
        d = Q / job
        if (d / "FAILED.json").exists():
            info = {}
            try:
                info = json.load(open(d / "FAILED.json"))
            except Exception:
                pass
            out["failed"].append({"job_id": job, "batch": b, "key": m["key"], "layer": m["layer"], "reason": str(info.get("reason") or info.get("error") or "")[:200]})
        elif not (d / "DONE").exists():
            out["not_done"].append({"job_id": job, "batch": b, "key": m["key"], "state": m.get("state")})
        else:
            try:
                out["rows"].append(row_of(job, m))
            except Exception as e:
                out["errors"].append({"job_id": job, "batch": b, "error": repr(e)[:300]})

# frozen prospective GP predictions for the three acquisition rounds; FE is joined locally by job id
out["acq"] = {}
for rnd in ("al1", "al2", "al3m"):
    picks = {p["rank"]: p for p in json.load(open(RES / f"db_al_{rnd}.json"))["picks"]}
    rows = []
    for p in sorted(glob.glob(str(Q / f"db_al_{rnd}_*"))):
        j = pathlib.Path(p)
        rk = int(j.name.split("_")[3])
        pk = picks.get(rk)
        spec = json.load(open(j / "spec.json"))
        if pk is None:
            continue
        mu, s = pk["pred_base"]["log_rot"]["gp"]
        rows.append({"job_id": j.name, "rank": rk, "group": pk["group"], "problem": pk.get("problem"), "mu": mu, "sd": s, "has_cfg": bool(spec.get("cfg")), "done": (j / "DONE").exists(), "failed": (j / "FAILED.json").exists()})
    out["acq"][rnd] = rows

# VAL-1, the comparison written before the results in the third-version plan, section 6.1
vals = {}
for tag, pat in (("far2.5", "db_ref_intact_val_n1200_far2.5_*"), ("far6", "db_ref_intact_val_n1200_0*")):
    g = sorted(glob.glob(str(Q / pat))) or [p for p in glob.glob(str(Q / "db_ref_intact_val_n1200_*")) if "far" not in p]
    if g and (pathlib.Path(g[0]) / "DONE").exists():
        vals[tag] = {"job_id": pathlib.Path(g[0]).name, "gauges": val_rows(pathlib.Path(g[0]).name)}
out["val1"] = vals
out["phase_space"] = {k: list(PHASE.space[k]) for k in PHASE.vars}
print("PAYLOAD " + json.dumps(out, default=float))
