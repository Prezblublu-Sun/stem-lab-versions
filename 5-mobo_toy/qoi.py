"""由 odb 导出的 CSV 计算关注量（QoI）。现代 Python 环境运行（CLAUDE.md §5.4 两段式的第二段）。

f1 微动：_fric 模型骨从面节点的切向滑移增量 |CSLIP1(LOAD) − CSLIP1(RELEASE)|，按节点所辖界面长度加权
          （二次边 Simpson 权 1/6、4/6、1/6）取 P95，单位 µm；另记 >50 µm、>150 µm 的长度占比。
f2 近端遮挡：_bond 模型 Gruen 7 ROI 内骨单元的平均应变能密度 SED = ΣELSE/ΣEVOL，相对完整股骨同一 ROI 的下降率（%）。
约束：_bond 模型柄单元（去掉假体头圆盘）形心 von Mises 的面积加权 P99（MPa）。
"""
from __future__ import annotations

import json
import pathlib

import numpy as np
import shapely

import femur2d as F

CFG = F.CFG


def _csv(path: pathlib.Path) -> dict[str, np.ndarray]:
    """读 odb 导出的 CSV；清理后的设计目录里是 .csv.gz。"""
    import csv
    import gzip
    path = pathlib.Path(path)
    opener = (lambda: open(path, newline="")) if path.exists() else (lambda: gzip.open(str(path) + ".gz", "rt", newline=""))
    with opener() as fh:
        r = csv.reader(fh)
        head = next(r)
        rows = list(r)
    out = {}
    for j, h in enumerate(head):
        col = [row[j] for row in rows]
        try:
            out[h] = np.array(col, dtype=float)
        except ValueError:
            out[h] = np.array(col)
    return out


def load_mesh(model_dir: pathlib.Path) -> dict:
    return dict(np.load(model_dir / "mesh.npz"))


def wquantile(x: np.ndarray, w: np.ndarray, q: float) -> float:
    o = np.argsort(x)
    x, w = x[o], w[o]
    c = np.cumsum(w) - 0.5 * w
    c /= w.sum()
    return float(np.interp(q, c, x))


def interface_nodes(mesh: dict, model: dict, region_prefix: str = "bone") -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """从面节点号、坐标、Simpson 权重（mm）。"""
    labels = mesh[f"{region_prefix}_labels"]
    nodes = mesh[f"{region_prefix}_nodes"]
    lut = {int(l): i for i, l in enumerate(labels)}
    conn = {}
    for key in mesh:
        if key.startswith(f"{region_prefix}_") and key.endswith("_conn"):
            reg = key[len(region_prefix) + 1:-5]
            for el, c in zip(mesh[f"{region_prefix}_{reg}_elab"], mesh[key]):
                conn[int(el)] = c
    w: dict[int, float] = {}
    for a, b, el, face in model["slave_edges"]:
        c = conn[el]
        mid = int(c[3 + (face - 1)])                  # face 1: n1-n2 → n4；face 2: n2-n3 → n5；face 3: n3-n1 → n6
        pa, pb = nodes[lut[a]], nodes[lut[b]]
        ln = float(np.linalg.norm(pb - pa))
        for n, wt in ((a, ln / 6), (b, ln / 6), (mid, 2 * ln / 3)):
            w[n] = w.get(n, 0.0) + wt
    lab = np.array(sorted(w))
    return lab, nodes[[lut[l] for l in lab]], np.array([w[l] for l in lab])


def micromotion(model_dir: pathlib.Path, job: str) -> dict:
    mesh, model = load_mesh(model_dir), json.loads((model_dir / "model.json").read_text())
    lab, xy, w = interface_nodes(mesh, model)
    d = model_dir / f"{job}_csv"
    c1, c2 = _csv(d / "RELEASE_CONTACT.csv"), _csv(d / "LOAD_CONTACT.csv")

    def field(c, name):
        m = c["field"] == name
        return dict(zip(c["node"][m].astype(int), c["value"][m]))
    s1, s2 = field(c1, "CSLIP1"), field(c2, "CSLIP1")
    st2, p2, p1 = field(c2, "CSTATUS"), field(c2, "CPRESS"), field(c1, "CPRESS")
    missing = [l for l in lab if l not in s2 or l not in s1]
    if len(missing) > 0.05 * len(lab):
        raise RuntimeError(f"CSLIP1 missing on {len(missing)}/{len(lab)} slave nodes")
    keep = np.array([l not in missing for l in lab])
    lab, xy, w = lab[keep], xy[keep], w[keep]
    slip = np.abs(np.array([s2[l] - s1[l] for l in lab])) * 1000.0          # µm
    status = np.array([st2.get(l, 0.0) for l in lab])
    thr = CFG["qoi"]["micromotion_thresholds_um"]
    wt = w / w.sum()
    return {
        "f1_p95_um": wquantile(slip, w, CFG["qoi"]["micromotion_percentile"] / 100),
        "f1_mean_um": float(np.sum(wt * slip)),
        "f1_max_um": float(slip.max()),
        f"frac_gt{thr[0]}": float(np.sum(wt * (slip > thr[0]))),
        f"frac_gt{thr[1]}": float(np.sum(wt * (slip > thr[1]))),
        "frac_open": float(np.sum(wt * (status < 0.5))),
        "frac_slip": float(np.sum(wt * ((status > 0.5) & (status < 1.5)))),
        "frac_stick": float(np.sum(wt * (status > 1.5))),
        "cpress_release_mean": float(np.sum(wt * np.array([p1.get(l, 0.0) for l in lab]))),
        "cpress_load_mean": float(np.sum(wt * np.array([p2.get(l, 0.0) for l in lab]))),
        "interface_length": float(w.sum()),
        "n_interface_nodes": int(len(lab)),
        "_profile": {"node": lab, "x": xy[:, 0], "z": xy[:, 1], "w": w, "slip_um": slip, "status": status,
                     "cpress": np.array([p2.get(l, 0.0) for l in lab]),
                     "cpress_pf": np.array([p1.get(l, 0.0) for l in lab])},
    }


