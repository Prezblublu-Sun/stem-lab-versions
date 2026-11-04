
import sys, json, pathlib
sys.path.insert(0, "v2")
import stability as S
Q = pathlib.Path.home() / "mobo_toy_v2" / "queue"
for j in sys.argv[1:]:
    d = Q / j
    if not (d / "DONE").exists():
        print(j, "not DONE"); continue
    r = json.loads((d / "result.json").read_text()); sp = json.loads((d / "spec.json").read_text())
    st = S.stability(d)
    print(j, "| femur", sp.get("femur_id") or "CT", "E", sp.get("E_canc"), "h_cut", sp.get("h_cut"), "L", sp["design"].get("L") if "design" in sp else None,
          "| f1", round(r.get("f1_p95_um") or -1, 1), "rot", round(st.get("rot_first_deg", -1), 4), "area", round(st.get("contact_area_load2_mm2", -1)),
          "frac", round(st.get("contact_frac_load2", -1), 3), "subsid", round(st.get("subsid_first_um", -1), 1), "A0", round((r.get("templating") or {}).get("A0", -1), 1),
          "| vm", r.get("vm_p99"), "sedG7", r.get("f2_g7_loss_pct"), "| wall", {u: round(v.get("wall_s", 0)) for u, v in json.loads((d / "solve.json").read_text()).items()})
