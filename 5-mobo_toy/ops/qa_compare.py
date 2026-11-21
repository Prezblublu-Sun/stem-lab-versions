"""把一个版本的 qa_report.json 与已知例外基线 ops/qa_baseline.json 比：只有**新增**的失败才算失败。

    PYTHONUTF8=1 .venv-mobo/Scripts/python.exe ops/qa_compare.py --db "../../db3406/v0.9"
    ... ops/qa_compare.py --db <版本目录> --accept        # 把这个版本的失败并入基线（要在 CHANGELOG 写明理由后再做）

退出码：新增失败 1；否则 0（已知例外照旧列出，但不算失败）。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "ops" / "qa_baseline.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--accept", action="store_true")
    a = ap.parse_args()
    rep = pathlib.Path(a.db) / "qa_report.json"
    if not rep.exists():
        print(f"没有 {rep}"); return 2
    q = json.loads(rep.read_text(encoding="utf-8"))
    base = json.loads(BASE.read_text(encoding="utf-8")) if BASE.exists() else {"known": {}}
    known = base.get("known", {})
    new_fail = {}
    gone = {}
    for c in q["checks"]:
        cid = str(c["id"])
        if c["status"] == "PASS":
            if cid in known:
                gone[cid] = known[cid]["failures"]
            continue
        kf = set(known.get(cid, {}).get("failures", []))
        extra = sorted(set(c["failures"]) - kf)
        fixed = sorted(kf - set(c["failures"]))
        if fixed:
            gone[cid] = fixed
        if extra:
            new_fail[cid] = {"name": c["name"], "failures": extra}
        print(f"检查 {cid} {c['status']}：{len(c['failures'])} 行失败，其中已知 {len(set(c['failures']) & kf)}，新增 {len(extra)}")
    for cid, items in gone.items():
        print(f"检查 {cid}：{len(items)} 条已知例外不再出现（基线可以收紧）")
    if new_fail:
        print("\n新增失败：")
        for cid, v in new_fail.items():
            print(f"  检查 {cid} {v['name']}")
            for f in v["failures"][:20]:
                print(f"    {f[:160]}")
        if a.accept:
            for cid, v in new_fail.items():
                known.setdefault(cid, {"name": v["name"], "status": "FAIL", "failures": []})
                known[cid]["failures"] = sorted(set(known[cid]["failures"]) | set(v["failures"]))
            base["known"] = known
            base["version"] = pathlib.Path(a.db).name
            BASE.write_text(json.dumps(base, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            print(f"已并入基线（{BASE.name}）。CHANGELOG 要写明为什么接受。")
            return 0
        return 1
    print("没有新增失败。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
