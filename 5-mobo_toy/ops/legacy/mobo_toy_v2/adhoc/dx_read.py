
import sys, json, pathlib
import numpy as np
sys.path.insert(0, "v2")
import stability as S
Q = pathlib.Path.home() / "mobo_toy_v2" / "queue"
rows = {}
for d in sorted(Q.glob("v3406_dx_*")):
    if not (d / "DONE").exists():
        continue
    sp = json.loads((d / "spec.json").read_text()); src = sp["source_job"]
    rows.setdefault(src, {})[sp["delta"]] = d
out = []
for src, dd in rows.items():
    dd[0.025] = Q / src
    rec = {"src": src.split("_")[2]}
    s0 = json.loads((Q / src / "spec.json").read_text())
    rec["L"] = round(s0["design"]["L"], 1); rec["h"] = round(s0["h_cut"], 1); rec["alpha"] = round(s0["design"]["alpha"], 1)
    for dl in (0.025, 0.1, 0.2):
        if dl in dd:
            r = json.loads((dd[dl] / "result.json").read_text()); st = S.stability(dd[dl])
            rec[f"f1_{dl}"] = round(r["f1_p95_um"]); rec[f"rot_{dl}"] = round(st["rot_first_deg"], 3); rec[f"area_{dl}"] = round(st["contact_area_load2_mm2"])
    out.append(rec)
print(json.dumps(out))
