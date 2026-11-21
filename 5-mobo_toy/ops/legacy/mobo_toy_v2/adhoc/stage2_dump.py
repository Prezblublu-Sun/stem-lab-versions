"""两次第二阶段（原分法 p2、新分法 p6）及其参考设计的逐设计数据（只读）：号、贴皮质比例、微动、领、去骨量。"""
import json
import pathlib
import sys

CODE = pathlib.Path.home() / "mobo_toy_v2" / "code"
sys.path.insert(0, str(CODE)); sys.path.insert(0, str(CODE / "v2"))
import jobs as J  # noqa: E402

out = {}
for k in (1, 2, 5, 6):
    st = json.loads((J.RESULTS / f"neckopt_p{k}.json").read_text())
    rows = []
    for r in st["records"]:
        res = J.result(r["job_id"]) or {}
        t = res.get("templating") or {}
        bl = res.get("bone_loss") or {}
        rows.append({"job": r["job_id"], "round": r.get("round"), "ok": r.get("ok"), "design": r.get("design"), "h_cut": r.get("h_cut"),
                     "A0": t.get("A0"), "e": t.get("e"), "s_bind": t.get("s_bind"), "cortex_frac": res.get("cortex_area_frac"),
                     "f1_body": res.get("f1_p95_um"), "f1_all": res.get("f1_all_p95_um"), "f1_first_body": res.get("f1_first_p95_um"),
                     "gt40": res.get("area_frac_gt40"), "open_load2": res.get("open_frac_load2"),
                     "collar_share": res.get("collar_force_share_load2"), "collar_open": res.get("collar_open_frac_load2"),
                     "collar_area": res.get("collar_area"), "iface": res.get("interface_area"),
                     "loss": bl.get("total_mm3"), "reamed": bl.get("reamed_mm3"), "vm_p99": res.get("vm_p99")})
    out[str(k)] = {"ref": st.get("ref"), "rows": rows}
for f in ("neckopt_p1_ref.json", "neckopt_p5_ref.json"):
    p = J.RESULTS / f
    if p.exists():
        out[f] = json.loads(p.read_text())
(pathlib.Path.home() / "mobo_toy_v2" / "adhoc" / "out" / "stage2_dump.json").write_text(json.dumps(out, default=float))
print({k: len(v["rows"]) for k, v in out.items() if isinstance(v, dict) and "rows" in v})
