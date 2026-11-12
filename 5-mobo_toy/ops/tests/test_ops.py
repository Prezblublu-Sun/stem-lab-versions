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
L. rows files in the gates: approval names their sha256, the guard freezes them, deploy makes the directory.  M. the judge compares the approved hash.
N. one definition in several places: code hash, hashed files, auxiliary files; db_latest is looked up on disk.
O. fetch_feed_manifests: where each manifest goes, byte-for-byte copies, the index, updates of manifests that moved on.
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
    an = OC.answer(jb, jdb)
    ok("J: answer = one entry per row in file order with class, code and what to tell; a row the database lacks has no class and tells nothing",
       [(x["label"], x["klass"], x["code"], x["tell"]) for x in an["rows"]] == [("R0", "OK", "ok", "result"), ("R1", "NUMERIC", "not_converged", "failed"),
                                                                                 ("R2", "ENV", "prep_out_of_memory", None), ("R3", "UNKNOWN", "solve_aborted", None), ("R4", None, None, None)]
       and an["batch"] == "j_batch" and an["db"] == "j_db", str(an)[:300])
    rc, out = run_script("ops/outcomes.py", [str(ROOT / "experiments" / "b28_fam"), "--db", str(DBROOT / "v0.12"), "--json"])
    a28 = json.loads(out) if rc == 0 else {}
    ok("J: outcomes --json on b28 / v0.12: 17 rows, 16 results and one failed (the mesh failure)", rc == 0 and len(a28.get("rows", [])) == 17
       and [x["tell"] for x in a28["rows"]].count("result") == 16 and [(x["label"], x["tell"]) for x in a28["rows"] if x["tell"] != "result"] == [("FAM1_0o", "failed")], out[:200])
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
    ok("K: feed_tokens for a batch that does not exist says none and stays shell-safe", FG.feed_tokens("b99zz").count("_sha256=none") == 4)
    ok("K: b33 is not a rows-file batch: its rows_in token is none", tk["rows_in_sha256"] == "none")

    # ---------------------------------------------------------------- L
    import guard_pretooluse as GP
    lb = tmp / "exp_l" / "experiments" / "b98_test"
    lb.mkdir(parents=True)
    gname = "gates" + ".py"
    for f, txt in (("proposal.md", "p"), (gname, "GATES = {}\n"), ("rows.json", "{}"), ("review.md", "r")):
        (lb / f).write_text(txt, encoding="utf-8")
    (lb / "rows_in.json").write_bytes(b'{"format": "stage_db rows_in 1",\r\n "rows": []}\r\n')
    gsha = hashlib.sha256((lb / gname).read_bytes()).hexdigest()
    rsha_lf = hashlib.sha256((lb / "rows_in.json").read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    (lb / "approval.md").write_text(f"approved\n{gsha}\n", encoding="utf-8")
    pr, _ = FG.check_batch_dir(lb)
    ok("L: a rows-file batch whose approval.md does not name the sha256 of rows_in.json is a problem", len(pr) == 1 and "rows_in.json" in pr[0] and rsha_lf in pr[0], str(pr))
    (lb / "approval.md").write_text(f"approved\n{gsha}\nrows_in {rsha_lf}\n", encoding="utf-8")
    ok("L: with the LF sha256 of rows_in.json in approval.md (the file on disk is CRLF) the batch dir passes", FG.check_batch_dir(lb) == ([], []))
    (lb / "rows_in.json").write_bytes(b'{"format": "stage_db rows_in 1",\r\n "rows": [1]}\r\n')
    ok("L: rows_in.json edited after approval is a problem", [x for x in FG.check_batch_dir(lb)[0] if "rows_in.json" in x])
    saved_root = GP.ROOT
    GP.ROOT = tmp / "exp_l"
    try:
        fz = [p.name for p in GP.frozen_paths()]
        (lb / "approval.md").unlink()
        fz0 = [p.name for p in GP.frozen_paths()]
    finally:
        GP.ROOT = saved_root
    ok("L: the guard treats rows_in.json as frozen once approval.md exists, and not before", "rows_in.json" in fz and gname in fz and "rows_in.json" not in fz0, f"{fz} {fz0}")
    dsrc = (ROOT / "ops" / "deploy.py").read_text(encoding="utf-8")
    ok("L: deploy makes the directory only for experiments/ paths and refuses unsafe path characters",
       'if rel.startswith("experiments/") else ""' in dsrc and DP.SAFE_REL.fullmatch("experiments/b34_x/rows_in.json") and DP.SAFE_REL.fullmatch("v2/stage_db.py")
       and not DP.SAFE_REL.fullmatch("experiments/b34 x/rows_in.json") and not DP.SAFE_REL.fullmatch("a;b") and not DP.SAFE_REL.fullmatch("$(x)/y"))
    ok("L: b33 has no rows file, so the feed gate asks Linux for nothing more", FG.rows_in_local("b33") is None and FG.rows_in_local("b99zz") is None)

    # ---------------------------------------------------------------- M
    ok("M: approval_sha: b33 matches, b28 (two hashes in approval.md) matches, b23 names none", FG.approval_sha(ROOT / "experiments" / "b33_r2cand") == []
       and FG.approval_sha(ROOT / "experiments" / "b28_fam") == [] and [k for k, _ in FG.approval_sha(ROOT / "experiments" / "b23_ow4")] == ["none"])
    ok("M: the judge of b23 went ahead with a reminder and recorded approval_sha = none; the judge of b28 recorded ok",
       r23.get("approval_sha") == "none" and r28.get("approval_sha") == "ok", f"{r23.get('approval_sha')} {r28.get('approval_sha')}")
    cm = tmp / "b28_changed"
    shutil.copytree(ROOT / "experiments" / "b28_fam", cm)
    gm = cm / ("gates" + ".py")
    gm.write_bytes(gm.read_bytes() + b"\n# one byte more\n")
    (cm / "result.json").unlink()
    rc, out = run_script("ops/judge.py", [str(cm), "--db", str(DBROOT / rec28_db)])
    ok("M: a judging file changed after approval is refused: exit 2, no result.json written", rc == 2 and "不判定" in out and not (cm / "result.json").exists(), f"rc {rc} {out[-120:]}")
    ok("M: the judge of b28 recorded the feed manifest fetched from Linux, and null for the rows file it does not have",
       pv28["inputs"]["feed_manifest"] == {"file": pv28["inputs"]["feed_manifest"]["file"], "sha256": hashlib.sha256((ROOT / "experiments" / "b28_fam" / "feed_manifest.json").read_bytes()).hexdigest()}
       and pv28["inputs"]["rows_in"] is None, str(pv28["inputs"].get("feed_manifest"))[:120])
    rc, out = run_script("ops/judge.py", [str(cm), "--db", str(DBROOT / rec28_db), "--replay"])
    rm = json.loads((cm / "result.json").read_text(encoding="utf-8")) if (cm / "result.json").exists() else {}
    ok("M: with --replay the same batch is judged with a reminder and result.json says approval_sha = mismatch",
       rc in (0, 1) and rm.get("approval_sha") == "mismatch" and rm.get("replay") is True and "提醒" in out, f"rc {rc} {rm.get('approval_sha')}")
    fsrc = (ROOT / "ops" / "feed_gate.py").read_text(encoding="utf-8")
    ok("K: start_feeder puts the tokens into the feed log line", "tokens = feed_tokens(batch)" in fsrc and "{tokens}" in fsrc.split("def start_feeder")[1].split("db_feed_{batch}.out")[0])
    ok("K: the judge of b23 (no rows.json) recorded rows = None", r23.get("provenance", {}).get("inputs", {}).get("rows", 0) is None)

    # ---------------------------------------------------------------- N
    import ast
    import re as _re
    import check_facts as CF
    sys.path.insert(0, str(ROOT / "tools"))
    import db_export as DX
    facts = json.loads((ROOT / "ops" / "facts.json").read_text(encoding="utf-8"))
    sdb = (ROOT / "v2" / "stage_db.py").read_text(encoding="utf-8")
    sjobs = (ROOT / "v2" / "jobs.py").read_text(encoding="utf-8")
    db_hash = _re.search(r'^DB_CODE_HASH = "([0-9a-f]{10})"', sdb, _re.M).group(1)
    ok("N: one code hash in three places: db_export, stage_db, facts.json", DX.EXPECTED_CODE_HASH == db_hash == facts["code_hash"], f"{DX.EXPECTED_CODE_HASH} {db_hash} {facts['code_hash']}")
    jobs_files = ast.literal_eval(_re.search(r"for f in (\(\"femur_real\.py\".*?\)):", sjobs, _re.S).group(1))
    ok("N: one list of hashed files in three places, in the same order: db_export, jobs.code_hash, facts.json",
       tuple(DX.HASHED_FILES) == tuple(jobs_files) == tuple(f.split("/", 1)[1] for f in facts["hashed_files"]), f"{DX.HASHED_FILES} {jobs_files}")

    def aux_of(rel):
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        return set(next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "AUX_FILES" for t in n.targets)))

    feeder_aux, export_aux = aux_of("v2/stage_db.py"), aux_of("tools/db_export.py")
    only_export = {"v2/bond_collar.py", "v2/import_stem.py", "v2/resorption.py", "v2/shielding.py"}   # they shape labels at export or belong to hooks no feeder batch uses
    ok("N: the exporter's auxiliary files hold every one the feeder checks; the four more are the known ones",
       feeder_aux <= export_aux and export_aux - feeder_aux == only_export, f"feeder only {sorted(feeder_aux - export_aux)}; export only {sorted(export_aux - feeder_aux)}")
    ld = tmp / "latest_db"
    for v, with_manifest in (("v0.9", True), ("v0.13", True), ("v0.14", True), ("v0.15", False), ("vX", True), ("raw", True)):
        (ld / v).mkdir(parents=True)
        if with_manifest:
            (ld / v / "manifest.json").write_text("{}", encoding="utf-8")
    ok("N: latest_db = the highest version by number that has a manifest (0.14, not 0.9; 0.15 without a manifest does not count)",
       CF.latest_db(ld) == "v0.14" and CF.latest_db(tmp / "no_such_root") is None and CF.latest_db(tmp / "exp_l") is None, str(CF.latest_db(ld)))
    ok("N: facts.json db_latest is the newest version on disk", CF.latest_db(CF.DB_ROOT) in (None, facts["db_latest"]), f"{CF.latest_db(CF.DB_ROOT)} {facts['db_latest']}")
    saved_dbroot = CF.DB_ROOT
    CF.DB_ROOT = ld
    try:
        c2, _, _ = CF.check([tmp / "bad" / "nothing_here"], {**facts, "db_latest": "v0.13"})
    finally:
        CF.DB_ROOT = saved_dbroot
    ok("N: a stale db_latest is a conflict", len(c2) == 1 and "v0.14" in c2[0] and "v0.13" in c2[0], str(c2))

    # ---------------------------------------------------------------- O
    import fetch_feed_manifests as FM
    fe = tmp / "fm" / "experiments"
    (fe / "b90_one").mkdir(parents=True)
    (fe / "b91_a").mkdir()
    (fe / "b91_b").mkdir()
    remote_m = {"b90": b'{"batch": "b90"}', "b91": b'{"batch": "b91"}', "b7m": b'{"batch": "b7m"}', "b2": b'{"batch": "b2"}'}
    pl0 = FM.plan(remote_m, fe)
    ok("O: a batch with one directory goes there; without one, or with two, it goes to the pool; nothing is written by the plan",
       {e["batch"]: e["file"] for e in pl0} == {"b90": "experiments/b90_one/feed_manifest.json", "b91": "experiments/_feed_manifests/db_manifest_b91.json",
                                               "b7m": "experiments/_feed_manifests/db_manifest_b7m.json", "b2": "experiments/_feed_manifests/db_manifest_b2.json"}
       and all(e["state"] == "new" for e in pl0) and [e["batch"] for e in pl0] == ["b2", "b7m", "b90", "b91"] and not (fe / FM.POOL).exists(), str(pl0)[:300])
    FM.write(remote_m, fe)
    idx = json.loads((fe / FM.POOL / "index.json").read_text(encoding="utf-8"))
    ok("O: write copies byte for byte and records the sha256 in the index", (fe / "b90_one" / "feed_manifest.json").read_bytes() == remote_m["b90"]
       and idx["b90"]["sha256"] == hashlib.sha256(remote_m["b90"]).hexdigest() and idx["b2"]["bytes"] == len(remote_m["b2"]) and set(idx) == set(remote_m))
    t_first = idx["b2"]["fetched_utc"]
    remote_m["b2"] = b'{"batch": "b2", "more": 1}'
    pl1 = FM.plan(remote_m, fe)
    ok("O: a second look says same for the untouched ones and changed for the one that moved on", {e["batch"]: e["state"] for e in pl1} == {"b2": "changed", "b7m": "same", "b90": "same", "b91": "same"})
    FM.write(remote_m, fe)
    idx2 = json.loads((fe / FM.POOL / "index.json").read_text(encoding="utf-8"))
    ok("O: the changed one is updated in place and in the index; the others keep their first fetch time",
       (fe / FM.POOL / "db_manifest_b2.json").read_bytes() == remote_m["b2"] and idx2["b2"]["sha256"] == hashlib.sha256(remote_m["b2"]).hexdigest()
       and idx2["b90"]["fetched_utc"] == idx["b90"]["fetched_utc"] and all(e["state"] == "same" for e in FM.plan(remote_m, fe)), f"{t_first} {idx2['b2']['fetched_utc']}")
    real_idx = json.loads((ROOT / "experiments" / FM.POOL / "index.json").read_text(encoding="utf-8"))
    bad_real = [b for b, e in real_idx.items() if hashlib.sha256((ROOT / e["file"]).read_bytes()).hexdigest() != e["sha256"]]
    ok(f"O: the {len(real_idx)} manifests in the repo still have the sha256 the index recorded", len(real_idx) >= 34 and not bad_real, str(bad_real))

    # ---------------------------------------------------------------- P
    import state as ST
    page = ST.to_html(["# STATE.md", "由 `ops/state.py` 生成，a < b & c。", "", "## 1 仓库", "| 项 | 值 |", "|---|---|", "| HEAD | `d53e8de` **脏** |", "| x | 1 > 0 |", "",
                       "**worker.log 末 3 行**：", "```", "2026-11-10 <claimed> & pushed", "```", "- 一条", "- 两条"], "状态 <页>")
    ok("P: the state page is one self-contained file: a table with a header row, headings, a code block, a list; text is escaped",
       page.startswith("<!doctype html>") and "<th>项</th><th>值</th>" in page and "<td>HEAD</td><td><code>d53e8de</code> <b>脏</b></td>" in page
       and "<h2>1 仓库</h2>" in page and "<pre>2026-11-10 &lt;claimed&gt; &amp; pushed</pre>" in page and "<li>一条</li><li>两条</li>" in page
       and "a &lt; b &amp; c" in page and "<td>1 &gt; 0</td>" in page and "<title>状态 &lt;页&gt;</title>" in page
       and "http" not in page and "<script" not in page and "---" not in page, page[:200])

    # ---------------------------------------------------------------- Q
    import copy
    import check_all as CA
    GOOD = {"freeze_rc": 0, "facts_rc": 0, "frozen_code_hash": "6d7af243d0", "linux_asked": True, "h_free_gb": 300.0,
            "git": {"head": "abc1234", "pushed": True, "dirty_pipeline": [], "dirty_other": ["AGENTS.md"]},
            "head_md5": {"v2/jobs.py": "11111111", "v2/stage_db.py": "22222222"},
            "linux": {"version_git": "abc1234", "md5": {"v2/jobs.py": "11111111", "v2/stage_db.py": "22222222"}, "code_hash": "6d7af243d0", "serve": True, "feeders": [],
                      "queue": {"NEW": 0, "READY": 0, "CLAIMED": 9, "SOLVED": 9, "DONE": 8, "FAILED": 1}, "ready_unclaimed": 0, "ready_oldest_min": 0, "root_free_gb": 145.0, "stop_flags": []},
            "worker": {"alive": True, "stop": False, "paused": []},
            "db": {"name": "v0.14", "n_rows": 1434, "exporter": "x", "has_qa": True, "qa_fails": ["1", "7", "13"], "published": "ok"},
            "batches": [{"name": "b33_r2cand", "approved": True, "has_rows": True, "judged": True, "rows_in": False, "n_rows": 9, "by_class": {"OK": 9}, "n_not_in_db": 0,
                         "judged_db": "v0.14", "gates": {"G53": "PASS"}}]}

    def st(inp):
        c, b = CA.evaluate(inp)
        return {n: s for n, s, _ in c + b}, " | ".join(d for _, _, d in c + b)

    def var(**over):
        x = copy.deepcopy(GOOD)
        for k, v in over.items():
            if isinstance(v, dict) and isinstance(x.get(k), dict):
                x[k].update(v)
            else:
                x[k] = v
        return x
    s, d = st(GOOD)
    ok("Q: everything in order -> every item is 过; a FAIL verdict of a gate is a result, not a failed check", set(s.values()) == {CA.OK} and len(s) == 14, str(s))
    ok("Q: the tables say so in one line and list both tables", CA.tables(*CA.evaluate(GOOD))[0].startswith("**没有不过的项**：过 14，注意 0，不过 0")
       and "| 系统 | 判断 | 说明 |" in CA.tables(*CA.evaluate(GOOD)) and "| `b33_r2cand` | 过 | 9 行：OK 9；判定：G53 PASS（v0.14） |" in CA.tables(*CA.evaluate(GOOD)))
    bad_cases = {"a broken freeze": (var(freeze_rc=1), "冻结的 8 个文件"), "a facts conflict": (var(facts_rc=1), "文档和事实表"),
                 "Linux unreachable when it was asked": (var(linux=None), "队列"),
                 "hashed files changed on Linux": (var(linux={"code_hash": "ffffffffff"}), "Linux 上的冻结"),
                 "a paused worker": (var(worker={"paused": ["transport"]}), "worker"),
                 "READY jobs waiting 90 min while the worker was not stopped": (var(linux={"ready_unclaimed": 2, "ready_oldest_min": 90}), "队列"),
                 "a feeder alive without serve": (var(linux={"serve": False, "feeders": ["b34"]}), "serve"),
                 "Linux root disk under 30 GB": (var(linux={"root_free_gb": 12.0}), "Linux 磁盘"), "H: under 50 GB": (var(h_free_gb=20.0), "本机磁盘"),
                 "a new QA failure": (var(db={"qa_fails": ["1", "7", "9", "13"]}), "数据库最新版本"),
                 "a published version that changed": (var(db={"published": "changed"}), "最新版本已发布"),
                 "no database version": (var(db=None), "数据库最新版本")}
    for label, (inp, item) in bad_cases.items():
        s, d = st(inp)
        ok(f"Q: {label} -> 不过 on that item", s[item] == CA.BAD, f"{item}: {s[item]}")
    unk = var()
    unk["batches"][0]["by_class"] = {"OK": 8, "UNKNOWN": 1}
    s, d = st(unk)
    ok("Q: a batch with a row that cannot be told apart -> 不过, and it says a person must look", s["b33_r2cand"] == CA.BAD and "要人看过" in d)
    note_cases = {"uncommitted pipeline files": (var(git={"dirty_pipeline": ["v2/stage_db.py"]}), "管线文件已提交"), "HEAD not pushed": (var(git={"pushed": False}), "已推到 J:"),
                  "a file on Linux that is not HEAD": (var(linux={"md5": {"v2/jobs.py": "11111111", "v2/stage_db.py": "33333333"}}), "Linux 上的代码是 HEAD"),
                  "VERSION on Linux names another commit": (var(linux={"version_git": "0000000"}), "Linux 上的代码是 HEAD"),
                  "the worker is not running": (var(worker={"alive": False}), "worker"), "serve down with nothing to do": (var(linux={"serve": False}), "serve"),
                  "the latest version is not published": (var(db={"published": None}), "最新版本已发布"), "no QA report": (var(db={"has_qa": False, "qa_fails": []}), "数据库最新版本"),
                  "READY jobs while the worker is away": (var(linux={"ready_unclaimed": 1, "ready_oldest_min": 5}, worker={"alive": False}), "队列")}
    for label, (inp, item) in note_cases.items():
        s, d = st(inp)
        ok(f"Q: {label} -> 注意, not 不过", s[item] == CA.NOTE and CA.BAD not in s.values(), f"{item}: {s[item]}")
    s, d = st(var(linux={"ready_unclaimed": 2, "ready_oldest_min": 90}, worker={"alive": False, "stop": True}))
    ok("Q: READY jobs waiting long while the user stopped the worker -> not 不过", s["队列"] == CA.NOTE)
    s, d = st(var(linux=None, linux_asked=False))
    ok("Q: --no-linux -> the five Linux items are 未查, nothing is 不过", [s[k] for k in ("Linux 上的代码是 HEAD", "Linux 上的冻结", "serve", "队列", "Linux 磁盘")] == [CA.SKIP] * 5 and CA.BAD not in s.values())
    nb = var()
    nb["batches"] = [dict(GOOD["batches"][0], name="b34_r2sts", approved=False, rows_in=True), dict(GOOD["batches"][0], name="b35_x", n_not_in_db=4, by_class={}, judged=False, gates={}),
                     dict(GOOD["batches"][0], name="b23_ow4", has_rows=False)]
    s, d = st(nb)
    ok("Q: a batch without approval, a batch whose rows are not exported, an old batch without rows.json -> 注意, 注意, 过",
       (s["b34_r2sts"], s["b35_x"], s["b23_ow4"]) == (CA.NOTE, CA.NOTE, CA.OK) and "还不能喂" in d and "4 行不在最新版本里" in d)
    lx = CA._linux({"VERSION": ["git=5ed2ada | deployed=2026-11-12T09:20:00Z", "mtime 2026-11-12 09:20"], "MD5": ["0123456789abcdef0123456789abcdef  v2/jobs.py"], "CODEHASH": ["6d7af243d0"],
                    "PROCS": ["379307 /home/u/venv/bin/python code/v2/stage_v2a.py serve --n-prep 2", "400 /home/u/venv/bin/python code/v2/stage_db.py feed b34"],
                    "QUEUE": ["NEW 1", "READY 2", "CLAIMED 3016", "SOLVED 3016", "DONE 3001", "FAILED 126"], "READY_AGE": ["75 db_cd_x", "3 db_cd_y"],
                    "DISK": ["/dev/sda2 457G 289G 145G 67% /"], "FLAGS": ["DB_H14_REF_OK", "STOP_DB_FEED"]})
    ok("Q: the Linux block is read: commit, md5, serve, feeder, queue, oldest READY, free disk, stop file",
       lx == {"version_git": "5ed2ada", "md5": {"v2/jobs.py": "01234567"}, "code_hash": "6d7af243d0", "serve": True, "feeders": ["b34"],
              "queue": {"NEW": 1, "READY": 2, "CLAIMED": 3016, "SOLVED": 3016, "DONE": 3001, "FAILED": 126}, "ready_unclaimed": 2, "ready_oldest_min": 75,
              "root_free_gb": 145.0, "stop_flags": ["STOP_DB_FEED"]} and CA._linux({}) is None, str(lx))
    import review_packet as RP2
    b34 = ROOT / "experiments" / "b34_r2sts"
    if (b34 / "rows_in.json").exists():
        text, _ = RP2.build("b34")
        ok("Q: the review packet of a row-file batch holds the row file and the source of build_file", "## rows_in.json" in text and '"base": "db_al_r2_05_e+1.5_07e94cd0"' in text
           and "def build_file(batch: str)" in text and "no build_b34" not in text)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

n_fail = sum(not c for _, c in checks)
print(f"{len(checks) - n_fail}/{len(checks)} passed, {n_fail} failed")
sys.exit(1 if n_fail else 0)
