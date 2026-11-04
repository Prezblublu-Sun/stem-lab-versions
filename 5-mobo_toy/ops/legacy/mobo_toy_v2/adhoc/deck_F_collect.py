"""批次 F 汇总（Linux）→ ~/mobo_toy_v2/deck/F/{F1_front.csv, F2_loads.csv, ofat_b1_wrapfit.csv}。
F1  新口径前沿 22 个设计：现行规则（原优化作业）vs 新领规则（F1 作业，领放不下时收窄）。
F2  8 个代表设计（新领规则）× 三种载荷：爬楼 2391 N（BW / E / B / F2_S1B_stair）、ISO 2300 N（10° / 9°）、高载 3606 N。
F3  B1 单因素扫描（新领规则）：F3 作业 + 领宽（CW）+ 基线（BW 的 FI），格式同 ofat.csv（baseline 记 B1w）。"""
from __future__ import annotations

import csv
import json
import math
import pathlib
import sys

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "code")); sys.path.insert(0, str(HOME / "code" / "v2")); sys.path.insert(0, str(HOME / "adhoc"))
import deck_C_collect as CC  # noqa: E402
import deck_master as D  # noqa: E402
import jobs as J  # noqa: E402

OUT = HOME / "deck" / "F"
KEYS = ("A0_shoulder_mm2", "entry_offset_e", "collar_w", "L", "alpha", "m", "f1_p95_um", "f1_all_p95_um", "f1_all_closed_p95_um", "area_frac_gt40",
        "collar_force_share_load2", "collar_open_frac_load2", "sed_chg_pct", "band_res06_pct", "vm_p99", "resected_mm3", "reamed_mm3", "bone_removed_mm3")


def rowm(j: str | None) -> dict:
    if not j:
        return {"state": "missing"}
    st = J.state(J.QROOT / j)
    if st != "DONE":
        out = {"state": st}
        if st == "FAILED":
            out["reason"] = (json.loads((J.QROOT / j / "FAILED.json").read_text()).get("reason") or "").splitlines()[0][:200]
        return out
    r = D.row_of(j)
    return {"state": "DONE", "job": j, **{k: r.get(k) for k in KEYS}}


def write(path, rows):
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if v is None or (isinstance(v, float) and not math.isfinite(v)) else v) for k, v in r.items()})


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    F = json.loads((J.RESULTS / "deck_F_ids.json").read_text())["jobs"]
    ids = {b: json.loads((J.RESULTS / f"deck_{b}_ids.json").read_text())["jobs"] for b in ("B", "E", "BW", "CW", "C")}
    # F1
    rows = []
    for k, j in F.items():
        if not k.startswith("F1_") or k.endswith("_contact"):
            continue
        src = k[3:]
        spec = json.loads((J.QROOT / j / "spec.json").read_text())
        old, new = rowm(src), rowm(j)
        newc = rowm(F.get(f"{k}_contact"))
        rows.append({"source_job": src, "collar_w_original": spec.get("collar_w_original"),
                     **{f"old_{a}": b for a, b in old.items()}, **{f"new_{a}": b for a, b in new.items()},
                     "new_sed_chg_pct_contact": newc.get("sed_chg_pct")})
    write(OUT / "F1_front.csv", rows)
    print("F1", len(rows), "designs;", sum(r["new_state"] == "DONE" for r in rows), "done")
    # F2
    stair = {"J1": ids["BW"]["J1"], "B2": ids["BW"]["B2"], "LA": ids["BW"]["LA"], "R1": ids["BW"]["R1"], "FI": ids["BW"]["FI"], "R2": ids["BW"]["R2"],
             "FI0": ids["B"]["FI0"], "S1B": F.get("F2_S1B_stair")}
    rows = []
    for c, js in stair.items():
        for ln, j in (("stair 2391 N", js), ("ISO 2300 N", F.get(f"F2_{c}_iso")), ("high 3606 N", F.get(f"F2_{c}_high"))):
            rows.append({"code": c, "load": ln, **rowm(j)})
    write(OUT / "F2_loads.csv", rows)
    print("F2", len(rows), "rows;", sum(r["state"] == "DONE" for r in rows), "done")
    # F3（格式同 ofat.csv）
    rows = []
    base_full, base_con = ids["BW"]["FI"], ids["BW"]["FI_contact"]
    r = {"baseline": "B1w", "factor": "baseline", "level": "baseline", "job": base_full, **CC.row(base_full)}
    rc = CC.row(base_con); r["sed_chg_pct_contact"] = rc.get("sed_chg_pct")
    rows.append(r)
    for k, j in F.items():
        if not k.startswith("F3_") or k.endswith("_contact"):
            continue
        _, b, rest = k.split("_", 2)
        factor, level = rest.rsplit("_", 1)
        r = {"baseline": "B1w", "factor": factor, "level": level, "job": j, **CC.row(j)}
        jc = F.get(f"{k}_contact")
        if jc:
            r["sed_chg_pct_contact"] = CC.row(jc).get("sed_chg_pct")
        rows.append(r)
    for w in (2.0, 4.0, 6.0):                                     # 领宽：CW；无领：批次 C
        kk = f"B1_collar_w_{w}"
        r = {"baseline": "B1w", "factor": "collar_w", "level": str(w), "job": ids["CW"][kk], **CC.row(ids["CW"][kk])}
        r["sed_chg_pct_contact"] = CC.row(ids["CW"][f"{kk}_contact"]).get("sed_chg_pct")
        rows.append(r)
    j0 = ids["C"]["B1_collar_w_0.0"]
    r = {"baseline": "B1w", "factor": "collar_w", "level": "0.0", "job": j0, **CC.row(j0)}; r["sed_chg_pct_contact"] = r.get("sed_chg_pct")
    rows.append(r)
    a0 = rows[0].get("A0_shoulder_mm2")
    for r in rows:
        a = r.get("A0_shoulder_mm2")
        r["shoulder_change_pct"] = 100.0 * (a / a0 - 1.0) if (a is not None and a0) else None
    write(OUT / "ofat_b1_wrapfit.csv", rows)
    print("F3", len(rows), "rows;", sum(r["state"] == "DONE" for r in rows), "done")


if __name__ == "__main__":
    main()
