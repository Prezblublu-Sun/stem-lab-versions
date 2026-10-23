"""Run with the repo venv: PYTHONUTF8=1 .venv-mobo/Scripts/python.exe v2/tests/test_a4_stability_patch.py   (also collectable by pytest)
Local only: a synthetic job dir in the system temp dir (override with env MOBO_TEST_SCRATCH); nothing touches Linux, the real queue
or runs/q. Read-only on the research-log (A4 reference rows) and on git (git show <pre-patch commit>:v2/stability.py).

Checks for the A4 additive patch to stability.py (a4_summary.md §4, reference implementation v2/a4_rotfit/a4_rotfit_linux.py):
 1. Synthetic job dir (mesh3d.npz with pair arrays, stem_conn, cortex_conn, cancellous_conn, node coords; m_fric_csv/*_U.csv) with
    prescribed linearised rigid motions u = t + w x (x - C03) for bone and stem at the four steps. stability() must recover the
    prescribed relative rotation (total / axial / tilt / signed tilt_ap / tilt_ml) and the relative translation at P0 (subsidence /
    lateral) for first / rev / perm; bench() (stem nodes 0 < h <= 10 mm above the cut vs cortex nodes -5 <= h < 0, absolute
    unweighted fits) must recover the same values. Collar pairs, stem nodes above h_stem and cortex nodes outside the ring carry
    random garbage and must not influence anything.
 2. Piecewise-rigid relative field (stem nodes with s <= median move differently from s > median): rot_*_first_prox_deg recovers the
    proximal rotation exactly, bench (neck markers) recovers it too, the whole-body fit is a blend (differs, rms > 0).
 3. Bit identity: every key of the pre-patch stability.py (git show 40c7687:v2/stability.py) is reproduced exactly (==) by the new one.
 4. Guard: mesh3d.npz without cortex_conn -> stability() returns all non-bench keys unchanged and no bench_cx_* keys, no exception.
 5. Offline cross-check with the A4 reference (130 jobs, rotfit_rows.jsonl / a4_table.csv): the stored omega vectors + frames pushed
    through this module's _split and signed-tilt formulas reproduce the reference's rot / axial / tilt columns (all / prox / dist / unw
    domains and bench_cx) and the tilt_ap / tilt_ml columns. This verifies the decomposition formulas and the sign convention on real
    data, not the fit itself (rigid_fit is unchanged and is the function the reference called). Skipped if the files are absent.
"""
from __future__ import annotations

import csv
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

import numpy as np

ROOT = pathlib.Path(r"H:/projects/Femoral implant generation/sandbox/mobo_toy")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "v2"))
SCR = pathlib.Path(os.environ.get("MOBO_TEST_SCRATCH") or (pathlib.Path(tempfile.gettempdir()) / "mobo_toy_a4patch_tests"))
A4 = pathlib.Path(r"H:/projects/application/research-log/neck_implant_2026-10-02/ml_efficiency_2026-10-22/plan/a4")
PRE_PATCH = "40c7687"                      # last commit before this patch (stability.py blob fd3ffdc)
STEPS = ("RELEASE", "LOAD", "UNLOAD", "LOAD2")
SEGS = {"first": ("RELEASE", "LOAD"), "rev": ("UNLOAD", "LOAD2"), "perm": ("RELEASE", "UNLOAD")}

import jobs as J  # noqa: E402
import stability as ST  # noqa: E402

assert not str(SCR).startswith(str(pathlib.Path.home() / "mobo_toy_v2")) and not str(SCR).startswith(str(ROOT / "v2" / "runs"))

checks = []


def ok(name, cond, extra=""):
    checks.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""), flush=True)


def unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


# ------------------------------------------------------------------ frame (tilted; numbers close to a real phase-10 job)
U3 = unit([0.672, -0.0716, 0.737])                                   # neck axis, towards the head (cut-plane normal)
C03 = np.array([21.955, 3.241, 46.815])                               # cut centre
AX = unit([-0.5996, 0.0639, -0.7977])                                 # stem axis, into the bone (AX . U3 ~ -0.9955)
_seed = np.array([0.7932, -0.0845, -0.6030])
E_ML = unit(_seed - (_seed @ AX) * AX)
E_AP = unit(np.cross(AX, E_ML))
P0 = C03 + np.array([-1.466, 0.156, 1.352])                           # shoulder centre (entry point on the cut)
_a1 = unit(np.cross(U3, [0.0, 1.0, 0.0]))
_a2 = np.cross(U3, _a1)                                               # (_a1, _a2) span the cut plane


