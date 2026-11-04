"""各优化阶段每个设计的股骨颈截骨量（只读）。resected_mm3 = 截骨面与头颈交界（距头心 25 mm）之间的骨体积（皮质 + 松质），
即"比最高截法多切掉的颈部骨"；另算一个常数：25 mm 截骨面以上的全部骨（股骨头 + 头颈交界以上的颈），绝对截骨量 = 常数 + resected。"""
import json
import pathlib
import sys

CODE = pathlib.Path.home() / "mobo_toy_v2" / "code"
sys.path.insert(0, str(CODE)); sys.path.insert(0, str(CODE / "v2"))
import femur_real as FR  # noqa: E402
import jobs as J  # noqa: E402

fm = FR.build()
const = fm.with_cut(25.0).resected_volume(ref_cut_mm=-60.0)        # 25 mm 截骨面以上的全部骨（头 + 交界以上的颈）
out = {"above_25mm_mm3": const, "check": {h: fm.with_cut(h).resected_volume() for h in (25.0, 26.0, 28.0, 30.0, 32.0)}, "phases": {}}
for k in (1, 2, 3, 5, 6):
    st = json.loads((J.RESULTS / f"neckopt_p{k}.json").read_text())
    rows = []
    for r in st["records"]:
        res = J.result(r["job_id"]) or {}
        bl = res.get("bone_loss") or {}
        rows.append({"job": r["job_id"], "round": r.get("round"), "h_cut": bl.get("h_cut_mm", r.get("h_cut")), "resected": bl.get("resected_mm3"),
                     "reamed": bl.get("reamed_mm3"), "f1_body": res.get("f1_p95_um"), "f1_all": res.get("f1_all_p95_um", res.get("f1_p95_um")),
                     "old_ok": r.get("ok"), "old_c": (r.get("c") or [None])[0], "design": r.get("design")})
    out["phases"][str(k)] = rows
print(json.dumps({"above_25mm_cm3": const / 1000, "check_cm3": {h: v / 1000 for h, v in out["check"].items()}}))
(pathlib.Path.home() / "mobo_toy_v2" / "adhoc" / "out" / "resect_dump.json").write_text(json.dumps(out, default=float))
