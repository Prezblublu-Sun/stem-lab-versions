"""对照 Naghavi 2023 论文之后的三组求解对照（在 Linux 上跑；本机只求解）。全部是“变体”作业（kind = variant），
不进任何常规数据集；完整股骨参照用 stage = "ata"，不会被 jobs.intact_ref 选作标准参照。

    mesh     皮质分区应力的网格检查：3 个设计 × (界面尺寸, 远场尺寸) ∈ {(2.0, 6), (1.4, 6), (1.4, 4), (1.0, 6)}，只解粘接模型
    iso      2300 N 对照工况：3 个设计，载荷方向角 10° / 9°（ISO 7206-4 的量级），只解粘接模型
    estem    柄模量敏感性：3 个设计 × E ∈ {95, 55, 20} GPa，M1 界面模型（摩擦 + 粘接），过盈 0.025 mm

    python v2/stage_ata.py submit            登记全部作业，id 写 results/ata_ids.json
    python v2/stage_ata.py status
    python v2/stage_ata.py collect           已完成的部分 → results/ata/summary.json

说明
* 1.0 mm 的完整股骨解不了（内存），该档用 1.4 mm 的完整股骨作参照，与此前的做法相同。
* iso 的方向符号沿用上楼工况（力指向外、后、下），只改角度和大小。
* estem 把整个假体（含颈与头）的模量一起改了；颈是静定的传力件，它的刚度不改变传到骨上的载荷。
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import jobs as J  # noqa: E402
import stage_m1 as M1S  # noqa: E402

IDS = J.RESULTS / "ata_ids.json"
OUT = J.RESULTS / "ata"
DESIGNS = ("base", "readout", "short")
MESH = ((2.0, 6.0), (1.4, 6.0), (1.4, 4.0), (1.0, 6.0))
ISO = {"load": {"resultant_N": 2300.0, "alpha_front_deg": 10.0, "alpha_sagit_deg": 9.0}}
E_STEM = (95000.0, 55000.0, 20000.0)
DELTA = 0.025
FR = {"slip_tol": 2.5e-4}
STD_REF = "ref_intact_h2_S_e7f3f3a8"            # 标准参照：生产网格、标准载荷、带应力导出


def core(d: str) -> dict:
    c = M1S.core_of(M1S.NAMED[d])
    return {**{k: v for k, v in c.items() if k != "kind"}, "kind": "variant", "stage": "ata"}


def specs() -> dict:
    sp = {"ref": {}, "mesh": {}, "iso": {}, "estem": {}}
    sp["ref"]["h1.4_f6"] = {"kind": "intact", "h_int": 1.4, "h_far": 6.0, "stage": "ata", "tag": "intact_h1.4_f6_S"}
    sp["ref"]["h1.4_f4"] = {"kind": "intact", "h_int": 1.4, "h_far": 4.0, "stage": "ata", "tag": "intact_h1.4_f4_S"}
    sp["ref"]["iso"] = {"kind": "intact", "h_int": 2.0, "h_far": 6.0, "stage": "ata", "tag": "intact_h2_iso_S", "cfg": ISO}
    return sp


def submit() -> dict:
    sp = specs()
    ids = {"ref": {k: J.submit(v) for k, v in sp["ref"].items()}, "mesh": {}, "iso": {}, "estem": {}, "std_ref": STD_REF}
    ref_of = {(2.0, 6.0): STD_REF, (1.4, 6.0): ids["ref"]["h1.4_f6"], (1.4, 4.0): ids["ref"]["h1.4_f4"], (1.0, 6.0): ids["ref"]["h1.4_f6"]}
    for d in DESIGNS:
        c = core(d)
        for h, hf in MESH:
            s = {**c, "h_int": h, "h_far": hf, "bond_only": True, "intact_job": ref_of[(h, hf)], "tag": f"mesh_{d}_h{h:g}_f{hf:g}"}
            if (h, hf) == (1.0, 6.0):
                s["intact_substituted_h"] = 1.4
            ids["mesh"][f"{d}:h{h:g}:f{hf:g}"] = J.submit(s)
        ids["iso"][d] = J.submit({**c, "h_int": 2.0, "bond_only": True, "cfg": ISO, "intact_job": ids["ref"]["iso"], "tag": f"iso_{d}"})
        for E in E_STEM:
            ids["estem"][f"{d}:E{E / 1000:g}"] = J.submit({**c, "h_int": 2.0, "model": "m1", **FR, "delta": DELTA,
                                                           "cfg": {"materials": {"titanium": {"E": E}}},
                                                           "tag": f"estem_{d}_E{E / 1000:g}_d{DELTA:g}"})
    ids["created"] = time.strftime("%Y-%m-%d %H:%M:%S")
    ids["code"] = J.code_hash()
    J.RESULTS.mkdir(parents=True, exist_ok=True)
    IDS.write_text(json.dumps(ids, indent=1))
    n = sum(len(v) for k, v in ids.items() if isinstance(v, dict))
    print(f"[ata] {n} jobs registered, code {ids['code']}", flush=True)
    return ids


def _flat(ids):
    return [(g, k, j) for g in ("ref", "mesh", "iso", "estem") for k, j in ids[g].items()]


def status() -> dict:
    ids = json.loads(IDS.read_text())
    st = {}
    for g, k, j in _flat(ids):
        s = J.state(J.QROOT / j)
        st.setdefault(s, []).append(f"{g}:{k}")
        if s == "FAILED":
            f = json.loads((J.QROOT / j / "FAILED.json").read_text())
            print("FAILED", g, k, j, f.get("level"), f.get("stage"), (f.get("reason") or "")[:300].replace("\n", " | "), flush=True)
    print(json.dumps({k: len(v) for k, v in st.items()}), flush=True)
    for k, v in st.items():
        if k not in ("DONE",):
            print(k, v, flush=True)
    return st


def _baseline_m1(d: str) -> str | None:
    """E = 110 GPa 的基线：同设计、同网格、同摩擦设置、同过盈的已解 M1 作业（取最新）。"""
    c = [(p.stat().st_mtime, p.name) for p in J.QROOT.glob(f"m1_{d}_h2_tol0.00025_delta{DELTA:g}_*") if (p / "DONE").exists()]
    return max(c)[1] if c else None


def collect() -> dict:
    import resorption as RS
    OUT.mkdir(parents=True, exist_ok=True)
    ids = json.loads(IDS.read_text())
    RS._init()
    out = {"ids": ids, "mesh": {}, "iso": {}, "estem": {}, "std": {}, "missing": []}

    def one(j, iname):
        if J.state(J.QROOT / j) != "DONE":
            out["missing"].append(j)
            return None
        rows, srow = RS.design_rows(j, iname)
        r = J.result(j)
        z = {f"{x['scheme']}:{x['tissue']}:{x['zone']}": {k: v for k, v in x.items() if k in
                                                           ("vol", "ssi_pct", "ssi_vw_pct", "sed_chg_pct", "res_0.4", "res_0.6", "res_0.75", "gain_0.6")}
             for x in rows}
        return {"job_id": j, "intact": iname or ids["std_ref"], "zones": z, "stem": srow,
                "n_tet": r.get("n_tet"), "wall_s": {k: v.get("wall_s") for k, v in r.get("solve", {}).items()},
                **{k: r.get(k) for k in ("f1_p95_um", "f1_first_p95_um", "f1_rev_p50_um", "area_frac_gt40", "vm_p99", "vm_max",
                                         "open_frac_release", "status_frac_slip", "f2_g7_loss_pct") if k in r}}

    ref_of = {"h2:f6": None, "h1.4:f6": ids["ref"]["h1.4_f6"], "h1.4:f4": ids["ref"]["h1.4_f4"], "h1:f6": ids["ref"]["h1.4_f6"]}
    for k, j in ids["mesh"].items():
        d, h, f = k.split(":")
        iname = ref_of[f"{h}:{f}"]
        if iname is not None and J.state(J.QROOT / iname) != "DONE":
            out["missing"].append(j)
            continue
        out["mesh"][k] = one(j, iname)
    for d, j in ids["iso"].items():
        if J.state(J.QROOT / ids["ref"]["iso"]) != "DONE":
            out["missing"].append(j)
            continue
        out["iso"][d] = one(j, ids["ref"]["iso"])
    for k, j in ids["estem"].items():
        out["estem"][k] = one(j, None)
    for d in DESIGNS:
        b = _baseline_m1(d)
        out["estem"][f"{d}:E110"] = one(b, None) if b else None
    for g in ("ref",):
        out[g] = {k: {"job_id": j, "state": J.state(J.QROOT / j), "n_tet": (J.result(j) or {}).get("n_tet"),
                      "prep": json.loads((J.QROOT / j / "prep.json").read_text()).get("n_tet") if (J.QROOT / j / "prep.json").exists() else None}
                  for k, j in ids[g].items()}
    out["created"] = time.strftime("%Y-%m-%d %H:%M:%S")
    (OUT / "summary.json").write_text(json.dumps(out, indent=1, default=float))
    print(f"[ata] collected; missing {len(out['missing'])}", flush=True)
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["submit", "status", "collect", "specs"])
    a = ap.parse_args()
    {"submit": submit, "status": status, "collect": collect, "specs": lambda: print(json.dumps(specs(), indent=1))}[a.cmd]()
