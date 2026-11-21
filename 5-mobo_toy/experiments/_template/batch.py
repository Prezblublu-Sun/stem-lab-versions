"""行规格。现阶段批次仍由 v2/stage_db.py 的 build_bNN 产生，这里只记引用，并把干跑输出的行列表存成 rows.json。

    PYTHONUTF8=1 .venv-mobo/Scripts/python.exe experiments/<批次>/batch.py --from-dry-run logs/db_dry_bNN.txt
"""
from __future__ import annotations

import json
import pathlib
import sys

STAGE_DB_BATCH = "bNN"            # v2/stage_db.py 里的批次号
HERE = pathlib.Path(__file__).resolve().parent


def main() -> int:
    rows = []
    if len(sys.argv) >= 3 and sys.argv[1] == "--from-dry-run":
        for ln in pathlib.Path(sys.argv[2]).read_text(encoding="utf-8", errors="replace").splitlines():
            parts = ln.split()
            if len(parts) >= 3 and parts[0] not in ("batch", "==") and parts[-1].startswith("db_"):
                rows.append({"label": parts[0], "job_id": parts[-1]})
    (HERE / "rows.json").write_text(json.dumps({"stage_db_batch": STAGE_DB_BATCH, "rows": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(rows)} rows -> rows.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
