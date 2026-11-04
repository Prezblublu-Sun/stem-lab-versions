"""Review (d13colfix): build the real D13 keys exactly as the repo's stage_deck.py would (d13_select + _d13_specs on the current
state files, prior = {}), check that deck_D13_collect.KEY_RE parses each key to the spec's source_job / label, and write
ids_real.json (key -> expected job id; 3 keys remapped to their DONE source job to exercise DONE paths). Read-only on the queue."""
import importlib.util
import json
import math
import pathlib
import sys

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent
HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "code"))
sys.path.insert(0, str(HOME / "code" / "v2"))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


SD = load("stage_deck_fix", HERE / "stage_deck_repo.py")
C = load("collector_fix", HERE / "deck_D13_collect.py")
import jobs as J  # noqa: E402

st13 = json.loads((HOME / "results" / "neckopt_p13.json").read_text())
st14 = json.loads((HOME / "results" / "neckopt_p14.json").read_text())
sel = SD.d13_select(st13, st14, prior={})
specs = SD._d13_specs(sel)
bad, out, counts = [], {}, {}
for k, s in specs.items():
    jid = J.job_id({**s, "created": ""})
    m = None
    for g, rx in C.KEY_RE:
        m = rx.match(k)
        if m:
            break
    if not m:
        bad.append(f"{k}: no KEY_RE match")
        continue
    counts[g] = counts.get(g, 0) + 1
    src, lab = m["src"], m.groupdict().get("label")
    if src != s.get("source_job"):
        bad.append(f"{k}: parsed src {src} != spec source_job {s.get('source_job')}")
    if g == "bond" and not (s.get("bond_only") and s.get("intact_job")):
        bad.append(f"{k}: bond spec without bond_only/intact_job")
    if g == "sts" and not math.isclose(float(lab[1:]), float(s["cfg"]["load"]["resultant_N"])):
        bad.append(f"{k}: label {lab} vs resultant_N {s['cfg']['load']['resultant_N']}")
    if g == "mesh" and not math.isclose(float(lab), float(s["h_int"])):
        bad.append(f"{k}: label {lab} vs h_int {s['h_int']}")
    if g != {"d13bond": "bond", "d13sts": "sts", "d13mesh": "mesh"}[s["stage"]]:
        bad.append(f"{k}: parsed group {g} vs stage {s['stage']}")
    out[k] = jid
print("keys", len(specs), counts, "parse problems", len(bad))
for b in bad:
    print("  PARSE PROBLEM", b)
print("n_designs", sel["n_designs"], "covered", len(sel["covered"]), "bond", len(sel["bond"]), "left_out", len(sel["bond_left_out"]),
      "sts", [(e["role"], e["job_id"]) for e in sel["sts"]], "mesh", [e["job_id"] for e in sel["mesh"]])
# remap three keys to their (DONE) source job: a D13_bond key on a fric_only source (no m_bond_csv), one sts, one mesh
remap = {}
for g in ("bond", "sts", "mesh"):
    k = next(k for k in sorted(out) if k.startswith(f"D13_{g}_"))
    src = specs[k]["source_job"]
    remap[k] = src
    out[k] = src
print("remapped to source:", remap)
(HERE / "ids_real.json").write_text(json.dumps({"jobs": out, "updated": "review d13colfix", "note": "TEST ONLY (d13colfix)",
                                                "expected_left_out": sorted(e["job_id"] for e in sel["bond_left_out"]),
                                                "expected_bond": sorted(e["job_id"] for e in sel["bond"]),
                                                "expected_sts": [[e["role"], e["job_id"]] for e in sel["sts"]],
                                                "expected_mesh": [e["job_id"] for e in sel["mesh"]], "remapped": remap}, indent=1))
print("wrote", HERE / "ids_real.json")
