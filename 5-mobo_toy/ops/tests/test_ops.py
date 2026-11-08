"""Run with the repo venv: PYTHONUTF8=1 .venv-mobo/Scripts/python.exe ops/tests/test_ops.py
Tests of the ops gates, in process where possible (coverage sees them), no ssh, no Linux, nothing under the queue.

A. check_freeze --quiet passes on the current tree.
B. guard_pretooluse denies a Write to a hashed file and a Bash redirect onto an approved gates.py; allows ordinary files and reads.
C. check_facts: clean on the repo; a synthetic file with the wrong neck axis or a foreign code_hash is a conflict; a frozen gates.py is reported as frozen, not a conflict.
D. feed_gate.check_batch_dir: missing files, sha mismatch, review warning; a complete directory passes.
E. review_packet builds a packet for b25 with gates.py, build_b25 and OPT1_ROWS in it.
F. judge replays b23_ow4 on v0.9 in a temp copy (never writes into the repo) and reproduces the recorded G30 value.
G. qa_compare on the latest version reports no new failure.
H. watch_remote.sh parses (bash -n) and refuses a stale lock only when the pid is alive.
I. deploy gate 5: the result files are the union of the two AUX_FILES lists; pushing one of them while a feeder is alive is refused,
   other files and an idle Linux pass; main() checks gate 5 before it writes anything to Linux.
"""
import contextlib
import hashlib
import io
import json
import pathlib
import runpy
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ops"))
sys.path.insert(0, str(ROOT / "v2"))
PY = sys.executable
DBROOT = pathlib.Path(r"H:/Projects/Femoral implant generation/db3406")
T0 = time.perf_counter()
checks = []


def ok(name, cond, extra=""):
    checks.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + f"(t={time.perf_counter() - T0:.0f}s) " + name + (f"  [{extra}]" if extra else ""), flush=True)


def run_script(rel, args=(), stdin=None):
    """Run an ops script in process with argv and optional stdin; return (exit code, stdout)."""
    buf = io.StringIO()
    old_argv, old_stdin = sys.argv, sys.stdin
    sys.argv = [str(ROOT / rel), *args]
    if stdin is not None:
        sys.stdin = io.StringIO(stdin)
    rc = 0
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            runpy.run_path(str(ROOT / rel), run_name="__main__")
    except SystemExit as e:
        rc = int(e.code or 0) if not isinstance(e.code, str) else 1
    finally:
        sys.argv, sys.stdin = old_argv, old_stdin
    return rc, buf.getvalue()


