"""阶段 0 网格、阶段 1 初始点、参考组图作业的现状与已有数字（只读）。"""
import json
import pathlib
import sys

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "code")); sys.path.insert(0, str(HOME / "code" / "v2"))
import jobs as J  # noqa: E402

ids = json.loads((J.RESULTS / "collar_ids.json").read_text())["jobs"]
rows = []
for k, j in ids.items():
    st = J.state(J.QROOT / j)
    r = J.result(j) if st == "DONE" else {}
    spec = json.loads((J.QROOT / j / "spec.json").read_text())
    rows.append({"name": k, "job": j, "state": st, "L": spec["design"]["L"], "w": spec["design"].get("collar_w", 0.0),
                 "f1": r.get("f1_p95_um"), "f1_all": r.get("f1_all_p95_um"), "share": r.get("collar_force_share_load2"),
                 "vm_p99": r.get("vm_p99"), "A0": (r.get("templating") or {}).get("A0"),
                 "loss": (r.get("bone_loss") or {}).get("total_mm3")})
for r in sorted(rows, key=lambda x: x["name"]):
    print(json.dumps(r, default=float))
cnt = {}
for r in rows:
    cnt[r["state"]] = cnt.get(r["state"], 0) + 1
print("stage0", cnt)
n1 = sorted(J.QROOT.glob("neck1_*"))
c1 = {}
for d in n1:
    s = J.state(d); c1[s] = c1.get(s, 0) + 1
print("neck1", len(n1), c1)
p = J.RESULTS / "neckopt_p1.json"
if p.exists():
    st = json.loads(p.read_text())
    print("neckopt_p1", {k: v for k, v in st.items() if k not in ("records", "warm_start_ids")})
    print("records", len(st.get("records", [])))
ref = json.loads((HOME / "adhoc" / "reffig2" / "ref2_ids.json").read_text())
c2 = {}
for k, j in ref.items():
    s = J.state(J.QROOT / j); c2[s] = c2.get(s, 0) + 1
print("ref2", c2)
