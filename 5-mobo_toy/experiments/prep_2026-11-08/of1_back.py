"""OF-1 extra rows after the second-model review (30-2): 3b with one factor set back to the A m 1.0 value, at 3b's entry offset +1.5. Local, 0 FE, read only.

    PYTHONUTF8=1 ../../.venv-mobo/Scripts/python.exe of1_back.py      writes data/of1_back.json

3b_back_n_a    u3b with u_n_a = A's value      3b_back_tau_a  u3b with u_tau_a = A's value
Templating is the production one (stage_db.ws_templating, femur cache read only). First reproduces 3b's own size and bone from FAM1_ROWS.
No placement check: these rows explain a mechanism, they are not candidates.
"""
import json
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "v2"))
import stage_db as DB  # noqa: E402

U_COLS = ["u_L", "u_alpha", "u_h_cut", "u_m", "u_rho_tip", "u_q", "u_lam", "u_g_ml", "u_g_ap", "u_n_a", "u_n_p", "u_tau_a", "u_tau_p"]
inp = json.load(open(HERE / "data" / "inputs.json", encoding="utf-8"))
u3b, uAm1 = np.array(inp["u3b"]), np.array(inp["uAm1"])
fam = {x[0]: x for x in DB.FAM1_ROWS}
assert np.allclose(fam["3b"][4], u3b, rtol=0, atol=1e-12), "u3b differs from FAM1_ROWS"
ph = DB.b2_phase()


def tpl(u, e, tag):
    spec = DB._variant(DB._phys(ph.spec_of(np.asarray(u, float), tag, bonded=True), tag), "db_ws", tag, "fric", entry_offset=float(e))
    return DB.ws_templating(spec)


t3 = tpl(u3b, 1.5, "chk_3b")
print(f"3b reproduced: size {t3['A0_star']:.3f} vs {fam['3b'][2]}, bone {t3['bone_mm3']:.2f} vs {fam['3b'][3]}, feasible {t3['feasible']}")
assert t3["feasible"] and abs(t3["A0_star"] - fam["3b"][2]) <= 0.01 and abs(t3["bone_mm3"] - fam["3b"][3]) <= 0.5
out = []
for name in ("u_n_a", "u_tau_a"):
    i = U_COLS.index(name)
    u = u3b.copy()
    u[i] = uAm1[i]
    lab = f"3b_back_{name[2:]}"
    t = tpl(u, 1.5, lab)
    print(f"{lab}: {name} {u3b[i]:.4f} -> {u[i]:.4f}; feasible {t['feasible']} ({t['reason']}), e {t['e_star']:+g}, size {t['A0_star']:.3f}, bone {t['bone_mm3']:.1f}")
    out.append({"label": lab, "e": 1.5, "A0": t["A0_star"], "bone_mm3": t["bone_mm3"], "u13": u.tolist(), "feasible": t["feasible"], "reason": t["reason"],
                "factor": name, "from": float(u3b[i]), "to": float(u[i])})
json.dump(out, open(HERE / "data" / "of1_back.json", "w", encoding="utf-8"), indent=1)
