"""Failure inventory (read-only on queue/results).

Outputs (~/mobo_toy_v2/deck/ml_eff/failures/):
  inventory_failed.json   one record per FAILED job: spec essentials, level/stage, parsed mesh attempts, surfaces named,
                          prep.log excerpt, timing (created -> FAILED), solve.json summary for L4
  inventory_retry.json    DONE jobs whose prep needed > 1 mesh attempt (prep.json mesh_attempt.previous_errors), parsed
  bo_records.json         per phase p7..p10: records in submission order with ok flag, x (unit), job, round, pool_idx;
                          plus meta (vars, pool size, warm start n)
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import re
import sys

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "code"))
sys.path.insert(0, str(HOME / "code" / "v2"))
import jobs as J  # noqa: E402

OUT = HOME / "deck" / "ml_eff" / "failures"
OUT.mkdir(parents=True, exist_ok=True)
ATT = re.compile(r"algo (\d+), h ([\d.]+), m (\d+): (.*?)(?= \| algo |\n|$)")


def err_class(s: str) -> str:
    s2 = s.lower()
    if "overlapping facets" in s2:
        return "overlapping_facets"
    if "segment and a facet intersect" in s2:
        return "plc_segment_facet"
    if "two facets intersect" in s2:
        return "plc_facet_facet"
    if "plc error" in s2:
        return "plc_other"
    if "hxt" in s2:
        return "hxt_failed"
    if "degenerate tetrahedra" in s2:
        return "degenerate_tets"
    if "undefined normal" in s2:
        return "undefined_normal"
    if "interface too small" in s2:
        return "interface_small"
    if "head load nodes" in s2:
        return "head_nodes_touch_interface"
    return "other"


def parse_attempts(reason: str):
    out = []
    for algo, h, m, msg in ATT.findall(reason):
        out.append({"algo": int(algo), "h": float(h), "m": int(m), "cls": err_class(msg), "msg": msg[:160]})
    return out


def tparse(s):
    try:
        return dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except Exception:                                             # noqa: BLE001
        return None


def main():
    failed, retry = [], []
    cur = J.code_hash()
    for d in sorted(J.QROOT.glob("*")):
        sp = d / "spec.json"
        if not sp.exists():
            continue
        spec = json.loads(sp.read_text())
        st = J.state(d)
        if st == "FAILED":
            f = json.loads((d / "FAILED.json").read_text())
            reason = f.get("reason", "")
            log = (d / "prep.log").read_text(errors="replace") if (d / "prep.log").exists() else ""
            rec = {"job": d.name, "stage": spec.get("stage"), "kind": spec.get("kind"), "model": spec.get("model"),
                   "collar_rule": spec.get("collar_rule"), "design": spec.get("design"), "h_cut": spec.get("h_cut"),
                   "margin": spec.get("margin"), "entry_offset": spec.get("entry_offset"), "cfg": spec.get("cfg"),
                   "h_int": spec.get("h_int"), "created": spec.get("created"),
                   "level": f.get("level"), "fail_stage": f.get("stage"), "fail_time": f.get("time"),
                   "attempts": parse_attempts(reason),
                   "surfaces": sorted({int(x) for p in re.findall(r"on surface (\d+) surface (\d+)", reason) for x in p}),
                   "reason_head": reason[:600], "prep_log_head": log[:600],
                   "current_code": J.job_id({**spec, "created": ""}) == d.name,
                   "has_prep": (d / "prep.json").exists(), "has_mesh": (d / "mesh3d.npz").exists()}
            t0, t1 = tparse(spec.get("created", "")), tparse(f.get("time", ""))
            rec["created_to_fail_s"] = (t1 - t0).total_seconds() if t0 and t1 else None
            if (d / "solve.json").exists():
                s = json.loads((d / "solve.json").read_text())
                rec["solve"] = {k: {kk: v.get(kk) for kk in ("status", "wall_s", "tries", "reason")} for k, v in s.items()}
            if (d / "prep.json").exists():
                p = json.loads((d / "prep.json").read_text())
                rec["prep"] = {k: p.get(k) for k in ("n_tet", "n_nodes", "interface_area_mm2", "templating", "mesh_attempt", "mesh_quality")}
            failed.append(rec)
        elif st == "DONE" and (d / "prep.json").exists():
            p = json.loads((d / "prep.json").read_text())
            ma = p.get("mesh_attempt") or {}
            prev = ma.get("previous_errors") or []
            if prev:
                retry.append({"job": d.name, "stage": spec.get("stage"), "kind": spec.get("kind"), "model": spec.get("model"),
                              "collar_rule": spec.get("collar_rule"), "design": spec.get("design"), "h_cut": spec.get("h_cut"),
                              "final_attempt": {k: ma.get(k) for k in ("algorithm3d", "h_int", "section_points")},
                              "n_previous": len(prev), "previous": [{"cls": err_class(e), "msg": e[:200]} for e in prev],
                              "code_hash": p.get("code_hash"), "current_hash": p.get("code_hash") == cur})
    (OUT / "inventory_failed.json").write_text(json.dumps(failed, indent=1, default=float))
    (OUT / "inventory_retry.json").write_text(json.dumps(retry, indent=1, default=float))
    # BO records per phase
    bo = {}
    for ph in range(1, 11):
        f = J.RESULTS / f"neckopt_p{ph}.json"
        if not f.exists():
            continue
        s = json.loads(f.read_text())
        recs = []
        for i, r in enumerate(s.get("records", [])):
            recs.append({"i": i, "job": r.get("job_id"), "round": r.get("round"), "pool_idx": r.get("pool_idx"), "ok": r.get("ok"),
                         "x": r.get("x"), "y": r.get("y"), "c": r.get("c"), "state": J.state(J.QROOT / r["job_id"]) if r.get("job_id") else None})
        bo[ph] = {"vars": list(s.get("space", {}).keys()), "space": s.get("space"), "fixed": s.get("fixed"), "mode": s.get("mode"),
                  "pool_size": s.get("pool_size"), "warm_start_n": s.get("warm_start_n"), "n_records": len(recs),
                  "pending": list((s.get("pending") or {}).keys()), "records": recs, "hv_hist": s.get("hv_hist")}
    (OUT / "bo_records.json").write_text(json.dumps(bo, default=float))
    # pool files for p9/p10 (for the blocked-region estimate)
    pools = sorted(str(p.name) for p in (J.RESULTS / "pools").glob("neckopt_p1[0]_*")) + sorted(str(p.name) for p in J.RESULTS.glob("neckopt_p10_pool_live*"))
    print("failed", len(failed), "retry", len(retry), "phases", sorted(bo), "pools", pools)
    from collections import Counter
    print(Counter((r["level"], r["current_code"]) for r in failed))
    print(Counter((r["stage"], r["final_attempt"]["algorithm3d"], r["previous"][0]["cls"]) for r in retry))


if __name__ == "__main__":
    main()