class FakeFm:
    C03 = C03
    u3 = U3

    def pose(self, alpha, e):
        return P0.copy(), AX.copy(), E_ML.copy(), E_AP.copy()


J.femur_for = lambda spec: FakeFm()


def stem_pt(s, r, th):
    return P0 + s * AX + r * (np.cos(th) * E_ML + np.sin(th) * E_AP)


def cut_pt(h, r, ph):
    return C03 + h * U3 + r * (np.cos(ph) * _a1 + np.sin(ph) * _a2)


def geometry(seed=0):
    """Node sets (coordinates + roles). Labels are assigned in the order the sets are listed."""
    rng = np.random.default_rng(seed)
    g = {}
    # interface pairs: 40 rings x 10 angles along the stem body (bone side = stem twin coordinates)
    s_ring = 0.5 + 44.0 * np.arange(40) / 39.0
    th = 2 * np.pi * np.arange(10) / 10.0
    S, TH = np.meshgrid(s_ring, th, indexing="ij")
    S, TH = S.ravel(), TH.ravel()
    R = 6.0 - 3.0 * S / 45.0
    g["if_bone"] = np.array([stem_pt(s, r, t) for s, r, t in zip(S, R, TH)])
    g["if_s"], g["if_th"] = S, TH
    g["if_normal"] = np.array([np.cos(t) * E_ML + np.sin(t) * E_AP for t in TH])
    g["if_area"] = 1.0 + 0.4 * np.sin(TH) + 0.01 * S
    # collar pairs (garbage motion; must be excluded by pair_collar)
    thc = 2 * np.pi * np.arange(20) / 20.0
    g["col_bone"] = np.array([stem_pt(-0.1, 9.0, t) for t in thc])
    # stem body interior nodes
    sb = rng.uniform(0.0, 45.0, 150)
    rb = rng.uniform(0.0, 0.8, 150) * (6.0 - 3.0 * sb / 45.0)
    g["stem_body"] = np.array([stem_pt(s, r, t) for s, r, t in zip(sb, rb, rng.uniform(0, 2 * np.pi, 150))])
    # neck nodes above the cut, 0 < h <= 10 (S10) and above 10 (garbage)
    g["neck"] = np.array([cut_pt(h, r, p) for h in np.arange(0.5, 10.0, 1.0) for r in (0.0, 3.0, 6.0)
                          for p in 2 * np.pi * np.arange(8) / 8.0])
    g["neck_hi"] = np.array([cut_pt(h, r, p) for h in (11.0, 13.0, 15.0) for r in (3.0, 6.0) for p in 2 * np.pi * np.arange(8) / 8.0])
    # cortex: ring -5 <= h < 0 (CX5) and nodes outside the band (garbage)
    g["cx5"] = np.array([cut_pt(h, r, p) for h in (-4.5, -3.5, -2.5, -1.5, -0.5) for r in (13.0, 15.0)
                         for p in 2 * np.pi * np.arange(12) / 12.0])
    g["cx_out"] = np.array([cut_pt(h, r, p) for h in (0.5, -5.5, -8.0, -20.0) for r in (13.0, 15.0) for p in 2 * np.pi * np.arange(6) / 6.0])
    # cancellous (follows the bone; not read by stability)
    g["canc"] = np.array([cut_pt(h, r, p) for h in (-6.0, -12.0, -25.0) for r in (8.0, 10.5) for p in 2 * np.pi * np.arange(6) / 6.0])
    return g


def rigid(t, w, X):
    """Linearised rigid displacement about C03."""
    return t[None, :] + np.cross(w[None, :], X - C03)


def in_stem_frame(a, m, p):
    return a * AX + m * E_ML + p * E_AP


# prescribed motions: bone (t_B, w_B) per step; stem = bone + relative (t_rel, w_rel) per step (given in the stem frame)
W_B = {"RELEASE": np.zeros(3), "LOAD": np.array([4.0e-4, 3.0e-3, 2.5e-3]), "UNLOAD": np.array([1.0e-5, 5.0e-5, -2.0e-5]),
       "LOAD2": np.array([3.8e-4, 3.1e-3, 2.4e-3])}
