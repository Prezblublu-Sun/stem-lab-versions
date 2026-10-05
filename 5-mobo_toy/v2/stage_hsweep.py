"""截骨深度单因素扫描（用户 2026-10-05 批准）：3 个代表设计，其余设计变量全部不动，只改截骨深度 25 / 27 / 29 / 31 / 32 mm。
尺寸仍按余量规则在每个截骨深度重新模板化（截骨面下移后肩部位置变了，号可能变），所以"其余不动"指设计变量不动。
FE 设置与优化时相同（M1、过盈 0.025、滑移容差 2.5e-4、网格 2.0、粘接模型领与骨共节点），kind = variant、stage = hsweep，
不进任何优化数据集。Linux 上跑。

    python v2/stage_hsweep.py submit      → results/hsweep_ids.json
    python v2/stage_hsweep.py status
    python v2/stage_hsweep.py collect     → results/hsweep/summary.json（含固定区 G7 皮质应变能与应力两种口径）
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import jobs as J  # noqa: E402
import stage_v2a as S  # noqa: E402

DESIGNS = {"joint_best": "neck3_a40_967145a2", "newsplit_long": "neck5_r7_5df27b13", "oldsplit_s2": "neck2_r11_0b9c7ed8"}
LEVELS = (25.0, 27.0, 29.0, 31.0, 32.0)
IDS = J.RESULTS / "hsweep_ids.json"
OUT = J.RESULTS / "hsweep"


def specs() -> dict:
    out = {}
    for name, job in DESIGNS.items():
        base = json.loads((J.QROOT / job / "spec.json").read_text())
        for h in LEVELS:
            out[f"{name}_h{h:g}"] = {"kind": "variant", "stage": "hsweep", "tag": f"{name}_h{h:g}", "design": dict(base["design"]),
                                     "h_int": S.H_PROD, "min_A0": base.get("min_A0", S.MIN_A0), "model": "m1", "h_cut": float(h),
                                     "slip_tol": base.get("slip_tol", 2.5e-4), "delta": base.get("delta", 0.025), "source_job": job}
    return out


def submit():
    ids = {k: J.submit(v) for k, v in specs().items()}
    IDS.write_text(json.dumps({"jobs": ids, "designs": DESIGNS, "levels": LEVELS, "created": time.strftime("%Y-%m-%d %H:%M:%S")}, indent=1))
    print(json.dumps(ids, indent=1))


def status():
    ids = json.loads(IDS.read_text())["jobs"]
    st = {}
    for k, j in ids.items():
        s = J.state(J.QROOT / j)
        st.setdefault(s, []).append(k)
        if s == "FAILED":
            f = json.loads((J.QROOT / j / "FAILED.json").read_text())
            print("FAILED", k, f.get("level"), (f.get("reason") or "")[:200].replace("\n", " | "))
    print(json.dumps({k: len(v) for k, v in st.items()}))


def collect():
    import resorption as RS
    OUT.mkdir(parents=True, exist_ok=True)
    meta = json.loads(IDS.read_text())
    rows = []
    for k, j in meta["jobs"].items():
        name, h = k.rsplit("_h", 1)
        row = {"design": name, "h_cut": float(h), "job": j, "state": J.state(J.QROOT / j), "source_job": DESIGNS[name]}
        if row["state"] == "DONE":
            r = J.result(j)
            t, bl = r.get("templating") or {}, r.get("bone_loss") or {}
            g7 = {}
            try:
                rr, _ = RS.design_rows(j)
                g7 = next((x for x in rr if x["scheme"] == "fixed" and x["zone"] == "G7" and x["tissue"] == "cortex"), {})
            except Exception as e:  # noqa: BLE001
                g7 = {"error": f"{type(e).__name__}: {e}"[:200]}
            row.update(A0=t.get("A0"), e=t.get("e"), f1_body=r.get("f1_p95_um"), f1_closed=r.get("f1_closed_p95_um"),
                       f1_all=r.get("f1_all_p95_um", r.get("f1_p95_um")), f1_first_body=r.get("f1_first_p95_um"),
                       gt40=r.get("area_frac_gt40"), open_load2=r.get("open_frac_load2"), collar_share=r.get("collar_force_share_load2"),
                       collar_open=r.get("collar_open_frac_load2"), resected_mm3=bl.get("resected_mm3"), reamed_mm3=bl.get("reamed_mm3"),
                       vm_p99=r.get("vm_p99"), sed_chg_pct=g7.get("sed_chg_pct"), ssi_pct=g7.get("ssi_pct"), iface=r.get("interface_area"))
        elif row["state"] == "FAILED":
            row["reason"] = json.loads((J.QROOT / j / "FAILED.json").read_text()).get("reason", "")[:300]
        rows.append(row)
    for name, job in DESIGNS.items():                                       # 原作业作对照（各自原来的截骨深度）
        r = J.result(job)
        rows.append({"design": name, "h_cut": (r.get("bone_loss") or {}).get("h_cut_mm"), "job": job, "state": "original",
                     "A0": (r.get("templating") or {}).get("A0"), "f1_body": r.get("f1_p95_um"), "f1_all": r.get("f1_all_p95_um", r.get("f1_p95_um")),
                     "resected_mm3": (r.get("bone_loss") or {}).get("resected_mm3"), "reamed_mm3": (r.get("bone_loss") or {}).get("reamed_mm3")})
    (OUT / "summary.json").write_text(json.dumps({"rows": rows, "collected": time.strftime("%Y-%m-%d %H:%M:%S")}, indent=1, default=float))
    for r in rows:
        print(json.dumps({k: (round(v, 2) if isinstance(v, float) else v) for k, v in r.items() if k not in ("job", "source_job")}, ensure_ascii=False))


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["submit", "status", "collect"])
    {"submit": submit, "status": status, "collect": collect}[ap.parse_args().cmd]()
