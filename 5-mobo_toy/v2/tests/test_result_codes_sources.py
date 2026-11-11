"""Run with the repo venv: PYTHONUTF8=1 .venv-mobo/Scripts/python.exe v2/tests/test_result_codes_sources.py
Local only: a fake queue in the system temp dir, a fake ssh, a fake solver, a fake clock. Nothing touches Linux, the real queue,
v2/runs or Abaqus.

A. jobs._fail: writes code and klass after the four old keys; a code given by the source wins; without a code the text decides;
   the old four-argument call still works; when result_codes cannot be imported the record is the old four keys and nothing raises.
B. run_abaqus: the failure returns it builds itself carry a code that is in result_codes.CODES.
C. solve_worker.Backoff: 20, 40, 80, 160, 300, 300 s; the marker appears at the 5th failure in a row and goes away on success.
D. solve_worker.main with fakes:
   D1 two transport failures on fetch, then fine: the job is released twice, never written as failed, solved and pushed once.
   D2 fetch never works: after RELEASE_MAX releases the job is written as failed with code transport_failed (the queue is not blocked).
   D3 a fetch that fails on the remote side (no .inp): failed at once with code fetch_error, never released.
   D4 ssh down for six rounds: waits 20..300 s, the transport marker is written at the 5th and removed when ssh is back.
   D5 licence unavailable twice, then fine: released twice, the next claim waits, solved and pushed once with status OK.
   D6 licence never there: after RELEASE_MAX releases the job is pushed as failed with code license_unavailable.
   D7 a solver time limit is pushed as failed at once (code solve_timeout), never released.
   D8 stop is requested while a job waits to be released: it is released before the worker exits, nothing stays CLAIMED.
   D9 fetch never works and the failure cannot be pushed either: the job goes back to the queue, it is not left CLAIMED.
"""
import json
import pathlib
import shutil
import sys
import tempfile
import time as _time
import types

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "v2"))
SCR = pathlib.Path(tempfile.mkdtemp(prefix="mobo_result_codes_"))

import jobs as J  # noqa: E402
import result_codes as RC  # noqa: E402
import run_abaqus as RA  # noqa: E402
import solve_worker as SW  # noqa: E402

J.QROOT = SCR / "queue"
J.QROOT.mkdir()
checks = []


def ok(name, cond, extra=""):
    checks.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""), flush=True)


# ------------------------------------------------------------------------------------------------ A
def failed(name, *args, **kw):
    d = J.QROOT / name
    d.mkdir(exist_ok=True)
    J._fail(d, *args, **kw)
    return json.loads((d / "FAILED.json").read_text())


f = failed("a1", "L1", "prep", "shoulder 91 mm² < prosthetic neck 154 mm²", code="shoulder_below_neck")
ok("A: code and klass come after the four old keys", list(f) == ["level", "stage", "reason", "time", "code", "klass"]
   and (f["code"], f["klass"], f["level"], f["stage"]) == ("shoulder_below_neck", "DESIGN", "L1", "prep"), str(f))
f = failed("a2", "L3", "prep", "anything at all", code="prep_out_of_memory")
ok("A: a code given by the source wins over the text", (f["code"], f["klass"]) == ("prep_out_of_memory", "ENV"), str(f))
f = failed("a3", "L4", "solve", "m_fric: TOO MANY ATTEMPTS MADE FOR THIS INCREMENT")
ok("A: the old four-argument call works and the text decides", (f["code"], f["klass"]) == ("not_converged", "NUMERIC"), str(f))
f = failed("a4", "L4", "solve", "m_fric: x", code="no_such_code")
ok("A: a code that is not in CODES is UNKNOWN / unclassified, not guessed", (f["code"], f["klass"]) == ("unclassified", "UNKNOWN"), str(f))
f = failed("a5", "L4", "solve", "m_fric: timeout > 21600 s", code=None)
ok("A: code=None (an old solve.json) falls back to the text", f["code"] == "solve_timeout", str(f))
saved = sys.modules.get("result_codes")
sys.modules["result_codes"] = None                           # import result_codes -> ImportError
try:
    f = failed("a6", "L1", "prep", "shoulder 91 mm² < prosthetic neck 154 mm²", code="shoulder_below_neck")
finally:
    sys.modules["result_codes"] = saved
ok("A: result_codes unreadable -> the old four keys, nothing raises", list(f) == ["level", "stage", "reason", "time"], str(f))

