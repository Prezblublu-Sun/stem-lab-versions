"""Review (d13colrev): independent recompute of a sample of collector values, NOT using deck_D13_collect.py code.
SED / SSI: stage_neckopt._calcar (the arms' own function) AND resorption.design_rows directly; vM, f1, bone: result.json;
rotation / contact / subsidence: stability.stability; arm records: stage_neckopt.record_of + the state-file record.
Compares with the collector's d13_rows.csv. Usage: indep.py <d13_rows.csv> <out.json>"""
import csv
import json
import math
import pathlib
import sys

sys.dont_write_bytecode = True
HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "code"))
sys.path.insert(0, str(HOME / "code" / "v2"))
import jobs as J  # noqa: E402
import resorption as RS  # noqa: E402
import stability as ST  # noqa: E402
import stage_neckopt as SN  # noqa: E402

rows_csv, out_json = sys.argv[1], sys.argv[2]
rows = list(csv.DictReader(open(rows_csv, encoding="utf-8")))
by_job = {}
for r in rows:
    by_job.setdefault(r["job"], r)
by_src = {}
for r in rows:
    by_src.setdefault(r["source_job"], r)
recs = {}
for p in (13, 14):
    for r in json.loads((HOME / "results" / f"neckopt_p{p}.json").read_text())["records"]:
        recs.setdefault(r["job_id"], r)

SAMPLE = {"sb14_a24_4dd6e4a2": "bond+fric", "collar_contact_FI_tied_d521cf81": "bond", "demo_FI_c166a2e2": "fric",
          "load_wrap_S1B_high_9f489c18": "fric", "load_wrap_S1B_stair_10ef948b": "fric",
          "v3406_noise_smoke_h16_hint1.94_1de5bb9e": "fric", "sb11_smoke_f_h16_898709ba": "fric", "sb13_a79_14e2b689": "bond+fric"}


def g7(job, iname):
    rows_, _ = RS.design_rows(job, iname=iname)
    g = [x for x in rows_ if x["scheme"] == "fixed" and x["zone"] == "G7" and x["tissue"] == "cortex"]
    assert len(g) == 1, (job, len(g))
    return g[0]["ssi_pct"], g[0]["sed_chg_pct"]


res_all, problems = {}, []


def cmp(job, name, mine, theirs, tol=1e-9):
    try:
        a = None if mine is None else float(mine)
        b = None if theirs in (None, "") else float(theirs)
    except ValueError:
        problems.append(f"{job} {name}: non-numeric {mine!r} / {theirs!r}")
        return
    if a is None and b is None:
        return
    if a is None or b is None or not math.isclose(a, b, rel_tol=tol, abs_tol=1e-12):
        problems.append(f"{job} {name}: independent {a} vs collector {b}")


for job, what in SAMPLE.items():
    d = J.QROOT / job
    spec = json.loads((d / "spec.json").read_text())
    res = json.loads((d / "result.json").read_text())
    out = {"vm_p99": res.get("vm_p99"), "f1_body_p95_um": res.get("f1_p95_um"), "bone_mm3": (res.get("bone_loss") or {}).get("total_mm3")}
    if "bond" in what:
        out["calcar_ssi"], out["calcar_sed"] = SN._calcar(job)
        out["dr_ssi"], out["dr_sed"] = g7(job, spec.get("intact_job") if spec.get("femur_id") else None)
    if "fric" in what:
        s = ST.stability(d)
        out.update({k: s.get(k) for k in ("rot_first_deg", "rot_axial_first_deg", "rot_tilt_first_deg", "contact_area_load2_mm2",
                                          "contact_frac_load2", "subsid_first_um")})
    if job in recs:
        rr = SN.record_of(job, "none", "v4" if job.startswith("sb14") else "v3", mm_limit=None)
        out["record_of"] = {k: rr.get(k) for k in ("sed_chg_pct", "ssi_pct", "vm_p99", "rot_first_deg", "contact_area_load2_mm2", "f1_body_p95_um", "bone_mm3")}
        out["state_record"] = {k: recs[job].get(k) for k in out["record_of"]}
        for k, v in out["record_of"].items():
            cmp(job, f"record_of vs state-file record {k}", v, recs[job].get(k), 1e-9)
    res_all[job] = out
    # collector rows: the job as a row (job column) and as a source (src_ columns)
    r = by_job.get(job)
    if r is not None:
        for k in ("vm_p99", "f1_body_p95_um", "bone_mm3", "rot_first_deg", "rot_axial_first_deg", "rot_tilt_first_deg", "contact_area_load2_mm2",
                  "subsid_first_um"):
            if k in out:
                cmp(job, k, out[k], r.get(k))
        if "bond" in what:
            cmp(job, "sed_chg_pct (vs _calcar)", out["calcar_sed"], r.get("sed_chg_pct"))
            cmp(job, "ssi_pct (vs _calcar)", out["calcar_ssi"], r.get("ssi_pct"))
            cmp(job, "sed_chg_pct (vs design_rows)", out["dr_sed"], r.get("sed_chg_pct"))
    rs = by_src.get(job)
    if rs is not None and rs["job"] != job:
        for k in ("vm_p99", "f1_body_p95_um", "bone_mm3", "rot_first_deg", "rot_axial_first_deg", "rot_tilt_first_deg", "contact_area_load2_mm2",
                  "subsid_first_um"):
            if k in out:
                cmp(job, "src_" + k, out[k], rs.get("src_" + k))
    if r is None and rs is None:
        problems.append(f"{job}: not in the collector CSV at all")

# derived: ratio and pct
r = by_job.get("load_wrap_S1B_high_9f489c18")
if r is not None:
    a, b = res_all["load_wrap_S1B_high_9f489c18"], res_all["load_wrap_S1B_stair_10ef948b"]
    for k in ("rot_first_deg", "contact_area_load2_mm2", "f1_body_p95_um"):
        cmp("sts ratio", k, a[k] / b[k], r.get("ratio_" + k))
r = by_job.get("v3406_noise_smoke_h16_hint1.94_1de5bb9e")
if r is not None:
    a, b = res_all["v3406_noise_smoke_h16_hint1.94_1de5bb9e"], res_all["sb11_smoke_f_h16_898709ba"]
    for k in ("rot_first_deg", "contact_area_load2_mm2", "f1_body_p95_um"):
        cmp("mesh pct", k, 100 * (a[k] - b[k]) / b[k], r.get("pct_" + k))
    pa = json.loads((J.QROOT / "v3406_noise_smoke_h16_hint1.94_1de5bb9e" / "prep.json").read_text())
    pb = json.loads((J.QROOT / "sb11_smoke_f_h16_898709ba" / "prep.json").read_text())
    na, nb = sum(pa["n_tet"].values()), sum(pb["n_tet"].values())
    cmp("mesh pct", "n_tet", 100 * (na - nb) / nb, r.get("pct_n_tet"))
    cmp("mesh pct", "n_pairs", 100 * (pa["n_pairs"] - pb["n_pairs"]) / pb["n_pairs"], r.get("pct_n_pairs"))
    cmp("mesh", "mesh_h", pa["mesh_attempt"]["h_int"], r.get("mesh_h"))
pathlib.Path(out_json).write_text(json.dumps({"values": res_all, "problems": problems}, indent=1, default=str))
print(json.dumps(res_all, indent=1, default=str))
print(f"{len(problems)} problems")
for p in problems:
    print("  PROBLEM", p)
