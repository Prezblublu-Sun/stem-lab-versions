"""Run with the repo venv: PYTHONUTF8=1 .venv-mobo/Scripts/python.exe v2/tests/test_al3m.py
Local only, synthetic rows; no FE, no Linux. AL-3' (stage_al round al3m, al_local --m-min, stage_db batch b7m): the m limit applies only to the new round.
The full selection needs the Linux candidate files and is checked by stage_al select al3m --dry there.
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
ok("u_of_m: 0.5 -> 0, 2.0 -> 1, 1.0 -> 1/3", abs(AL.u_of_m(0.5)) < 1e-12 and abs(AL.u_of_m(2.0) - 1) < 1e-12 and abs(AL.u_of_m(1.0) - 1 / 3) < 1e-12)
ok("U_M is the m column", AL.U_COLS[AL.U_M] == "u_m")
ok("older rounds have no m_min", all("m_min" not in AL.ROUNDS[r] for r in ("al1", "al2", "al3")))
a3, am = AL.ROUNDS["al3"], AL.ROUNDS["al3m"]
ok("al3m = al3 except sources and m_min", am["m_min"] == 1.0 and am["sources"] == ("pool65k", "cr4096", "loc_al3m")
   and all(am[k] == a3[k] for k in ("plan", "n_global", "n_random", "unc", "p_floor", "overflow", "after", "random_sources")))
ok("loc_al3m is a registered local source, distinct files", set(AL.LOCAL_SOURCES) >= {"loc_al3", "loc_al3m"}
   and not set(AL.LOCAL_SOURCES["loc_al3"].values()) & set(AL.LOCAL_SOURCES["loc_al3m"].values()))
ok("b7m batch and layers", "b7m" in DB.BATCHES and DB.AL_BATCHES["b7m"] == ("al3m", "AL-3m", "AL3M") and DB.AL_BATCHES["b7"] == ("al3", "AL-3", "AL3")
   and DB.LAYER_SOURCE["AL-3m"] == "al_adaptive" and DB.LAYER_SOURCE["AL-3m rand"] == "al_random" and DB.LAYER_SELECTION["AL-3m"] == "adaptive"
   and DB.LAYER_SELECTION["AL-3m rand"] == "iid" and all(L in DB.SLOW_START_LAYERS and L in DB.B2_LAYERS for L in ("AL-3m", "AL-3m sts", "AL-3m rand")))


def row(i, m, rot, contact, bone, cond=None, forced=None):
    u = [0.5] * 13
    u[AL.U_M] = AL.u_of_m(m)
    u[0] = 0.1 + 0.01 * i                                # distinct designs
    return {"job_id": f"j{i}", "design_key": f"d{i}", "u13": u, "tpl6": [0.0] * 6, "cond": cond or dict(AL.BASE), "y": [np.log10(rot), np.log10(contact), 0.0],
            "bone": bone, "forced_e": forced, "in_E": False, "source": "x"}


rows = [row(0, 0.5, 0.03, 2300, 4900), row(1, 0.5, 0.05, 2000, 7900), row(2, 1.0, 0.06, 2100, 8300), row(3, 1.5, 0.20, 1500, 7300),
        row(4, 1.2, 0.40, 1200, 4800), row(5, 0.75, 0.04, 2200, 8700), row(6, 1.1, 0.08, 2400, 9900)]
c0 = LOC.centers(copy.deepcopy(rows))
c1 = LOC.centers(copy.deepcopy(rows), 1.0)
ok("al_local without --m-min picks the m 0.5 best as before", "j0" in {c["job_id"] for c in c0})
um = AL.u_of_m(1.0)
ok("al_local --m-min: every center has m >= 1.0", c1 and all(c["u13"][AL.U_M] >= um - 1e-12 for c in c1), [c["job_id"] for c in c1])
ok("al_local --m-min: the m >= 1.0 bests are centers", {"j2", "j3", "j4", "j6"} >= {c["job_id"] for c in c1} and "j2" in {c["job_id"] for c in c1})
edge = np.asarray(next(c for c in c1 if c["job_id"] == "j2")["u13"])      # exactly m 1.0, so about half of the free directions go below it
P0 = LOC.perturb(edge, 50, 123)
P1 = LOC.perturb(edge, 50, 123, um)
ok("perturb without the limit is unchanged in shape and can go below m 1.0", P0.shape == (50, 13) and (P0[:, AL.U_M] < um).any())
ok("perturb with the limit stays at m >= 1.0, in the cube", P1.shape == (50, 13) and (P1[:, AL.U_M] >= um).all() and (P1 >= 0).all() and (P1 <= 1).all())

n_fail = sum(not c for _, c in checks)
print(f"\n{len(checks) - n_fail} / {len(checks)} passed, {n_fail} failed")
sys.exit(1 if n_fail else 0)
