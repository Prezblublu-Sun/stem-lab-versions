"""Pre-FE geometric features for every comparable job (DONE or FAILED after templating), current code only.

Per job: design, templating (stored for DONE / recomputed for FAILED, plus a recompute check on a sample of DONE jobs),
fine-sampled cancellous-layer thickness between stem surface and endosteal surface (fail_fgeom.thin_layer),
in-plane neck-base clearance and cut-plane cancellous ring width (fail_fgeom.neck_clearance), coarse templating
penetration as the optimiser sees it (geom3d.penetration with the design margin), stem-axis / neck-axis angle.

    run.sh fail_features.py [--workers 3] [--check 12]   -> deck/ml_eff/failures/features.json
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import resource
import sys
import time
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import fail_fgeom as FG  # noqa: E402

OUT = FG.HOME / "deck" / "ml_eff" / "failures"
DESIGN_KEYS = ("L", "alpha", "collar_w", "m", "rho_tip", "q", "lam", "g_ml", "g_ap", "n_a", "n_p", "tau_a", "tau_p", "cap_h", "collar_t")


def _limit():
    resource.setrlimit(resource.RLIMIT_AS, (6 << 30, 6 << 30))


def candidates():
    J = FG.J
    out = []
    for d in sorted(J.QROOT.glob("*")):
        sp = d / "spec.json"
        if not sp.exists():
            continue
        spec = json.loads(sp.read_text())
        if spec.get("kind") not in ("design", "variant") or spec.get("model") != "m1" or spec.get("bond_only") or spec.get("import_stem"):
            continue
        st = J.state(d)
        if st not in ("DONE", "FAILED"):
            continue
        cur = J.job_id({**spec, "created": ""}) == d.name
        prep_cur = False
        if (d / "prep.json").exists():
            prep_cur = json.loads((d / "prep.json").read_text()).get("code_hash") == J.code_hash()
        if not (cur or prep_cur):
            continue
        lvl = None
        if st == "FAILED":
            lvl = json.loads((d / "FAILED.json").read_text()).get("level")
            if lvl in ("L1", "SKIP"):
                continue
        out.append((d.name, st, lvl))
    return out


def one(args):
    job, st_, lvl, recheck = args
    t0 = time.time()
    J = FG.J
    d = J.QROOT / job
    spec = json.loads((d / "spec.json").read_text())
    rec = {"job": job, "state": st_, "level": lvl, "stage": spec.get("stage"), "kind": spec.get("kind"),
           "collar_rule": spec.get("collar_rule"), "h_cut": spec.get("h_cut"), "h_int": spec.get("h_int"),
           "cfg": bool(spec.get("cfg")), "margin_spec": spec.get("margin"), "entry_offset": spec.get("entry_offset"),
           "model_keys": [k for k in ("mu", "E_canc", "interference", "lagrange", "cycles", "torque", "h_far", "slip_tol", "delta")
                          if spec.get(k) is not None and not (k == "slip_tol" and spec[k] == 2.5e-4) and not (k == "delta" and spec[k] == 0.025)]}
    rec.update({k: spec["design"].get(k) for k in DESIGN_KEYS})
    try:
        stored = None
        for f in ("result.json", "prep.json"):
            if (d / f).exists():
                stored = json.loads((d / f).read_text()).get("templating")
                if stored:
                    break
        if stored and not recheck:
            fm = FG.femur_for(spec)
            st = FG.G.Stem3D(**spec["design"])
            A0, alpha, e = stored["A0"], stored["alpha"], stored["e"]
            pose = fm.pose(alpha, e)
            rec["tpl_src"] = "stored"
            rec.update({f"tpl_{k}": stored.get(k) for k in ("alpha", "e", "A0", "contact", "s_bind", "volume", "margin")})
        else:
            st, fm, pl = FG.template_for(spec)
            if not pl.get("fit"):
                rec["tpl_src"] = "recomputed_nofit"
                rec["tpl_reason"] = pl.get("reason")
                return rec
            A0, alpha, e, pose = pl["A0"], pl["alpha"], pl["e"], pl["pose"]
            rec["tpl_src"] = "recomputed"
            rec.update({f"tpl_{k}": pl.get(k) for k in ("alpha", "e", "A0", "contact", "s_bind", "volume", "margin")})
            if stored:
                rec["tpl_check_dA0"] = float(A0 - stored["A0"])
                rec["tpl_check_de"] = float(e - stored["e"])
        margin = st.m if spec.get("margin") is None else float(spec["margin"])
        rec["pen_coarse_mm"] = float(FG.G.penetration(st, fm, A0, pose, margin))     # what templating sees (should be <= 0.05)
        rec.update(FG.thin_layer(st, fm, A0, pose))
        rec.update(FG.neck_clearance(st, fm, A0, pose))
        P0, dax, _, _ = pose
        rec["axis_neck_angle_deg"] = float(math.degrees(math.acos(np.clip(-dax @ fm.u3, -1, 1))))
        rec["tl_margin_shortfall_mm"] = float(margin - rec["tl_min_mm"])            # > 0: fine sampling finds the stem closer than m
    except Exception as ex:                                                          # noqa: BLE001
        rec["err"] = f"{type(ex).__name__}: {ex}"[:300]
    rec["wall_s"] = time.time() - t0
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--check", type=int, default=12, help="DONE jobs re-templated to verify the recompute path")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    c = candidates()
    if a.limit:
        c = c[:a.limit]
    rng = np.random.default_rng(0)
    done_idx = [i for i, x in enumerate(c) if x[1] == "DONE"]
    chk = set(rng.choice(done_idx, size=min(a.check, len(done_idx)), replace=False).tolist()) if a.check else set()
    tasks = [(j, s, l, i in chk) for i, (j, s, l) in enumerate(c)]
    print(f"{len(tasks)} jobs ({sum(1 for t in tasks if t[1] == 'FAILED')} failed, {len(chk)} rechecks)", flush=True)
    t0 = time.time()
    with Pool(a.workers, initializer=_limit) as p:
        res = p.map(one, tasks, chunksize=4)
    (OUT / "features.json").write_text(json.dumps(res, default=float))
    errs = [r for r in res if r.get("err")]
    print(f"done {len(res)} in {time.time() - t0:.0f} s; errors {len(errs)}", flush=True)
    for r in errs[:10]:
        print("ERR", r["job"], r["err"], flush=True)
    for r in res:
        if r.get("tpl_check_dA0") is not None:
            print("check", r["job"], round(r["tpl_check_dA0"], 4), r["tpl_check_de"], flush=True)


if __name__ == "__main__":
    main()
