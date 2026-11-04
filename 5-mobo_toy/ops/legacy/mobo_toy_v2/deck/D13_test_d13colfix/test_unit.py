"""d13colfix unit checks: design_match None cases, load helpers, min_gap, and the row_err path (d13_row patched to raise for one key).
Run from ~/mobo_toy_v2 under sandbox_run.py; writes only outU/ in this folder."""
import importlib.util
import json
import pathlib
import sys

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("collector_fix", HERE / "deck_D13_collect.py")
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)

res = {}
D = {"a": 1.0, "b": "x"}
res["dm_design_None"] = C.design_match({"design": None, "h_cut": 25.0}, {"design": D, "h_cut": 25.0})
res["dm_design_missing"] = C.design_match({"h_cut": 25.0}, {"design": D, "h_cut": 25.0})
res["dm_hcut_null"] = C.design_match({"design": D, "h_cut": None}, {"design": D, "h_cut": 25.0})
res["dm_hcut_str"] = C.design_match({"design": D, "h_cut": "abc"}, {"design": D, "h_cut": 25.0})
res["dm_same"] = C.design_match({"design": D, "h_cut": 25.0}, {"design": dict(D), "h_cut": 25.0})
res["dm_diff_value"] = C.design_cmp({"design": D, "h_cut": 25.0}, {"design": {"a": 2.0, "b": "x"}, "h_cut": 25.0})
res["dm_diff_hcut"] = C.design_cmp({"design": D, "h_cut": 25.0}, {"design": D, "h_cut": 16.0})
res["load_of_cfg_str"] = C._load_of({"cfg": "abc"})
res["load_of_load_list"] = C._load_of({"cfg": {"load": [1, 2]}})
res["applied_stair"] = C.applied_load({"load_N": [-782.1262347740976, 698.2115423007943, -2148.874169204898], "torque": True})
res["applied_none"] = C.applied_load({"load_N": None})
res["applied_up"] = C.applied_load({"load_N": [0.0, 0.0, 10.0]})
res["min_gap"] = C.min_gap([0.0100, 0.0102, 0.0200])
res["mesh_check_fallback"] = C.mesh_check({"state": "DONE", "spec_h_int": 2.0, "mesh_h": 1.94, "mesh_algo": 1, "mesh_sec_pts": 40,
                                           "mesh_n_prev_err": 2, "mesh_prev_err": "algo 1 ... || algo 10 ..."})
res["mesh_check_default_h"] = C.mesh_check({"state": "DONE", "spec_h_int": None, "mesh_h": 2.0, "mesh_algo": 1, "mesh_sec_pts": 40})
res["tpl_missing"] = C.tpl_cmp({"state": "DONE", "src_state": "DONE", "tpl_A0": 1.0, "src_tpl_A0": 1.0})

orig = C.d13_row


def boom(key, *a, **k):
    if key == "D13_bond_sb14_a24_4dd6e4a2":
        raise TypeError("injected test failure (d13colfix unit test)")
    return orig(key, *a, **k)


C.d13_row = boom
sys.argv = ["deck_D13_collect.py", "--ids", str(HERE / "ids_unit.json"), "--out", str(HERE / "outU"), "--no-fronts",
            "--stage-deck", str(HERE / "stage_deck_repo.py")]
C.main()
import argparse  # noqa: E402
fr = {"err": "synthetic (unit test)", "mesh": [{"job_id": "SRC_A", "fronts": ["F13", "P3"]}, {"job_id": "SRC_B", "fronts": ["P3"]}],
      "sts": [{"job_id": "S1", "role": "a"}, {"job_id": "S2", "role": "b"}]}
syn = [{"group": "D13_mesh", "key": "D13_mesh_h1.94_SRC_A", "job": "m1", "source_job": "SRC_A", "label": "1.94", "state": "DONE", "pct_rot_first_deg": 3.0},
       {"group": "D13_mesh", "key": "D13_mesh_h1.94_SRC_B", "job": "m2", "source_job": "SRC_B", "label": "1.94", "state": "DONE", "pct_rot_first_deg": -4.5},
       {"group": "D13_sts", "key": "D13_sts_F1714_S1", "job": "s1", "source_job": "S1", "label": "F1714", "state": "DONE",
        "rot_first_deg": 0.0100, "src_rot_first_deg": 0.0200, "load_check": "ok", "src_load_check": "ok"},
       {"group": "D13_sts", "key": "D13_sts_F1714_S2", "job": "s2", "source_job": "S2", "label": "F1714", "state": "pending",
        "queue_state": "READY", "load_check": "ok (spec only: job not DONE)", "src_load_check": "ok"},
       {"group": "D13_sts", "key": "D13_sts_F1714_S3", "job": "s3", "source_job": "S3", "label": "F1714", "state": "DONE",
        "rot_first_deg": 0.0102, "src_rot_first_deg": 0.0210, "load_check": "ok", "src_load_check": "ok"}]
md = C.md_tables(syn, fr, {}, argparse.Namespace(ids="synthetic", out="synthetic"),
                 {"generated": "-", "ids_updated": "-", "code_version": "-", "state13": "-", "state14": "-", "fields_not_found": []})
res["md_role_second"] = "| D13_mesh_h1.94_SRC_B | 转动第二 |" in md
res["md_role_first"] = "| D13_mesh_h1.94_SRC_A | 转动最小 |" in md
res["md_within_noise"] = "within mesh noise" in md
res["md_pending_check"] = "作业 只核对了 spec；源 ok" in md
res["md_rank_line"] = [ln for ln in md.splitlines() if ln.startswith("F1714：")]
print("UNIT RESULTS")
print(json.dumps(res, indent=1, default=str))
