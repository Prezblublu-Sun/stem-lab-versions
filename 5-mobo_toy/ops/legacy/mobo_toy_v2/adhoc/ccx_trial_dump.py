"""CalculiX 试算：各作业目录（queue / queue_<变体>）里已完成设计的 Abaqus 对 CalculiX 指标（只读，输出 JSON 到 stdout）。"""
import json
import pathlib

BASE = pathlib.Path.home() / "mobo_toy_v2"
KEYS = ("f1_p95_um", "f1_all_p95_um", "f1_closed_p95_um", "f1_first_p95_um", "area_frac_gt40", "open_frac_load2",
        "collar_force_share_load2", "collar_open_frac_load2", "cpress_release_p50", "status_frac_stick", "status_frac_slip",
        "f2_g7_loss_pct", "f2_g1_loss_pct", "vm_p99")
rows = []
for q in sorted((BASE / "ccx").glob("queue*")):
    opts = json.loads((q / "opts.json").read_text()) if (q / "opts.json").exists() else {}
    for d in sorted(q.glob("neck*")):
        if not (d / "DONE").exists():
            continue
        b = json.loads((d / "result.json").read_text())
        a = json.loads((BASE / "queue" / d.name / "result.json").read_text())
        sj = b.get("solve", {})
        tr = sj.get("m_fric", {}).get("translate", {})
        rows.append({"job": d.name, "queue": q.name, "stick_slope": tr.get("friction", {}).get("stick_slope"),
                     "offset": "linear" if "n_nodes_moved" in (tr.get("interference") or {}) else "nodes-only",
                     "mesh_identical": json.loads((d / "mesh_check.json").read_text()).get("identical"),
                     "design": {k: a["spec"]["design"].get(k) for k in ("L", "alpha", "collar_w", "m")}, "h_cut": a.get("h_cut_mm"),
                     "abq": {k: a.get(k) for k in KEYS}, "ccx": {k: b.get(k) for k in KEYS},
                     "wall_min": {"abq": round(a["solve"]["m_fric"]["wall_s"] / 60, 1), "ccx": round(sj["m_fric"]["wall_s"] / 60, 1)},
                     "opts": opts})
print(json.dumps(rows))