# ------------------------------------------------------------------------------------------------ B
src = "".join((ROOT / p).read_text(encoding="utf-8") for p in ("run_abaqus.py", "v2/solve_worker.py", "v2/jobs.py", "v2/stage_v2a.py"))
import re  # noqa: E402
lit = set(re.findall(r'"code": "([a-z_]+)"', src)) | set(re.findall(r'code="([a-z_]+)"', src)) | set(re.findall(r'"([a-z_]+)" if [^\n]{0,60} else "([a-z_]+)"\)', src)[0] if re.findall(r'"([a-z_]+)" if [^\n]{0,60} else "([a-z_]+)"\)', src) else ())
lit |= {"export_incomplete"} if '"L5", e["reason"], "export_incomplete"' in src else set()
ok("B: every code written in jobs.py, stage_v2a.py, run_abaqus.py and solve_worker.py is in result_codes.CODES",
   len(lit) >= 9 and lit <= set(RC.CODES), str(sorted(lit - set(RC.CODES))) + " of " + str(sorted(lit)))
orig_run, orig_cfg = RA.subprocess.run, RA.CFG
RA.CFG = {"abaqus": {"cpus_per_job": 1, "timeout_s": 1, "license_retry": {"max_tries": 2, "wait_s": 0}}}


def fake_run_timeout(cmd, **kw):
    if "terminate" in cmd:
        return types.SimpleNamespace(stdout="", stderr="", returncode=0)
    raise RA.subprocess.TimeoutExpired(cmd, kw.get("timeout", 1))


inp = SCR / "u_fric.inp"
inp.write_text("*HEADING\n")
try:
    RA.subprocess.run = fake_run_timeout
    r = RA.run_job(inp)
    ok("B: a solver time limit -> L4 with code solve_timeout", (r["status"], r.get("code")) == ("L4", "solve_timeout"), str(r))
    RA.subprocess.run = lambda cmd, **kw: types.SimpleNamespace(stdout="Abaqus Error: license not available", stderr="", returncode=1)
    r = RA.run_job(inp)
    ok("B: licence refused on every try -> L4 with code license_unavailable", (r["status"], r.get("code"), r["tries"]) == ("L4", "license_unavailable", 2), str(r))
    RA.subprocess.run = lambda cmd, **kw: types.SimpleNamespace(stdout="", stderr="", returncode=1)
    (SCR / "u_fric.msg").write_text(" ***ERROR: TOO MANY ATTEMPTS MADE FOR THIS INCREMENT\n")
    RA._read_orig = RA._read
    RA._read = lambda p: " ***ERROR: TOO MANY ATTEMPTS MADE FOR THIS INCREMENT" if p.suffix == ".msg" else ""
    r = RA.run_job(inp)
    ok("B: a solver error carries no code (Linux reads the text) and the text classifies as not_converged",
       r["status"] == "L4" and "code" not in r and RC.classify("L4", "solve", "u_fric: " + r["reason"]).code == "not_converged", str(r))
    RA._read = RA._read_orig
    RA.run_job = lambda inp, **kw: {"job": "u", "status": "OK", "wall_s": 1.0, "reason": "", "tries": 1}
    RA.export_odb = lambda odb, out_dir, script=None: {"status": "L5", "reason": "odb export timeout"}
    r = RA.run_and_export(inp)
    ok("B: a failed odb export -> L5 with code export_incomplete", (r["status"], r.get("code")) == ("L5", "export_incomplete"), str(r))
finally:
    RA.subprocess.run, RA.CFG = orig_run, orig_cfg

# ------------------------------------------------------------------------------------------------ C / D: fakes
RUNS = SCR / "runs"
RUNS.mkdir()
SW.LOG, SW.LOCAL, SW.STOP_LOCAL = RUNS / "worker.log", RUNS / "q", RUNS / "worker.STOP"


class Clock:
    """A clock that only moves when the worker sleeps."""

    def __init__(self):
        self.now, self.sleeps = 1_000_000.0, []

    def sleep(self, s):
        self.sleeps.append(s)
        self.now += s
        if len(self.sleeps) > 400:
            raise RuntimeError("the worker loop does not end")

    def time(self):
        return self.now

    strftime = staticmethod(_time.strftime)


def marker(kind):
    return RUNS / f"worker.PAUSED_{kind}.json"


SW.time = clk = Clock()
b = SW.Backoff("transport")
waits = [b.fail(f"x{i}") for i in range(4)]
m4 = marker("transport").exists()
waits += [b.fail("x4"), b.fail("x5")]
ok("C: waits double from 20 s and stop at 300 s", waits == [20, 40, 80, 160, 300, 300], str(waits))
mj = json.loads(marker("transport").read_text(encoding="utf-8")) if marker("transport").exists() else {}
ok("C: no marker after 4 failures, a marker at the 5th naming the kind and the reason", not m4 and mj.get("kind") == "transport" and mj.get("n_fail") == 5 and mj.get("what") == "x4", str(mj))
ok("C: until = now + the wait", abs(b.until - clk.now - 300) < 1e-6)
b.ok()
ok("C: one success clears the count, the wait and the marker", b.n == 0 and b.until == 0.0 and not marker("transport").exists())


