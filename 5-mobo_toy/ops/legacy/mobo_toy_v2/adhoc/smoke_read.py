
import sys, json, pathlib
sys.path.insert(0, "v2")
import stability as S
Q = pathlib.Path.home() / "mobo_toy_v2" / "queue"
for j in ("sb11_smoke_f_h16_898709ba", "sb11_smoke_f_h20_da62abd1"):
    d = Q / j
    r = json.loads((d / "result.json").read_text())
    st = S.stability(d)
    keys = ("f1_p95_um", "f1_first_p95_um", "f1_closed_p95_um", "frac_open", "fric_only")
    print(j, {k: r.get(k) for k in keys}, "bone", (r.get("bone_loss") or {}).get("total_mm3"), "A0", (r.get("templating") or {}).get("A0"))
    print("   stab", {k: round(v, 5) if isinstance(v, float) else v for k, v in st.items() if k in ("rot_first_deg", "rot_axial_first_deg", "rot_tilt_first_deg", "rot_perm_deg", "subsid_first_um", "subsid_perm_um", "contact_area_load2_mm2", "contact_frac_load2", "rigid_fit_rms_first", "bench_cx_rot_perm_deg")})
    print("   solve", {u: v.get("wall_s") for u, v in json.loads((d / "solve.json").read_text()).items()})
