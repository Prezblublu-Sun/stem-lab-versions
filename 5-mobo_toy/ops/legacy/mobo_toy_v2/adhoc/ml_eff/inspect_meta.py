"""Read-only: print meta of neckopt_p7..p10.json and list the phase pools."""
import json
import pathlib

import numpy as np

HOME = pathlib.Path.home() / "mobo_toy_v2"
R = HOME / "results"
for ph in (7, 8, 9, 10):
    st = json.loads((R / f"neckopt_p{ph}.json").read_text())
    meta = {k: v for k, v in st.items() if k not in ("records", "warm_start_ids", "lengthscales", "hv_hist", "pending")}
    print("==== phase", ph)
    print(json.dumps(meta, default=float)[:1500])
    hv = st.get("hv_hist", [])
    print("hv_hist n", len(hv), "first", hv[:2], "last", hv[-2:])
    recs = st["records"]
    print("records", len(recs), "ok", sum(r["ok"] for r in recs), "feasible", sum(r["ok"] and r["c"][0] <= 0 for r in recs),
          "rounds", sorted(set(r["round"] for r in recs))[:5], "...", "pool_idx None", sum(r.get("pool_idx") is None for r in recs))
    print("warm ids", len(st.get("warm_start_ids", [])), st.get("warm_start_ids", [])[:3])
    print("rec keys", list(recs[0].keys()))
for f in sorted((R / "pools").glob("neckopt_p*")):
    if f.suffix == ".npz":
        z = np.load(f)
        print(f.name, z["U"].shape)
    else:
        print(f.name, f.read_text()[:300])
for f in sorted(R.glob("neckopt_p*_pool_live.npz")):
    z = np.load(f)
    print(f.name, z["U"].shape)
