"""Doc drift check for the facts in ops/facts.json: any file that restates a fact with a different value fails the check.
Fast (a few hundred files, regex only); runs in pre-commit.

    PYTHONUTF8=1 .venv-mobo/Scripts/python.exe ops/check_facts.py [--quiet] [--paths DIR ...] [--list]

Checked:
  code_hash      a 10-hex value within 40 chars after "code_hash" that is not the fact
  hashed files   docs/freeze/M1-3406-v1.json lists exactly facts.hashed_files
  neck axis      the known-wrong baked vector (first 8 digits of its components) anywhere; the right vector may be restated freely
  db_latest      "最新版本 | `vX.Y`" in STATE.md must be facts.db_latest (STATE.md is generated, so a mismatch means facts.json is stale)
Exempt: experiments/*/gates.py that have an approval.md (frozen by rule; listed as 'frozen'), ops/facts.json itself, this file, .git, docs/freeze.
--list prints every place a fact is restated, for the one-place audit.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_PATHS = [ROOT / "AGENTS.md", ROOT / "CLAUDE.md", ROOT / "README.md", ROOT / "STATE.md", ROOT / "docs", ROOT / "ops", ROOT / "experiments", ROOT / "conclusions",
                 ROOT / "v2", ROOT / "tools", pathlib.Path(r"H:/projects/application/research-log/neck_implant_2026-10-02/代理_2026-11-04"),
                 pathlib.Path(r"H:/projects/application/research-log/neck_implant_2026-10-02/opt_F微动去骨_2026-11-04"),
                 pathlib.Path(r"H:/projects/application/research-log/neck_implant_2026-10-02/结果整理_2026-11-03/scripts")]
EXT = {".md", ".py", ".json", ".txt", ".sh", ".yaml"}
# tests carry fake hashes and the known-wrong axis on purpose; results / runs / out / reports hold historical hashes of earlier code versions
SKIP_PARTS = {".git", "__pycache__", "_packet", "work", "legacy", "freeze", "node_modules", ".venv-mobo", ".venv-gpu", "tests", "results", "runs", "out", "reports", "audit3"}
SKIP_NAMES = {"build_audit3_doc.py"}                      # documents the audit-3 code versions by their own hashes


def load_facts() -> dict:
    return json.loads((ROOT / "ops" / "facts.json").read_text(encoding="utf-8"))


def files(paths: list[pathlib.Path]):
    for p in paths:
        if p.is_file():
            yield p
        elif p.is_dir():
            for f in p.rglob("*"):
                if f.is_file() and f.suffix.lower() in EXT and f.name not in SKIP_NAMES and not (set(f.parts) & SKIP_PARTS) and f.stat().st_size < 3_000_000:
                    yield f


def frozen_gates() -> set[pathlib.Path]:
    out = set()
    for d in (ROOT / "experiments").glob("*"):
        if d.is_dir() and (d / "approval.md").exists() and (d / "gates.py").exists():
            out.add((d / "gates.py").resolve())
    return out


def check(paths: list[pathlib.Path], facts: dict, list_only: bool = False) -> tuple[list[str], list[str], list[str]]:
    """Returns (conflicts, frozen_notes, restatements)."""
    conflicts, frozen, restate = [], [], []
    ch = facts["code_hash"]
    wrong = facts["neck_axis_u_baked_wrong"]
    wrong_pat = re.compile(r"|".join(re.escape(f"{abs(v):.8f}"[:10]) for v in wrong))
    right_pat = re.compile(re.escape(f"{facts['neck_axis_u'][0]:.5f}"))
    ch_pat = re.compile(r"code_hash[^\n]{0,40}?\b([0-9a-f]{10})\b")
    fz = frozen_gates()
    me = pathlib.Path(__file__).resolve()
    for f in files(paths):
        if f.resolve() == me or f.name == "facts.json":
            continue
        try:
            t = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(f)
        for m in ch_pat.finditer(t):
            v = m.group(1)
            if v == ch:
                restate.append(f"{rel}: code_hash")
            elif v in ("3d631ff204", "ebefa65488"):
                restate.append(f"{rel}: code_hash variant {v} (remote.py 12-digit / all-LF value, explained in runbook)")
            else:
                conflicts.append(f"{rel}: code_hash {v} != {ch}")
        if wrong_pat.search(t):
            if f.resolve() in fz:
                frozen.append(f"{rel}: wrong baked neck axis (frozen gates.py, judged with it; see facts.json note)")
            elif "wrong" in t[max(0, wrong_pat.search(t).start() - 300):wrong_pat.search(t).start() + 300].lower() or "u_baked" in t:
                restate.append(f"{rel}: mentions the wrong baked axis as wrong")
            else:
                conflicts.append(f"{rel}: uses the wrong baked neck axis {wrong[0]:.4f}, {wrong[1]:.4f}, {wrong[2]:.4f}")
        if right_pat.search(t):
            restate.append(f"{rel}: neck_axis_u")
    fzj = ROOT / "docs" / "freeze" / "M1-3406-v1.json"
    if fzj.exists():
        listed = json.loads(fzj.read_text(encoding="utf-8")).get("hashed_files")
        if listed is not None and sorted(listed) != sorted(facts["hashed_files"]):
            conflicts.append(f"docs/freeze/M1-3406-v1.json hashed_files {listed} != facts.json")
    st = ROOT / "STATE.md"
    if st.exists():
        m = re.search(r"最新版本 \| `(v[0-9.]+)`", st.read_text(encoding="utf-8", errors="replace"))
        if m and m.group(1) != facts["db_latest"]:
            conflicts.append(f"STATE.md says db {m.group(1)}, facts.json says {facts['db_latest']} (update facts.json)")
    return conflicts, frozen, restate


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--paths", nargs="*", default=None)
    a = ap.parse_args()
    paths = [pathlib.Path(p) for p in a.paths] if a.paths else DEFAULT_PATHS
    conflicts, frozen, restate = check(paths, load_facts())
    if a.list:
        for r in restate:
            print("restated", r)
    for f in frozen:
        if not a.quiet:
            print("frozen  ", f)
    for c in conflicts:
        print("CONFLICT", c)
    if not a.quiet or conflicts:
        print(f"facts: {len(conflicts)} conflict(s), {len(frozen)} frozen, {len(restate)} restatement(s)")
    return 1 if conflicts else 0


if __name__ == "__main__":
    sys.exit(main())
