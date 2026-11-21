"""b32 / b32b before feeding (second-model review 6): prep the two real specs locally with the current code, plus the base row's physics as a
friction-only row without foam_refine; 0 FE, writes only a temp queue and data/prep_local.json.

    PYTHONUTF8=1 ../../.venv-mobo/Scripts/python.exe prep_local.py        (low priority: the solver runs on this machine)
"""
import json
import pathlib
import shutil
import sys
import tarfile
import tempfile
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "v2"))
import gmsh  # noqa: E402
import jobs as J  # noqa: E402
import stage_db as DB  # noqa: E402

RAW = pathlib.Path(r"H:/projects/Femoral implant generation/db3406/raw")
base = DB.F5_SMOKE_BASE
with tarfile.open(RAW / f"{base}.tar.xz", "r:xz") as tf:
    src = json.loads(tf.extractfile(f"{base}/spec.json").read())
    m0 = json.loads(tf.extractfile(f"{base}/model3d.json").read()) if f"{base}/model3d.json" in tf.getnames() else {}
p_ = DB._phys(src, base)
specs = {"prod": DB._variant(p_, "db_fd", src["tag"] + "_prodcheck", "fric")}
for b, hs in DB.F5_SMOKE_H.items():
    for h in hs:
        specs[f"{b}_h{h:g}"] = DB._variant(p_, "db_fd", f"{src['tag']}_f5h{h:g}", "fric", foam_refine={"h": float(h)}, slip_tol=round(DB.F5_SLIP_REF * DB.H_PROD / float(h), 9))
Q = pathlib.Path(tempfile.gettempdir()) / "mobo_toy_b32_prep"
shutil.rmtree(Q, ignore_errors=True)
J.QROOT = Q
Q.mkdir(parents=True)
out = {"gmsh": gmsh.__version__, "base": base, "base_linux_record": {k: m0.get(k) for k in ("n_nodes", "n_tet", "n_pairs", "interface_area_mm2")}}
for name, spec in specs.items():
    d = Q / name
    d.mkdir()
    (d / "spec.json").write_text(json.dumps(spec))
    t = time.perf_counter()
    st = J.prep(name)
    rec = {"state": st, "seconds": round(time.perf_counter() - t), "slip_tol": spec.get("slip_tol"), "foam_refine": spec.get("foam_refine")}
    if st == "READY":
        m = json.loads((d / "model3d.json").read_text())
        p = json.loads((d / "prep.json").read_text())
        rec.update({k: m.get(k) for k in ("n_nodes", "n_tet", "n_pairs", "n_slave_faces", "interface_area_mm2", "slip_tol", "mesh_attempt")})
        rec["prep_foam_refine"] = p.get("foam_refine")
        rec["inp_MB"] = round(sum(f.stat().st_size for f in d.glob("*.inp")) / 2 ** 20, 1)
    else:
        rec["failed"] = (d / "FAILED.json").read_text()[:600]
    out[name] = rec
    print(name, json.dumps(rec, default=str)[:700], flush=True)
(HERE / "data").mkdir(exist_ok=True)
(HERE / "data" / "prep_local.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