def scenario(fetch_plan, solve_plan, claims_plan=None, max_pushes=1, stop_after_solves=None, push_down=False):
    """Run SW.main() against fakes. fetch_plan / solve_plan: lists consumed call by call, the last entry repeats.
    fetch entry: "ok" | "transport" | "remote". solve entry: a result dict. claims_plan: per claim call "down" or "ok".
    Returns what happened."""
    global clk
    SW.time = clk = Clock()
    for k in ("transport", "license"):
        marker(k).unlink(missing_ok=True)
    SW.LOG.unlink(missing_ok=True)
    SW.TO_RELEASE.clear()
    st = {"state": "READY", "released": 0, "pushed": [], "fetch": 0, "solve": 0, "claim": 0, "marker_seen": set(), "stop": False}

    def nxt(plan, i):
        return plan[min(i, len(plan) - 1)]

    def claim_next(n):
        i, st["claim"] = st["claim"], st["claim"] + 1
        for k in ("transport", "license"):
            if marker(k).exists():
                st["marker_seen"].add(k)
        if claims_plan is not None:
            if nxt(claims_plan, i) == "down":
                raise SW.R.RemoteError("remote command failed (255): ssh: connect to host: Connection timed out")
            if i >= len(claims_plan) - 1:
                st["stop"] = True
            return []
        if st["state"] != "READY":
            return []
        st["state"] = "CLAIMED"
        return ["jobA"]

    def fetch(jid):
        i, st["fetch"] = st["fetch"], st["fetch"] + 1
        what = nxt(fetch_plan, i)
        if what == "transport":
            raise SW.TransportError(f"fetch {jid}: ssh: connect to host: Connection timed out")
        if what == "remote":
            raise RuntimeError(f"job {jid} has no .inp files")
        d = SW.LOCAL / jid
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
        (d / "m_fric.inp").write_text("*HEADING\n")
        return [d / "m_fric.inp"]

    def sh(cmd, timeout=60, stdin=None):
        if "mv CLAIMED READY" in cmd:
            if st["state"] == "CLAIMED":
                st["state"] = "READY"
            st["released"] += 1
            return ""
        raise AssertionError(f"unexpected remote command: {cmd}")

    def push(jid, results):
        if push_down:
            st["push_refused"] = st.get("push_refused", 0) + 1
            if st["push_refused"] >= 2:
                st["stop"] = True
            raise SW.R.RemoteError("remote command failed (255): ssh: connect to host: Connection timed out")
        st["pushed"].append(json.loads(json.dumps(results, default=str)))
        st["state"] = "SOLVED"
        if len(st["pushed"]) >= max_pushes:
            st["stop"] = True

    def run_and_export(inp, cpus=None, timeout=None):
        i, st["solve"] = st["solve"], st["solve"] + 1
        if stop_after_solves is not None and st["solve"] >= stop_after_solves:
            st["stop"] = True
        return dict(nxt(solve_plan, i))

    saved = (SW.claim_next, SW.fetch, SW.R.sh, SW.push, SW.RA.run_and_export, SW.stop_requested)
    SW.claim_next, SW.fetch, SW.R.sh, SW.push, SW.RA.run_and_export = claim_next, fetch, sh, push, run_and_export
    SW.stop_requested = lambda: st["stop"]
    try:
        SW.main()
    finally:
        SW.claim_next, SW.fetch, SW.R.sh, SW.push, SW.RA.run_and_export, SW.stop_requested = saved
    st["sleeps"] = list(clk.sleeps)
    st["log"] = SW.LOG.read_text(encoding="utf-8") if SW.LOG.exists() else ""
    return st


OK_RES = {"status": "OK", "wall_s": 1.0, "reason": ""}
SW.KEEP = {"fric": [], "bond": [], "intact": []}

s = scenario(["transport", "transport", "ok"], [OK_RES])
ok("D1: two transport failures on fetch -> released twice, waits 20 and 40 s, solved and pushed once as OK, never written as failed",
   s["released"] == 2 and [x for x in s["sleeps"] if x in (20, 40, 80)] == [20, 40] and len(s["pushed"]) == 1
   and s["pushed"][0]["m_fric"]["status"] == "OK" and "code" not in s["pushed"][0]["m_fric"] and not marker("transport").exists(),
   str({k: s[k] for k in ("released", "sleeps", "pushed")}))

