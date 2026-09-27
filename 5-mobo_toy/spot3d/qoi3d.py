"""3D 关注量：与 2D 同定义（f1 = 从面节点切向滑移增量 P95，f2 = Gruen 7 ROI 平均 SED 下降率），ROI 在 3D 中取全部 y。"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import femur2d as F  # noqa: E402
import qoi  # noqa: E402

FACES = {1: (0, 1, 2), 2: (0, 3, 1), 3: (1, 3, 2), 4: (2, 3, 0)}
FACE_MID = {1: (4, 5, 6), 2: (7, 8, 4), 3: (8, 9, 5), 4: (6, 9, 7)}   # Abaqus C3D10 面上的中点节点


def _mesh(d):
    m = dict(np.load(d / "mesh3d.npz"))
    lab, X = m["node_labels"], m["nodes"]
    lut = np.full(int(lab.max()) + 1, -1); lut[lab] = np.arange(len(lab))
    return m, X, lut


def micromotion(d: pathlib.Path, job: str) -> dict:
    m, X, lut = _mesh(d)
    info = json.loads((d / "model3d.json").read_text())
    conn = {}
    for r in ("cortex", "cancellous"):
        for el, row in zip(m[f"{r}_elab"], m[f"{r}_conn"]):
            conn[int(el)] = row
    w = {}
    for el, fc in info["slave"]:
        row = conn[el]
        cn = [int(row[k]) for k in FACES[fc]]
        P = X[lut[cn]]
        A = 0.5 * np.linalg.norm(np.cross(P[1] - P[0], P[2] - P[0]))
        for n in cn + [int(row[k]) for k in FACE_MID[fc]]:
            w[n] = w.get(n, 0.0) + A / 6.0
    c1 = qoi._csv(d / f"{job}_csv" / "RELEASE_CONTACT.csv")
    c2 = qoi._csv(d / f"{job}_csv" / "LOAD_CONTACT.csv")

    def fld(c, name):
        k = c["field"] == name
        return dict(zip(c["node"][k].astype(int), c["value"][k]))
    a1, a2, b1, b2 = fld(c1, "CSLIP1"), fld(c1, "CSLIP2"), fld(c2, "CSLIP1"), fld(c2, "CSLIP2")
    st = fld(c2, "CSTATUS")
    lab = np.array([n for n in w if n in b1 and n in a1])
    ww = np.array([w[n] for n in lab])
    slip = np.array([np.hypot(b1[n] - a1[n], b2.get(n, 0.0) - a2.get(n, 0.0)) for n in lab]) * 1000.0
    s = np.array([st.get(n, 0.0) for n in lab])
    wt = ww / ww.sum()
    return {"f1_p95_um": qoi.wquantile(slip, ww, 0.95), "f1_mean_um": float(np.sum(wt * slip)),
            "frac_open": float(np.sum(wt * (s < 0.5))), "frac_stick": float(np.sum(wt * (s > 1.5))),
            "n_slave_nodes": int(len(lab)), "interface_area": float(ww.sum())}


def zone_sed(d: pathlib.Path, job: str, dorr: str, E: float) -> dict:
    m, X, lut = _mesh(d)
    f = F.build(dorr, E)
    zq = F.CFG["qoi"]
    C0, u = f.cut
    en = qoi._csv(d / f"{job}_csv" / "LOAD_ENER.csv")
    e_by = dict(zip(en["elem"].astype(int), en["else"])); v_by = dict(zip(en["elem"].astype(int), en["evol"]))
    out = {}
    for zname, cond in (("gruen7", lambda c: c[:, 0] >= zq["zone7"]["x_min"]), ("gruen1", lambda c: c[:, 0] < zq["zone1"]["x_max"])):
        E_, V_ = 0.0, 0.0
        for r in ("cortex", "cancellous"):
            cen = X[lut[m[f"{r}_conn"][:, :4]]].mean(1)
            below = ((cen[:, [0, 2]] - C0) @ u) <= 0
            sel = cond(cen) & (cen[:, 2] >= zq["zone7"]["z_min"]) & below
            for el in m[f"{r}_elab"][sel]:
                E_ += e_by.get(int(el), 0.0); V_ += v_by.get(int(el), 0.0)
        out[zname] = E_ / V_ if V_ else float("nan")
    return out
