"""队列维护（Linux）：按失败级别/原因把作业放回队列；重新登记完整股骨参照。每次操作打印清单，不静默。

    python v2/maint.py requeue --stage prep --level L3 [--contains near-zero]   → 删 FAILED.json，回到 NEW（重新建模）
    python v2/maint.py requeue --stage solve --level L4 --contains timeout       → 清掉求解结果，回到 READY（重新求解）
    python v2/maint.py intact 2.0 1.4 1.0                                       → 用当前代码哈希登记完整股骨参照
"""
from __future__ import annotations

import json
import pathlib
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import jobs as J  # noqa: E402
import stage_v2a as S  # noqa: E402


def requeue(stage: str, level: str, contains: str = "") -> list[str]:
    done = []
    for d in sorted(J.QROOT.glob("*")):
        f = d / "FAILED.json"
        if not f.exists():
            continue
        r = json.loads(f.read_text())
        if r["stage"] != stage or r["level"] != level or contains not in r["reason"]:
            continue
        if stage == "prep":
            f.unlink()
        elif stage == "solve":
            if not any(d.glob("*.inp")):
                print(f"skip {d.name}: no .inp left to re-solve")
                continue
            for p in [f, d / "SOLVED", d / "solve.json", d / "CLAIMED"]:
                if p.exists():
                    p.unlink()
            for c in d.glob("*_csv"):
                shutil.rmtree(c)
            (d / "READY").write_text("requeued")
        else:
            raise ValueError(stage)
        done.append(d.name)
        print(f"requeued {d.name} ({level} {stage}: {r['reason'][:80]})")
    return done


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["requeue", "intact"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--stage", default="prep")
    ap.add_argument("--level", default="L3")
    ap.add_argument("--contains", default="")
    a = ap.parse_args()
    if a.cmd == "requeue":
        print(len(requeue(a.stage, a.level, a.contains)), "requeued")
    else:
        for h in a.args:
            print("intact", h, J.submit(S.intact_spec(float(h))))
