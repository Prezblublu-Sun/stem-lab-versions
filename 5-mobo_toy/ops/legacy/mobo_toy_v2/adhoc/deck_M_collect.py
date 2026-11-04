"""批 MI / M / M14（方法闸门，2026-10-23）的结果汇总，在 Linux 上运行（只读队列）：
对 RS6 源作业和每个变体作业读 result.json（f1、vM、SED、n_tet、参照）、prep.json（模板化 α/e/A0、实际网格 h）、solve.json（墙钟）、
并用 stability.py 重算转动 / 接触 / 下沉。输出 ~/mobo_toy_v2/deck/M/deck_M_rows.csv。
    ~/mobo_toy_v2/run.sh adhoc/deck_M_collect.py
"""
from __future__ import annotations

import csv
import json
import pathlib
import sys

HOME = pathlib.Path.home() / "mobo_toy_v2"
Q, RES, OUT = HOME / "queue", HOME / "results", HOME / "deck" / "M"
sys.path.insert(0, str(HOME / "code" / "v2"))
sys.path.insert(0, str(HOME / "code"))
import stability as S  # noqa: E402

RS6 = {"a69": "neck10_a69_e394e85c", "a24": "neck10_a24_41b88dd9", "a12": "neck10_a12_b1fbfd1c", "e2a": "neck9_init_e2a68dea",
       "a36": "neck10_a36_0911f520", "a19": "neck10_a19_c15fe9c6"}
ARM = {"mg_remesh": "A3", "mg_slip": "C3slip", "mg_coarse": "C3coarse", "mg_fine": "C3fine"}


def row_of(job: str, code: str, arm: str) -> dict:
    d = Q / job
    st = "DONE" if (d / "DONE").exists() else ("FAILED" if (d / "FAILED.json").exists() else "pending")
    r = {"job": job, "code": code, "arm": arm, "state": st}
    if st != "DONE":
        if st == "FAILED":
            fl = json.loads((d / "FAILED.json").read_text())
            r["fail"] = f"{fl.get('level')}: {(fl.get('reason') or '')[:160]}"
        return r
    res = json.loads((d / "result.json").read_text())
    prep = json.loads((d / "prep.json").read_text())
    spec = json.loads((d / "spec.json").read_text())
    t = prep.get("templating") or {}
    ma = prep.get("mesh_attempt") or {}
    nt = prep.get("n_tet") or {}
    sol = json.loads((d / "solve.json").read_text()) if (d / "solve.json").exists() else {}
    wall = {}
    for u, v in (sol.get("units") or sol or {}).items() if isinstance(sol, dict) else []:
        if isinstance(v, dict) and "wall_s" in v:
            wall[u] = v["wall_s"]
    stab = S.stability(d)
    # 阶段 10 用的股骨距口径（stage_neckopt._calcar）：固定解剖区 G7、只算皮质、各自的完整股骨参照
    try:
        import numpy as np
        import resorption as RS
        rows_, _ = RS.design_rows(job, iname=res.get("intact_job"))
        g7 = next((x for x in rows_ if x["scheme"] == "fixed" and x["zone"] == "G7" and x["tissue"] == "cortex"), {})
        v3 = {k: (None if g7.get(k) is None or not np.isfinite(g7[k]) else float(g7[k])) for k in ("ssi_pct", "sed_chg_pct")}
    except Exception as e:                                            # noqa: BLE001
        v3 = {"ssi_pct": None, "sed_chg_pct": None, "calcar_err": f"{type(e).__name__}: {str(e)[:120]}"}
    r.update(v3)
    r.update({"h_int": spec.get("h_int"), "slip_tol": spec.get("slip_tol"), "mesh_h": ma.get("h_int"), "mesh_attempt": ma.get("attempt"),
              "tpl_alpha": t.get("alpha"), "tpl_e": t.get("e"), "tpl_A0": t.get("A0"),
              "n_tet": sum(int(v) for v in nt.values()) if nt else None, "n_pairs": prep.get("n_pairs"),
              "f1_p95_um": res.get("f1_p95_um"), "f1_first_p95_um": res.get("f1_first_p95_um"), "vm_p99": res.get("vm_p99"),
              "sed_g7_pct": res.get("f2_g7_loss_pct"), "intact_job": res.get("intact_job"),
              "fric_wall_s": wall.get("m_fric"), "bond_wall_s": wall.get("m_bond"), "solve_raw": json.dumps(sol)[:300] if not wall else "",
              "rot_first_deg": stab.get("rot_first_deg"), "rot_axial_first_deg": stab.get("rot_axial_first_deg"),
              "rot_tilt_first_deg": stab.get("rot_tilt_first_deg"), "rot_perm_deg": stab.get("rot_perm_deg"),
              "subsid_first_um": stab.get("subsid_first_um"), "contact_area_load2_mm2": stab.get("contact_area_load2_mm2"),
              "contact_frac_load2": stab.get("contact_frac_load2"), "rigid_fit_rms_first": stab.get("rigid_fit_rms_first")})
    return r


def main():
    rows = [row_of(j, c, "source") for c, j in RS6.items()]
    for batch in ("MI", "M", "M14"):
        f = RES / f"deck_{batch}_ids.json"
        if not f.exists():
            continue
        for key, job in json.loads(f.read_text())["jobs"].items():
            if batch == "MI":
                d = Q / job
                rows.append({"job": job, "code": key, "arm": "intact", "state": "DONE" if (d / "DONE").exists() else "pending"})
                continue
            code = key.split("_")[-1] if batch == "M14" else key.split("_")[2]
            rows.append(row_of(job, code, ARM[job.split("_")[0] + "_" + job.split("_")[1]]))
    OUT.mkdir(parents=True, exist_ok=True)
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(OUT / "deck_M_rows.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    print(len(rows), "rows ->", OUT / "deck_M_rows.csv")
    for r in rows:
        print(f"{r['arm']:9s} {r['code']:5s} {r['state']:7s}", r.get("fail", ""), "" if r["state"] != "DONE" or r["arm"] == "intact" else
              f"rot {r['rot_first_deg']:.4f} area {r['contact_area_load2_mm2']:.0f} f1 {r['f1_p95_um']:.2f} sedv3 {r.get('sed_chg_pct')} "
              f"sedg7 {r['sed_g7_pct']:.1f} h {r['mesh_h']} wall {r['fric_wall_s']} {r.get('calcar_err', '')}")


if __name__ == "__main__":
    main()
