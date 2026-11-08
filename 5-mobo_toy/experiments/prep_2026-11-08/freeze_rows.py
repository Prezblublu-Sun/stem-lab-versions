"""Freeze the rows of b29 (RS-1), b30 (OF-1) and b31 (R2) for v2/stage_db.py: (label, entry offset, size mm2, bone mm3, u13). Local, read only.

    python -X utf8 freeze_rows.py      writes data/stage_db_rows.txt (paste into stage_db.py) and data/of1_rows.json
"""
import json
import pathlib

import numpy as np

D = pathlib.Path(__file__).resolve().parent / "data"
out = []
rs = json.load(open(D / "rs1_rows.json", encoding="utf-8"))
out.append("RS1_ROWS = (" + ",\n            ".join(f"({r['label']!r}, {r['e']!r}, {round(r['A0'], 3)!r}, {round(r['bone_mm3'], 2)!r}, ({', '.join(repr(float(v)) for v in r['u13'])}))" for r in rs) + ")")
g = np.load(D / "geom_of1.npz")
lab = json.load(open(D / "of1_labels.json", encoding="utf-8"))
of = []
for i, l in enumerate(lab):
    if l.startswith("h_cut") or not g["ok"][i]:
        continue
    of.append({"label": l, "e": float(g["e"][i]), "A0": float(g["A0"][i]), "bone_mm3": float(g["bone"][i]), "u13": g["u13"][i].tolist(), "fast_F": float(g["F"][i])})
json.dump(of, open(D / "of1_rows.json", "w", encoding="utf-8"), indent=1)
of += [r for r in json.load(open(D / "of1_back.json", encoding="utf-8")) if r["feasible"]]      # 11-08 review 30-2: 3b with one factor set back, of1_back.py
out.append("OF1_ROWS = (" + ",\n            ".join(f"({r['label']!r}, {r['e']!r}, {round(r['A0'], 3)!r}, {round(r['bone_mm3'], 2)!r}, ({', '.join(repr(float(v)) for v in r['u13'])}))" for r in of) + ")")
r2 = json.load(open(D / "r2_rows.json", encoding="utf-8"))
out.append("R2_ROWS = (" + ",\n           ".join(f"({r['label']!r}, {r['e']!r}, {round(r['A0'], 3)!r}, {round(r['bone_mm3'], 2)!r}, ({', '.join(repr(float(v)) for v in r['u13'])}))" for r in r2) + ")")
(D / "stage_db_rows.txt").write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
print("RS1", len(rs), "OF1", len(of), "R2", len(r2))