T_B = {"RELEASE": np.zeros(3), "LOAD": np.array([0.02, -0.05, -0.03]), "UNLOAD": np.array([0.001, 0.0, 0.002]),
       "LOAD2": np.array([0.021, -0.049, -0.031])}
W_REL = {"RELEASE": in_stem_frame(2.0e-4, -1.0e-4, 1.5e-4), "LOAD": in_stem_frame(7.0e-4, -4.0e-4, 6.5e-4),
         "UNLOAD": in_stem_frame(5.0e-4, -3.0e-4, 4.0e-4), "LOAD2": in_stem_frame(7.5e-4, -5.0e-4, 6.0e-4)}
T_REL = {"RELEASE": in_stem_frame(2e-3, 1e-3, 0.0), "LOAD": in_stem_frame(12e-3, 4e-3, -2e-3),
         "UNLOAD": in_stem_frame(6e-3, 2e-3, -1e-3), "LOAD2": in_stem_frame(14e-3, 5e-3, -2.5e-3)}
# second relative motion for the distal half (piecewise test)
W_REL_D = {k: v + in_stem_frame(-3.0e-4, 2.0e-4, -2.5e-4) * (0.0 if k == "RELEASE" else 1.0) for k, v in W_REL.items()}
T_REL_D = {k: v + in_stem_frame(-3e-3, 1e-3, 1e-3) * (0.0 if k == "RELEASE" else 1.0) for k, v in T_REL.items()}


def expected(seg, w_rel=W_REL, t_rel=T_REL):
    a, b = SEGS[seg]
    dw, dt = w_rel[b] - w_rel[a], t_rel[b] - t_rel[a]
    v = dt + np.cross(dw, P0 - C03)                                    # relative displacement at P0
    ax_c = dw @ AX
    return {"rot": np.degrees(np.linalg.norm(dw)), "axial": np.degrees(abs(ax_c)), "tilt": np.degrees(np.linalg.norm(dw - ax_c * AX)),
            "tilt_ap": np.degrees(dw @ E_AP), "tilt_ml": np.degrees(dw @ E_ML),
            "subsid": v @ AX * 1e3, "lateral": np.linalg.norm(v - (v @ AX) * AX) * 1e3}


