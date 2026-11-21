"""一个批次各行的结局。只读：只读批次的 rows.json 和一版数据库的 scalars.csv，不写任何文件。

    PYTHONUTF8=1 .venv-mobo/Scripts/python.exe ops/outcomes.py experiments/b31_r2 --db "../../db3406/v0.13"
    ... ops/outcomes.py experiments/b31_r2 --db "../../db3406/v0.13" --json      # 给选点脚本读：每行的作业号、结局、该告诉策略什么

类和名字见 v2/result_codes.py。数据库有 result_class / result_code 两列时（导出器 0.2.6 起）直接读；没有时从
fail_level、fail_stage、fail_reason 现认，结果一样。

每一行还带 tell：该告诉选点策略什么。result = 结果；infeasible = 这个设计放不进去；failed = 算了但没算出来；
None = 不告诉（环境、出错、跳过、待查都不是设计的性质）。数据库里没有的行也是 None。
"""
from __future__ import annotations

import collections
import csv
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "v2"))
import result_codes as RC  # noqa: E402


def batch_rows(rows_json: pathlib.Path) -> list[tuple[str, str]]:
    """(label, job_id) of every row a batch's rows.json lists, at any depth, in file order."""
    out: list[tuple[str, str]] = []

    def walk(x) -> None:
        if isinstance(x, dict):
            if isinstance(x.get("job_id"), str):
                out.append((str(x.get("label", "")), x["job_id"]))
            else:
                for v in x.values():
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(json.loads(pathlib.Path(rows_json).read_text(encoding="utf-8")))
    return out


def row_result(x: dict) -> RC.Result | None:
    """The outcome of one scalars.csv row: the exported code when the row has one, else from the failure text.
    None for a row that is neither DONE nor FAILED (not finished when it was exported)."""
    if x.get("result_code"):
        return RC.of_code(x["result_code"])
    return RC.for_job(x.get("status"), x.get("fail_level"), x.get("fail_stage"), x.get("fail_reason"))


def outcomes(batch_dir: str | pathlib.Path, db_dir: str | pathlib.Path) -> dict | None:
    """Outcome of each row of the batch in this database version. None when the batch has no rows.json (batches before b25).

    A row the database does not hold (or holds unfinished) is listed under not_in_db, not classified.
    """
    rj = pathlib.Path(batch_dir) / "rows.json"
    if not rj.exists():
        return None
    rows = batch_rows(rj)
    want = {j for _, j in rows}
    got: dict[str, RC.Result] = {}
    with open(pathlib.Path(db_dir) / "scalars.csv", encoding="utf-8", newline="") as f:
        for x in csv.DictReader(f):
            if x["job_id"] in want:
                r = row_result(x)
                if r is not None:                       # an unfinished row is treated like a row the database does not hold
                    got[x["job_id"]] = r
    by_class: collections.Counter = collections.Counter()
    not_ok, not_in_db, tell = [], [], {}
    for label, jid in rows:
        if jid not in got:
            not_in_db.append({"label": label, "job_id": jid})
            tell[jid] = None
            continue
        r = got[jid]
        by_class[r.klass] += 1
        tell[jid] = RC.TELL_STRATEGY.get(r.klass)
        if r.klass != "OK":
            not_ok.append({"label": label, "job_id": jid, "klass": r.klass, "code": r.code})
    return {"n_rows": len(rows), "by_class": {k: by_class[k] for k in RC.KLASSES if by_class[k]}, "not_ok": not_ok, "not_in_db": not_in_db,
            "tell": tell}


def answer(batch_dir: str | pathlib.Path, db_dir: str | pathlib.Path) -> dict | None:
    """The "tell" half of ask and tell, for a selection script: one entry per row of the batch, in the order of rows.json.
    tell = "result": read the row's numbers from this database version by job_id; "infeasible": the design does not fit the bone;
    "failed": the mesh or the solve failed numerically (may be physical); None: nothing about the design is known (environment, error,
    skipped, cannot be told, or not in this version) -- do not treat it as a failure of the design."""
    o = outcomes(batch_dir, db_dir)
    if o is None:
        return None
    bad = {x["job_id"]: x for x in o["not_ok"]}
    missing = {x["job_id"] for x in o["not_in_db"]}
    rows = []
    for label, jid in batch_rows(pathlib.Path(batch_dir) / "rows.json"):
        k, c = ("OK", "ok") if jid not in bad and jid not in missing else (bad[jid]["klass"], bad[jid]["code"]) if jid in bad else (None, None)
        rows.append({"label": label, "job_id": jid, "klass": k, "code": c, "tell": o["tell"][jid]})
    return {"batch": pathlib.Path(batch_dir).resolve().name, "db": pathlib.Path(db_dir).resolve().name, "rows": rows}


def table(o: dict | None) -> str:
    """The markdown table judge.py prints under the gates."""
    if o is None:
        return "各行的结局：这个批次没有 rows.json，不报。"
    lines = ["| 结局 | 行数 | 哪些行 |", "|---|---|---|"]
    for k, n in o["by_class"].items():
        who = "；".join(f"{x['label'] or x['job_id']}（{x['code']}）" for x in o["not_ok"] if x["klass"] == k)
        lines.append(f"| {RC.KLASS_ZH[k]} | {n} | {who} |")
    if o["not_in_db"]:
        lines.append(f"| 不在这版数据库里 | {len(o['not_in_db'])} | {'；'.join(x['label'] or x['job_id'] for x in o['not_in_db'])} |")
    n_unknown = o["by_class"].get("UNKNOWN", 0)
    tail = f"\n有 {n_unknown} 行待查：从记录里分不出是设计、数值还是环境的问题，用这个判定前要人看过。" if n_unknown else ""
    return f"各行的结局（rows.json 共 {o['n_rows']} 行）：\n" + "\n".join(lines) + tail


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="一个批次各行的结局。只读，不写文件。")
    ap.add_argument("batch_dir")
    ap.add_argument("--db", required=True)
    ap.add_argument("--json", action="store_true", help="每行一项的 JSON（answer），给选点脚本读")
    a = ap.parse_args()
    if a.json:
        print(json.dumps(answer(a.batch_dir, a.db), ensure_ascii=False, indent=1))
        return 0
    print(table(outcomes(a.batch_dir, a.db)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
