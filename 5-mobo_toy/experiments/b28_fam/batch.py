"""行规格：v2/stage_db.py 的 build_b28 产生，这里只记引用，并把干跑输出的行列表存成 rows.json。

    PYTHONUTF8=1 .venv-mobo/Scripts/python.exe experiments/b28_fam/batch.py --from-dry-run <干跑日志>
"""
from __future__ import annotations

import json
import pathlib
import sys

STAGE_DB_BATCH = "b28"            # v2/stage_db.py 里的批次号
HERE = pathlib.Path(__file__).resolve().parent


def main() -> int:
    rows = []
    if len(sys.argv) >= 3 and sys.argv[1] == "--from-dry-run":
        t = pathlib.Path(sys.argv[2]).read_text(encoding="utf-8", errors="replace")
        d = json.loads(t[t.index("DRY-RUN-JSON") + len("DRY-RUN-JSON"):])
        rows = [{"label": r.get("key"), "job_id": r.get("id") or r.get("expected_id")} for r in d.get("jobs", [])]
    (HERE / "rows.json").write_text(json.dumps({"stage_db_batch": STAGE_DB_BATCH, "rows": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(rows)} rows -> rows.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
