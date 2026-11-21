"""看一眼 E0 输出（Linux）：python3 e0_peek.py <csv>"""
import csv
import sys

KEYS = ("f1_p95_um", "A0_shoulder_mm2", "entry_offset_e", "has_collar", "C_geo_ring_cortex_frac", "C_mesh_collar_cortex_area_frac",
        "C_mech_collar_cortex_force_share", "collar_closed_frac", "geom_check_A0_e", "neck_protrusion_mm", "body_cortex_area_frac",
        "prox_cortex_area_frac", "prox_slip_rev_p95_um", "dist_slip_rev_p95_um", "prox_area_frac", "med_area_frac", "body_press_fit_mean_MPa",
        "production_settings", "sed_chg_pct", "spec_collar_rule", "e0_errors")
R = list(csv.DictReader(open(sys.argv[1])))
print(len(R), "rows", len(R[0]), "cols")
for r in R:
    d = {}
    for k in KEYS:
        v = r.get(k, "")
        try:
            d[k] = round(float(v), 3)
        except ValueError:
            d[k] = v
    print(r["job_id"], d)
