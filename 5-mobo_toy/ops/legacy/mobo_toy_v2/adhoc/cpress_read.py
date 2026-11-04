
import sys, pathlib, numpy as np, csv
Q = pathlib.Path.home() / "mobo_toy_v2" / "queue"
for j in sys.argv[1:]:
    out = []
    for step in ("RELEASE", "LOAD"):
        f = Q / j / "m_fric_csv" / f"{step}_CONTACT.csv"
        v = np.array([float(r["value"]) for r in csv.DictReader(open(f)) if r["field"] == "CPRESS"])
        v = v[v > 1e-6]
        out.append(f"{step}: n {len(v)} p50 {np.percentile(v, 50):.2f} p90 {np.percentile(v, 90):.2f} p99 {np.percentile(v, 99):.1f} max {v.max():.0f} MPa; >5 MPa {np.mean(v > 5) * 100:.0f} %")
    print(j.split("_")[-2], " | ".join(out))
