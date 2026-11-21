"""FEA settings check (2026-10-28): build Abaqus decks for chosen 3406 designs OUTSIDE the queue, with the production code path
(jobs.prep's sequence: femur_for -> collar rule -> templating under a_bounds_cap -> model3d_m1.build) and optional model options.
Writes ~/mobo_toy_v2/deck/fea_check/<variant>/{m_fric.inp, m_bond.inp, mesh3d.npz, model3d.json, spec.json}. Nothing in queue/ is touched.
Linux: cd ~/mobo_toy_v2/code && OMP_NUM_THREADS=1 nice -n 19 taskset -c 8-11 ../run.sh <this> <out_root> <job_id> <variant> [key=value ...]
  variant     name of the output sub-directory
  key=value   model options passed to model3d_m1.build: mu, lagrange (0/1), slip_tol, delta, E_canc, h_int, h_far, cycles, interference
The deck header line records the options; gmsh is deterministic, so 'base' reproduces the queue job's deck.
"""
import json
import pathlib
import sys
import time

sys.path.insert(0, "v2")
import geom3d as G  # noqa: E402
import jobs as J  # noqa: E402
import model3d_m1 as M1  # noqa: E402

CAST = {"mu": float, "slip_tol": float, "delta": float, "E_canc": float, "h_int": float, "h_far": float, "cycles": int,
        "lagrange": lambda v: v in ("1", "true", "True"), "interference": str}


def main():
    out_root, job, variant = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    opts = {}
    for kv in sys.argv[4:]:
        k, v = kv.split("=", 1)
        opts[k] = CAST[k](v)
    spec = json.loads((J.QROOT / job / "spec.json").read_text())
    if spec.get("kind") not in ("design", "variant") or spec.get("model") != "m1":
        raise SystemExit(f"{job}: not an m1 design job")
    d = out_root / variant
    if d.exists():
        raise SystemExit(f"{d} exists; refusing to overwrite")
    d.mkdir(parents=True)
    t0 = time.time()
    fm = J.femur_for(spec)
    mc = spec.get("margin_check")
    import collar_rule as CR
    if spec.get("collar_rule") == "neck_in_shoulder":
        CR.install_neck(min_A0=float(spec.get("min_A0", 0.0)), margin_check=mc)
    elif spec.get("collar_rule") == "wrap_fit":
        CR.install(min_A0=float(spec.get("min_A0", 0.0)), margin_check=mc)
    elif mc:
        CR.install_margin_check(mc)
    st = G.Stem3D(**spec["design"])
    with J.a_bounds_cap(spec.get("a_bounds_max")):
        pl = G.template(st, fm, margin=spec.get("margin"))
    if not pl["fit"]:
        raise SystemExit(f"templating failed: {pl['reason']}")
    kw = dict(h_int=spec["h_int"], h_far=spec.get("h_far"), delta=spec.get("delta"), mu=spec.get("mu"), torque=spec.get("torque", True),
              E_canc=spec.get("E_canc"), slip_tol=spec.get("slip_tol"), lagrange=spec.get("lagrange"), interference=spec.get("interference"),
              cycles=spec.get("cycles"))
    kw.update(opts)
    info = M1.build(st, fm, pl, d, "m", **kw)
    rec = {"source_job": job, "variant": variant, "options": opts, "build_kw": kw, "templating": {k: pl[k] for k in ("alpha", "e", "A0", "volume")},
           "n_tet": info.get("n_tet"), "mesh_attempt": info.get("mesh_attempt"), "code_hash": J.code_hash(), "t_s": round(time.time() - t0, 1)}
    (d / "spec.json").write_text(json.dumps(spec, indent=1))
    (d / "variant.json").write_text(json.dumps(rec, indent=1, default=str))
    print(json.dumps({k: rec[k] for k in ("variant", "options", "n_tet", "t_s")}, default=str))


if __name__ == "__main__":
    main()
