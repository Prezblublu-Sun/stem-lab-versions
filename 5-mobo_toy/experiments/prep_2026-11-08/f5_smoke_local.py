"""F5 smoke, local and 0 FE: prep the A row at m 1.0 (db3406 raw spec, friction only, h 2.0) three times in a temp queue, without foam_refine,
with h 0.7 and with h 0.5; print element and node counts, interface nodes, mesh attempt and time. Writes only the temp queue.

    PYTHONUTF8=1 ../../.venv-mobo/Scripts/python.exe f5_smoke_local.py          (start it at low priority, the solver runs on this machine)
"""
import json
import pathlib
import shutil
import sys
import tarfile
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "v2"))
import jobs as J  # noqa: E402

RAW = pathlib.Path(r"H:/projects/Femoral implant generation/db3406/raw")
CTRL = "db_ws_p13_a105_91e458e3_m1_2a79b613"
BASE = pathlib.Path(tempfile.gettempdir()) / "mobo_toy_f5_smoke"
shutil.rmtree(BASE, ignore_errors=True)
J.QROOT = BASE / "queue"
J.QROOT.mkdir(parents=True)
with tarfile.open(RAW / f"{CTRL}.tar.xz", "r:xz") as tf:
    spec0 = json.loads(tf.extractfile(f"{CTRL}/spec.json").read())
    prep0 = json.loads(tf.extractfile(f"{CTRL}/prep.json").read())
print("source", CTRL, "h_int", spec0.get("h_int"), "fric_only", spec0.get("fric_only"), "recorded elements", prep0.get("n_elements") or prep0.get("elements"), flush=True)
out = {}
for name, fr in (("prod", None), ("h0.7", {"h": 0.7}), ("h0.5", {"h": 0.5})):
    spec = dict(spec0, tag=f"f5smoke_{name}", stage="f5smoke")
    if fr:
        spec["foam_refine"] = fr
    jid = f"f5smoke_{name}"
    d = J.QROOT / jid
    d.mkdir()
    (d / "spec.json").write_text(json.dumps(spec))
    t = time.perf_counter()
    st = J.prep(jid)
    dt = time.perf_counter() - t
    rec = {"state": st, "seconds": round(dt)}
    if st == "READY":
        p = json.loads((d / "prep.json").read_text())
        m = json.loads((d / "model3d.json").read_text())
        rec.update({k: m.get(k) for k in ("n_elements", "n_nodes", "elements", "nodes", "n_tets", "quality_min", "mesh_attempt") if k in m})
        rec["foam_refine"] = p.get("foam_refine")
        rec["templating"] = p.get("templating")
        rec["inp_MB"] = round(sum(f.stat().st_size for f in d.glob("*.inp")) / 2 ** 20, 1)
        rec["model3d_keys"] = sorted(m)[:40]
    else:
        rec["failed"] = (d / "FAILED.json").read_text()[:600] if (d / "FAILED.json").exists() else None
    out[name] = rec
    print(name, json.dumps(rec, default=str)[:900], flush=True)
(pathlib.Path(__file__).resolve().parent / "data" / "f5_smoke_local.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