tmp = pathlib.Path(tempfile.mkdtemp(prefix="mobo_ops_tests_"))
try:
    # ---------------------------------------------------------------- A
    rc, out = run_script("ops/check_freeze.py", ["--quiet"])
    ok("A: freeze intact", rc == 0, out[-200:])

    # ---------------------------------------------------------------- B
    hashed = str(ROOT / "v2" / "geom3d.py")
    rc, out = run_script("ops/guard_pretooluse.py", stdin=json.dumps({"tool_name": "Write", "tool_input": {"file_path": hashed, "content": "x"}}))
    ok("B: Write to a hashed file is denied (exit 2)", rc == 2, out[:120])
    rc, out = run_script("ops/guard_pretooluse.py", stdin=json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(ROOT / "docs" / "runbook.md"), "content": "x"}}))
    ok("B: Write to an ordinary file is allowed", rc == 0)
    rc, out = run_script("ops/guard_pretooluse.py", stdin=json.dumps({"tool_name": "Bash", "tool_input": {"command": "echo x > experiments/b25_opt1/gates.py"}}))
    ok("B: Bash redirect onto an approved gates.py is denied", rc == 2, out[:120])
    rc, out = run_script("ops/guard_pretooluse.py", stdin=json.dumps({"tool_name": "Bash", "tool_input": {"command": "cat experiments/b25_opt1/gates.py"}}))
    ok("B: reading gates.py is allowed", rc == 0)

    # ---------------------------------------------------------------- C
    import check_facts as CF
    facts = CF.load_facts()
    conflicts, frozen, restate = CF.check(CF.DEFAULT_PATHS, facts)
    ok("C: no fact conflict in the repo and the surrogate folders", not conflicts, "; ".join(conflicts)[:300])
    ok("C: the frozen b25 gates.py is reported as frozen, not as a conflict", any("b25_opt1" in f for f in frozen), "; ".join(frozen)[:200])
    bad = tmp / "bad"
    bad.mkdir()
    (bad / "a.py").write_text("U = np.array([0.9138995811072274, 0.06263424660728525, 0.4010791777242645])\n", encoding="utf-8")
    (bad / "b.md").write_text("code_hash is `0123456789` today\n", encoding="utf-8")
    (bad / "c.md").write_text(f"code_hash {facts['code_hash']}; axis {facts['neck_axis_u'][0]:.5f}\n", encoding="utf-8")
    c2, f2, r2 = CF.check([bad], facts)
    ok("C: wrong axis and foreign code_hash are conflicts, restatements of the right values are not", len(c2) == 2 and any("a.py" in c for c in c2) and any("b.md" in c for c in c2) and any("c.md" in r for r in r2), "; ".join(c2))

    # ---------------------------------------------------------------- D
    import feed_gate as FG
    d = tmp / "experiments" / "b99_test"
    d.mkdir(parents=True)
    p, w = FG.check_batch_dir(d)
    ok("D: an empty batch dir has 4 missing files", sum("missing" in x for x in p) == 4, "; ".join(p))
    for f in ("proposal.md", "rows.json"):
        (d / f).write_text("{}", encoding="utf-8")
    (d / "gates.py").write_text("GATES = {}\n", encoding="utf-8")
    sha = hashlib.sha256((d / "gates.py").read_bytes()).hexdigest()
    (d / "approval.md").write_text("| sha | 0000000000000000000000000000000000000000000000000000000000000000 |\n", encoding="utf-8")
    p, w = FG.check_batch_dir(d)
    ok("D: a wrong sha256 in approval.md is a problem", any("does not match" in x for x in p), "; ".join(p))
    (d / "approval.md").write_text(f"| sha | {sha} |\n", encoding="utf-8")
    p, w = FG.check_batch_dir(d)
    ok("D: complete dir passes with a review warning", not p and any("review.md" in x for x in w), "; ".join(w))
    p, w = FG.check_batch_dir(d, require_review=True)
    ok("D: --require-review turns the warning into a problem", any("review.md" in x for x in p))
    (d / "review.md").write_text("ok", encoding="utf-8")
    p, w = FG.check_batch_dir(d, require_review=True)
    ok("D: with review.md nothing is left", not p and not w)
    ok("D: batch_dir resolves b25 and refuses an unknown batch", FG.batch_dir("b25") is not None and FG.batch_dir("b00") is None)

    # ---------------------------------------------------------------- E
    import review_packet as RP
    text, bd = RP.build("b25")
    ok("E: packet for b25 holds gates.py, build_b25 and OPT1_ROWS", "GATES = {" in text and "def build_b25" in text and "OPT1_ROWS = (" in text and "审查清单" in text, f"{len(text)} chars")
    out = tmp / "packet.md"
    rc, msg = run_script("ops/review_packet.py", ["b25", "--out", str(out)])
    ok("E: --out writes the packet where told", rc == 0 and out.exists() and "sha256" in msg)

    # ---------------------------------------------------------------- F
    src = ROOT / "experiments" / "b23_ow4"
    cp = tmp / "b23_ow4"
    shutil.copytree(src, cp)
    before = (src / "result.json").read_bytes()
    rc, out = run_script("ops/judge.py", [str(cp), "--db", str(DBROOT / "v0.9")])
    res = json.loads((cp / "result.json").read_text(encoding="utf-8"))
    ok("F: judge replays b23 on v0.9 in a temp copy; G30 value as recorded", rc == 0 and abs(res["gates"]["G30"]["value"] - 0.0364) < 1e-3 and (src / "result.json").read_bytes() == before, str(res["gates"]["G30"]["value"]))

    # ---------------------------------------------------------------- G
    latest = sorted((p for p in DBROOT.glob("v0.*") if p.is_dir() and (p / "manifest.json").exists()), key=lambda p: int(p.name.split(".")[1]))[-1]
    r = subprocess.run([PY, str(ROOT / "ops" / "qa_compare.py"), "--db", str(latest)], capture_output=True, cwd=str(ROOT))
    ok(f"G: qa_compare on {latest.name} reports no new failure", r.returncode == 0, (r.stdout + r.stderr).decode("utf-8", "replace")[-160:])

    # ---------------------------------------------------------------- H
    bash = pathlib.Path(r"C:/Program Files/Git/usr/bin/bash.exe")
    if bash.exists():
        r = subprocess.run([str(bash), "-n", str(ROOT / "ops" / "watch_remote.sh")], capture_output=True)
        ok("H: watch_remote.sh parses", r.returncode == 0, r.stderr.decode()[:120])
        w = tmp / "w"
        (w / "logs").mkdir(parents=True)
        (w / "logs" / "watcher.lock").write_text("999999 other 2026-11-04T00:00:00Z b00\n")
        script = (ROOT / "ops" / "watch_remote.sh").read_text(encoding="utf-8").replace("cd ~/mobo_toy_v2 || exit 1", f"cd '{w.as_posix()}' || exit 1")
        (w / "watch.sh").write_text(script, encoding="utf-8", newline="\n")
        r = subprocess.run([str(bash), str(w / "watch.sh"), "b00", "test"], capture_output=True, timeout=60)
        ok("H: a stale lock (dead pid) does not refuse; a missing manifest exits 4", r.returncode == 4, r.stdout.decode()[:120])
    else:
        ok("H: skipped, no Git bash", True)
    # ---------------------------------------------------------------- I
    import deploy as DP
    aux = DP.result_files()
    ok("I: result files = both AUX_FILES lists (jobs.py, foam_refine.py, inp_writer.py in; stage_db.py, gates out)",
       {"v2/jobs.py", "v2/foam_refine.py", "inp_writer.py", "v2/collar_rule.py", "abaqus/odb_export.py"} <= aux and "v2/stage_db.py" not in aux
       and not any(x.endswith("gates.py") for x in aux), str(sorted(aux)))
    why = DP.aux_gate(["v2/jobs.py", "v2/stage_db.py"], aux, ["b29 123", "b30 456"])
    ok("I: an AUX file while feeders are alive -> refused, names the file and the feeders", why is not None and why.startswith("门 5") and "v2/jobs.py" in why
       and "b29 123" in why and "v2/stage_db.py" not in why.split("是喂料器")[0], why)
    ok("I: a non-AUX file while feeders are alive -> passes", DP.aux_gate(["v2/stage_db.py", "v2/tests/test_x.py"], aux, ["b29 123"]) is None)
    ok("I: an AUX file with no feeder alive -> passes", DP.aux_gate(["v2/jobs.py"], aux, []) is None)
    src = (ROOT / "ops" / "deploy.py").read_text(encoding="utf-8")
    ok("I: main() runs gate 5 before the first write to Linux, and the override is an explicit flag",
       0 < src.index("why = aux_gate(") < src.index("cat > .{p.name}.new") and "--allow-aux-with-feeders" in src)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

n_fail = sum(not c for _, c in checks)
print(f"{len(checks) - n_fail}/{len(checks)} passed, {n_fail} failed")
sys.exit(1 if n_fail else 0)
