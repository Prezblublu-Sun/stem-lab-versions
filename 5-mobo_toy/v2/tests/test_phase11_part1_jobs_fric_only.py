"""Run with the repo venv: PYTHONUTF8=1 .venv-mobo/Scripts/python.exe v2/tests/test_phase11_part1_jobs_fric_only.py
Local only (fake queue in the system temp dir); part 2 needs part 1 run first; part 3 reads the research-log tables.
"""
"""Part 1 tests (local only, fake queue in scratch; nothing touches Linux, the real queue or runs/q).

1. jobs.prep with spec fric_only: M1.build / collar_rule templating / femur_for monkeypatched -> READY, m_bond.inp deleted,
   prep.json carries fric_only + margin_check; guard fric_only+bond_only -> FAILED L1; margin_check "dense" reaches collar_rule.
2. jobs.post fric_only branch with post_m1 monkeypatched -> DONE without any intact reference; result keys as specified.
3. Regression: bonded (non fric_only) post path still goes through intact_ref + PM1.evaluate.
4. stability.stability on the fric_only job dir (synthetic pairs / U tables) -> works with result.json lacking vm/sed keys.
"""
import json
import pathlib
import shutil
import sys
import types

import numpy as np

ROOT = pathlib.Path(r"H:/projects/Femoral implant generation/sandbox/mobo_toy")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "v2"))
import tempfile
SCR = pathlib.Path(tempfile.gettempdir()) / "mobo_toy_phase11_tests" / "fake_queue"   # fake queue outside the repo
shutil.rmtree(SCR, ignore_errors=True)
(SCR / "queue").mkdir(parents=True)
(SCR / "results").mkdir()

import jobs as J  # noqa: E402
import geom3d as G  # noqa: E402
import collar_rule as CR  # noqa: E402
import model3d_m1 as M1  # noqa: E402
import post_m1 as PM1  # noqa: E402

J.QROOT, J.RESULTS = SCR / "queue", SCR / "results"
assert J.QROOT.exists() and not str(J.QROOT).startswith(str(pathlib.Path.home() / "mobo_toy_v2"))

checks = []


def ok(name, cond, extra=""):
    checks.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""), flush=True)


class FakeFm:
    cut_from_head_mm = 25.25
    cfg = {"prosthesis": {"neck_radius_mm": 7.0}}

    def resected_volume(self):
        return 1234.5

    def pose(self, a, e):
        return np.array([0.0, 0.0, 29.5]), np.array([0.0, 0.0, -1.0]), np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])


J.femur_for = lambda spec: FakeFm()
DESIGN = {"L": 48.25, "rho_tip": 0.35, "q": 1.45, "lam": 1.67, "g_ml": 0.43, "g_ap": 0.51, "n_a": 2.96, "n_p": 5.40,
          "tau_a": -0.05, "tau_p": 0.106, "alpha": 29.7, "m": 0.5, "cap_h": 1.5}
BASE = {"kind": "design", "design": DESIGN, "h_int": 2.0, "min_A0": 153.93804002589985, "stage": "neck11", "model": "m1",
        "h_cut": 25.25, "slip_tol": 2.5e-4, "delta": 0.025, "collar_rule": "neck_in_shoulder"}
TPL = {"fit": True, "alpha": 29.7, "e": 0.0, "A0": 292.19, "contact": 0.0, "s_bind": 0.0, "volume": 3300.0, "margin": 0.5}

built = {}


def fake_build(st, fm, pl, d, name, **kw):
    (d / f"{name}_fric.inp").write_text("*HEADING fric")
    (d / f"{name}_bond.inp").write_text("*HEADING bond")
    built["kw"] = kw
    return {"n_tet": {"cortex": 1, "cancellous": 2, "stem": 3}}


M1.build = fake_build


