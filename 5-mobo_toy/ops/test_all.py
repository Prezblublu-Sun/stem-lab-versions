"""统一测试入口：把 v2/tests/test_*.py（各自独立、按退出码判）、tools/tests/test_db_tools.py、tests/（pytest）串起来跑，汇总成表。

    PYTHONUTF8=1 .venv-mobo/Scripts/python.exe ops/test_all.py                      # 全部
    ... ops/test_all.py --only stage_db_b2 tpl_record                               # 名字含这些片段的
    ... ops/test_all.py --changed-files "v2/stage_db.py docs/goal.md"               # pre-push 用：按改动挑测试
    ... ops/test_all.py --list

挑选规则（--changed-files）：
  改了 v2/jobs.py、v2/stage_db.py、v2/tpl_record.py、v2/collar_rule.py、v2/stage_al.py、v2/al_local.py、v2/stage_neckopt.py、
  v2/stage_deck.py、v2/stage_v2a.py、v2/stability.py、v2/femur_3406.py、钩子模块、tools/ → 全部；
  只改 docs/ ops/ experiments/ conclusions/ *.md → 只跑 ops/check_freeze.py；
  其它 → 全部。
每个测试文件一个子进程、低优先级、串行（Abaqus 可能在跑）；单个文件超时 900 s 记 TIMEOUT。退出码：有失败 1，否则 0。
"""
from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
PY = ROOT / ".venv-mobo" / "Scripts" / "python.exe"
PY = str(PY) if PY.exists() else sys.executable
ENV = {**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}
ALL_TRIGGERS = ("v2/jobs.py", "v2/stage_db.py", "v2/tpl_record.py", "v2/collar_rule.py", "v2/stage_al.py", "v2/al_local.py",
                "v2/stage_neckopt.py", "v2/stage_deck.py", "v2/stage_v2a.py", "v2/stability.py", "v2/femur_3406.py",
                "v2/torsion_load.py", "v2/pose_fixed.py", "v2/bond_collar.py", "v2/resorption.py", "v2/shielding.py", "inp_writer.py")
DOC_ONLY_PREFIXES = ("docs/", "ops/", "experiments/", "conclusions/", "AGENTS.md", "CLAUDE.md", "README.md", "STATE.md", ".claude/")


def discover() -> list[tuple[str, list[str]]]:
    items: list[tuple[str, list[str]]] = []
    for p in sorted((ROOT / "v2" / "tests").glob("test_*.py")):
        items.append((f"v2/tests/{p.name}", [PY, str(p)]))
    t = ROOT / "tools" / "tests" / "test_db_tools.py"
    if t.exists():
        items.append(("tools/tests/test_db_tools.py", [PY, str(t)]))
    o = ROOT / "ops" / "tests" / "test_ops.py"
    if o.exists():
        items.append(("ops/tests/test_ops.py", [PY, str(o)]))
    if (ROOT / "tests").exists():
        items.append(("tests/ (pytest)", [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(ROOT / "tests")]))
    return items


def low_priority_kwargs() -> dict:
    if os.name == "nt":
        return {"creationflags": 0x00004000}  # BELOW_NORMAL_PRIORITY_CLASS
    return {}


def run_one(name: str, cmd: list[str], timeout: float) -> tuple[str, float, str]:
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=str(ROOT), env=ENV, capture_output=True, timeout=timeout, **low_priority_kwargs())
        out = (r.stdout + r.stderr).decode("utf-8", "replace")
        tail = [ln for ln in out.strip().splitlines() if ln.strip()][-1:] or [""]
        return ("PASS" if r.returncode == 0 else f"FAIL rc {r.returncode}"), time.time() - t0, tail[0][:120]
    except subprocess.TimeoutExpired:
        return "TIMEOUT", time.time() - t0, ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--changed-files", default=None)
    ap.add_argument("--timeout", type=float, default=900)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--coverage", action="store_true", help="run every test under coverage (in-process code only) and print the report")
    ap.add_argument("--cov-min-ops", type=float, default=0.0, help="fail when the line coverage of ops/*.py is below this percent")
    a = ap.parse_args()
    items = discover()
    if a.list:
        for n, _ in items:
            print(n)
        return 0
    if a.changed_files is not None:
        files = [f.strip().replace("\\", "/") for f in a.changed_files.split() if f.strip()]
        if files and all(f.startswith(DOC_ONLY_PREFIXES) or f.endswith(".md") for f in files):
            print("只改了文档和 ops，只核对冻结" + ("，再跑 ops 的测试" if any(f.startswith("ops/") for f in files) else ""))
            r = subprocess.run([PY, str(ROOT / "ops" / "check_freeze.py"), "--quiet"], cwd=str(ROOT), env=ENV)
            if r.returncode != 0:
                return r.returncode
            if any(f.startswith("ops/") and f.endswith((".py", ".sh")) for f in files):
                items = [(n, c) for n, c in items if n.startswith("ops/")]
            else:
                return 0
        # 其它情况一律全部跑（改动触发全量是保守做法；按文件挑测试留到以后）
    if a.only:
        items = [(n, c) for n, c in items if any(k in n for k in a.only)]
    if a.coverage:
        for f in ROOT.glob(".coverage*"):
            f.unlink()
        src = ",".join(str(ROOT / d) for d in ("v2", "tools", "ops"))
        items = [(n, [PY, "-m", "coverage", "run", "-p", f"--source={src}", *c[1:]]) for n, c in items]
    rows = []
    t0 = time.time()
    n_fail = 0
    for n, cmd in items:
        st, dt, tail = run_one(n, cmd, a.timeout)
        if not st.startswith("PASS"):
            n_fail += 1
        rows.append((n, st, dt, tail))
        print(f"{st:10s} {dt:6.0f} s  {n}  {tail}", flush=True)
    print(f"\n{len(items) - n_fail}/{len(items)} 个测试文件通过，用时 {time.time() - t0:.0f} s")
    if a.coverage:
        subprocess.run([PY, "-m", "coverage", "combine", "-q"], cwd=str(ROOT), env=ENV)
        r = subprocess.run([PY, "-m", "coverage", "report", "--format=total"], cwd=str(ROOT), env=ENV, capture_output=True)
        total = r.stdout.decode("utf-8", "replace").strip()
        r = subprocess.run([PY, "-m", "coverage", "report", "--include=ops/*.py", "--format=total"], cwd=str(ROOT), env=ENV, capture_output=True)
        ops_total = r.stdout.decode("utf-8", "replace").strip()
        subprocess.run([PY, "-m", "coverage", "report", "--skip-empty", "--sort=cover"], cwd=str(ROOT), env=ENV)
        print(f"\n覆盖率：全部 {total} %，ops/*.py {ops_total} %（只计进程内执行的代码，子进程里跑的不计）")
        try:
            if a.cov_min_ops and float(ops_total) < a.cov_min_ops:
                print(f"ops 覆盖率 {ops_total} % < 下限 {a.cov_min_ops} %")
                return 1
        except ValueError:
            pass
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
