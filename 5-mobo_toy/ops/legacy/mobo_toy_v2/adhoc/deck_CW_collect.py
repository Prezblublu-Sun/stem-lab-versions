"""领宽扫描按新领规则重算的汇总（Linux）→ ~/mobo_toy_v2/deck/ofat_collar_wrapfit.csv。
每个基线：现行规则（批次 C + 批次 B 基线）与 wrap_fit（批次 CW + 批次 BW 基线）两条线；无领水平两种规则相同，取批次 C 的结果。"""
from __future__ import annotations

import csv
import json
import math
import pathlib
import sys

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "code")); sys.path.insert(0, str(HOME / "code" / "v2")); sys.path.insert(0, str(HOME / "adhoc"))
import deck_C_collect as CC  # noqa: E402
import jobs as J  # noqa: E402


def pair(full: str, contact: str | None) -> dict:
    r = CC.row(full)
    if contact:
        rc = CC.row(contact)
        r["sed_chg_pct_contact"], r["band_res06_pct_contact"] = rc.get("sed_chg_pct"), rc.get("band_res06_pct")
    return r


def main():
    ids = {b: json.loads((J.RESULTS / f"deck_{b}_ids.json").read_text())["jobs"] for b in ("B", "C", "BW", "CW")}
    out = []
    for b, code in (("B1", "FI"), ("B2", "B2")):
        for rule, base_ids, sweep_ids, prefix in (("current", ids["B"], ids["C"], b), ("wrap_fit", ids["BW"], ids["CW"], b)):
            out.append({"baseline": b, "rule": rule, "level": 3.0, "is_baseline": True, "job": base_ids[code], **pair(base_ids[code], base_ids.get(f"{code}_contact"))})
            for w in (0.0, 2.0, 4.0, 6.0):
                src = ids["C"] if (w == 0.0 or rule == "current") else sweep_ids
                k = f"{prefix}_collar_w_{w}"
                out.append({"baseline": b, "rule": rule, "level": w, "is_baseline": False, "job": src[k], **pair(src[k], src.get(f"{k}_contact"))})
    keys = list(dict.fromkeys(k for r in out for k in r))
    with open(HOME / "deck" / "ofat_collar_wrapfit.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, keys)
        w.writeheader()
        for r in out:
            w.writerow({k: ("" if v is None or (isinstance(v, float) and not math.isfinite(v)) else v) for k, v in r.items()})
    for r in out:
        print(r["baseline"], r["rule"], r["level"], r["state"], {k: (round(r[k], 2) if isinstance(r.get(k), float) else r.get(k))
                                                                 for k in ("A0_shoulder_mm2", "f1_p95_um", "collar_force_share_load2", "sed_chg_pct", "bone_removed_mm3")})


if __name__ == "__main__":
    main()
