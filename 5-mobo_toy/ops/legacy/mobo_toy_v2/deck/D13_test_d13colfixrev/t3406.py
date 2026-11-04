"""Review (d13colfixrev): load_eff / job_info / mesh_check / applied_load on phase 13/14 (sawbone3406) jobs incl. the two fallback-mesh records."""
import importlib.util, json, pathlib, sys
sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("collector_rev3", HERE / "deck_D13_collect.py")
C = importlib.util.module_from_spec(spec); spec.loader.exec_module(C)
for j in ("sb14_a24_4dd6e4a2", "sb14_a18_d3f4733f", "sb13_init_ce80becf"):
    i = C.job_info(j)
    r = {k: i.get(k) for k in ("state", "mesh_h", "mesh_algo", "mesh_sec_pts", "mesh_n_prev_err", "load_N_mag", "load_alpha_front_deg", "load_alpha_sagit_deg", "load_torque")}
    r["mesh_check"] = C.mesh_check(i)
    r.update(C.load_eff(j))
    print(j, json.dumps(r, default=str))
print("WARN", C.WARN)