def fake_tpl(stem, fem, **kw):
    mc = kw.get("margin_check") or CR.MARGIN_CHECK
    return {**TPL, "margin_check": mc, "pose": fem.pose(29.7, 0.0), "collar_rule": "neck_in_shoulder"}


CR.template_neck_in_shoulder = fake_tpl   # install_neck's lambda looks this name up at call time

# ---------------------------------------------------------------- 1. prep
jid = J.submit({**BASE, "tag": "a0", "fric_only": True})
d = J.QROOT / jid
ok("prep fric_only -> READY", J.prep(jid) == "READY")
ok("m_bond.inp deleted, m_fric.inp kept", not (d / "m_bond.inp").exists() and (d / "m_fric.inp").exists())
prep = json.loads((d / "prep.json").read_text())
ok("prep.json fric_only True + margin_check sparse", prep.get("fric_only") is True and prep.get("margin_check") == "sparse")
ok("prep.json templating/bone_loss present", prep["templating"]["A0"] == 292.19 and prep["bone_loss"]["total_mm3"] == 1234.5 + 3300.0)
ok("M1.build got slip_tol/delta from spec", built["kw"]["slip_tol"] == 2.5e-4 and built["kw"]["delta"] == 0.025)

j2 = J.submit({**BASE, "tag": "guard", "fric_only": True, "bond_only": True})
ok("prep fric_only+bond_only -> FAILED L1", J.prep(j2) == "FAILED" and json.loads((J.QROOT / j2 / "FAILED.json").read_text())["level"] == "L1")
j2b = J.submit({**BASE, "tag": "guard2", "fric_only": True, "model": "v2"})
ok("prep fric_only with model v2 -> FAILED L1", J.prep(j2b) == "FAILED")

j3 = J.submit({**BASE, "tag": "dense", "fric_only": True, "margin_check": "dense"})
st3 = J.prep(j3)
p3 = json.loads((J.QROOT / j3 / "prep.json").read_text())
ok("prep margin_check dense -> READY, recorded, collar_rule default switched", st3 == "READY" and p3["margin_check"] == "dense" and CR.MARGIN_CHECK == "dense")
CR.set_margin_check("sparse")
j4 = J.submit({**BASE, "tag": "bonded", "collar_rule": None, "margin_check": "dense"})
installed = {}
CR.install_margin_check = lambda mode: installed.setdefault("mode", mode) or setattr(G, "template", lambda stem, fem, **kw: {**TPL, "margin_check": mode})
ok("prep margin_check without collar_rule -> install_margin_check", J.prep(j4) == "READY" and installed.get("mode") == "dense"
   and (J.QROOT / j4 / "m_bond.inp").exists())
ok("job ids differ (fric_only / margin_check enter the hash)", len({jid, j2, j3, j4}) == 4)

# ---------------------------------------------------------------- 2. post (fric_only)
calls = []
PM1.micromotion = lambda dd, job: calls.append(("mm", job)) or {"f1_p95_um": 12.3, "f1_all_p95_um": 12.3, "interface_area": 2000.0, "n_pairs": 5}
PM1.contact_stats = lambda dd, job: calls.append(("cs", job)) or {"status_frac_stick": 0.8}
PM1.collar_load = lambda dd, job: calls.append(("cl", job)) or {}
PM1.qoi3d = types.SimpleNamespace(micromotion=lambda dd, job: calls.append(("old", job)) or {"f1_p95_um": 9.9, "frac_open": 0.1})


def _boom(*a, **k):
    raise AssertionError("intact reference lookup must not be called for fric_only")


