"""Feed start gate: every check that must hold before a batch is fed, in one place; --start then launches the Linux feeder.
Starting the feeder writes to Linux, so --start needs the user's say in the conversation (AGENTS.md red line 2).

    PYTHONUTF8=1 .venv-mobo/Scripts/python.exe ops/feed_gate.py b25 --check            # all gates, nothing launched
    ... ops/feed_gate.py b25 --check --no-linux                                           # local gates only
    ... ops/feed_gate.py b25 --start --session local_xxx                                   # gates, then start the feeder

Gates (any failure = exit 1, nothing launched):
  1 freeze intact (ops/check_freeze.py)
  2 experiments/<batch>_*/ has proposal.md, gates.py, approval.md, rows.json; approval.md names the sha256 of gates.py (raw or LF bytes)
  3 review.md present (second-model review); a warning only, fatal with --require-review
  4 pipeline files (v2/, tools/, inp_writer.py, config.yaml) committed, HEAD pushed to j/master
  5 Linux VERSION says git=<HEAD>; Linux v2/stage_db.py LF md5 equals the local file
  6 no feeder pid alive for the batch on Linux; no STOP_DB_FEED* file; root disk >= 30 GB
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "v2"))
PY = ROOT / ".venv-mobo" / "Scripts" / "python.exe"
PY = str(PY) if PY.exists() else sys.executable
REQUIRED = ("proposal.md", "gates.py", "approval.md", "rows.json")


def lf_md5(b: bytes) -> str:
    return hashlib.md5(b.replace(b"\r\n", b"\n")).hexdigest()


def git(*args: str) -> tuple[int, str]:
    r = subprocess.run(["git", *args], capture_output=True, cwd=str(ROOT))
    return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace").strip()


def batch_dir(batch: str, root: pathlib.Path = ROOT) -> pathlib.Path | None:
    hits = sorted(p for p in (root / "experiments").glob(f"{batch}_*") if p.is_dir())
    return hits[0] if len(hits) == 1 else None


def check_batch_dir(d: pathlib.Path | None, require_review: bool = False) -> tuple[list[str], list[str]]:
    """Gates 2 and 3 on one batch directory. Returns (problems, warnings)."""
    problems, warnings = [], []
    if d is None:
        return ["experiments/<batch>_* missing or ambiguous"], warnings
    for f in REQUIRED:
        if not (d / f).exists():
            problems.append(f"{d.name}/{f} missing")
    g = d / "gates.py"
    a = d / "approval.md"
    if g.exists() and a.exists():
        raw = g.read_bytes()
        shas = {hashlib.sha256(raw).hexdigest(), hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()}
        found = set(re.findall(r"\b[0-9a-f]{64}\b", a.read_text(encoding="utf-8", errors="replace")))
        if not found:
            problems.append(f"{d.name}/approval.md names no sha256")
        elif not (found & shas):
            problems.append(f"{d.name}/approval.md sha256 does not match gates.py (frozen file changed?)")
    if not (d / "review.md").exists():
        (problems if require_review else warnings).append(f"{d.name}/review.md missing: no second-model review")
    return problems, warnings


def local_gates(batch: str, require_review: bool) -> tuple[list[str], list[str]]:
    problems, warnings = [], []
    r = subprocess.run([PY, str(ROOT / "ops" / "check_freeze.py"), "--quiet"], cwd=str(ROOT))
    if r.returncode != 0:
        problems.append("gate 1: freeze broken")
    p2, w2 = check_batch_dir(batch_dir(batch), require_review)
    problems += [f"gate 2/3: {x}" for x in p2]
    warnings += [f"gate 3: {x}" for x in w2]
    rc, por = git("status", "--porcelain", "--", "v2", "tools", "inp_writer.py", "config.yaml")
    # tracked changes always count; untracked files count only when they are code (a log or a report history cannot be running code)
    dirty = [ln[3:] for ln in por.splitlines() if ln.strip() and (not ln.startswith("??") or ln[3:].rstrip("/").endswith((".py", ".yaml", ".sh", ".json")))]
    if dirty:
        problems.append("gate 4: pipeline files not committed: " + ", ".join(dirty[:8]))
    rc, _ = git("merge-base", "--is-ancestor", "HEAD", "j/master")
    if rc != 0:
        problems.append("gate 4: HEAD not pushed to j/master")
    return problems, warnings


def linux_gates(batch: str) -> list[str]:
    import remote as R
    problems = []
    rc, head = git("rev-parse", "--short", "HEAD")
    out = R.sh(f"cd ~/{R.RBASE} && cat code/VERSION 2>/dev/null | head -n 1; tr -d '\\r' < code/v2/stage_db.py | md5sum | cut -c1-32; "
               f"p=$(cat logs/db_feed_{batch}.pid 2>/dev/null); if [ -n \"$p\" ] && kill -0 $p 2>/dev/null; then echo FEEDER_ALIVE $p; else echo FEEDER_NONE; fi; "
               f"ls STOP_DB_FEED* 2>/dev/null | tr '\\n' ' '; echo; df -BG --output=avail / | tail -1 | tr -d ' G'", timeout=60)
    lines = out.strip().splitlines()
    ver, md5r, feeder, stops, disk = (lines + [""] * 5)[:5]
    if f"git={head}" not in ver:
        problems.append(f"gate 5: Linux VERSION '{ver}' is not git={head}; run ops/deploy.py --files v2/stage_db.py first")
    if md5r != lf_md5((ROOT / "v2" / "stage_db.py").read_bytes()):
        problems.append("gate 5: Linux v2/stage_db.py differs from the local file")
    if feeder.startswith("FEEDER_ALIVE"):
        problems.append(f"gate 6: a feeder for {batch} is alive ({feeder})")
    if stops.strip():
        problems.append(f"gate 6: stop file present: {stops.strip()}")
    try:
        if int(disk) < 30:
            problems.append(f"gate 6: root disk {disk} GB < 30 GB")
    except ValueError:
        problems.append(f"gate 6: could not read disk space ('{disk}')")
    return problems


def start_feeder(batch: str, session: str) -> str:
    import remote as R
    return R.sh(f"cd ~/{R.RBASE}/code && [ -e ../logs/db_feed_{batch}.pid ] && kill -0 $(cat ../logs/db_feed_{batch}.pid) 2>/dev/null && {{ echo REFUSED pid alive; exit 2; }}; "
                f"echo \"started by {session} $(date -u +%FT%TZ) git={subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], capture_output=True, cwd=str(ROOT)).stdout.decode().strip()}\" >> ../logs/db_feed_{batch}.out; "
                f"(setsid nohup taskset -c 4-11 nice -n 19 ../run.sh v2/stage_db.py feed {batch} >> ../logs/db_feed_{batch}.out 2>&1 < /dev/null & echo $! > ../logs/db_feed_{batch}.pid); "
                f"sleep 45; cat ../logs/db_feed_{batch}.pid; cut -c1-200 ../logs/db_feed_{batch}.out | tail -n 6", timeout=120)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("batch")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--start", action="store_true")
    ap.add_argument("--no-linux", action="store_true")
    ap.add_argument("--require-review", action="store_true")
    ap.add_argument("--session", default="unknown")
    a = ap.parse_args()
    if not (a.check or a.start):
        print("--check or --start"); return 2
    problems, warnings = local_gates(a.batch, a.require_review)
    if not a.no_linux and not problems:
        problems += linux_gates(a.batch)
    for w in warnings:
        print("WARN", w)
    for p in problems:
        print("FAIL", p)
    if problems:
        print(f"{len(problems)} gate(s) failed; feeder not started"); return 1
    print("all gates passed" + (" (local only)" if a.no_linux else ""))
    if a.start:
        if a.no_linux:
            print("--start needs Linux gates"); return 2
        print(start_feeder(a.batch, a.session))
    return 0


if __name__ == "__main__":
    sys.exit(main())
