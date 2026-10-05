"""粘接模型的领底面处理（规格选项 bond_collar，2026-10-05 由副本 I:\\UCL_theses\\2610 opt 的 BOND_COLLAR 移植）。

    "tied"（默认，不写也一样）：领面与骨共节点，即假定领也骨整合、能传拉力（此前全部作业的做法）。
    "contact"：领面节点（pair_collar，含柄身与领交接的一圈）在柄侧换成孪生节点（与摩擦模型同号、同坐标），
               领底面与截骨面硬接触 + 库仑摩擦（μ、滑移容差与摩擦模型相同），初始间隙 0：领只受压、可掀起、不传拉力；
               柄身仍与骨共节点。分析步改为非线性增量。

做法：model3d_m1.build 照常建模后，本模块只改写该作业自己的 m_bond.inp 与 mesh3d.npz（stem_conn_bond），
不改 model3d_m1.py（它计入作业 id 的代码哈希；改了会让已解作业与新作业对不上号）。两种选项都另外保留粘接模型
LOAD 步的节点位移（LOAD_U.csv），以便用柄单元内力按同一方法算领承载比例；contact 另保留接触量与接触力。
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from inp_writer import Inp, _f  # noqa: E402
from model3d_m1 import CONTACT_M1, DEFAULTS, interface_faces  # noqa: E402
from spot3d.model3d import FACES  # noqa: E402

MODES = ("tied", "contact")


def collar_contact_block(mu: float, slip_tol: float) -> str:
    """领底面接触：硬接触 + 库仑摩擦，初始间隙 0（两侧节点重合）。与副本 model3d_m1.collar_contact_block 相同。"""
    return f"""*SURFACE INTERACTION, NAME=COLLAR
*FRICTION, SLIP TOLERANCE={_f(slip_tol)}
{_f(mu)},
*SURFACE BEHAVIOR, PRESSURE-OVERCLOSURE=HARD
*CONTACT PAIR, INTERACTION=COLLAR, TYPE=SURFACE TO SURFACE, SMALL SLIDING
S_BONE_C, S_STEM_C
*CLEARANCE, SLAVE=S_BONE_C, MASTER=S_STEM_C, VALUE=0."""


def split(m: dict):
    """领面节点换孪生节点后的柄连接、映射，以及领面的从面 / 主面（三个角节点都是领面节点的界面三角面）。"""
    elems = {"cortex": m["cortex_conn"], "cancellous": m["cancellous_conn"], "stem": m["stem_conn_bond"]}
    cmap = {int(n): int(t) for n, t, c in zip(m["pair_bone"], m["pair_stem"], m["pair_collar"]) if c}
    conn = np.array([[cmap.get(int(n), int(n)) for n in row] for row in elems["stem"]], dtype=np.int64)
    slave, master = interface_faces(elems, ["cortex", "cancellous"])
    cs, cm = [], []
    for s, mm in zip(slave, master):
        r, i, fc = s
        if all(int(elems[r][i][k]) in cmap for k in FACES[fc]):
            cs.append(s)
            cm.append(mm)
    return conn, cmap, cs, cm


def apply(d: pathlib.Path, spec: dict, cfg: dict) -> dict:
    """作业目录 d 已由 model3d_m1.build 写好；按 spec["bond_collar"] 改写粘接模型。返回写进 prep.json 的记录。"""
    mode = spec.get("bond_collar", "tied")
    if mode not in MODES:
        raise ValueError(f"bond_collar must be one of {MODES}, got {mode!r}")
    keep = json.loads((d / "keep.json").read_text())
    npz = dict(np.load(d / "mesh3d.npz"))
    has_collar = bool(npz["pair_collar"].any())
    # 接触量只有真有领面接触时才导得出（2026-10-06：无领设计按 contact 提交时曾因缺 LOAD_CONTACT.csv 判 L5）
    keep["bond"] = sorted(set(keep["bond"]) | {"LOAD_U.csv"} | ({"LOAD_CONTACT.csv", "LOAD_CFORCE.csv"} if mode == "contact" and has_collar else set()))
    (d / "keep.json").write_text(json.dumps(keep))
    if mode == "tied":
        return {"bond_collar": "tied"}
    if not has_collar:
        return {"bond_collar": "contact", "bond_collar_faces": 0, "note": "no collar: identical to tied"}
    conn, cmap, cs, cm = split(npz)
    if len(cs) < 10:
        raise ValueError(f"bonded-model collar contact too small: {len(cs)} faces")
    labs = npz["node_labels"]
    X = dict(zip(labs.astype(int).tolist(), npz["nodes"]))
    mu = float(spec["mu"]) if spec.get("mu") is not None else float(cfg["interface"]["mu"])
    slip_tol = float(spec["slip_tol"]) if spec.get("slip_tol") is not None else DEFAULTS["slip_tol"]
    elab = {r: npz[f"{r}_elab"] for r in ("cortex", "cancellous", "stem")}
    lines = (d / "m_bond.inp").read_text().splitlines()
    out, i, n_stem, stage = [], 0, 0, None
    surf = Inp("")
    surf.lines = []
    surf.element_surface("S_BONE_C", [(elab[r][k], fc) for r, k, fc in cs])
    surf.element_surface("S_STEM_C", [(elab[r][k], fc) for r, k, fc in cm])
    while i < len(lines):
        ln = lines[i]
        up = ln.strip().upper()
        if up.startswith("*NODE") and not up.startswith("*NODE OUTPUT") and stage is None:
            out.append(ln)
            i += 1
            while i < len(lines) and not lines[i].startswith("*"):
                out.append(lines[i])
                i += 1
            out += [f"{t}, {_f(X[t][0])}, {_f(X[t][1])}, {_f(X[t][2])}" for t in sorted(cmap.values())]   # 孪生节点：与原节点同坐标
            stage = "nodes"
            continue
        if up.startswith("*ELEMENT") and "ELSET=STEM" in up.replace(" ", ""):
            out.append(ln)
            i += 1
            k = 0
            while i < len(lines) and not lines[i].startswith("*"):
                lab = int(lines[i].split(",")[0])
                out.append(f"{lab}, " + ", ".join(str(int(v)) for v in conn[k]))
                k += 1
                i += 1
            n_stem = k
            continue
        if up.startswith("*STEP"):
            out += surf.lines + collar_contact_block(mu, slip_tol).splitlines()
            out.append("*STEP, NAME=LOAD, INC=1000")
            i += 1
            assert lines[i].strip().upper() == "*STATIC", lines[i]
            out += ["*STATIC", "0.25, 1., 1e-08, 1."]
            i += 2
            continue
        if up.startswith("*END STEP"):
            out += CONTACT_M1.splitlines()
        out.append(ln)
        i += 1
    if n_stem != len(conn):
        raise ValueError(f"stem element block not rewritten completely: {n_stem} of {len(conn)}")
    (d / "m_bond.inp").write_text("\n".join(out) + "\n", encoding="ascii")
    npz["stem_conn_bond"] = conn
    np.savez_compressed(d / "mesh3d.npz", **npz)
    return {"bond_collar": "contact", "bond_collar_faces": len(cs), "bond_collar_twins": len(cmap)}