def _elem_centroids(mesh: dict, prefix: str, region: str):
    lab = mesh[f"{prefix}_labels"]
    nodes = mesh[f"{prefix}_nodes"]
    lut = np.full(int(lab.max()) + 1, -1)
    lut[lab] = np.arange(len(lab))
    conn = mesh[f"{prefix}_{region}_conn"]
    p = nodes[lut[conn[:, :3]]]
    return mesh[f"{prefix}_{region}_elab"], p.mean(axis=1)


def zone_sed(model_dir: pathlib.Path, job: str, step: str = "LOAD") -> dict:
    """各 ROI 的平均 SED（MPa = MJ/m³）。"""
    mesh = load_mesh(model_dir)
    model = json.loads((model_dir / "model.json").read_text())
    f = F.build(model["dorr"], model["E_cancellous"])
    zones = f.zones()
    en = _csv(model_dir / f"{job}_csv" / f"{step}_ENER.csv")
    e_by = dict(zip(en["elem"].astype(int), en["else"]))
    v_by = dict(zip(en["elem"].astype(int), en["evol"]))
    out = {}
    elabs, cents = [], []
    for reg in ("cortex", "cancellous"):
        if f"bone_{reg}_conn" in mesh:
            el, ce = _elem_centroids(mesh, "bone", reg)
            elabs.append(el); cents.append(ce)
    elabs, cents = np.concatenate(elabs), np.vstack(cents)
    for zname, zpoly in zones.items():
        inside = shapely.contains_xy(zpoly, cents[:, 0], cents[:, 1])
        E = sum(e_by.get(int(e), 0.0) for e in elabs[inside])
        V = sum(v_by.get(int(e), 0.0) for e in elabs[inside])
        out[zname] = {"SE": E, "V": V, "SED": E / V if V > 0 else float("nan"), "n": int(inside.sum())}
    return out


def stem_vm(model_dir: pathlib.Path, job: str, step: str = "LOAD") -> dict:
    mesh = load_mesh(model_dir)
    s = _csv(model_dir / f"{job}_csv" / f"{step}_S.csv")
    mis = dict(zip(s["elem"].astype(int), s["mises"]))
    el, ce = _elem_centroids(mesh, "stem", "stem")
    lab = mesh["stem_labels"]; nodes = mesh["stem_nodes"]
    lut = np.full(int(lab.max()) + 1, -1); lut[lab] = np.arange(len(lab))
    p = nodes[lut[mesh["stem_stem_conn"][:, :3]]]
    area = 0.5 * np.abs((p[:, 1, 0] - p[:, 0, 0]) * (p[:, 2, 1] - p[:, 0, 1]) - (p[:, 2, 0] - p[:, 0, 0]) * (p[:, 1, 1] - p[:, 0, 1]))
    H = np.array(CFG["femur"]["head_center"], dtype=float)
    keep = np.linalg.norm(ce - H, axis=1) > CFG["stem"]["head_radius"]
    v = np.array([mis[int(e)] for e in el])
    q = CFG["qoi"]["stem_vm_percentile"] / 100
    return {"vm_p99": wquantile(v[keep], area[keep], q), "vm_max": float(v[keep].max())}


def evaluate_dir(model_dir: pathlib.Path, name: str, intact: dict) -> dict:
    """intact: {"gruen7": SED, "gruen1": SED}（同 dorr、同松质骨模量的完整股骨）。"""
    mm = micromotion(model_dir, f"{name}_fric")
    zs = zone_sed(model_dir, f"{name}_bond")
    vm = stem_vm(model_dir, f"{name}_bond")
    prof = mm.pop("_profile")
    out = {**mm, **vm,
           "f2_g7_loss_pct": 100.0 * (1.0 - zs["gruen7"]["SED"] / intact["gruen7"]),
           "f2_g1_loss_pct": 100.0 * (1.0 - zs["gruen1"]["SED"] / intact["gruen1"]),
           "sed_g7": zs["gruen7"]["SED"], "sed_g1": zs["gruen1"]["SED"]}
    np.savez_compressed(model_dir / "interface_profile.npz", **prof)
    return out
