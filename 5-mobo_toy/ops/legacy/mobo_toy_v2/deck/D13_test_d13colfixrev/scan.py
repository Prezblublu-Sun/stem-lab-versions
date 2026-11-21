"""Review (d13colfixrev): read-only scan of queue/*/prep.json + spec.json for DONE jobs whose mesh is not the first attempt,
torque False jobs, cfg.load jobs, and check the collector's load_N inversion against the effective load on a sample. Writes nothing
(prints only)."""
import json
import math
import pathlib
import sys

sys.dont_write_bytecode = True
HOME = pathlib.Path.home() / "mobo_toy_v2"
Q = HOME / "queue"
fallback, torque_false, cfgload, n = [], [], [], 0
for d in sorted(Q.iterdir()):
    if not (d / "result.json").exists() or not (d / "prep.json").exists():
        continue
    try:
        prep = json.loads((d / "prep.json").read_text())
        sp = json.loads((d / "spec.json").read_text())
    except Exception as e:  # noqa: BLE001
        print("UNREADABLE", d.name, e)
        continue
    n += 1
    ma = prep.get("mesh_attempt") or {}
    h_exp = sp.get("h_int") if sp.get("h_int") is not None else 2.0
    a = (ma.get("h_int"), ma.get("algorithm3d"), ma.get("section_points"))
    if a[0] is not None and (not math.isclose(a[0], h_exp) or a[1] != 1 or a[2] != 40):
        fallback.append((d.name, sp.get("femur_id"), sp.get("model"), sp.get("h_int"), a, len(ma.get("previous_errors") or []),
                         (d / "m_fric_csv").is_dir(), (d / "m_bond_csv").is_dir()))
    if prep.get("torque") is False or sp.get("torque") is False:
        torque_false.append((d.name, sp.get("femur_id"), prep.get("torque"), prep.get("load_N")))
    cfg = sp.get("cfg")
    if isinstance(cfg, dict) and cfg.get("load") is not None:
        cfgload.append((d.name, sp.get("femur_id"), json.dumps(cfg.get("load")), prep.get("load_N")))
print("DONE jobs with prep.json:", n)
print("mesh not first attempt:", len(fallback))
for x in fallback:
    print("  FB", x)
print("torque False:", len(torque_false))
for x in torque_false[:15]:
    print("  TF", x)
print("cfg.load jobs:", len(cfgload))
for x in cfgload[:40]:
    print("  CL", x)
