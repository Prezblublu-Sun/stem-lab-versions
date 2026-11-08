"""b33: pick the R2 rows to confirm, by the rule written in proposal.md. Read only on db3406 v0.13; writes data/picks.json.

    PYTHONUTF8=1 ../../.venv-mobo/Scripts/python.exe pick.py

Rule: among the R2 rows that are better than 3b (b31's G49 definition, against the A family curve, 3b at +9.68 mm / -0.0738 dex), the margin of a
route = min(F margin / 0.6 mm, micromotion margin / 0.029 dex) (F re-mesh sd; largest micromotion re-mesh difference); a row's margin = the larger of
its two routes. Sort by margin, keep rows whose design (u13) is not already kept, take the first 3.
"""
import ast
import importlib.util
import json
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "v2"))
import stage_db as DB  # noqa: E402

V13 = pathlib.Path(r"H:/projects/Femoral implant generation/db3406/v0.13")
SD_F, SD_L, N_PICK = 0.6, 0.029, 3
s = importlib.util.spec_from_file_location("g31", ROOT / "experiments" / "b31_r2" / "gates.py")
g = importlib.util.module_from_spec(s)
s.loader.exec_module(g)
res = g.judge(str(V13))
rows = ast.literal_eval(res["G49"]["note"].split("逐行 ", 1)[1].split("；不可判", 1)[0])       # the gate's own per-row table (a dict literal)
u = {x[0]: tuple(x[4]) for x in DB.R2_ROWS}
cand = []
for lab, t in rows.items():
    if not t["better_than_3b"]:
        continue
    dF, dl = t["dF_mm"], t["dlog_f1"]
    r1 = min((dF - (g.DF3 + g.IMP_F)) / SD_F, ((g.DL3 + g.IMP_L) - dl) / SD_L)
    r2 = min(((g.DL3 - g.IMP_L2) - dl) / SD_L, (dF - (g.DF3 - g.IMP_F2)) / SD_F)
    cand.append((max(r1, r2), lab, dF, dl, t["bone"]))
cand.sort(reverse=True)
picks, seen = [], set()
for m, lab, dF, dl, bone in cand:
    if u[lab] in seen:
        continue
    seen.add(u[lab])
    picks.append(lab)
    if len(picks) == N_PICK:
        break
out = {"rule": __doc__.split("Rule: ", 1)[1].strip(), "db": "v0.13", "candidates": [{"label": lab, "margin": round(m, 2), "dF_mm": dF, "dlog_f1": dl, "bone_cm3": bone,
       "twin_of_a_pick": u[lab] in {u[p] for p in picks} and lab not in picks} for m, lab, dF, dl, bone in cand], "picks": picks}
(HERE / "data").mkdir(exist_ok=True)
(HERE / "data" / "picks.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
for c in out["candidates"]:
    print(c)
print("picks", picks, "stage_db.R2C_WINNERS", DB.R2C_WINNERS, "same" if tuple(picks) == tuple(DB.R2C_WINNERS) else "DIFFERENT")
sys.exit(0 if tuple(picks) == tuple(DB.R2C_WINNERS) else 1)