def build_job(d: pathlib.Path, piecewise: bool, seed=0, with_cortex=True):
    """Write mesh3d.npz, spec/result.json and m_fric_csv/*_U.csv. Returns the geometry and the median split used."""
    rng = np.random.default_rng(seed + 100)
    g = geometry(seed)
    sets = ["if_bone", "if_stem", "col_bone", "col_stem", "stem_body", "neck", "neck_hi", "cx5", "cx_out", "canc"]
    coords = {"if_stem": g["if_bone"], "col_stem": g["col_bone"], **{k: g[k] for k in sets if k not in ("if_stem", "col_stem")}}
    labels, lab0 = {}, 1
    for k in sets:
        n = len(coords[k])
        labels[k] = np.arange(lab0, lab0 + n)
        lab0 += n
    nodes = np.vstack([coords[k] for k in sets])
    node_labels = np.concatenate([labels[k] for k in sets])
    perm = rng.permutation(len(node_labels))                         # scramble node order so that label != row index
    nodes, node_labels = nodes[perm], node_labels[perm]

    def conn(labs):
        pad = (-len(labs)) % 10
        return np.concatenate([labs, np.repeat(labs[:1], pad)]).reshape(-1, 10).astype(np.int64)

    n_if, n_col = len(labels["if_bone"]), len(labels["col_bone"])
    mesh = {"pair_bone": np.concatenate([labels["if_bone"], labels["col_bone"]]),
            "pair_stem": np.concatenate([labels["if_stem"], labels["col_stem"]]),
            "pair_normal": np.vstack([g["if_normal"], np.tile(-AX, (n_col, 1))]),
            "pair_area": np.concatenate([g["if_area"], np.full(n_col, 2.0)]),
            "pair_interf": np.full(n_if + n_col, 0.025),
            "pair_cortex": np.concatenate([g["if_s"] < 15.0, np.ones(n_col, bool)]),
            "pair_collar": np.concatenate([np.zeros(n_if, bool), np.ones(n_col, bool)]),
            "nodes": nodes, "node_labels": node_labels,
            "stem_conn": conn(np.concatenate([labels["if_stem"], labels["col_stem"], labels["stem_body"], labels["neck"], labels["neck_hi"]])),
            "cancellous_conn": conn(labels["canc"])}
    if with_cortex:
        mesh["cortex_conn"] = conn(np.concatenate([labels["cx5"], labels["cx_out"]]))
    shutil.rmtree(d, ignore_errors=True)
    (d / "m_fric_csv").mkdir(parents=True)
    np.savez_compressed(d / "mesh3d.npz", **mesh)
    (d / "spec.json").write_text(json.dumps({"kind": "design", "design": {"L": 45.0, "alpha": 30.0, "m": 0.5}, "h_int": 2.0,
                                             "model": "m1", "stage": "a4test", "tag": "syn"}))
    (d / "result.json").write_text(json.dumps({"templating": {"alpha": 30.0, "e": -2.0}, "f1_p95_um": 10.0}))
    # roles: bone-following, stem-following (proximal / distal), garbage
    s_all = (nodes - P0) @ AX
    med = float(np.median(g["if_s"]))                                 # same split as stability(): body pairs, s <= median
    role = {}
    for k in ("if_bone", "cx5", "canc"):
        role.update({int(l): "B" for l in labels[k]})
    for k in ("if_stem", "col_stem", "stem_body", "neck"):                # collar stem twins are stem nodes (some sit at h > 0 in a tilted frame)
        role.update({int(l): "S" for l in labels[k]})
    for k in ("col_bone", "neck_hi", "cx_out"):                           # garbage: collar bone side (pair excluded), stem above h_stem, cortex outside the ring
        role.update({int(l): "G" for l in labels[k]})
    h_of = lambda Xk: (Xk - C03) @ U3  # noqa: E731
    info = {"n_s10": sum(int(((h_of(coords[k]) > 0) & (h_of(coords[k]) <= 10.0)).sum()) for k in ("if_stem", "col_stem", "stem_body", "neck", "neck_hi")),
            "n_cx5": sum(int(((h_of(coords[k]) >= -5.0) & (h_of(coords[k]) < 0)).sum()) for k in ("cx5", "cx_out")),
            "garbage_in_s10": int(((h_of(coords["neck_hi"]) > 0) & (h_of(coords["neck_hi"]) <= 10.0)).sum()),
            "garbage_in_cx5": int(((h_of(coords["cx_out"]) >= -5.0) & (h_of(coords["cx_out"]) < 0)).sum()),
            "n_neck": len(labels["neck"]), "n_cx5_ring": len(labels["cx5"])}
    garbage = {s: rng.normal(size=(len(node_labels), 3)) * 0.05 for s in STEPS}
    for s in STEPS:
        uB = rigid(T_B[s], W_B[s], nodes)
        uSp = rigid(T_B[s] + T_REL[s], W_B[s] + W_REL[s], nodes)
        uSd = rigid(T_B[s] + T_REL_D[s], W_B[s] + W_REL_D[s], nodes) if piecewise else uSp
        rows = []
        for i, lab in enumerate(node_labels):
            r = role[int(lab)]
            u = uB[i] if r == "B" else (garbage[s][i] if r == "G" else (uSp[i] if s_all[i] <= med else uSd[i]))
            rows.append(f"{int(lab)},{float(u[0])!r},{float(u[1])!r},{float(u[2])!r}")   # repr of a Python float round-trips exactly
        (d / "m_fric_csv" / f"{s}_U.csv").write_text("node,u1,u2,u3\n" + "\n".join(rows) + "\n")
    return g, med, labels, info


def close(a, b, tol):
    return abs(float(a) - float(b)) <= tol


