"""判定：跑某个批次目录的 gates.py，写 result.json，打印表。agent 不改判据，只跑这个。

    PYTHONUTF8=1 .venv-mobo/Scripts/python.exe ops/judge.py experiments/b23_ow4 --db "../../db3406/v0.9"

检查：批次目录要有 approval.md（没有 = 未批准，拒绝判定，除非 --replay）；gates.py 的 sha256 写进 result.json。
退出码：有 FAIL 1；全 PASS 0；有 NA 但无 FAIL 也是 0（NA 要人工补判，表里标明）。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import pathlib
import sys
import time


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("batch_dir")
    ap.add_argument("--db", required=True)
    ap.add_argument("--replay", action="store_true", help="事后回放，不要求 approval.md")
    a = ap.parse_args()
    bd = pathlib.Path(a.batch_dir).resolve()
    gp = bd / "gates.py"
    if not gp.exists():
        print(f"没有 {gp}"); return 2
    if not (bd / "approval.md").exists() and not a.replay:
        print("没有 approval.md：未批准的批次不判定"); return 2
    db = pathlib.Path(a.db).resolve()
    man = db / "manifest.json"
    if not man.exists():
        print(f"{db} 不是导出的版本目录（没有 manifest.json）"); return 2
    spec = importlib.util.spec_from_file_location("gates", gp)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    res = mod.judge(str(db))
    sha = hashlib.sha256(gp.read_bytes()).hexdigest()
    out = {"batch": bd.name, "db": db.name, "db_rows": json.loads(man.read_text(encoding="utf-8")).get("n_rows"),
           "gates_sha256": sha, "judged_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "replay": a.replay,
           "gates": {k: {"desc": mod.GATES.get(k, ""), **v} for k, v in res.items()}}
    (bd / "result.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"| 判据 | 结果 | 值 | 阈值 | 说明 |\n|---|---|---|---|---|")
    n_fail = 0
    for k, v in res.items():
        n_fail += v["status"] == "FAIL"
        print(f"| {k} | {v['status']} | {v['value'] if v['value'] is not None else '—'} | {v['threshold']} | {str(v['note'])[:140]} |")
    print(f"\n数据 {db.name}（{out['db_rows']} 行），gates.py sha256 {sha[:12]}，result.json 已写。")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
