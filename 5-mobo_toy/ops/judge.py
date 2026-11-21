"""判定：跑某个批次目录的 gates.py，写 result.json，打印表。agent 不改判据，只跑这个。

    PYTHONUTF8=1 .venv-mobo/Scripts/python.exe ops/judge.py experiments/b23_ow4 --db "../../db3406/v0.9"

检查：批次目录要有 approval.md（没有 = 未批准，拒绝判定，除非 --replay）；gates.py 的 sha256 写进 result.json。
approval.md 里记的 sha256 要和现在的 gates.py 对得上（ops/feed_gate.py 的 approval_sha，喂料门用的同一个函数）：对不上 = 判据在批准之后变了，
拒绝判定，--replay 时只提醒；approval.md 里一个 sha256 都没有（b23 这样的旧批次）只提醒。
判据表下面再报本批各行的结局（ops/outcomes.py，类和名字见 v2/result_codes.py：完成、设计不可行、没算出来、环境、出错、跳过、待查），也写进 result.json 的 outcomes。
这只是报告：不改任何判据的结果，不改退出码。批次没有 rows.json 时不报。
来历（ops/provenance.py）在跑判据之前取，写进 result.json 的 provenance：本仓库的提交号和未提交的改动，
gates.py、approval.md、rows.json、rows_in.json（行文件批次）、feed_manifest.json（ops/fetch_feed_manifests.py 取回的喂料清单）、
数据版本的 manifest.json 和 scalars.csv 的 sha256。没有的文件记 null。
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

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import feed_gate  # noqa: E402
import outcomes  # noqa: E402
import provenance  # noqa: E402


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
    sha_notes = feed_gate.approval_sha(bd)
    if any(k == "mismatch" for k, _ in sha_notes) and not a.replay:
        print("；".join(m for _, m in sha_notes) + "：判据和批准时的不是同一份，不判定"); return 2
    db = pathlib.Path(a.db).resolve()
    man = db / "manifest.json"
    if not man.exists():
        print(f"{db} 不是导出的版本目录（没有 manifest.json）"); return 2
    prov = provenance.record("judge", {"gates": gp, "approval": bd / "approval.md", "rows": bd / "rows.json", "rows_in": bd / "rows_in.json",
                                       "feed_manifest": bd / "feed_manifest.json", "db_manifest": man, "db_scalars": db / "scalars.csv"})
    spec = importlib.util.spec_from_file_location("gates", gp)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    res = mod.judge(str(db))
    sha = hashlib.sha256(gp.read_bytes()).hexdigest()
    oc = outcomes.outcomes(bd, db)
    out = {"batch": bd.name, "db": db.name, "db_rows": json.loads(man.read_text(encoding="utf-8")).get("n_rows"),
           "gates_sha256": sha, "judged_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "replay": a.replay,
           "gates": {k: {"desc": mod.GATES.get(k, ""), **v} for k, v in res.items()}, "outcomes": oc, "provenance": prov,
           "approval_sha": "ok" if not sha_notes else sha_notes[0][0]}
    (bd / "result.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"| 判据 | 结果 | 值 | 阈值 | 说明 |\n|---|---|---|---|---|")
    n_fail = 0
    for k, v in res.items():
        n_fail += v["status"] == "FAIL"
        print(f"| {k} | {v['status']} | {v['value'] if v['value'] is not None else '—'} | {v['threshold']} | {str(v['note'])[:140]} |")
    for _, m in sha_notes:
        print(f"提醒：{m}")
    print("\n" + outcomes.table(oc))
    print(f"\n数据 {db.name}（{out['db_rows']} 行），gates.py sha256 {sha[:12]}，{provenance.one_line(prov)}，result.json 已写。")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
