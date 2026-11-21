"""Mesh-only probe for the 3406 intact reference at candidate interface sizes (no queue, no FE solve).
Builds the intact model exactly as jobs.prep does for kind 'intact' into a scratch dir and reports
BuildError or the tet quality summary. Usage: ../run.sh <this> <outdir> h1 [h2 ...]"""
import json
import pathlib
import sys
import time

sys.path.insert(0, "v2")
import jobs as J  # noqa: E402
import model3d_v2 as M  # noqa: E402

out = pathlib.Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
for h in [float(x) for x in sys.argv[2:]]:
    spec = {"h_int": h, "femur_id": "sawbone3406", "neck_axis": "isthmus", "kind": "intact"}
    d = out / f"intact_h{h:g}"
    d.mkdir(exist_ok=True)
    t0 = time.time()
    try:
        fm = J.femur_for(spec)
        info = M.build_intact(fm, d, "intact", h_roi=h, h_far=6.0)
        q = info.get("quality") if isinstance(info, dict) else None
        print(json.dumps({"h": h, "ok": True, "s": round(time.time() - t0, 1), "n_tet": (info or {}).get("n_tet"),
                          "quality": q}, default=str)[:600], flush=True)
    except M.BuildError as e:
        print(json.dumps({"h": h, "ok": False, "s": round(time.time() - t0, 1), "error": str(e)[:300]}), flush=True)
