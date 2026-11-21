"""Compare the computed metrics with the values already reported in the research logs (third-version plan section 12, second-week FEA record, b14 document). Writes data/check_against_logs.txt.

A DIFF is a finding, not an error to tune away: either the log or this pack is wrong, and the table must say which.
"""
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent.parent
M = json.load(open(HERE / "data/metrics.json", encoding="utf-8"))
caps = {c["cap"]: c for c in M["cost"]["caps"]}
scan = M["one_factor"]


def s(factor, series, x, key):
    return next(r for r in scan if r["factor"] == factor and r["series"] == series and abs(r["x"] - x) < 0.02)[key]


def c(note, key):
    return next(r for r in scan if r["note"] == note)[key]


P, V, Y, C, CD, CL = M["prospective"], M["val1"], M["sensitivity"], M["cycles"], M["cycles_dex_vs_A"], M["cluster"]
C4 = M["cycles_c4_ratio"]
checks = [
    # name, computed, logged, tolerance, where
    ("A rotation", M["A"]["rot"], 0.03663, 5e-6, "FEA record 4-cycle table"),
    ("WS_m1 rotation", M["WS_m1"]["rot"], 0.05933, 5e-6, "FEA record b19"),
    ("m 0.75 dex", s("m", "A", 0.75, "dex_vs_A"), 0.094, 5e-4, "memory, b14"),
    ("m 1.0 dex", s("m", "A", 1.0, "dex_vs_A"), 0.209, 5e-4, "second plan section 6"),
    ("m 1.5 dex", s("m", "A", 1.5, "dex_vs_A"), 0.456, 5e-4, "memory, b14"),
    ("alpha 50 dex, m 0.5", s("alpha", "m0.5", 50, "dex_vs_ctrl"), -0.048, 5e-4, "second plan section 6"),
    ("alpha 55 dex, m 0.5", s("alpha", "m0.5", 55, "dex_vs_ctrl"), -0.020, 5e-4, "memory, b14"),
    ("alpha 60 dex, m 0.5", s("alpha", "m0.5", 60, "dex_vs_ctrl"), -0.008, 5e-4, "memory, b14"),
    ("b15 alpha 50 dex", s("alpha", "m1.0", 50, "dex_vs_ctrl"), -0.059, 5e-4, "third plan 22:34"),
    ("b15 alpha 55 dex", s("alpha", "m1.0", 55, "dex_vs_ctrl"), -0.025, 5e-4, "third plan 22:34"),
    ("b15 alpha 60 dex", s("alpha", "m1.0", 60, "dex_vs_ctrl"), -0.015, 5e-4, "third plan 22:34"),
    ("L 44 dex, m 1.0", s("L", "m1.0", 44, "dex_vs_ctrl"), -0.036, 5e-4, "FEA record b19"),
    ("L 44 rotation, m 1.0", s("L", "m1.0", 44, "rot"), 0.05464, 5e-6, "FEA record b19"),
    ("L 44 bone, m 1.0", s("L", "m1.0", 44, "bone"), 8.35, 5e-3, "FEA record b19"),
    ("alpha 50 L 44 against WS_m1", c("wl_m1_a50_L44", "dex_vs_ctrl"), -0.121, 5e-4, "FEA record b19"),
    ("alpha 55 L 44.75 rotation", c("wl_m1_a55_L44.75", "rot"), 0.04426, 5e-6, "FEA record b19"),
    ("alpha 55 L 44.75 bone", c("wl_m1_a55_L44.75", "bone"), 8.82, 5e-3, "FEA record b19"),
    ("A L 44.5 rotation", s("L", "m0.5", 44.5, "rot"), 0.03083, 5e-6, "FEA record b8"),
    ("A L 44.5 dex", s("L", "m0.5", 44.5, "dex_vs_ctrl"), -0.075, 5e-4, "FEA record b8"),
    ("cap 5, m>=1", caps[5]["m_ge1_rot"], 0.494, 5e-4, "FEA record 22:16"),
    ("cap 5.5, m>=1", caps[5.5]["m_ge1_rot"], 0.380, 5e-4, "FEA record 22:16"),
    ("cap 6, m>=1", caps[6]["m_ge1_rot"], 0.273, 5e-4, "FEA record 22:16"),
    ("cap 7, m>=1, after b20", caps[7]["m_ge1_rot"], 0.1388, 5e-4, "FEA record b20"),
    ("cap 7.5, m>=1", caps[7.5]["m_ge1_rot"], 0.105, 5e-4, "FEA record 22:16"),
    ("cap 8, m>=1, after b11p e 0 rows", caps[8]["m_ge1_rot"], 0.0662, 5e-4, "FEA record b11p"),
    ("cap 8.5, m>=1", caps[8.5]["m_ge1_rot"], 0.055, 5e-4, "FEA record 22:16"),
    ("AL-3 opt RMSE", P["al3m"]["opt"]["rmse"], 0.021, 5e-4, "FEA record 22:16"),
    ("AL-3 opt bias", P["al3m"]["opt"]["bias"], 0.013, 5e-4, "FEA record 22:16"),
    ("AL-3 opt in 90 %", P["al3m"]["opt"]["n_in90"], 16, 0, "FEA record 22:16"),
    ("AL-3 opt worse", P["al3m"]["opt"]["n_worse"], 15, 0, "FEA record 22:16"),
    ("AL-3 random RMSE", P["al3m"]["random"]["rmse"], 0.035, 5e-4, "FEA record 22:16"),
    ("AL-2 opt RMSE", P["al2"]["opt"]["rmse"], 0.040, 5e-4, "FEA record 11-02 11:45 entry"),
    ("AL-2 opt coverage", P["al2"]["opt"]["cov90"], 0.86, 5e-3, "FEA record 11-02 11:45 entry"),
    ("AL-1 opt RMSE", P["al1"]["opt"]["rmse"], 0.118, 5e-4, "FEA record 11-02 11:45 entry, kept as written and corrected on 11-03"),
    ("AL-1 opt coverage", P["al1"]["opt"]["cov90"], 0.63, 5e-3, "FEA record 11-02 11:45 entry, kept as written and corrected on 11-03"),
    ("AL-1 opt RMSE against al1_eval.json", P["al1"]["opt"]["rmse"], 0.0810, 5e-4, "al1_eval.json"),
    ("AL-1 opt coverage against the 11-01 summary", P["al1"]["opt"]["cov90"], 0.74, 5e-3, "11-01 summary 8.2"),
    ("noise rms", CL["nz3_rms"], 0.0051, 5e-5, "third plan 16:54"),
    ("noise 2 rms", CL["nz3_2rms"], 0.010, 5e-4, "third plan 16:54"),
    ("A to second dex", CL["A_to_second_dex"], 0.029, 5e-4, "third plan 16:54"),
    ("c10 A", C["A"]["ratio_10_1"], 1.083, 5e-4, "FEA record 15:19"),
    ("c10 m 1.0", C["A m1"]["ratio_10_1"], 1.091, 5e-4, "FEA record 15:19"),
    ("c10 init29", C["init29"]["ratio_10_1"], 1.229, 5e-4, "FEA record 15:19"),
    ("c10 C", C["C"]["ratio_10_1"], 1.276, 5e-4, "FEA record 15:19"),
    ("c10 C vs A", CD["C"]["c10"], 1.056, 5e-4, "FEA record 15:19"),
    ("c10 init29 vs A", CD["init29"]["c10"], 0.876, 5e-4, "FEA record 15:19"),
    ("c4 A", C4["A"], 1.067, 5e-4, "FEA record 12:30"),
    ("c4 a100, log computed from rounded peaks", C4["a100"], 1.080, 1e-3, "FEA record 12:30"),
    ("c4 a95", C4["a95"], 1.062, 5e-4, "FEA record 12:30"),
    ("c4 al1_07", C4["al1_07"], 1.060, 5e-4, "FEA record 12:30"),
    ("VAL median", V["ours"]["median_rel_pct"], 25.4, 0.05, "third plan 22:43"),
    ("VAL far 6 median", V["ours_far6"]["median_rel_pct"], 27.2, 0.05, "third plan 22:43"),
    ("VAL +15 median", V["plus15"]["median_rel_pct"], 19.5, 0.05, "third plan 22:43"),
    ("VAL -15 median", V["minus15"]["median_rel_pct"], 36.5, 0.05, "third plan 22:43"),
    ("Naghavi median", V["naghavi"]["median_rel_pct"], 27.0, 0.05, "third plan 22:43"),
    ("VAL bias", V["ours"]["bias_mpa"], -4.02, 5e-3, "third plan 22:43"),
    ("VAL Pearson", V["ours"]["pearson"], 0.864, 5e-4, "third plan 22:43"),
    ("Naghavi Pearson", V["naghavi"]["pearson"], 0.992, 5e-4, "third plan 22:43"),
    ("mu 0.2 Spearman", Y["mu0.2"]["spearman"], 0.989, 5e-4, "third plan 03:28"),
    ("mu 0.15 Spearman", Y["mu0.15"]["spearman"], 1.000, 5e-4, "third plan 03:28"),
    ("mu 0.2 median dex", Y["mu0.2"]["median"], 0.306, 5e-4, "third plan 03:28"),
    ("mu 0.15 median dex", Y["mu0.15"]["median"], 0.471, 5e-4, "third plan 03:28"),
    ("stair 3606 Kendall", Y["stair3606"]["kendall"], 0.867, 5e-4, "third plan 02:57"),
    ("sagittal 40 Kendall", Y["sag40"]["kendall"], 0.867, 5e-4, "third plan 02:57"),
    ("m 1.0 against A, 3606 N", M["m_cost_by_condition"]["stair3606"], 0.294, 5e-4, "third plan 02:57"),
    ("m 1.0 against A, sagittal 40", M["m_cost_by_condition"]["sag40"], 0.250, 5e-4, "third plan 02:57"),
    ("m 1.0 against A, mu 0.2", M["m_cost_by_condition"]["mu0.2"], 0.179, 5e-4, "third plan 03:28"),
    ("m 1.0 against A, mu 0.15", M["m_cost_by_condition"]["mu0.15"], 0.144, 5e-4, "third plan 03:28"),
    ("AL-3 global RMSE", P["al3m"]["global"]["rmse"], 0.065, 5e-4, "FEA record 01:11"),
    ("AL-3 global in 90 %", P["al3m"]["global"]["n_in90"], 14, 0, "FEA record 01:11"),
    ("G18 delta 0.05 Kendall", M["g18"]["delta0.05"]["kendall"], 0.974, 5e-4, "third plan 16:31"),
    ("G18 3839 N Kendall", M["g18"]["rise3839"]["kendall"], 0.923, 5e-4, "third plan 16:31"),
    ("G18 both Kendall", M["g18"]["delta0.05_rise3839"]["kendall"], 0.929, 5e-4, "third plan 16:31"),
    ("b20 m 1.75 rotation", next(r for r in scan if r["factor"] == "m" and abs(r["x"] - 1.75) < 1e-6)["rot"], 0.1388, 5e-4, "FEA record b20"),
    ("b20 m 2.0 rotation", next(r for r in scan if r["factor"] == "m" and abs(r["x"] - 2.0) < 1e-6)["rot"], 0.3827, 5e-4, "FEA record b20"),
    ("b11p a100 e +2 rotation", next(r for r in M["offset_table"] if r["design"] == "a100" and r["e"] == 2.0)["rot"], 0.1167, 5e-4, "FEA record b11p"),
    ("b11p A e -2 rotation", next(r for r in M["offset_table"] if r["design"] == "A" and r["e"] == -2.0)["rot"], 0.2590, 5e-4, "FEA record b11p"),
    ("OW-2 m 1.0 e +2 rotation, read directly from the queue", min(M["offset_rows"], key=lambda r: r["rot"])["rot"], 0.09310, 5e-6, "inspect_ow.py on the queue"),
    ("OW-2 m 1.0 e +2 bone", min(M["offset_rows"], key=lambda r: r["rot"])["bone"], 5.3227, 5e-4, "inspect_ow.py on the queue"),
    ("foam yield median, spun-out design excluded", Y["foam_yield"]["times_median"], 2.5, 0.05, "11-01 summary 7.2"),
    ("foam yield Spearman", Y["foam_yield"]["spearman_reported"], 0.991, 5e-4, "11-01 summary 7.2"),
]
out, bad = [], 0
for name, got, want, tol, where in checks:
    ok = abs(got - want) <= tol
    bad += not ok
    out.append(f"{'ok  ' if ok else 'DIFF'} {name}: computed {got:.5g}, logged {want:g} ({where})")
out.append(f"{len(checks) - bad} / {len(checks)} agree, {bad} differ. Snapshot {M['snapshot_utc']}.")
text = "\n".join(out) + "\n"
(HERE / "data/check_against_logs.txt").write_text(text, encoding="utf-8")
print("\n".join(x for x in out if x.startswith("DIFF") or " agree" in x))
