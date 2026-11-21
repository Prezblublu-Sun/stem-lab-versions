"""Merge a frozen db3406 export with the read-only Linux snapshot into one table, and compute every number the conclusions table and the figures quote.

    python -X utf8 pack_data.py [--db <export dir>]

Writes data/rows.csv, data/fig1..fig6_*.csv and data/metrics.json. Rows already in the export come from the export; the snapshot only adds rows the export does not have,
so pointing --db at v0.7 makes the snapshot redundant without any other change. Rotation is the production first-load rotation rot_first_deg in both sources.
"""
import argparse
import csv
import json
import math
import pathlib
import re
from statistics import median

import numpy as np
from scipy.stats import kendalltau, spearmanr

HERE = pathlib.Path(__file__).resolve().parent.parent
DATA = HERE / "data"
FY = pathlib.Path(r"H:\projects\application\research-log\neck_implant_2026-10-02\db3406_checks\FEA_settings_2026-10-28\fy_analysis.json")
VARS = ("L", "alpha", "h_cut", "m", "rho_tip", "q", "lam", "g_ml", "g_ap", "n_a", "n_p", "tau_a", "tau_p")
SIG_VARS = tuple(v for v in VARS if v != "h_cut")  # h_cut sits outside spec["design"], and the other 12 continuous variables already identify a design
CAPS = (5, 5.5, 6, 6.5, 7, 7.5, 8, 8.5, 9, 10)
NOISE_DEX = 0.012
A_JOB = "sb13_a105_91e458e3"
WS_M1 = "db_ws_p13_a105_91e458e3_m1_2a79b613"
INIT29 = "sb13_init_2943f28a"
C_JOB = "sb14_a29_6ad70033"
TAG_A = "p13_a105_91e458e3"
# measured Mises, Naghavi FE (MPa), depth below the lesser trochanter (mm), read from thesis figure 5-23a, third-version plan section 6.1
GAUGES = {"M1": (0.0, 15.57, 10.97), "MX1": (16.0, 24.31, 19.51), "M2": (31.75, 19.31, 14.60), "MX2": (47.75, 18.15, 14.27), "M3": (63.5, 16.83, 13.64), "M4": (95.25, 15.32, 11.92),
          "L1": (0.0, 9.74, 6.43), "L2": (31.75, 13.66, 9.16), "L3": (63.5, 11.83, 7.73), "L4": (95.25, 8.96, 4.66)}
# single runs reported in the FEA settings check, 10-28, section 5; ratios of first-load rotation against the linear-elastic base
SETTINGS_CHECK = {"element_nlgeom": [("A C3D10M", 1.026), ("A NLGEOM", 1.007)], "mu0.5": [("A", 0.34), ("init29", 0.50)], "cortex10.7": [("A", 1.35), ("init29", 1.22)]}


