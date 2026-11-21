"""一条命令复算结论总表的全部数字，并与研究日志里现有的 metrics.json 逐项比对。

    python -X utf8 conclusions/recompute.py [--db "H:/projects/Femoral implant generation/db3406/v0.9"] [--figures]

做法：把研究日志 `结果整理_2026-11-03/scripts/`（汇报会话的脚本，只读）复制到 conclusions/work/scripts/，把 FY 路径改成绝对路径，
复制 data/now_raw.txt（Linux 快照；导出已覆盖时它只是冗余），然后在 conclusions/work/ 里跑 pack_data → make_table（→ make_figures）。
产物：conclusions/work/data/metrics.json、conclusions/work/结论总表.md、conclusions/metrics_diff.md（与研究日志 metrics.json 的差异）。
研究日志里的原件不动。用系统 python -X utf8（numpy、scipy、matplotlib 在系统环境里）。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
SRC = pathlib.Path(r"H:\projects\application\research-log\neck_implant_2026-10-02\结果整理_2026-11-03")
FY_ABS = pathlib.Path(r"H:\projects\application\research-log\neck_implant_2026-10-02\db3406_checks\FEA_settings_2026-10-28\fy_analysis.json")
WORK = HERE / "work"


def flatten(o, prefix="") -> dict[str, object]:
    out = {}
    if isinstance(o, dict):
        for k, v in o.items():
            out.update(flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            out.update(flatten(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = o
    return out


def same(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))
    return a == b


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=r"H:/projects/Femoral implant generation/db3406/v0.9")
    ap.add_argument("--figures", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    if not SRC.exists():
        print(f"没有 {SRC}"); return 2
    (WORK / "scripts").mkdir(parents=True, exist_ok=True)
    (WORK / "data").mkdir(exist_ok=True)
    for p in (SRC / "scripts").glob("*.py"):
        txt = p.read_text(encoding="utf-8")
        if p.name == "pack_data.py":
            old_line = 'FY = HERE.parent / "db3406_checks/FEA_settings_2026-10-28/fy_analysis.json"'
            if old_line not in txt:
                print("pack_data.py 里找不到 FY 那一行，脚本可能变了；停止"); return 2
            txt = txt.replace(old_line, 'FY = pathlib.Path(r"%s")' % str(FY_ABS))
        (WORK / "scripts" / p.name).write_text(txt, encoding="utf-8")
    shutil.copy2(SRC / "data" / "now_raw.txt", WORK / "data" / "now_raw.txt")
    env = {"PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    import os
    env = {**os.environ, **env}
    r = subprocess.run([sys.executable, "-X", "utf8", str(WORK / "scripts" / "pack_data.py"), "--db", a.db], cwd=str(WORK), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(r.stdout.strip()[-600:]);
    if r.returncode != 0:
        print(r.stderr[-1500:]); return 1
    r = subprocess.run([sys.executable, "-X", "utf8", str(WORK / "scripts" / "make_table.py")], cwd=str(WORK), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(r.stderr[-1500:]); return 1
    if a.figures:
        r = subprocess.run([sys.executable, "-X", "utf8", str(WORK / "scripts" / "make_figures.py")], cwd=str(WORK), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            print(r.stderr[-1500:]); return 1
    new = json.loads((WORK / "data" / "metrics.json").read_text(encoding="utf-8"))
    old = json.loads((SRC / "data" / "metrics.json").read_text(encoding="utf-8"))
    fn, fo = flatten(new), flatten(old)
    changed = [(k, fo.get(k), fn.get(k)) for k in sorted(set(fn) | set(fo)) if not same(fo.get(k), fn.get(k))]
    lines = [f"# 数字复算差异（{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}）", "",
             f"研究日志版：export `{old.get('export')}`，{old.get('n_rows')} 行；本次：export `{new.get('export')}`，{new.get('n_rows')} 行。",
             f"扁平化后共 {len(fn)} 个数字 / 字段，不同的 {len(changed)} 个。相同的不列。", "", "| 字段 | 研究日志版 | 本次 |", "|---|---|---|"]
    for k, vo, vn in changed[:400]:
        lines.append(f"| `{k}` | {vo} | {vn} |")
    if len(changed) > 400:
        lines.append(f"| … | 还有 {len(changed) - 400} 个 | |")
    (HERE / "metrics_diff.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    tbl = WORK / "结论总表.md"
    print(f"结论总表：{tbl}（{tbl.stat().st_size} 字节）；差异 {len(changed)} / {len(fn)} → conclusions/metrics_diff.md；用时 {time.time() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
