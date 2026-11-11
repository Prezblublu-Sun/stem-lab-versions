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
J. result_codes: every rule has a hand-written case and gives the expected class and code; an unknown reason falls through to
   unclassified; outcomes on a synthetic batch; judge on a temp copy of b28 leaves every gate as recorded and reports the one mesh failure.
K. provenance: the commit of HEAD; changed and untracked files in a temp repo; the cap; no repo -> an error entry, no exception;
   inputs hashed by content; the judge of b28 recorded HEAD and the hashes of its gates.py and of the database it read.
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

    # ---------------------------------------------------------------- J
    import outcomes as OC
    import result_codes as RC
    cases = (   # (level, stage, reason, class, code): one or more per rule, with reasons the code can write but the data does not hold yet
        ("", "", "", "OK", "ok"),
        ("L1", "prep", "shoulder 131 mm² < prosthetic neck 154 mm²", "DESIGN", "shoulder_below_neck"),
        ("L1", "prep", "templating: collar_rule neck_in_shoulder: no offset works (e 0: shoulder ...)", "DESIGN", "no_entry_offset"),
        ("L1", "prep", "templating: tip too thin (3.1 mm² < 4)", "DESIGN", "tip_too_thin"),
        ("L1", "prep", "templating: blocked (smallest size hits cortex at every offset)", "DESIGN", "blocked_by_cortex"),
        ("L1", "prep", "templating: something new", "DESIGN", "templating_other"),
        ("L1", "prep", "fric_only needs model m1 and excludes bond_only", "ERROR", "invalid_spec"),
        ("L1", "prep", "foam_refine needs model m1", "ERROR", "invalid_spec"),
        ("L1", "prep", "foam_refine is only for design / variant jobs, not kind 'intact'", "ERROR", "invalid_spec"),
        ("L1", "prep", "collar is implemented only in the M1 interface model (spec model = m1)", "ERROR", "invalid_spec"),
        ("L3", "prep", "foam_refine: the size field hook was not called", "ERROR", "hook_error"),
        ("L3", "prep", "foam_refine: ImportError: no module", "ERROR", "hook_error"),
        ("L3", "prep", "prep process exited with code -9 (signal 9) under a 24 GB memory limit; ...", "ENV", "prep_out_of_memory"),
        ("L3", "prep", "mesh generation ran away in memory (>24 GB under RLIMIT_AS; killed the ...", "ENV", "prep_out_of_memory"),
        ("L3", "prep", "BuildError: L3: meshing failed after retries: algo 1, h 2, m 40: Exception: Invalid boundary mesh", "NUMERIC", "mesh_failed"),
        ("L3", "prep", "BuildError: L3: meshing failed after retries: algo 1, h 2, m 40: L3: degenerate tetrahedra: {...}", "NUMERIC", "mesh_failed"),
        ("L3", "prep", "BuildError: L3: degenerate tetrahedra: {'cortex': {'min_vol': 1e-7, 'n_tiny': 3}}", "NUMERIC", "mesh_degenerate"),
        ("L4", "solve", "m_fric: TOO MANY ATTEMPTS MADE FOR THIS INCREMENT ANALYSIS SUMMARY: TOTAL OF 37 INCREMENTS", "NUMERIC", "not_converged"),
        ("L4", "solve", "m_fric: timeout > 14400 s", "ENV", "solve_timeout"),
        ("L4", "solve", "m_fric: license unavailable after 5 tries", "ENV", "license_unavailable"),
        ("L4", "solve", "fetch: fetch failed: ssh: connect to host", "ENV", "transport_failed"),
        ("L4", "solve", "intact: analysis not completed (see .msg)", "UNKNOWN", "solve_aborted"),
        ("L4", "solve", "m_fric: unknown failure (see .log/.msg)", "UNKNOWN", "solve_aborted"),
        ("L4", "solve", "m_fric: runner exception: OSError: [WinError 5]", "UNKNOWN", "runner_exception"),
        ("L5", "solve", "m_bond: missing export LOAD_CONTACT.csv", "UNKNOWN", "export_incomplete"),
        ("L5", "solve", "m_fric: odb export timeout", "UNKNOWN", "export_incomplete"),
        ("L5", "post", "KeyError: 'gruen7'\nTraceback ...", "ERROR", "post_exception"),
        ("SKIP", "solve", "skipped on purpose 2026-10-05 10:12: with zero interference the stem is fully released", "SKIP", "skipped"),
        ("L3", "prep", "MemoryError: \nTraceback ...", "ENV", "prep_out_of_memory"),
    )
    wrong = [(c[2][:40], RC.classify(*c[:3])[:2]) for c in cases if RC.classify(*c[:3])[:2] != c[3:]]
    ok(f"J: result_codes.classify gives the expected class and code on {len(cases)} hand-written cases", not wrong, str(wrong[:3]))
    ok("J: every rule has a case, and every rule's code is in CODES", {r[2] for r in RC._RULES} <= {c[4] for c in cases} and {r[2] for r in RC._RULES} <= set(RC.CODES),
       str({r[2] for r in RC._RULES} - {c[4] for c in cases}))
    ok("J: a reason no rule knows falls through to UNKNOWN / unclassified", RC.classify("L4", "solve", "m_fric: the moon was in the wrong phase")[:2] == ("UNKNOWN", "unclassified"))
    ok("J: a code given by the source wins over the text; a code outside CODES is unclassified, not guessed",
       RC.classify("L3", "prep", "BuildError: L3: meshing failed after retries", "prep_out_of_memory")[:2] == ("ENV", "prep_out_of_memory")
       and RC.classify("L4", "solve", "m_fric: timeout > 5 s", "no_such_code")[:2] == ("UNKNOWN", "unclassified"))
    ok("J: for_job: DONE is ok whatever else the row says; FAILED with nothing recorded is unclassified, never ok; an unfinished job has no outcome",
       RC.for_job("DONE", "L4", "solve", "old text")[:2] == ("OK", "ok") and RC.for_job("FAILED", None, None, "")[:2] == ("UNKNOWN", "unclassified")
       and RC.for_job("READY", None, None, None) is None and RC.for_job("FAILED", "L1", "prep", "templating: tip too thin (3 < 4)").code == "tip_too_thin")
    ok("J: every class in CODES is one of the seven, every class has a Chinese name, and what the worker retries by itself is ENV",
       {k for k, _ in RC.CODES.values()} == set(RC.KLASSES) == set(RC.KLASS_ZH) and all(RC.CODES[c][0] == "ENV" for c in RC.AUTO_RETRY))
    jb, jdb = tmp / "j_batch", tmp / "j_db"
    jb.mkdir(); jdb.mkdir()
    (jb / "rows.json").write_text(json.dumps({"stage_db_batch": "bxx", "rows": [{"label": f"R{i}", "job_id": f"job{i}"} for i in range(5)]}), encoding="utf-8")
    (jdb / "scalars.csv").write_text(
        "job_id,status,fail_level,fail_stage,fail_reason\n"
        "job0,DONE,,,\n"
        "job1,FAILED,L4,solve,m_fric: TOO MANY ATTEMPTS MADE FOR THIS INCREMENT\n"
        "job2,FAILED,L3,prep,prep process exited with code -9 (signal 9) under a 24 GB memory limit\n"
        "job3,FAILED,L4,solve,intact: analysis not completed (see .msg)\n"
        "other,DONE,,,\n", encoding="utf-8")
    (tmp / "j_db2").mkdir()
    (tmp / "j_db2" / "scalars.csv").write_text(           # an export with the two result columns: the exported code is used, an unfinished row is not an outcome
        "job_id,status,fail_level,fail_stage,fail_reason,result_code,result_class\n"
        "job0,DONE,,,,ok,OK\n"
        "job1,FAILED,L3,prep,BuildError: L3: meshing failed after retries,prep_out_of_memory,ENV\n"
        "job2,READY,,,,,\n", encoding="utf-8")
    oc2 = OC.outcomes(jb, tmp / "j_db2")
    ok("J: with result columns in the database the exported code wins over the text; an unfinished row counts as not in the database",
       oc2["by_class"] == {"OK": 1, "ENV": 1} and [x["label"] for x in oc2["not_in_db"]] == ["R2", "R3", "R4"], str(oc2))
    oc = OC.outcomes(jb, jdb)
    ok("J: outcomes on a synthetic batch: one row per class, the row the database lacks is listed, rows of other batches are left out",
       oc["n_rows"] == 5 and oc["by_class"] == {"OK": 1, "NUMERIC": 1, "ENV": 1, "UNKNOWN": 1} and [x["label"] for x in oc["not_in_db"]] == ["R4"]
       and [(x["label"], x["code"]) for x in oc["not_ok"]] == [("R1", "not_converged"), ("R2", "prep_out_of_memory"), ("R3", "solve_aborted")], str(oc))
    ok("J: tell = what a selection strategy may be told: the result, failed, or nothing (ENV, UNKNOWN and rows the database lacks)",
       oc["tell"] == {"job0": "result", "job1": "failed", "job2": None, "job3": None, "job4": None}, str(oc["tell"]))
    ok("J: the table names the UNKNOWN row and says a person must look", "R3（solve_aborted）" in OC.table(oc) and "有 1 行待查" in OC.table(oc))
    ok("J: a batch without rows.json -> None, and the table says so", OC.outcomes(tmp / "b23_ow4", DBROOT / "v0.9") is None and "不报" in OC.table(None))
    r23 = json.loads((tmp / "b23_ow4" / "result.json").read_text(encoding="utf-8"))
    ok("J: the judge of F wrote outcomes = null for b23 (no rows.json)", "outcomes" in r23 and r23["outcomes"] is None)
    src = ROOT / "experiments" / "b28_fam"
    cp = tmp / "b28_fam"
    shutil.copytree(src, cp)
    before = (src / "result.json").read_bytes()
    rec = json.loads(before.decode("utf-8"))
    rec28_db = rec["db"]
    rc, out = run_script("ops/judge.py", [str(cp), "--db", str(DBROOT / rec28_db)])
    r28 =json.loads((cp / "result.json").read_text(encoding="utf-8"))
    same = {k: (v["status"], v["value"]) for k, v in r28["gates"].items()} == {k: (v["status"], v["value"]) for k, v in rec["gates"].items()}
    ok("J: judge on a temp copy of b28: every gate as recorded, the repo file untouched, and outcomes holds the one mesh failure (FAM1_0o)",
       same and (src / "result.json").read_bytes() == before and r28["outcomes"]["by_class"] == {"OK": 16, "NUMERIC": 1}
       and [(x["label"], x["code"]) for x in r28["outcomes"]["not_ok"]] == [("FAM1_0o", "mesh_failed")]
       and "| 没算出来 | 1 | FAM1_0o（mesh_failed） |" in out, f"rc {rc} same {same} {r28['outcomes']['by_class']}")

    # ---------------------------------------------------------------- K
    import provenance as PV

    def g(cwd, *args):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.autocrlf=false", *args], cwd=str(cwd), capture_output=True)

    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT), capture_output=True).stdout.decode().strip()
    st = PV.git_state()
    ok("K: git_state on this repo gives the full commit of HEAD", len(head) == 40 and st.get("commit") == head and isinstance(st.get("dirty"), list), str(st)[:120])
    kr = tmp / "k_repo"
    kr.mkdir()
    g(kr, "init", "-q")
    (kr / "a.txt").write_text("one\n", encoding="utf-8")
    g(kr, "add", "a.txt")
    g(kr, "commit", "-q", "-m", "one")
    clean = PV.git_state(kr)
    (kr / "a.txt").write_bytes(b"two\n")
    (kr / "新.txt").write_text("x\n", encoding="utf-8")
    dirty = PV.git_state(kr)
    ok("K: a clean temp repo has no dirty line; a changed file and an untracked file are both listed, the commit stays",
       clean.get("n_dirty") == 0 and dirty.get("n_dirty") == 2 and dirty["commit"] == clean["commit"]
       and sorted(dirty["dirty"]) == [" M a.txt", "?? 新.txt"], f"{clean} {dirty}")
    for i in range(PV.DIRTY_MAX + 5):
        (kr / f"u{i}.txt").write_text("x", encoding="utf-8")
    many = PV.git_state(kr)
    ok("K: the dirty list is capped, n_dirty is the true count", many["n_dirty"] == PV.DIRTY_MAX + 7 and len(many["dirty"]) == PV.DIRTY_MAX, str(many["n_dirty"]))
    nr = pathlib.Path(tempfile.mkdtemp(prefix="mobo_ops_norepo_"))
    try:
        inside = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(nr), capture_output=True).returncode == 0
        ok("K: outside a repo git_state returns an error entry and does not raise", inside or ("error" in PV.git_state(nr) and "commit" not in PV.git_state(nr)),
           "skipped: the temp folder is inside a repo" if inside else "")
    finally:
        shutil.rmtree(nr, ignore_errors=True)
    rec = PV.record("test", {"a": kr / "a.txt", "none": kr / "missing.txt"}, root=kr)
    ok("K: record hashes an input by content, names it relative to the root, and gives None for a missing file",
       rec["inputs"]["a"] == {"file": "a.txt", "sha256": hashlib.sha256(b"two\n").hexdigest()} and rec["inputs"]["none"] is None and rec["action"] == "test", str(rec["inputs"]))
    pv28 = r28.get("provenance", {})
    ok("K: the judge of b28 recorded HEAD, the hash of the gates.py it ran, and the database's manifest and scalars",
       pv28.get("git", {}).get("commit") == head and pv28["inputs"]["gates"]["sha256"] == r28["gates_sha256"]
       and pv28["inputs"]["db_manifest"]["sha256"] == hashlib.sha256((DBROOT / rec28_db / "manifest.json").read_bytes()).hexdigest()
       and pv28["inputs"]["db_scalars"]["sha256"] == hashlib.sha256((DBROOT / rec28_db / "scalars.csv").read_bytes()).hexdigest()
       and pv28["inputs"]["rows"] is not None and f"代码 {head[:7]}" in out, str(pv28.get("git", {}))[:160])
    import feed_gate as FG
    tk = dict(x.split("=") for x in FG.feed_tokens("b33").split())
    b33 = ROOT / "experiments" / "b33_r2cand"
    ok("K: feed_tokens for b33: the commit of HEAD, the dirty count, and the sha256 of rows.json, gates.py and approval.md",
       tk["commit"] == head and tk["dirty"] == str(st["n_dirty"]) and all(
           tk[f"{k}_sha256"] == hashlib.sha256((b33 / f).read_bytes()).hexdigest() for k, f in (("rows", "rows.json"), ("gates", "gates.py"), ("approval", "approval.md"))), str(tk)[:200])
    ok("K: feed_tokens for a batch that does not exist says none and stays shell-safe", FG.feed_tokens("b99zz").count("_sha256=none") == 3)
    fsrc = (ROOT / "ops" / "feed_gate.py").read_text(encoding="utf-8")
    ok("K: start_feeder puts the tokens into the feed log line", "tokens = feed_tokens(batch)" in fsrc and "{tokens}" in fsrc.split("def start_feeder")[1].split("db_feed_{batch}.out")[0])
    ok("K: the judge of b23 (no rows.json) recorded rows = None", r23.get("provenance", {}).get("inputs", {}).get("rows", 0) is None)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

n_fail = sum(not c for _, c in checks)
print(f"{len(checks) - n_fail}/{len(checks)} passed, {n_fail} failed")
sys.exit(1 if n_fail else 0)
