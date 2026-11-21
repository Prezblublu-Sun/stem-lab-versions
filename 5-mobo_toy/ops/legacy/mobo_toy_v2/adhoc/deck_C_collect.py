"""批次 C 汇总（Linux）：单因素扫描 → ~/mobo_toy_v2/deck/ofat.csv。
每行 = 一个基线 × 因素 × 水平：完整作业（摩擦 + 领共节点粘接）的指标，加同水平接触领粘接模型的股骨距量；不可行的记原因与肩部面积。
基线：B1 = 现行设置的 FI（批次 B 的 demo_FI / demo_FI_contact），B2 = neck5_r10（批次 B 的 demo_B2 / demo_B2_contact）。"""
from __future__ import annotations

import csv
import json
import math
import pathlib
import re
import sys

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "code")); sys.path.insert(0, str(HOME / "code" / "v2")); sys.path.insert(0, str(HOME / "adhoc"))
import deck_master as D  # noqa: E402
import jobs as J  # noqa: E402
import stage_deck as SD  # noqa: E402

KEEP = ("A0_shoulder_mm2", "entry_offset_e", "f1_p95_um", "f1_body_label", "f1_all_p95_um", "f1_all_closed_p95_um", "f1_first_p95_um",
        "area_frac_gt40", "open_frac_load2", "collar_force_share_load2", "collar_open_frac_load2", "sed_chg_pct", "ssi_pct", "band_res06_pct",
        "g7_res06_pct", "vm_p99", "resected_mm3", "reamed_mm3", "bone_removed_mm3", "L", "alpha", "m", "collar_w", "rho_tip", "q", "lam",
        "var_mu", "var_delta")


def row(j: str) -> dict:
    st = J.state(J.QROOT / j)
    if st == "DONE":
        r = D.row_of(j)
        return {"state": "DONE", **{k: r.get(k) for k in KEEP}}
    if st == "FAILED":
        f = json.loads((J.QROOT / j / "FAILED.json").read_text())
        reason = (f.get("reason") or "").splitlines()[0][:200]
        m = re.search(r"shoulder (\d+(?:\.\d+)?) mm", reason)
        return {"state": "FAILED", "level_fail": f.get("level"), "reason": reason, "A0_shoulder_mm2": float(m.group(1)) if m else None}
    return {"state": st}


def main():
    ids_c = json.loads((J.RESULTS / "deck_C_ids.json").read_text())["jobs"]
    ids_b = json.loads((J.RESULTS / "deck_B_ids.json").read_text())["jobs"]
    out = []
    base = {"B1": ("FI", ids_b["FI"], ids_b["FI_contact"]), "B2": ("B2", ids_b["B2"], ids_b["B2_contact"])}
    for b, (code, jf, jc) in base.items():
        r = {"baseline": b, "factor": "baseline", "level": "baseline", "job": jf, **row(jf)}
        rc = row(jc)
        r["sed_chg_pct_contact"], r["band_res06_pct_contact"] = rc.get("sed_chg_pct"), rc.get("band_res06_pct")
        out.append(r)
    for key, j in ids_c.items():
        if key.endswith("_contact"):
            continue
        b, rest = key.split("_", 1)
        factor, level = rest.rsplit("_", 1)
        r = {"baseline": b, "factor": factor, "level": level, "job": j, **row(j)}
        jc = ids_c.get(f"{key}_contact")
        if jc:
            rc = row(jc)
            r["sed_chg_pct_contact"], r["band_res06_pct_contact"] = rc.get("sed_chg_pct"), rc.get("band_res06_pct")
            r["contact_state"] = rc["state"]
        out.append(r)
    b0 = {r["baseline"]: r for r in out if r["factor"] == "baseline"}
    for r in out:
        a, a0 = r.get("A0_shoulder_mm2"), b0[r["baseline"]].get("A0_shoulder_mm2")
        r["shoulder_change_pct"] = 100.0 * (a / a0 - 1.0) if (a is not None and a0) else None
    keys = list(dict.fromkeys(k for r in out for k in r))
    with open(HOME / "deck" / "ofat.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, keys)
        w.writeheader()
        for r in out:
            w.writerow({k: ("" if v is None or (isinstance(v, float) and not math.isfinite(v)) else v) for k, v in r.items()})
    print(len(out), "rows;", sum(r["state"] == "DONE" for r in out), "done,", sum(r["state"] == "FAILED" for r in out), "infeasible")


if __name__ == "__main__":
    main()
