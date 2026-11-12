"""行规格：experiments/b34_r2sts/rows_in.json（行文件批次，v2/stage_db.py 的 build_file 读它）。这里只把干跑输出的行列表存成 rows.json。

    PYTHONUTF8=1 .venv-mobo/Scripts/python.exe experiments/b34_r2sts/batch.py --from-dry-run <干跑日志>
"""
from __future__ import annotations

import json
import pathlib
import sys

STAGE_DB_BATCH = "b34"            # 行文件批次：不在 v2/stage_db.py 的 BATCHES 里
HERE = pathlib.Path(__file__).resolve().parent


def main() -> int:
    if len(sys.argv) < 3 or sys.argv[1] != "--from-dry-run":
        print(__doc__)
        return 2
    t = pathlib.Path(sys.argv[2]).read_text(encoding="utf-8", errors="replace")
    d, _ = json.JSONDecoder().raw_decode(t[t.index("DRY-RUN-JSON") + len("DRY-RUN-JSON"):].lstrip())     # text after the JSON (a log tail) is ignored
    if d.get("problems"):
        print(f"the dry run lists problems, rows.json not written: {d['problems'][:3]}")
        return 1
    rows = [{"label": r.get("key"), "job_id": r.get("id") or r.get("expected_id")} for r in d.get("jobs", [])]
    (HERE / "rows.json").write_text(json.dumps({"stage_db_batch": STAGE_DB_BATCH, "rows": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(rows)} rows -> rows.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
