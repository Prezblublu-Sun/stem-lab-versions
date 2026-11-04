"""行规格：v2/stage_db.py 的 build_b26、build_b27 产生，这里只记引用，并把干跑输出的行列表存成 rows.json。

    PYTHONUTF8=1 .venv-mobo/Scripts/python.exe experiments/b26_sts1714/batch.py --from-dry-run <b26 干跑日志> <b27 干跑日志>
"""
from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent


def main() -> int:
    out = {}
    for b, p in zip(("b26", "b27"), sys.argv[2:]):
        t = pathlib.Path(p).read_text(encoding="utf-8", errors="replace")
        d = json.loads(t[t.index("DRY-RUN-JSON") + len("DRY-RUN-JSON"):])
        out[b] = [{"label": r.get("key"), "job_id": r.get("id") or r.get("expected_id")} for r in d.get("jobs", [])]
    (HERE / "rows.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print({k: len(v) for k, v in out.items()}, "rows -> rows.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