s = scenario(["transport"], [OK_RES])
ok("D2: fetch never works -> released RELEASE_MAX times, then written as failed with code transport_failed",
   s["released"] == SW.RELEASE_MAX and s["fetch"] == SW.RELEASE_MAX + 1 and s["solve"] == 0
   and s["pushed"] == [{"fetch": {"status": "L4", "reason": s["pushed"][0]["fetch"]["reason"], "code": "transport_failed"}}]
   and s["pushed"][0]["fetch"]["reason"].startswith("fetch failed: "), str({k: s[k] for k in ("released", "fetch", "pushed")}))
ok("D2: that record classifies as ENV on the Linux side", RC.classify("L4", "solve", "fetch: " + s["pushed"][0]["fetch"]["reason"], s["pushed"][0]["fetch"]["code"])[:2] == ("ENV", "transport_failed"))

s = scenario(["remote"], [OK_RES])
ok("D3: no .inp on the remote side -> failed at once with code fetch_error, never released, no wait",
   s["released"] == 0 and s["fetch"] == 1 and s["pushed"][0]["fetch"]["code"] == "fetch_error" and not [x for x in s["sleeps"] if x >= 20],
   str({k: s[k] for k in ("released", "fetch", "pushed", "sleeps")}))

s = scenario(["ok"], [OK_RES], claims_plan=["down"] * 6 + ["ok", "ok"])
ok("D4: ssh down six rounds -> waits 20, 40, 80, 160, 300, 300 s",
   [x for x in s["sleeps"] if x >= 20] == [20, 40, 80, 160, 300, 300], str(s["sleeps"]))
ok("D4: the transport marker is there from the 5th failure and gone once ssh is back; the log says PAUSED and RESUMED",
   "transport" in s["marker_seen"] and not marker("transport").exists() and "PAUSED (transport)" in s["log"] and "RESUMED (transport) after 6" in s["log"], s["log"][-300:])

LIC = {"status": "L4", "wall_s": 1.0, "reason": "license unavailable after 5 tries", "tries": 5, "code": "license_unavailable"}
s = scenario(["ok"], [LIC, LIC, OK_RES])
ok("D5: licence unavailable twice, then fine -> released twice, solved three times, pushed once as OK",
   s["released"] == 2 and s["solve"] == 3 and len(s["pushed"]) == 1 and s["pushed"][0]["m_fric"]["status"] == "OK"
   and "license_unavailable: released back to the queue (2 of 3)" in s["log"] and not marker("license").exists(),
   str({k: s[k] for k in ("released", "solve", "pushed")}) + s["log"][-200:])
t_claims = sum(x for x in s["sleeps"])
ok("D5: the next claim waited at least 20 s and then 40 s (the worker idles in 15 s steps)", t_claims >= 60 and s["claim"] >= 3, f"slept {t_claims} s, {s['claim']} claims")

s = scenario(["ok"], [LIC])
ok("D6: licence never there -> released RELEASE_MAX times, then pushed as failed with code license_unavailable",
   s["released"] == SW.RELEASE_MAX and s["solve"] == SW.RELEASE_MAX + 1 and len(s["pushed"]) == 1
   and (s["pushed"][0]["m_fric"]["status"], s["pushed"][0]["m_fric"]["code"]) == ("L4", "license_unavailable"),
   str({k: s[k] for k in ("released", "solve", "pushed")}))

TMO = {"status": "L4", "wall_s": 21600.0, "reason": "timeout > 21600 s", "tries": 1, "code": "solve_timeout"}
s = scenario(["ok"], [TMO])
ok("D7: a solver time limit is pushed as failed at once (code solve_timeout), never released",
   s["released"] == 0 and s["solve"] == 1 and s["pushed"][0]["m_fric"]["code"] == "solve_timeout", str({k: s[k] for k in ("released", "solve", "pushed")}))

s = scenario(["ok"], [LIC], stop_after_solves=1)
ok("D8: stop requested while a job waits to be released -> released before the worker exits, the job is READY again, nothing pushed",
   s["released"] == 1 and s["state"] == "READY" and s["pushed"] == [] and not SW.TO_RELEASE and "stop requested; exiting" in s["log"],
   str({k: s[k] for k in ("released", "state", "pushed")}))

s = scenario(["transport"], [OK_RES], push_down=True)
ok("D9: fetch never works and the failure cannot be pushed -> the job is released again, not left CLAIMED, never marked SOLVED",
   s["released"] >= SW.RELEASE_MAX + 1 and s["state"] == "READY" and s["pushed"] == [] and not SW.TO_RELEASE,
   str({k: s.get(k) for k in ("released", "state", "pushed", "push_refused")}))

shutil.rmtree(SCR, ignore_errors=True)
bad = [k for k, v in checks if not v]
print(f"\n{len(checks) - len(bad)}/{len(checks)} checks passed" + (f"; FAILED: {bad}" if bad else ""))
sys.exit(1 if bad else 0)
