"""After deploying the F5 hook (second-model review 6): on Linux, in adhoc/f5 only, prep (1) an exact copy of the b32 base row's spec and compare
the mesh with the base row's own model3d.json in the queue (the new jobs.py must not change a job without foam_refine), (2) the b32 h 1.0 spec,
and the b32b h 0.7 spec, to see the hook work with Linux's gmsh. 0 FE; reads the queue, writes only ~/mobo_toy_v2/adhoc/f5/.
Exit 1 unless the copy has the recorded node, tet, pair and face counts and the contact pairs are >= 2.0 x (h 1.0) and >= 4.0 x (h 0.7).

    cd ~/mobo_toy_v2/code && OMP_NUM_THREADS=1 nice -n 19 taskset -c 4-11 ../run.sh ../adhoc/f5/linux_check.py
"""
import json
import pathlib
import shutil
import sys
import time

sys.path.insert(0, "v2")
import gmsh  # noqa: E402
import jobs as J  # noqa: E402

BASE = "db_ws_p13_a105_91e458e3_ow_m1_e+2_c9ca96c8"
A = pathlib.Path.home() / "mobo_toy_v2" / "adhoc" / "f5"
Q = A / "queue"
REAL = J.QROOT
src = json.loads((REAL / BASE / "spec.json").read_text())
rec = json.loads((REAL / BASE / "model3d.json").read_text())
shutil.rmtree(Q, ignore_errors=True)
Q.mkdir(parents=True)
J.QROOT = Q
f5 = {}
for h, slip in ((1.0, 5e-4), (0.7, 0.000714286)):
    f5[h] = {k: v for k, v in src.items() if k != "intact_job"}
    f5[h].update(stage="db_fd", tag=src["tag"] + f"_f5h{h:g}", fric_only=True, foam_refine={"h": h}, slip_tol=slip)
keys = ("n_nodes", "n_tet", "n_pairs", "n_slave_faces", "interface_area_mm2", "mesh_attempt")
out = {"gmsh": gmsh.__version__, "code_hash": J.code_hash(), "record": {k: rec.get(k) for k in keys}}
for name, spec in (("base_copy", src), ("f5h1", f5[1.0]), ("f5h0.7", f5[0.7])):
    d = Q / name
    d.mkdir()
    (d / "spec.json").write_text(json.dumps(spec))
    t = time.perf_counter()
    st = J.prep(name)
    r = {"state": st, "seconds": round(time.perf_counter() - t)}
    if st == "READY":
        m = json.loads((d / "model3d.json").read_text())
        r.update({k: m.get(k) for k in keys})
        r["prep_foam_refine"] = json.loads((d / "prep.json").read_text()).get("foam_refine")
    else:
        r["failed"] = (d / "FAILED.json").read_text()[:500]
    out[name] = r
b = out["base_copy"]
out["base_copy_equals_record"] = all(b.get(k) == rec.get(k) for k in ("n_nodes", "n_tet", "n_pairs", "n_slave_faces"))
ratio = {n: (round(out[n]["n_pairs"] / rec["n_pairs"], 2) if out[n].get("n_pairs") else None) for n in ("f5h1", "f5h0.7")}
out["pairs_ratio"] = ratio
out["ok"] = bool(out["base_copy_equals_record"] and (ratio["f5h1"] or 0) >= 2.0 and (ratio["f5h0.7"] or 0) >= 4.0)
(A / "linux_check.json").write_text(json.dumps(out, indent=1, default=str))
print(json.dumps(out, default=str))
sys.exit(0 if out["ok"] else 1)