J.intact_ref, J.explicit_ref = _boom, _boom
(d / "solve.json").write_text(json.dumps({"m_fric": {"status": "OK", "wall_s": 1000.0}}))
(d / "SOLVED").write_text("x")
ok("post fric_only -> DONE", J.post(jid) == "DONE")
res = json.loads((d / "result.json").read_text())
ok("post used m_fric for all four readers", sorted(calls) == sorted([("mm", "m_fric"), ("cs", "m_fric"), ("cl", "m_fric"), ("old", "m_fric")]), str(calls))
ok("result: fric_only True, no vm_p99 / sed keys", res.get("fric_only") is True and not any(k in res for k in ("vm_p99", "sed_gruen7", "f2_g7_loss_pct")))
ok("result: intact_job / intact_substituted_h None", res["intact_job"] is None and res["intact_substituted_h"] is None)
ok("result: templating / n_tet / bone_loss / h_cut_mm", res["templating"] == prep["templating"] and res["n_tet"] == prep["n_tet"]
   and res["bone_loss"] == prep["bone_loss"] and res["h_cut_mm"] == 25.25)
ok("result: f1_cslip_p95_um / frac_open / model / f1_p95_um", res["f1_cslip_p95_um"] == 9.9 and res["frac_open"] == 0.1 and res["model"] == "m1" and res["f1_p95_um"] == 12.3)
ok("m_fric.inp removed after post", not (d / "m_fric.inp").exists())
line = json.loads((J.RESULTS / "runs_v2a.jsonl").read_text().strip().splitlines()[-1])
ok("runs_v2a.jsonl variant.fric_only True", line["variant"]["fric_only"] is True and line["job_id"] == jid)

# ---------------------------------------------------------------- 3. regression: bonded path
J.intact_ref = lambda h, E=None: {"gruen7": 1.0, "gruen1": 1.0, "intact_job": "ref_fake", "intact_substituted_h": None}
J.explicit_ref = lambda spec: None
PM1.evaluate = lambda dd, name, fm, ref: {"f1_p95_um": 11.0, "vm_p99": 100.0, "model": "m1", "_ref": ref["intact_job"]}
d4 = J.QROOT / j4
(d4 / "solve.json").write_text(json.dumps({"m_fric": {"status": "OK"}, "m_bond": {"status": "OK"}}))
(d4 / "SOLVED").write_text("x")
ok("post bonded -> DONE via intact_ref + evaluate", J.post(j4) == "DONE" and json.loads((d4 / "result.json").read_text())["intact_job"] == "ref_fake")

# ---------------------------------------------------------------- 4. stability on the fric_only dir (synthetic pairs / U)
import stability as ST  # noqa: E402
import post_m1 as PM  # noqa: E402
n = 8
rng = np.random.default_rng(0)
nodes = rng.normal(size=(2 * n, 3)) * 10
PM.pairs = lambda dd: {"pair_bone": np.arange(1, n + 1), "pair_stem": np.arange(n + 1, 2 * n + 1), "pair_normal": np.tile([0.0, 0.0, 1.0], (n, 1)),
                       "pair_area": np.ones(n), "pair_interf": np.zeros(n), "pair_cortex": np.zeros(n, bool), "n": 2 * n, "nodes": nodes,
                       "node_labels": np.arange(1, 2 * n + 1), "pair_collar": np.zeros(n, bool)}
(d / "m_fric_csv").mkdir()
for s in ST.STEPS:
    (d / "m_fric_csv" / f"{s}_U.csv").write_text("node,u1,u2,u3\n")
read = []
PM._utab = lambda path, nn: read.append(path.name) or (rng.normal(size=(nn + 1, 3)) * 1e-3)
out = ST.stability(d)
ok("stability on fric_only dir: rotation / contact keys", all(k in out for k in ("rot_first_deg", "rot_axial_first_deg", "contact_area_load2_mm2", "subsid_first_um")))
ok("stability read only m_fric_csv U tables", sorted(set(read)) == sorted(f"{s}_U.csv" for s in ST.STEPS), str(sorted(set(read))))

bad = [k for k, v in checks if not v]
print(f"\n{len(checks) - len(bad)}/{len(checks)} checks passed" + (f"; FAILED: {bad}" if bad else ""))
sys.exit(1 if bad else 0)
