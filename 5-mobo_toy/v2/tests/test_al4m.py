"""Run with the repo venv: PYTHONUTF8=1 .venv-mobo/Scripts/python.exe v2/tests/test_al4m.py
Local only, synthetic rows; no FE, no Linux. AL-4m (stage_al round al4m, al_local --bands): the bands apply only to the new round.
The full selection needs the Linux candidate files and v0.7, and is checked by stage_al select al4m --dry there. The al3m replay on Linux checks that the older rounds did not move.
"""
import copy
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(r"H:/projects/Femoral implant generation/sandbox/mobo_toy")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "v2"))
import al_local as LOC  # noqa: E402
import jobs as J  # noqa: E402
import stage_al as AL  # noqa: E402
import stage_db as DB  # noqa: E402

checks = []


def ok(name, cond, extra=""):
    checks.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""), flush=True)


ok("code_hash unchanged", J.code_hash() == DB.DB_CODE_HASH)
a3m, a4 = AL.ROUNDS["al3m"], AL.ROUNDS["al4m"]
ok("al4m: three bands of 4, 12 picks in all", a4["plan"] == (("band", (6000.0, 6500.0), 4), ("band", (6500.0, 7000.0), 4), ("band", (7000.0, 7400.0), 4)))
ok("al4m: no global and no random rows, nothing fills the global group", a4["n_global"] == 0 and a4["n_random"] == 0 and a4["no_global_fill"] is True)
ok("al4m: overflow only to the next bands", a4["overflow"] == ("band7000", "band7400"))
ok("al4m: m_min, p_floor, uncertainty as al3m", a4["m_min"] == a3m["m_min"] == 1.0 and a4["p_floor"] == a3m["p_floor"] and a4["unc"] == a3m["unc"])
ok("al4m: the export must contain al1, al2 and al3m", a4["after"] == ("al1", "al2", "al3m"))
ok("al4m: its own local source, distinct files", a4["sources"] == ("pool65k", "cr4096", "loc_al4m") and "loc_al4m" in AL.LOCAL_SOURCES
   and not set(AL.LOCAL_SOURCES["loc_al4m"].values()) & (set(AL.LOCAL_SOURCES["loc_al3m"].values()) | set(AL.LOCAL_SOURCES["loc_al3"].values())))
ok("older rounds have no band and no no_global_fill", all(p != "band" for r in ("al1", "al2", "al3", "al3m") for p, _, _ in AL.ROUNDS[r]["plan"]) and all("no_global_fill" not in AL.ROUNDS[r] for r in ("al1", "al2", "al3", "al3m")))
ok("al3m plan unchanged", a3m["plan"] == (("robust", None, 2), ("cap", 5000.0, 2), ("cap", 6000.0, 6), ("cap", 8000.0, 2), ("cap", 10000.0, 2), ("baseline", None, 5)))

bone = np.array([5900.0, 6000.0, 6100.0, 6500.0, 6500.1, 7000.0])
mean = np.log10(np.array([0.30, 0.30, 0.30, 0.30, 0.30, 0.10]))
sd = np.full(6, 0.02)
best = float(np.log10(0.273))
p, ei = AL.band_problem(bone, mean, sd, best, 6000.0, 6500.0)
inside = np.array([False, False, True, True, False, False])
ok("band_problem: lower bound open, upper bound closed", (p[inside] > 0).all() and (p[~inside] == 0).all() and (ei[inside] > 0).all() and (ei[~inside] == 0).all(), p.round(4).tolist())
t = best - AL.EPS_DEX
ok("band_problem: inside the band it equals the cap score", np.allclose(p[inside], AL.phi((t - mean[inside]) / sd[inside])) and np.allclose(ei[inside], AL.expected_improvement(mean[inside], sd[inside], t)))
p0, e0 = AL.band_problem(bone, mean, sd, None, 6000.0, 6500.0)
ok("band_problem: no FE best means no score", (p0 == 0).all() and (e0 == 0).all())
ok("band_problem: a better candidate has the larger P", AL.band_problem(np.array([6200.0, 6200.0]), np.log10(np.array([0.2, 0.3])), np.array([0.02, 0.02]), best, 6000.0, 6500.0)[0].tolist() == sorted(AL.band_problem(np.array([6200.0, 6200.0]), np.log10(np.array([0.2, 0.3])), np.array([0.02, 0.02]), best, 6000.0, 6500.0)[0].tolist(), reverse=True))


def row(i, m, rot, contact, bone_, cond=None, forced=None):
    u = [0.5] * 13
    u[AL.U_M] = AL.u_of_m(m)
    u[0] = 0.1 + 0.01 * i
    return {"job_id": f"j{i}", "design_key": f"d{i}", "u13": u, "tpl6": [0.0] * 6, "cond": cond or dict(AL.BASE), "y": [np.log10(rot), np.log10(contact), 0.0],
            "bone": bone_, "forced_e": forced, "in_E": False, "source": "x"}


rows = [row(0, 1.06, 0.273, 1700, 5650), row(1, 1.5, 0.276, 1700, 6730), row(2, 1.5, 0.105, 1900, 7380), row(3, 1.75, 0.14, 1800, 6920), row(4, 1.2, 1.46, 700, 6430),
        row(5, 0.5, 0.05, 2300, 6600), row(6, 1.03, 0.067, 2100, 7910), row(7, 1.0, 0.059, 2150, 8300), row(8, 1.4, 0.40, 1200, 6300, forced=-2.0), row(9, 1.3, 0.2, 1500, 7100, cond=dict(AL.STS)),
        row(10, 1.09, 0.095, 2000, 7760), row(11, 1.3, 0.33, 1500, 5740), row(12, 1.1, 0.5, 1200, 7050), row(13, 1.6, 0.6, 1100, 7300)]
B = [(5500.0, 6000.0), (6000.0, 6500.0), (6500.0, 7000.0), (7000.0, 7400.0), (7400.0, 8000.0)]
cs = LOC.centers(copy.deepcopy(rows), 1.0, B)
ids = {c["job_id"] for c in cs}
ok("al_local --bands: the best of each band are centers", {"j0", "j11", "j1", "j3", "j2", "j6", "j10"} <= ids, sorted(ids))
ok("al_local --bands: above 1 deg is not a center", "j4" not in ids)
ok("al_local --bands: m below the limit is not a center", "j5" not in ids)
ok("al_local --bands: a forced offset or another load is not a center", not {"j8", "j9"} & ids)
ok("al_local --bands: outside the bands is not a center", "j7" not in ids)
ok("al_local --bands: at most N_CAP per band", all(sum(1 for c in cs for w in c["why"] if w.startswith(f"band{hi:g}#")) <= LOC.N_CAP for _, hi in B))
c0 = LOC.centers(copy.deepcopy(rows), 1.0)
ok("al_local without --bands still uses the caps", any(w.startswith("cap") for c in c0 for w in c["why"]) and not any(w.startswith("band") for c in c0 for w in c["why"]))

n_fail = sum(not c for _, c in checks)
print(f"\n{len(checks) - n_fail} / {len(checks)} passed, {n_fail} failed")
sys.exit(1 if n_fail else 0)