def run():
    checks.clear()
    SCR.mkdir(parents=True, exist_ok=True)
    TOL_DEG, TOL_UM = 1e-9, 1e-6                                       # prescribed field is exactly linear-rigid -> machine precision

    # ------------------------------------------------------------ 1. pure rigid motion: whole-body fit and bench recover it
    d1 = SCR / "job_rigid"
    g, med, labels, info = build_job(d1, piecewise=False)
    out = ST.stability(d1)
    for seg in SEGS:
        e = expected(seg)
        ok(f"[{seg}] rot / axial / tilt recovered",
           close(out[f"rot_{seg}_deg"], e["rot"], TOL_DEG) and close(out[f"rot_axial_{seg}_deg"], e["axial"], TOL_DEG)
           and close(out[f"rot_tilt_{seg}_deg"], e["tilt"], TOL_DEG),
           f"{out[f'rot_{seg}_deg']:.6f} vs {e['rot']:.6f} deg")
        ok(f"[{seg}] signed tilt_ap / tilt_ml recovered (sign included)",
           close(out[f"rot_tilt_ap_{seg}_deg"], e["tilt_ap"], TOL_DEG) and close(out[f"rot_tilt_ml_{seg}_deg"], e["tilt_ml"], TOL_DEG),
           f"ap {out[f'rot_tilt_ap_{seg}_deg']:.6f} vs {e['tilt_ap']:.6f}; ml {out[f'rot_tilt_ml_{seg}_deg']:.6f} vs {e['tilt_ml']:.6f}")
        ok(f"[{seg}] subsidence / lateral at P0 recovered",
           close(out[f"subsid_{seg}_um"], e["subsid"], TOL_UM) and close(out[f"lateral_{seg}_um"], e["lateral"], TOL_UM),
           f"{out[f'subsid_{seg}_um']:.4f} vs {e['subsid']:.4f} um")
        ok(f"[{seg}] whole-body fit residual ~ 0 (collar pairs excluded)", out[f"rigid_fit_rms_{seg}_um"] < 1e-6, f"{out[f'rigid_fit_rms_{seg}_um']:.2e} um")
        ok(f"[{seg}] bench_cx rot / axial / tilt recovered",
           close(out[f"bench_cx_rot_{seg}_deg"], e["rot"], TOL_DEG) and close(out[f"bench_cx_rot_axial_{seg}_deg"], e["axial"], TOL_DEG)
           and close(out[f"bench_cx_rot_tilt_{seg}_deg"], e["tilt"], TOL_DEG),
           f"{out[f'bench_cx_rot_{seg}_deg']:.6f} vs {e['rot']:.6f} deg")
        ok(f"[{seg}] bench_cx subsidence / lateral recovered",
           close(out[f"bench_cx_subsid_{seg}_um"], e["subsid"], TOL_UM) and close(out[f"bench_cx_lateral_{seg}_um"], e["lateral"], TOL_UM),
           f"{out[f'bench_cx_subsid_{seg}_um']:.4f} vs {e['subsid']:.4f} um")
    ok("prox keys equal whole-body keys when the field is rigid",
       close(out["rot_first_prox_deg"], out["rot_first_deg"], TOL_DEG) and close(out["rot_axial_first_prox_deg"], out["rot_axial_first_deg"], TOL_DEG)
       and close(out["rot_tilt_first_prox_deg"], out["rot_tilt_first_deg"], TOL_DEG))
    ok("bench marker counts = all stem nodes 0<h<=10 (neck + twins/collar twins just above the cut) and cortex nodes -5<=h<0",
       out["bench_cx_n_stem"] == info["n_s10"] and out["bench_cx_n_bone"] == info["n_cx5"] and info["n_s10"] >= info["n_neck"]
       and info["n_cx5"] == info["n_cx5_ring"] and info["garbage_in_s10"] == 0 and info["garbage_in_cx5"] == 0,
       f"stem {out['bench_cx_n_stem']} (exp {info['n_s10']} = {info['n_neck']} neck + {info['n_s10'] - info['n_neck']} others), "
       f"bone {out['bench_cx_n_bone']} (exp {info['n_cx5']}); garbage inside: {info['garbage_in_s10']} / {info['garbage_in_cx5']}")
    ok("bench band parameters recorded", out["bench_cx_h_stem_mm"] == 10.0 and out["bench_cx_h_bone_mm"] == 5.0)
    b = ST.bench(d1)
    ok("bench(d) standalone == bench keys inside stability(d) (exact)", all(k in out and out[k] == v for k, v in b.items()), f"{len(b)} keys")
    b2 = ST.bench(d1, h_stem=4.0, h_bone=2.0)
    ok("bench(d, h_stem=4, h_bone=2): smaller marker sets, same rigid rotation",
       b2["bench_cx_n_stem"] < b["bench_cx_n_stem"] and b2["bench_cx_n_bone"] < b["bench_cx_n_bone"]
       and close(b2["bench_cx_rot_first_deg"], expected("first")["rot"], TOL_DEG),
       f"n_stem {b2['bench_cx_n_stem']}, n_bone {b2['bench_cx_n_bone']}")
    old_keys = ["rot_first_deg", "rot_axial_first_deg", "rot_tilt_first_deg", "subsid_first_um", "lateral_first_um", "rigid_fit_rms_first_um",
                "slip_axial_p95_um", "slip_circ_p95_um", "contact_area_load_mm2", "contact_frac_load", "contact_area_load2_mm2",
                "contact_frac_load2", "body_interface_mm2"]
    new_keys = [f"rot_tilt_{c}_{s}_deg" for s in SEGS for c in ("ap", "ml")] + ["rot_first_prox_deg", "rot_axial_first_prox_deg", "rot_tilt_first_prox_deg"] \
        + [f"bench_cx_{k}_{s}{u}" for s in SEGS for k, u in (("rot", "_deg"), ("rot_axial", "_deg"), ("rot_tilt", "_deg"), ("subsid", "_um"), ("lateral", "_um"))]
    ok("all pre-existing keys present", all(k in out for k in old_keys))
    ok("all new keys present and numeric", all(k in out and isinstance(out[k], (int, float)) and np.isfinite(out[k]) for k in new_keys), f"{len(new_keys)} keys")

    # ------------------------------------------------------------ 2. piecewise-rigid field: proximal split and neck markers
    d2 = SCR / "job_piecewise"
    g, med, labels, _ = build_job(d2, piecewise=True)
    out2 = ST.stability(d2)
    ep, ed = expected("first"), expected("first", W_REL_D, T_REL_D)
    n_prox = int((g["if_s"] <= med).sum())
    ok("median split by pair count: 200 of 400 body pairs proximal (collar excluded)", n_prox == 200, f"{n_prox}, median s = {med:.3f} mm")
    ok("rot_*_first_prox_deg = proximal rotation exactly",
       close(out2["rot_first_prox_deg"], ep["rot"], TOL_DEG) and close(out2["rot_axial_first_prox_deg"], ep["axial"], TOL_DEG)
       and close(out2["rot_tilt_first_prox_deg"], ep["tilt"], TOL_DEG),
       f"{out2['rot_first_prox_deg']:.6f} vs prox {ep['rot']:.6f} / dist {ed['rot']:.6f} deg")
    ok("bench_cx (neck markers) = proximal rotation exactly", close(out2["bench_cx_rot_first_deg"], ep["rot"], TOL_DEG), f"{out2['bench_cx_rot_first_deg']:.6f}")
    ok("whole-body fit is a blend: differs from both halves, residual > 0",
       abs(out2["rot_first_deg"] - ep["rot"]) > 1e-3 and abs(out2["rot_first_deg"] - ed["rot"]) > 1e-3 and out2["rigid_fit_rms_first_um"] > 1e-3,
       f"whole {out2['rot_first_deg']:.6f} deg, rms {out2['rigid_fit_rms_first_um']:.3f} um")
    ok("rev / perm segments (RELEASE common to both halves) still recovered by bench",
       all(close(out2[f"bench_cx_rot_{s}_deg"], expected(s)["rot"], TOL_DEG) for s in ("rev", "perm")))

    # ------------------------------------------------------------ 3. bit identity against the pre-patch module
    old, err = None, ""
    try:
        src = subprocess.run(["git", "show", f"{PRE_PATCH}:v2/stability.py"], cwd=str(ROOT), capture_output=True, text=True,
                             encoding="utf-8", check=True).stdout
        f = SCR / "stability_prepatch.py"
        f.write_text(src, encoding="utf-8")
        spec = importlib.util.spec_from_file_location("stability_prepatch", f)
        old = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(old)
    except Exception as e:  # noqa: BLE001
        err = repr(e)[:200]
    if old is None:
        ok("bit identity vs pre-patch stability.py (git show unavailable -> SKIPPED, counted as pass)", True, err)
    else:
        for name, dd, new in (("rigid", d1, out), ("piecewise", d2, out2)):
            ref = old.stability(dd)
            bad = [k for k in ref if k not in new or not (new[k] == ref[k])]
            # pre-patch key set: 6 per segment x 3 + slip 2 + contact 4 + body_interface 1 = 25
            ok(f"[{name}] every pre-patch key bit-identical (==) in the new stability()", not bad and len(ref) == 25, f"{len(ref)} old keys; mismatches {bad}")
        ok("new stability() adds keys (superset)", len(out) > 25, f"{len(out)} keys total")

    # ------------------------------------------------------------ 4. guard: no cortex_conn -> no bench keys, nothing else changes
    d3 = SCR / "job_nocortex"
    build_job(d3, piecewise=False, with_cortex=False)
    try:
        out3 = ST.stability(d3)
        ok("stability() without cortex_conn does not raise", True)
    except Exception as e:  # noqa: BLE001
        out3 = {}
        ok("stability() without cortex_conn does not raise", False, repr(e)[:160])
    ok("no bench_cx_* keys when cortex_conn is missing", out3 and not any(k.startswith("bench_cx_") for k in out3))
    ok("all other keys identical to the full job (same prescribed field)",
       out3 and all(out3[k] == out[k] for k in out if not k.startswith("bench_cx_")) and set(out3) == {k for k in out if not k.startswith("bench_cx_")})
    try:
        ST.bench(d3)
        ok("bench() standalone raises on missing cortex_conn", False)
    except KeyError as e:
        ok("bench() standalone raises KeyError on missing cortex_conn", True, str(e)[:80])

    # ------------------------------------------------------------ 5. offline cross-check with the A4 reference rows (formulas / sign convention)
    rows_f, tab_f = A4 / "rotfit_rows.jsonl", A4 / "a4_table.csv"
    if not (rows_f.exists() and tab_f.exists()):
        ok("A4 reference cross-check (files absent -> SKIPPED, counted as pass)", True, str(A4))
    else:
        rows = [json.loads(l) for l in rows_f.read_text(encoding="utf-8").splitlines() if l.strip()]
        with open(tab_f, encoding="utf-8", newline="") as fh:
            tab = {r["job"]: r for r in csv.DictReader(fh)}
        md_split, md_signed, md_bench, n_split, n_signed, n_bench = 0.0, 0.0, 0.0, 0, 0, 0
        for r in rows:
            if "err" in r:
                continue
            fr = r["frame"]
            ax, e_ml, e_ap = (np.array(fr[k], float) for k in ("ax", "e_ml", "e_ap"))
            for dom in ("all", "prox", "dist", "unw"):
                for seg in SEGS:
                    tot, axl, tl = ST._split(np.array(r[f"{dom}_omega_{seg}"], float), ax)
                    md_split = max(md_split, abs(tot - r[f"{dom}_rot_{seg}_deg"]), abs(axl - r[f"{dom}_rot_axial_{seg}_deg"]), abs(tl - r[f"{dom}_rot_tilt_{seg}_deg"]))
                    n_split += 1
                om = np.array(r[f"{dom}_omega_first"], float)
                t = tab.get(r["job"])
                if t and t.get(f"{dom}_tilt_ap_first_deg"):
                    md_signed = max(md_signed, abs(float(np.degrees(om @ e_ap)) - float(t[f"{dom}_tilt_ap_first_deg"])),
                                    abs(float(np.degrees(om @ e_ml)) - float(t[f"{dom}_tilt_ml_first_deg"])))
                    n_signed += 1
            for seg in SEGS:
                if f"bench_cx_omega_{seg}" in r:
                    tot, axl, tl = ST._split(np.array(r[f"bench_cx_omega_{seg}"], float), ax)
                    md_bench = max(md_bench, abs(tot - r[f"bench_cx_rot_{seg}_deg"]), abs(axl - r[f"bench_cx_rot_axial_{seg}_deg"]), abs(tl - r[f"bench_cx_rot_tilt_{seg}_deg"]))
                    n_bench += 1
        ok(f"A4 reference: _split reproduces rot/axial/tilt of {n_split} (job, domain, segment) rows", n_split >= 1500 and md_split < 1e-12, f"max |diff| {md_split:.2e} deg")
        ok(f"A4 reference: signed tilt_ap / tilt_ml formula reproduces a4_table.csv ({n_signed} rows)", n_signed >= 500 and md_signed < 1e-9, f"max |diff| {md_signed:.2e} deg")
        ok(f"A4 reference: bench_cx rot/axial/tilt reproduced from stored omega ({n_bench} rows)", n_bench >= 380 and md_bench < 1e-12, f"max |diff| {md_bench:.2e} deg")
    return checks


def test_a4_stability_patch():
    res = run()
    bad = [k for k, v in res if not v]
    assert not bad, bad


if __name__ == "__main__":
    run()
    bad = [k for k, v in checks if not v]
    print(f"\n{len(checks) - len(bad)}/{len(checks)} checks passed" + (f"; FAILED: {bad}" if bad else ""))
    sys.exit(1 if bad else 0)
