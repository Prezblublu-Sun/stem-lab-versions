"""批次 A 汇总（Linux）：每个设计的粘接模型两种领（tied 共节点 / contact 只受压）对照。
    sed_chg_pct     固定 7 区皮质应变能变化（匹配的完整股骨参照）
    band_res06_pct  截骨面下方近端带（固定 1 + 7 区）皮质里应变能比 < 0.4 的体积分数
    collar_share    粘接模型里领承担的力占比：柄单元内力（线弹性，由 LOAD_U.csv 的节点位移算）在领面节点上的合力，
                    投到全部界面节点合力方向上的比例（与摩擦模型 collar_force_share 的定义相同）
    collar_open     contact 时领面掀起的面积比例（LOAD_CONTACT.csv 的 COPEN > 1 µm，几何面积加权）
回归：tied 的粘接模型结果与原作业逐字节比较（LOAD_ENER.csv、LOAD_S.csv）。输出 ~/mobo_toy_v2/deck/A_collar_contact.json
"""
from __future__ import annotations

import hashlib
import json
import math
import pathlib
import sys

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "code")); sys.path.insert(0, str(HOME / "code" / "v2"))
import numpy as np  # noqa: E402

import ccx_port as CP  # noqa: E402
import jobs as J  # noqa: E402
import post_m1 as PM1  # noqa: E402
import qoi  # noqa: E402
import resorption as RS  # noqa: E402
import stage_deck as SD  # noqa: E402

E_TI, NU_TI = 110000.0, 0.3


def calcar(j: str) -> dict:
    res = json.loads((J.QROOT / j / "result.json").read_text())
    rows, _ = RS.design_rows(j, res.get("intact_job"))
    fx = {r["zone"]: r for r in rows if r["scheme"] == "fixed" and r["tissue"] == "cortex"}
    g7, g1 = fx["G7"], fx["G1"]
    return {"sed_chg_pct": g7.get("sed_chg_pct"), "ssi_pct": g7.get("ssi_pct"), "g7_res06_pct": g7.get("res_0.6"),
            "band_res06_pct": (g7["res_0.6"] * g7["vol"] + g1["res_0.6"] * g1["vol"]) / (g7["vol"] + g1["vol"]), "vm_p99": res.get("vm_p99")}


def collar_bond(j: str) -> dict:
    d = J.QROOT / j
    m = dict(np.load(d / "mesh3d.npz"))
    col = m["pair_collar"].astype(bool)
    if not col.any():
        return {"collar_share": math.nan}
    n = int(m["node_labels"].max())
    U = PM1._utab(d / "m_bond_csv" / "LOAD_U.csv", n)
    U = np.nan_to_num(U)
    X = {int(a): b for a, b in zip(m["node_labels"], m["nodes"])}
    conn = m["stem_conn_bond"]
    used = set(np.unique(conn).tolist())
    fs = CP.stem_nodal_forces(X, U, conn, E_TI, NU_TI)
    side = np.array([int(t) if int(t) in used else int(b) for b, t in zip(m["pair_bone"], m["pair_stem"])])   # 柄侧实际用的节点
    F = np.array([fs.get(int(k), np.zeros(3)) for k in side])
    tot, fc = F.sum(0), F[col].sum(0)
    out = {"collar_share": float(fc @ tot / (tot @ tot)), "interface_force_N": float(np.linalg.norm(tot)), "collar_force_N": float(np.linalg.norm(fc))}
    cf = d / "m_bond_csv" / "LOAD_CONTACT.csv"
    if cf.exists():
        t = qoi._csv(cf)
        node = t["node"].astype(int)
        cop = np.full(n + 1, np.nan)
        k = (t["field"] == "COPEN") & (node <= n)
        cop[node[k]] = t["value"][k]
        c = cop[m["pair_bone"][col]]
        w = m["pair_area"][col]
        ok = np.isfinite(c)
        out["collar_open"] = float(w[ok & (c > 1e-3)].sum() / w[ok].sum()) if ok.any() else math.nan
        out["collar_copen_nodes"] = int(ok.sum())
    return out


def same_file(a: pathlib.Path, b: pathlib.Path) -> bool | None:
    if not (a.exists() and b.exists()):
        return None
    return hashlib.sha256(a.read_bytes()).hexdigest() == hashlib.sha256(b.read_bytes()).hexdigest()


if __name__ == "__main__":
    ids = json.loads((J.RESULTS / "deck_A_ids.json").read_text())["jobs"]
    out = {}
    for code in SD.A_CODES:
        rec = {"source_job": SD.SOURCES[code]}
        for mode in ("tied", "contact"):
            j = ids[f"{code}_{mode}"]
            st = J.state(J.QROOT / j)
            r = {"job_id": j, "state": st}
            if st == "DONE":
                r.update(calcar(j)); r.update(collar_bond(j))
                p = json.loads((J.QROOT / j / "prep.json").read_text())
                r["bond_collar_faces"] = p.get("bond_collar_faces"); r["A0"] = (p.get("templating") or {}).get("A0")
            elif st == "FAILED":
                r["reason"] = json.loads((J.QROOT / j / "FAILED.json").read_text()).get("reason", "")[:300]
            rec[mode] = r
        src = J.QROOT / SD.SOURCES[code]
        tj = J.QROOT / ids[f"{code}_tied"]
        if code not in ("FI",):
            rec["tied_bit_identical_to_source"] = {f: same_file(src / "m_bond_csv" / f, tj / "m_bond_csv" / f) for f in ("LOAD_ENER.csv", "LOAD_S.csv")}
        out[code] = rec
        print(code, json.dumps({k: (v if not isinstance(v, dict) else {kk: (round(vv, 3) if isinstance(vv, float) else vv) for kk, vv in v.items()
                                                                       if kk not in ("job_id",)}) for k, v in rec.items()}, default=str), flush=True)
    (HOME / "deck" / "A_collar_contact.json").write_text(json.dumps(out, indent=1, default=float))
