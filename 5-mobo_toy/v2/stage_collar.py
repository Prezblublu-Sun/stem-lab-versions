"""领与椭圆截面的求解验证（在 Linux 上跑；本机只求解）。用户 2026-10-02 要求加入“领的有无和尺寸、椭圆截面、带领的柄的接触”。
全部是“变体”作业（kind = variant），不进任何常规数据集。M1 界面模型，过盈 0.025 mm，生产网格与摩擦设置。

    python v2/stage_collar.py submit     登记作业，id 写 results/collar_ids.json
    python v2/stage_collar.py status
    python v2/stage_collar.py collect    → results/collar/summary.json

作业
    base_w0        基准设计无领：回归检查，应与改动前的同设置作业（m1_base_h2_tol0.00025_delta0.025_*）结果相同
    base_w2 / w4   基准设计加 2、4 mm 领：领的尺寸
    short_w3       25 mm 短柄加 3 mm 领：短柄最依赖压配，看领能否补上
    neck_w0 / w3   椭圆截面的颈部柄（L 30、λ 1.3、α 40°，接近只占股骨颈的设计），无领与 3 mm 领
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import geom3d as G  # noqa: E402
import jobs as J  # noqa: E402
import stage_m1 as M1S  # noqa: E402
import stage_v2a as S  # noqa: E402

IDS = J.RESULTS / "collar_ids.json"
OUT = J.RESULTS / "collar"
DELTA = 0.025
FR = {"slip_tol": 2.5e-4}
NECK = G.ellipse_design(30.0, 0.5, 1.0, 1.3, 40.0)
KEYS = ("f1_p95_um", "f1_first_p95_um", "f1_rev_p50_um", "area_frac_gt40", "area_frac_gt150", "open_frac_load2", "interface_area",
        "f1_all_p95_um", "f1_first_all_p95_um", "collar_area", "collar_n_pairs", "collar_slip_rev_p95_um", "collar_slip_first_p95_um",
        "collar_open_frac_load2", "collar_open_frac_unload", "collar_gap_p95_load2_um", "collar_force_share_load",
        "collar_force_share_load2", "collar_force_N_load2", "contact_force_total_N_load2", "cpress_release_p50",
        "status_frac_stick", "status_frac_slip", "vm_p99", "vm_max", "f2_g7_loss_pct")


def cases() -> dict:
    base = M1S.core_of(None)
    short = M1S.core_of(M1S.NAMED["short"])
    neck = {**base, "design": dict(NECK)}
    out = {}
    for name, core, w in (("base_w0", base, 0.0), ("base_w2", base, 2.0), ("base_w4", base, 4.0), ("short_w3", short, 3.0),
                          ("neck_w0", neck, 0.0), ("neck_w3", neck, 3.0)):
        dsg = dict(core["design"])
        if w > 0:
            dsg.update(collar_w=w, collar_t=G.COLLAR_T)
        out[name] = {**{k: v for k, v in core.items() if k != "kind"}, "design": dsg, "kind": "variant", "stage": "collar",
                     "h_int": 2.0, "model": "m1", **FR, "delta": DELTA, "tag": name}
    return out


def submit() -> dict:
    ids = {k: J.submit(v) for k, v in cases().items()}
    rec = {"jobs": ids, "created": time.strftime("%Y-%m-%d %H:%M:%S"), "code": J.code_hash()}
    J.RESULTS.mkdir(parents=True, exist_ok=True)
    IDS.write_text(json.dumps(rec, indent=1))
    print(json.dumps(rec, indent=1), flush=True)
    return rec


def status() -> dict:
    ids = json.loads(IDS.read_text())["jobs"]
    st = {}
    for k, j in ids.items():
        s = J.state(J.QROOT / j)
        st.setdefault(s, []).append(k)
        if s == "FAILED":
            f = json.loads((J.QROOT / j / "FAILED.json").read_text())
            print("FAILED", k, j, f.get("level"), f.get("stage"), (f.get("reason") or "")[:300].replace("\n", " | "), flush=True)
    print(json.dumps({k: len(v) for k, v in st.items()}), flush=True)
    for k, v in st.items():
        print(k, v, flush=True)
    return st


def collect() -> dict:
    import resorption as RS
    OUT.mkdir(parents=True, exist_ok=True)
    ids = json.loads(IDS.read_text())["jobs"]
    RS._init()
    out = {"jobs": {}, "missing": []}
    for k, j in ids.items():
        if J.state(J.QROOT / j) != "DONE":
            out["missing"].append(k)
            continue
        r = J.result(j)
        prep = json.loads((J.QROOT / j / "prep.json").read_text())
        rows, srow = RS.design_rows(j)
        zones = {f"{x['scheme']}:{x['zone']}": {kk: x.get(kk) for kk in ("ssi_pct", "res_0.6")} for x in rows
                 if x["tissue"] == "cortex" and x["zone"] in ("G1", "G7", "total")}
        out["jobs"][k] = {"job_id": j, **{kk: r.get(kk) for kk in KEYS}, "templating": r.get("templating"),
                          "collar": {kk: v for kk, v in (prep.get("collar") or {}).items() if kk != "outline_uv"} or None,
                          "n_tet": prep.get("n_tet"), "wall_s": {kk: v.get("wall_s") for kk, v in r.get("solve", {}).items()},
                          "zones": zones, "stem_regions": {kk: srow.get(kk) for kk in ("vm_max_body_deep", "vm_max_junction", "vm_max_neck_free")}}
    old = sorted(J.QROOT.glob("m1_base_h2_tol0.00025_delta0.025_*"))
    if old and "base_w0" in out["jobs"]:
        ro = J.result(old[0].name)
        out["regression"] = {"old_job": old[0].name, **{kk: [ro.get(kk), out["jobs"]["base_w0"].get(kk)]
                                                        for kk in ("f1_p95_um", "f1_first_p95_um", "vm_p99")}}
    out["created"] = time.strftime("%Y-%m-%d %H:%M:%S")
    (OUT / "summary.json").write_text(json.dumps(out, indent=1, default=float))
    print(json.dumps(out, indent=1, default=float)[:6000], flush=True)
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["submit", "status", "collect"])
    {"submit": submit, "status": status, "collect": collect}[ap.parse_args().cmd]()
