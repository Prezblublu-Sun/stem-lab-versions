
import sys, json, pathlib
import numpy as np
sys.path.insert(0, "v2")
import stability as S
Q = pathlib.Path.home() / "mobo_toy_v2" / "queue"
for j in sys.argv[1:]:
    d = Q / j
    r = json.loads((d / "result.json").read_text()); sp = json.loads((d / "spec.json").read_text())
    st = S.stability(d)
    # peak contact pressure on the cancellous side at RELEASE and LOAD (press-fit stress vs foam strength)
    pk = {}
    for step in ("RELEASE", "LOAD"):
        f = d / "m_fric_csv" / f"{step}_CONTACT.csv"
        if f.exists():
            import csv
            rows = list(csv.DictReader(open(f)))
            col = next((c for c in rows[0] if "CPRESS" in c.upper()), None) if rows else None
            if col:
                v = np.array([float(x[col]) for x in rows if x[col] not in ("", "nan")])
                v = v[v > 0]
                pk[step] = (round(float(np.percentile(v, 50)), 2), round(float(np.percentile(v, 95)), 2), round(float(v.max()), 1)) if len(v) else None
    print(j, "| delta", sp.get("delta"), "h", sp.get("h_cut"), "L", round(sp["design"]["L"], 1),
          "| f1", round(r.get("f1_p95_um") or -1, 1), "rot", round(st["rot_first_deg"], 4), "area", round(st["contact_area_load2_mm2"]),
          "frac", round(st["contact_frac_load2"], 3), "subsid", round(st["subsid_first_um"], 1), "perm", round(st["rot_perm_deg"], 4),
          "| CPRESS p50/p95/max MPa", pk)