def num(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def write_csv(name, rows, cols=None):
    cols = cols or (list(rows[0]) if rows else [])
    with open(DATA / name, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def from_export(r, origin):
    o = {"job_id": r["job_id"], "origin": origin, "layer": r["layer"], "key": "", "source": r["source"], "kind": r["kind"], "status": r["status"], "tag": r["tag"], "source_job": r.get("source_job", ""),
         "bone": (num(r["bone_total_mm3"]) or float("nan")) / 1000, "e": num(r["tpl_e"]), "A0": num(r["tpl_A0"]), "rot": num(r["rot_first_deg"]), "rot_axial": num(r["rot_axial_first_deg"]), "rot_tilt": num(r["rot_tilt_first_deg"]),
         "rot_perm": num(r["rot_perm_deg"]), "rot_rev": num(r["rot_rev_deg"]), "contact": num(r["contact_area_load2_mm2"]), "f1": num(r["f1_p95_um"]), "press": num(r["cpress_release_p95"]), "vm": num(r["vm_p99_MPa"]),
         "delta": num(r["delta_mm"]), "load_R": num(r["load_R_N"]), "af": num(r["alpha_front_deg"]), "as": num(r["alpha_sagit_deg"]), "h_int": num(r["h_int_mm"]), "E_canc": num(r["E_canc_MPa"]), "mu": num(r["mu"]),
         "cycles": num(r["cycles"]), "forced_e": num(r["entry_offset_forced_mm"]), "in_box": r["in_bounds_v1"] == "true"}
    o.update({v: num(r[v]) for v in VARS})
    return o


def from_snapshot(r):
    st, d, cfg = r.get("stability") or {}, r.get("design") or {}, (r.get("cfg") or {}).get("load") or {}
    o = {"job_id": r["job_id"], "origin": "snapshot " + r["batch"], "layer": r["layer"], "key": r["key"], "source": r["source"], "kind": r["kind"], "status": "DONE", "tag": r.get("tag") or "", "source_job": r.get("source_job") or "",
         "bone": (r.get("bone_mm3") or float("nan")) / 1000, "e": (r.get("tpl") or {}).get("e"), "A0": (r.get("tpl") or {}).get("A0"), "rot": st.get("rot_first_deg"), "rot_axial": st.get("rot_axial_first_deg"), "rot_tilt": st.get("rot_tilt_first_deg"),
         "rot_perm": st.get("rot_perm_deg"), "rot_rev": st.get("rot_rev_deg"), "contact": st.get("contact_area_load2_mm2"), "f1": (r.get("result") or {}).get("f1_p95_um"), "press": (r.get("result") or {}).get("cpress_release_p95"), "vm": (r.get("result") or {}).get("vm_p99"),
         "delta": r.get("delta"), "load_R": cfg.get("resultant_N", 2391.0), "af": cfg.get("alpha_front_deg", 20.0), "as": cfg.get("alpha_sagit_deg", 18.0), "h_int": r.get("h_int"), "E_canc": 155.0, "mu": r.get("mu") or 0.3,
         "cycles": r.get("cycles"), "forced_e": r.get("entry_offset"), "in_box": bool(r.get("in_box"))}
    o.update({v: num(d.get(v)) for v in VARS})
    o["h_cut"] = num(r.get("h_cut"))
    return o


def sig(r):
    return tuple(None if r[v] is None else round(r[v], 6) for v in SIG_VARS)


def is_strict(r):
    return (r["rot"] is not None and r["status"] == "DONE" and r["delta"] == 0.1 and r["load_R"] == 2391.0 and r["af"] == 20.0 and r["as"] == 18.0 and r["h_int"] == 2.0
            and r["E_canc"] == 155.0 and r["mu"] == 0.3 and r["cycles"] == 2 and r["forced_e"] is None)


def is_curve(r):
    """Strict baseline, plus the fixed-offset L scans the plan reports on the same footing: offset held at its templated value of 0, nothing else changed."""
    fixed = r["layer"] in ("W-0 L", "WL-1") and r["forced_e"] == 0.0
    return is_strict(r) or (r["rot"] is not None and (fixed or r["layer"] == "OW-2") and r["delta"] == 0.1 and r["h_int"] == 2.0 and r["load_R"] == 2391.0)


def envelope(rows):
    out, best = [], float("inf")
    for r in sorted(rows, key=lambda x: x["bone"]):
        if r["rot"] < best:
            best = r["rot"]
            out.append(r)
    return out


def tag_suffix(r):
    t = r["tag"] or ""
    return t[len(TAG_A) + 1:] if t.startswith(TAG_A + "_") else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=r"H:/projects/Femoral implant generation/db3406/v0.8")
    a = ap.parse_args()
    db = pathlib.Path(a.db)
    payload_line = [ln for ln in open(DATA / "now_raw.txt", encoding="utf-8") if ln.startswith("PAYLOAD ")][-1]
    now = json.loads(payload_line[len("PAYLOAD "):])
    export = list(csv.DictReader(open(db / "scalars.csv", encoding="utf-8")))
    rows = [from_export(r, db.name) for r in export]
    have = {r["job_id"] for r in rows}
    snap = {r["job_id"]: r for r in now["rows"]}
    rows += [from_snapshot(r) for r in now["rows"] if r["job_id"] not in have and r.get("kind") != "intact"]
    by_id = {r["job_id"]: r for r in rows}
    for r in rows:
        r["strict"] = is_strict(r)
        r["curve"] = is_curve(r)
        r["m_ge1"] = r["m"] is not None and r["m"] >= 0.999
    cols = ["job_id", "origin", "layer", "key", "source", "kind", "status", "strict", "curve", "in_box", "m_ge1"] + list(VARS) + ["bone", "e", "A0", "rot", "rot_axial", "rot_tilt", "rot_perm", "rot_rev", "contact", "f1", "press", "vm", "delta", "load_R", "af", "as", "h_int", "E_canc", "mu", "cycles", "forced_e", "tag", "source_job"]
    write_csv("rows.csv", rows, cols)

    A, M1 = by_id[A_JOB], by_id[WS_M1]
    M = {"export": db.name, "snapshot_utc": now["snapshot_utc"], "n_rows": len(rows), "n_export": len(export), "n_snapshot": len(rows) - len(export), "n_done": sum(r["status"] == "DONE" for r in rows), "n_failed": sum(r["status"] != "DONE" for r in rows), "not_done": [x for x in now["not_done"] if x["job_id"] not in have], "failed": now["failed"], "errors": now["errors"],
         "noise_dex": NOISE_DEX, "A": {k: A[k] for k in ("rot", "bone", "rot_perm", "rot_rev", "rot_axial", "rot_tilt", "contact", "f1", "A0")}, "WS_m1": {k: M1[k] for k in ("rot", "bone", "rot_perm", "rot_rev", "rot_axial", "rot_tilt", "contact", "f1", "A0", "vm")}}
    dex_A = lambda x: math.log10(x / A["rot"])  # noqa: E731

    # figure 1: cost curve
    curve = [r for r in rows if r["curve"] and r["bone"] == r["bone"]]
    free = [r for r in curve if r["layer"] != "OW-2" or r["forced_e"] == 0.0]         # the envelopes and caps stay on the offset the template picks; forced-offset OW-2 rows at e -2 and +2 are reported apart
    hi, ho = [r for r in free if r["m_ge1"] and r["in_box"]], [r for r in free if r["in_box"]]
    M["offset_rows"] = [{k: r[k] for k in ("job_id", "key", "m", "L", "alpha", "e", "A0", "bone", "rot", "rot_axial", "rot_tilt", "rot_perm", "rot_rev", "contact", "f1", "vm")} for r in curve if r["layer"] == "OW-2" and r["forced_e"] != 0.0]
    code = {"a105": "A", "a100": "a100", "a95": "a95", "a82": "a82", "a96": "a96"}
    table = [{"design": "A", "e": 0.0, **{k: M1[k] for k in ("A0", "bone", "rot", "rot_axial", "rot_tilt", "rot_perm", "rot_rev", "contact", "f1", "vm", "press")}}]
    for r in rows:
        if r["layer"] == "OW-2" and r["rot"] is not None:
            table.append({"design": code[re.search(r"_(a\d+)_", r["job_id"]).group(1)], "e": r["forced_e"], **{k: r[k] for k in ("A0", "bone", "rot", "rot_axial", "rot_tilt", "rot_perm", "rot_rev", "contact", "f1", "vm", "press")}})
    table.sort(key=lambda t: (t["design"] != "A", t["design"], t["e"]))
    M["offset_table"] = table
    write_csv("fig7_offset.csv", table)
    env_m1, env_all = envelope(hi), envelope(ho)
    env_ids_m1, env_ids_all = {r["job_id"] for r in env_m1}, {r["job_id"] for r in env_all}
    write_csv("fig1_cost_curve.csv", [dict(r, on_env_m1=r["job_id"] in env_ids_m1, on_env_all=r["job_id"] in env_ids_all) for r in curve],
              ["job_id", "origin", "layer", "key", "m", "L", "alpha", "e", "forced_e", "bone", "rot", "f1", "m_ge1", "in_box", "strict", "on_env_m1", "on_env_all"])
    caps = []
    for cap in CAPS:
        b1 = [r for r in hi if r["bone"] <= cap]
        b0 = [r for r in ho if r["bone"] <= cap]
        pick1, pick0 = min(b1, key=lambda r: r["rot"], default=None), min(b0, key=lambda r: r["rot"], default=None)
        caps.append({"cap": cap, "m_ge1_rot": pick1 and pick1["rot"], "m_ge1_bone": pick1 and pick1["bone"], "m_ge1_job": pick1 and pick1["job_id"], "m_ge1_f1": pick1 and pick1["f1"], "n_m_ge1": len(b1),
                     "all_rot": pick0 and pick0["rot"], "all_bone": pick0 and pick0["bone"], "all_job": pick0 and pick0["job_id"], "all_m": pick0 and pick0["m"]})
    write_csv("fig1_caps.csv", caps)
    gap = sorted(r["bone"] for r in hi if 6.5 <= r["bone"] <= 8.0)
    M["cost"] = {"caps": caps, "n_curve": len(curve), "n_m_ge1_in_box": len(hi), "bones_m_ge1_6p5_to_8": gap, "env_m1": [{k: r[k] for k in ("job_id", "bone", "rot", "m", "key", "f1")} for r in env_m1], "env_all": [{k: r[k] for k in ("job_id", "bone", "rot", "m", "key", "f1")} for r in env_all]}

    # figure 2: one-factor scans, all on the shape of A; reference values from the base rows
    scans = []
    def add(factor, series, x, r, ctrl, note=""):
        scans.append({"factor": factor, "series": series, "x": x, "job_id": r["job_id"], "rot": r["rot"], "bone": r["bone"], "rot_axial": r["rot_axial"], "rot_tilt": r["rot_tilt"], "contact": r["contact"], "times_A": r["rot"] / A["rot"], "dex_vs_A": dex_A(r["rot"]), "dex_vs_ctrl": math.log10(r["rot"] / ctrl["rot"]), "times_ctrl": r["rot"] / ctrl["rot"], "e": r["e"], "A0": r["A0"], "f1": r["f1"], "in_box": r["in_box"], "note": note})
    add("m", "A", A["m"], A, A)
    add("L", "m0.5", A["L"], A, A)
    add("alpha", "m0.5", A["alpha"], A, A)
    add("L", "m1.0", M1["L"], M1, M1)
    add("alpha", "m1.0", M1["alpha"], M1, M1)
    for r in rows:
        s = tag_suffix(r)
        if s is None or r["rot"] is None or r["delta"] != 0.1 or r["h_int"] != 2.0 or r["cycles"] != 2 or r["load_R"] != 2391.0 or r["mu"] != 0.3:
            continue
        if re.fullmatch(r"m[\d.]+", s):
            add("m", "A", r["m"], r, A)
            if r["job_id"] == WS_M1:
                continue
        elif re.fullmatch(r"a\d+", s):
            add("alpha", "m0.5", r["alpha"], r, A)
        elif re.fullmatch(r"L[\d.]+", s):
            add("L", "m0.5", r["L"], r, A)
        elif re.fullmatch(r"m1_a\d+", s):
            add("alpha", "m1.0", r["alpha"], r, M1)
        elif re.fullmatch(r"wl_m1_L[\d.]+", s):
            add("L", "m1.0", r["L"], r, M1)
        elif re.fullmatch(r"wl_m1_a\d+_L[\d.]+", s):
            add("combo", s.split("_")[2], r["L"], r, M1, s)
    order = {"m": 0, "L": 1, "alpha": 2, "combo": 3}
    scans.sort(key=lambda s: (order[s["factor"]], s["series"], s["x"]))
    write_csv("fig2_one_factor.csv", scans)
    M["one_factor"] = scans

    # figure 3: mechanism across the strict baseline
    mech = [{"job_id": r["job_id"], "rot": r["rot"], "perm_share": r["rot_perm"] / r["rot"], "rev_share": r["rot_rev"] / r["rot"], "spin_share": r["rot_axial"] / r["rot"], "tilt_share": r["rot_tilt"] / r["rot"], "contact": r["contact"], "m_ge1": r["m_ge1"], "in_box": r["in_box"]}
            for r in rows if r["strict"] and r["rot_perm"] is not None and r["rot_axial"] is not None and r["contact"] is not None]
    write_csv("fig3_mechanism.csv", mech)
    bands = [(0, 0.1), (0.1, 0.3), (0.3, 1.0), (1.0, 1e9)]
    M["mechanism"] = {"bands": [{"lo": lo, "hi": hi_, "n": len(s), "perm_share_median": median(x["perm_share"] for x in s), "rev_share_median": median(x["rev_share"] for x in s), "spin_share_median": median(x["spin_share"] for x in s), "contact_median": median(x["contact"] for x in s)}
                                for lo, hi_ in bands for s in [[x for x in mech if lo <= x["rot"] < hi_]] if s],
                      "named": {n: {"rot": by_id[j]["rot"], "perm": by_id[j]["rot_perm"], "rev": by_id[j]["rot_rev"], "spin": by_id[j]["rot_axial"], "tilt": by_id[j]["rot_tilt"], "contact": by_id[j]["contact"]} for n, j in (("A", A_JOB), ("WS_m1", WS_M1), ("init29", INIT29), ("C", C_JOB))},
                      "spearman_rot_contact": float(spearmanr([x["rot"] for x in mech], [x["contact"] for x in mech]).statistic)}

    # figure 4: sensitivity; every dot is one design against its own strict baseline row
    base_by_sig = {}
    for r in rows:
        if r["strict"]:
            base_by_sig.setdefault(sig(r), r)
    for r in rows:                                        # a design whose only baseline row holds the offset at its templated 0, such as WL_m1_L44
        if r["curve"] and r["forced_e"] == 0.0:
            base_by_sig.setdefault(sig(r), r)
    pairs = {}
    def pair(group, label, r):
        b = base_by_sig.get(sig(r))
        if b is not None and b["job_id"] != r["job_id"] and r["rot"] is not None:
            pairs.setdefault((group, label), []).append((b["job_id"], r["job_id"], b["rot"], r["rot"]))
    for r in rows:
        if r["rot"] is None or r["status"] != "DONE":
            continue
        fe_ok = r["forced_e"] is None or (r["layer"] == "CD-2" and r["forced_e"] == 0.0)
        core = r["delta"] == 0.1 and r["E_canc"] == 155.0 and fe_ok and r["cycles"] == 2 and r["mu"] == 0.3
        stair = r["load_R"] == 2391.0 and r["af"] == 20.0 and r["as"] == 18.0
        if core and stair and r["h_int"] in (1.94, 2.06):
            pair("numerics", "mesh_h1.94_2.06", r)
        elif core and stair and r["h_int"] == 2.4:
            pair("numerics", "mesh_h2.4", r)
        elif core and stair and r["h_int"] == 1.4:
            pair("numerics", "mesh_h1.4", r)
        elif r["E_canc"] == 155.0 and fe_ok and r["cycles"] == 2 and r["mu"] == 0.3 and stair and r["h_int"] == 2.0 and r["delta"] in (0.025, 0.05, 0.2):
            pair("physics", f"delta{r['delta']}", r)
        elif r["E_canc"] == 155.0 and r["forced_e"] is None and r["delta"] == 0.1 and r["cycles"] == 2 and stair and r["h_int"] == 2.0 and r["mu"] in (0.15, 0.2):
            pair("physics", f"mu{r['mu']}", r)
        elif core and r["h_int"] == 2.0 and r["load_R"] == 3839.0 and r["af"] == 24.0 and r["as"] == 8.0:
            pair("load", "rise3839", r)
        elif core and r["h_int"] == 2.0 and r["load_R"] == 1714.0 and r["af"] == 24.0 and r["as"] == 8.0:
            pair("load", "rise1714", r)
        elif r["E_canc"] == 155.0 and r["forced_e"] is None and r["cycles"] == 2 and r["mu"] == 0.3 and r["h_int"] == 2.0 and r["delta"] == 0.05 and r["load_R"] == 3839.0:
            pair("load", "delta0.05_rise3839", r)
        elif core and r["h_int"] == 2.0 and r["load_R"] == 3606.0:
            pair("load", "stair3606", r)
        elif core and r["h_int"] == 2.0 and r["load_R"] == 2391.0 and r["as"] == 40.0:
            pair("load", "sag40", r)
    # cycles from the rows' own first-cycle peak, which equals the 2-cycle row to 5 decimals
    cyc = {}
    for r in now["rows"]:
        if r.get("per_cycle"):
            cyc.setdefault(int(r["cycles"]), []).append(r)
    sens = []
    for n, rs in cyc.items():
        for r in rs:
            p = r["per_cycle"]["peak"]
            sens.append({"group": "cycles", "label": f"cycles{n}", "base_job": r["job_id"], "job_id": r["job_id"], "base_rot": p[0], "rot": p[-1], "dex": math.log10(p[-1] / p[0])})
    for (g, lab), ps in pairs.items():
        for bj, j, b, v in ps:
            sens.append({"group": g, "label": lab, "base_job": bj, "job_id": j, "base_rot": b, "rot": v, "dex": math.log10(v / b)})
    fy = json.load(open(FY, encoding="utf-8"))
    for d in fy["designs"]:
        if d.get("rot_yld") and d["rot_yld"] / d["rot_lin"] < 20:
            sens.append({"group": "physics", "label": "foam_yield", "base_job": d["source"], "job_id": d["deck"], "base_rot": d["rot_lin"], "rot": d["rot_yld"], "dex": math.log10(d["rot_yld"] / d["rot_lin"])})
    for lab, items in SETTINGS_CHECK.items():
        g = "numerics" if lab == "element_nlgeom" else "physics"
        for nm, ratio in items:
            sens.append({"group": g, "label": lab, "base_job": nm, "job_id": "FEA settings check 10-28 section 5", "base_rot": None, "rot": None, "dex": math.log10(ratio)})
    write_csv("fig4_sensitivity.csv", sens)
    summ = {}
    for s in sens:
        summ.setdefault(s["label"], []).append(s)
    M["sensitivity"] = {}
    for lab, ss in summ.items():
        dd = sorted(x["dex"] for x in ss)
        e = {"group": ss[0]["group"], "n": len(dd), "min": dd[0], "median": median(dd), "max": dd[-1], "times_median": 10 ** median(dd), "times_min": 10 ** dd[0], "times_max": 10 ** dd[-1]}
        bs, vs = [x["base_rot"] for x in ss], [x["rot"] for x in ss]
        if len(dd) >= 5 and all(x is not None for x in bs + vs):
            e["spearman"] = float(spearmanr(bs, vs).statistic)
            e["kendall"] = float(kendalltau(bs, vs).statistic)
            tight = [(b, v) for b, v in zip(bs, vs) if b < 0.1]
            e["n_tight"] = len(tight)
            if len(tight) >= 5:
                e["spearman_tight"] = float(spearmanr([b for b, _ in tight], [v for _, v in tight]).statistic)
        M["sensitivity"][lab] = e
    same = set.intersection(*[{x["base_job"] for x in summ[d]} for d in ("delta0.025", "delta0.05", "delta0.2")])
    M["delta_same_designs"] = {"n": len(same), **{d: median(x["dex"] for x in summ[d] if x["base_job"] in same) for d in ("delta0.025", "delta0.05", "delta0.2")}}
    M["sensitivity"]["foam_yield"].update({"spearman_reported": fy["metrics"]["rot"]["spearman"], "top5_overlap": fy["metrics"]["rot"]["top5_overlap"], "best_unchanged": fy["metrics"]["rot"]["best_linear"] == fy["metrics"]["rot"]["best_yield"], "spun_out": fy["spun_out"]})
    # the cost of margin under other conditions: m 1.0 against A, each on its own condition
    M["m_cost_by_condition"] = {"stair": math.log10(M1["rot"] / A["rot"])}
    for lab in ("stair3606", "sag40", "mu0.2", "mu0.15"):
        a_, m_ = [s for s in sens if s["label"] == lab and s["base_job"] == A_JOB], [s for s in sens if s["label"] == lab and s["base_job"] == WS_M1]
        if a_ and m_:
            M["m_cost_by_condition"][lab] = math.log10(m_[0]["rot"] / a_[0]["rot"])
    # G18: Kendall tau on the b9p design set only, as the criterion was written
    cd2 = {sig(r) for r in rows if r["layer"] == "CD-2" and r["delta"] == 0.05 and r["load_R"] == 2391.0}
    cd2_both = {sig(r) for r in rows if r["layer"] == "CD-2" and r["delta"] == 0.05 and r["load_R"] == 3839.0}
    M["g18"] = {}
    for lab in ("delta0.05", "rise3839", "delta0.05_rise3839"):
        ps = [(by_id[x["base_job"]]["rot"], x["rot"]) for x in sens if x["label"] == lab and sig(by_id[x["base_job"]]) in (cd2_both if lab == "delta0.05_rise3839" else cd2)]
        M["g18"][lab] = {"n": len(ps), "kendall": float(kendalltau([a for a, _ in ps], [b for _, b in ps]).statistic), "median_dex": float(np.median([math.log10(b / a) for a, b in ps]))}
    # NZ-3: the top cluster at h 2.0
    top = ["sb13_a82_cd8c77ad", "sb13_a96_429a3bcc", "sb13_a100_b1cce588", "sb13_a95_173c181a"]
    ranked = sorted(top, key=lambda j: by_id[j]["rot"])
    nz3 = [s["dex"] for s in sens if s["label"] == "mesh_h1.94_2.06" and s["base_job"] in top and s["job_id"] in snap]
    M["cluster"] = {"A_to_second_dex": math.log10(by_id[ranked[0]]["rot"] / A["rot"]), "adjacent_dex": [math.log10(by_id[ranked[i + 1]]["rot"] / by_id[ranked[i]]["rot"]) for i in range(3)], "nz3_n": len(nz3), "nz3_rms": float(np.sqrt(np.mean(np.square(nz3)))) if nz3 else None, "nz3_2rms": 2 * float(np.sqrt(np.mean(np.square(nz3)))) if nz3 else None, "nz3_max": max(abs(x) for x in nz3) if nz3 else None}

    # cycles detail, also for figure 4's note
    cyc_rows, CY = [], {}
    names = {"p13_a105_91e458e3": "A", "p13_a105_91e458e3_m1": "A m1", "p13_init_2943f28a": "init29", "p14_a29_6ad70033": "C", "p13_a82_cd8c77ad": "a82", "p13_a96_429a3bcc": "a96", "p13_a100_b1cce588": "a100", "p13_a95_173c181a": "a95", "db_al_al1_07": "al1_07"}
    for r in now["rows"]:
        if not r.get("per_cycle"):
            continue
        base = re.sub(r"_c\d+$", "", r["tag"])
        nm = next((v for k, v in names.items() if base == k or base.startswith(k + "_b") or base.startswith(k + "_")), base) if base not in names else names[base]
        pc = r["per_cycle"]
        for k, v in enumerate(pc["peak"], 1):
            cyc_rows.append({"design": nm, "cycles": r["cycles"], "k": k, "peak": v, "resid": pc["resid"][k - 1] if k <= len(pc["resid"]) else None, "rev": pc["rev"][k - 1] if k <= len(pc["rev"]) else None, "sub_um": pc["sub_um"][k - 1] if k <= len(pc["sub_um"]) else None})
        CY.setdefault(nm, {})[int(r["cycles"])] = {"job_id": r["job_id"], "peak": pc["peak"], "rev": pc["rev"], "sub_um": pc["sub_um"]}
    write_csv("fig4_cycles_detail.csv", cyc_rows)
    c10 = {k: v[10] for k, v in CY.items() if 10 in v}
    M["cycles"] = {k: {"peak1": v["peak"][0], "peak4": v["peak"][3], "peak10": v["peak"][9], "ratio_10_1": v["peak"][9] / v["peak"][0], "ratio_10_4": v["peak"][9] / v["peak"][3], "sub1": v["sub_um"][0], "sub9": v["sub_um"][8], "sub_inc9": v["sub_um"][8] - v["sub_um"][7], "rev1": v["rev"][0], "rev9": v["rev"][8]} for k, v in c10.items()}
    M["cycles_order_same"] = sorted(c10, key=lambda k: c10[k]["peak"][0]) == sorted(c10, key=lambda k: c10[k]["peak"][9])
    M["cycles_dex_vs_A"] = {k: {"c1": math.log10(c10[k]["peak"][0] / c10["A"]["peak"][0]), "c10": math.log10(c10[k]["peak"][9] / c10["A"]["peak"][9])} for k in c10}
    c4 = {k: v[4] for k, v in CY.items() if 4 in v}
    M["cycles_c4_ratio"] = {k: v["peak"][3] / v["peak"][0] for k, v in c4.items()}

    # figure 5: VAL-1
    val = []
    v0 = now["val1"]["far2.5"]["gauges"]
    v6 = now["val1"]["far6"]["gauges"]
    for g, (dep, ex, nf) in GAUGES.items():
        val.append({"gauge": g, "side": "medial" if g[0] == "M" else "lateral", "depth_mm": dep, "measured": ex, "model_far2.5": v0[g]["p0"], "model_far6": v6[g]["p0"], "naghavi_fe": nf, "turned_plus15": v0[g]["p15"], "turned_minus15": v0[g]["m15"], "rel_err_pct": 100 * (v0[g]["p0"] - ex) / ex, "naghavi_rel_err_pct": 100 * (nf - ex) / ex})
    write_csv("fig5_validation.csv", val)
    E = np.array([v["measured"] for v in val])
    def stats(F):
        F = np.array(F)
        r = np.abs(F - E) / E
        b = (F - E)
        return {"median_rel_pct": float(np.median(r) * 100), "bias_mpa": float(b.mean()), "loa": [float(b.mean() - 1.96 * b.std(ddof=1)), float(b.mean() + 1.96 * b.std(ddof=1))], "pearson": float(np.corrcoef(E, F)[0, 1]), "n_low": int((F < E).sum())}
    M["val1"] = {"job_far2.5": now["val1"]["far2.5"]["job_id"], "job_far6": now["val1"]["far6"]["job_id"], "ours": stats([v["model_far2.5"] for v in val]), "ours_far6": stats([v["model_far6"] for v in val]), "plus15": stats([v["turned_plus15"] for v in val]), "minus15": stats([v["turned_minus15"] for v in val]), "naghavi": stats([v["naghavi_fe"] for v in val]),
                 "near_neck": {v["gauge"]: v["rel_err_pct"] for v in val if v["depth_mm"] <= 16}, "M4": next(v["rel_err_pct"] for v in val if v["gauge"] == "M4")}

    # figure 6: frozen GP prediction against the FE that came after it; rows with a changed load are set aside
    acq, A6 = [], {}
    for rnd, rs in now["acq"].items():
        for p in rs:
            if p["has_cfg"] or not p["done"] or p["job_id"] not in by_id or by_id[p["job_id"]]["rot"] is None:
                continue
            fe = by_id[p["job_id"]]["rot"]
            err = math.log10(fe) - p["mu"]
            acq.append({"round": rnd, "group": p["group"], "problem": p["problem"], "rank": p["rank"], "job_id": p["job_id"], "pred_deg": 10 ** p["mu"], "sd_dex": p["sd"], "fe_deg": fe, "err_dex": err, "z": err / p["sd"]})
    write_csv("fig6_prospective.csv", acq)
    for rnd in ("al1", "al2", "al3m"):
        A6[rnd] = {}
        for g in ("opt", "global", "random"):
            s = [x for x in acq if x["round"] == rnd and x["group"] == g]
            if s:
                e, z = np.array([x["err_dex"] for x in s]), np.array([x["z"] for x in s])
                A6[rnd][g] = {"n": len(s), "rmse": float(np.sqrt((e ** 2).mean())), "bias": float(e.mean()), "sd_median": float(np.median([x["sd_dex"] for x in s])), "cov90": float((np.abs(z) < 1.645).mean()), "n_in90": int((np.abs(z) < 1.645).sum()), "max_abs": float(np.abs(e).max()), "n_worse": int((e > 0).sum())}
    M["prospective"] = A6
    e_cfg = [math.log10(by_id[p["job_id"]]["rot"]) - p["mu"] for p in now["acq"]["al1"] if p["group"] == "opt" and p["done"] and p["job_id"] in by_id and by_id[p["job_id"]]["rot"] is not None]
    M["al1_opt_with_changed_load"] = {"n": len(e_cfg), "rmse": float(np.sqrt(np.mean(np.square(e_cfg))))}
    M["pick2"] = next({"bone": r["bone"], "rot": r["rot"], "job_id": r["job_id"]} for r in rows if r["job_id"].startswith("db_al_al3m_02_"))

    (DATA / "metrics.json").write_text(json.dumps(M, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print(f"rows {len(rows)} (export {len(export)}, snapshot {len(rows) - len(export)}); strict {sum(r['strict'] for r in rows)}; curve {len(curve)}; not done {len(M['not_done'])}; DONE {M['n_done']}; FAILED {M['n_failed']}")


main()
