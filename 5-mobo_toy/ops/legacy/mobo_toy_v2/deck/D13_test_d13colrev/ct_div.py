"""Review (d13colrev): CT job with intact_job — collector's calcar (iname = spec intact_job) vs stage_neckopt._calcar (standard CT ref)."""
import json, pathlib, sys
sys.dont_write_bytecode = True
HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "code")); sys.path.insert(0, str(HOME / "code" / "v2"))
import resorption as RS, stage_neckopt as SN, jobs as J
job = "load_wrap_S1B_high_9f489c18"
spec = json.loads((J.QROOT / job / "spec.json").read_text())
def g7(iname):
    rows, _ = RS.design_rows(job, iname=iname)
    g = next(r for r in rows if r["scheme"] == "fixed" and r["zone"] == "G7" and r["tissue"] == "cortex")
    return g["ssi_pct"], g["sed_chg_pct"]
print("intact_job", spec.get("intact_job"), "femur_id", spec.get("femur_id"))
print("collector-style (iname=spec intact_job):", g7(spec.get("intact_job")))
print("stage_neckopt._calcar (CT -> standard ref):", SN._calcar(job))
