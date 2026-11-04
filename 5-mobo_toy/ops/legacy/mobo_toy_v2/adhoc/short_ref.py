"""改动前的短柄（无领）同设置作业：哪一个是当前代码下的、结果是多少（只读）。"""
import json
import pathlib
import sys

CODE = pathlib.Path.home() / "mobo_toy_v2" / "code"
sys.path.insert(0, str(CODE)); sys.path.insert(0, str(CODE / "v2"))
import jobs as J  # noqa: E402
import stage_m1 as M1S  # noqa: E402

short = M1S.core_of(M1S.NAMED["short"])["design"]
for p in sorted(J.QROOT.glob("m1_short_h2_tol0.00025_delta0.025_*")) + sorted(J.QROOT.glob("m1_base_h2_tol0.00025_delta0.025_*")):
    s = json.loads((p / "spec.json").read_text())
    st = J.state(p)
    r = J.result(p.name) if st == "DONE" else {}
    print(p.name, st, s.get("code_hash") or s.get("code"), int((p / "spec.json").stat().st_mtime),
          r.get("f1_p95_um"), r.get("f1_first_p95_um"), "same_design" if s["design"] == short else "", sorted(k for k in s if k != "design"))
