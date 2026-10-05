"""开源求解器 CalculiX（ccx 2.23，conda-forge，装在 Linux 用户目录 ~/opt/ccx）复核 Abaqus 结果（用户 2026-10-05）。

做法：同一规格在 Linux 上重建模型（jobs.prep，代码哈希与原作业相同，网格确定性；逐个核对单元数），把 Abaqus 的 .inp
翻译成 ccx 能读的 .inp，ccx 求解后把结果写成与 abaqus/odb_export.py 完全相同的 CSV，再用原后处理（jobs.post →
post_m1 / post / resorption）算指标。后处理代码一行不改，口径与 Abaqus 结果一致。作业在单独的目录
~/mobo_toy_v2/ccx/queue/<原 job_id>/，不进正式队列和任何优化数据集。

翻译（Abaqus → ccx）
* 接触：面对面罚函数接触（ccx 的 SURFACE TO SURFACE）。法向 = OPTS["normal"]；摩擦 = 库仑 μ 加粘着刚度 λ（ccx 的
  stick slope，N/mm³）。Abaqus 用滑移容差（弹性滑移 ≤ 2.5e-4 × 单元尺寸 ≈ 0.5 µm）；λ 按释放后接触压力中位数换算，
  使同样压力下的弹性滑移相同。
* 过盈：Abaqus 用逐节点的 *CLEARANCE, TABULAR（皮质相邻节点 0，其余 −δ）加 *CONTACT INTERFERENCE, SHRINK 逐步消除；
  ccx 的 *CLEARANCE 只能整对给一个值。两种做法可选：
    "offset"（默认）把柄侧孪生节点沿柄外法向移出 δ_i（逐节点，与 Abaqus 的 offset 法相同），ccx 在第一步直接消除重叠；
    "split"  从面按节点过盈分两组（≥ 一半节点有过盈的面给 −δ），两个接触对。
* 输出：.dat 里节点位移（全部节点，7 位有效数字）、支座反力、单元积分点应力 / 应变或单元应变能与体积；.frd 里接触量
  （CDIS / CSTR，从节点）。单元形心量 = 4 个积分点的平均（C3D10 的应力在单元内线性，平均即形心值）。
* 节点接触力（CFORCE，领的承载比例用）：ccx 不直接给，由柄单元的内力 Σ Bᵀσ（积分点应力，线弹性）在界面孪生节点上求出，
  界面孪生节点只受接触力，所以这就是骨对柄的接触力；骨侧的力取反。

    python v2/ccx_port.py lame [--interference offset|split]      Lamé 压配解析解对照
    python v2/ccx_port.py setup <job_id>...                         复制规格到 ccx 队列（含完整股骨参照）
    python v2/ccx_port.py run <job_id>... [--cpus 4]                 建模 → 翻译 → 求解 → 转换 → 后处理
    python v2/ccx_port.py batch <job_id>... | --phases 5,6,1,2,3     调度（资源规则见 DEFAULT_CTL；可续跑）
    python v2/ccx_port.py ctl status|pause|resume|stop|stop-now|set key=value
    python v2/ccx_port.py compare <job_id>...                        与 Abaqus 结果对照
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys
import time
import traceback

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import jobs as J  # noqa: E402

BASE = pathlib.Path.home() / "mobo_toy_v2" / "ccx"
CQ = BASE / "queue"
CRES = BASE / "results"


def _set_queue(name: str) -> None:
    """换作业目录（求解参数变体用：~/mobo_toy_v2/ccx/queue_<变体>/，参数覆盖写在该目录的 opts.json）。"""
    global CQ
    CQ = BASE / name


def _entry(e: str) -> tuple[str, pathlib.Path, list[str]]:
    """调度条目 "job_id" 或 "job_id@变体" → (job_id, 作业目录, 额外命令行参数)。"""
    j, _, v = e.partition("@")
    return (j, BASE / f"queue_{v}" / j, ["--queue", f"queue_{v}"]) if v else (j, CQ / j, [])
CCX = pathlib.Path.home() / "opt" / "ccx" / "bin" / "ccx"
P50_ABQ = 2.7                               # Abaqus 释放后界面接触压力中位数的典型值（MPa，如 neck5_r7 2.70）
# 法向：ccx 的面对面罚接触不支持 HARD（自动退化为线性且刚度极小），也不允许 SMALL SLIDING；线性罚刚度 K（N/mm³）与大间隙时的
# 拉应力 σ∞（MPa，ccx 手册建议约为最大压力的 0.25 %）显式给定
OPTS = {"normal": (5.0e4, 0.005), "stick_slope": None, "interference": "offset", "small_sliding": False, "timeout": 4 * 3600,
        "freq": 10000}
GAMMA_ABQ = 2.5e-4 * 2.0                    # Abaqus 弹性滑移上限（mm）：滑移容差 × 特征单元尺寸 2 mm

# C3D10 面（Abaqus 与 ccx 编号相同）：角点 + 边中点，节点序号从 0 起
FACE_NODES = {1: (0, 1, 2, 4, 5, 6), 2: (0, 3, 1, 7, 8, 4), 3: (1, 3, 2, 8, 9, 5), 4: (2, 3, 0, 9, 7, 6)}


# ------------------------------------------------------------------------------------------------ 翻译
def _blocks(lines):
    """把 inp 切成 (关键字行, 数据行列表)；注释行丢掉。"""
    out, cur = [], None
    for ln in lines:
        s = ln.strip()
        if not s or s.startswith("**"):
            continue
        if s.startswith("*"):
            cur = [s, []]
            out.append(cur)
        elif cur is not None:
            cur[1].append(s)
    return out


def _kw(head: str) -> str:
    return head.split(",")[0].strip().upper()


def _param(head: str, name: str):
    m = re.search(rf"{name}\s*=\s*([^,]+)", head, re.I)
    return m.group(1).strip() if m else None


def _strip_param(head: str, name: str) -> str:
    return re.sub(rf",\s*{name}\s*=\s*[^,]+", "", head, flags=re.I)


def _outputs(kind: str, has_rf: bool, freq: int) -> list[str]:
    f = f", FREQUENCY={freq}" if freq else ""
    rf = [f"*NODE PRINT, NSET=NRF{f}", "RF"] if has_rf else []
    if kind in ("fric", "lame"):
        return [f"*NODE PRINT, NSET=NALL{f}", "U"] + rf + [f"*CONTACT FILE{f}", "CDIS, CSTR", f"*EL PRINT, ELSET=EALL{f}", "S, E"]
    return rf + [f"*EL PRINT, ELSET=EALL{f}", "S, ELSE, EVOL"]


def translate(src: pathlib.Path, dst: pathlib.Path, kind: str, npz: pathlib.Path | None, opts: dict) -> dict:
    """Abaqus .inp → ccx .inp。kind = fric | bond | intact | lame。返回翻译记录（步名、过盈处理、接触参数）。"""
    B = _blocks(src.read_text().splitlines())
    m = dict(np.load(npz)) if npz is not None and npz.exists() else {}
    rec = {"kind": kind, "steps": [], "interference": None}
    nodes, elsets, conn = {}, [], {}
    for head, data in B:
        if _kw(head) == "*NODE":
            for s in data:
                p = s.split(",")
                nodes[int(p[0])] = np.array([float(p[1]), float(p[2]), float(p[3])])
        elif _kw(head) == "*ELEMENT":
            elsets.append(_param(head, "ELSET"))
            for s in data:
                p = [int(x) for x in s.replace(",", " ").split()]
                conn[p[0]] = p[1:]
    delta = None
    if kind in ("fric", "lame"):
        cl = [(h, d) for h, d in B if _kw(h) == "*CLEARANCE"]
        if cl:
            delta = -float(cl[0][1][0].split(",")[1])
        mode = opts["interference"] if delta else "none"
        rec["interference"] = {"mode": mode, "delta": delta}
        if mode == "offset":                                   # 柄侧孪生节点沿柄外法向移出 δ_i（与 Abaqus offset 法相同）
            di = m["pair_interf"]
            for t, v, dd in zip(m["pair_stem"], m["pair_normal"], di):
                if dd > 0:
                    nodes[int(t)] = nodes[int(t)] + dd * v
            rec["interference"]["n_offset"] = int((di > 0).sum())
    out = ["** translated from Abaqus input by v2/ccx_port.py for CalculiX 2.23", "*NODE"]
    out += [f"{n}, {x[0]:.10g}, {x[1]:.10g}, {x[2]:.10g}" for n, x in sorted(nodes.items())]
    lam = opts.get("stick_slope")
    step, i, seen_step = None, 0, False
    rf_nodes = set()
    for head, data in B:
        k = _kw(head)
        if k in ("*NODE", "*HEADING"):
            continue
        if k == "*STEP" and not seen_step:
            seen_step = True
            out += ["*NSET, NSET=NALL"] + [", ".join(map(str, c)) for c in _chunks(sorted(nodes))]
            out += ["*ELSET, ELSET=EALL", ", ".join(e for e in elsets if e)]
            nrf = sorted(rf_nodes)
            if nrf:
                out += ["*NSET, NSET=NRF"] + [", ".join(map(str, c)) for c in _chunks(nrf)]
            rec["n_rf_nodes"] = len(nrf)
        if k == "*NSET" and _param(head, "NSET") in ("FIXED", "HEADN"):
            for s in data:
                rf_nodes.update(int(x) for x in s.replace(",", " ").split())
        if k == "*FRICTION":
            mu = float(data[0].split(",")[0])
            if mu <= 0:                                          # ccx 要求 μ > 0；无摩擦即不写 *FRICTION
                rec["friction"] = {"mu": 0.0}
                continue
            if lam is None:
                raise ValueError("stick_slope not set")
            out += ["*FRICTION", f"{mu:g}, {lam:g}"]
            rec["friction"] = {"mu": mu, "stick_slope": lam}
            continue
        if k == "*SURFACE BEHAVIOR":
            nb = opts["normal"]
            out += ["*SURFACE BEHAVIOR, PRESSURE-OVERCLOSURE=LINEAR", f"{nb[0]:g}, {nb[1]:g}"]
            rec["normal"] = nb
            continue
        if k == "*CONTACT PAIR":
            h = "*CONTACT PAIR, INTERACTION=FRIC, TYPE=SURFACE TO SURFACE" + (", SMALL SLIDING" if opts["small_sliding"] else "")
            if rec["interference"] and rec["interference"]["mode"] == "split":
                out += _split_surfaces(B, conn, m, delta)
                out += [h, "S_BONE_I, S_STEM", "S_BONE_N, S_STEM", f"*CLEARANCE, MASTER=S_STEM, SLAVE=S_BONE_I, VALUE={-delta:g}"]
            else:
                out += [h] + data
            continue
        if k in ("*CLEARANCE", "*CONTACT INTERFERENCE", "*OUTPUT", "*NODE OUTPUT", "*ELEMENT OUTPUT", "*CONTACT OUTPUT"):
            continue
        if k == "*STEP":
            step = _param(head, "NAME") or f"STEP{len(rec['steps']) + 1}"
            rec["steps"].append(step)
            out.append(_strip_param(head, "NAME"))
            continue
        if k == "*END STEP":
            out += _outputs(kind, bool(rf_nodes), opts.get("freq", 0)) + ["*END STEP"]
            continue
        out += [head] + data
    dst.write_text("\n".join(out) + "\n")
    return rec


def _chunks(xs, n=16):
    return [xs[i:i + n] for i in range(0, len(xs), n)]


def _split_surfaces(B, conn, m, delta) -> list[str]:
    """从面（S_BONE_S1..S4 单元集）按节点过盈分两组：≥ 一半节点有过盈 → S_BONE_I（−δ），其余 → S_BONE_N。"""
    di = dict(zip(m["pair_bone"].astype(int), m["pair_interf"]))
    sets = {(_param(h, "ELSET") or ""): d for h, d in B if _kw(h) == "*ELSET"}
    groups = {"I": {}, "N": {}}
    for fc in (1, 2, 3, 4):
        els = sets.get(f"S_BONE_S{fc}")
        if not els:
            continue
        for e in (int(x) for s in els for x in s.replace(",", " ").split()):
            nn = [conn[e][j] for j in FACE_NODES[fc]]
            frac = np.mean([di.get(n, 0.0) > 0 for n in nn])
            groups["I" if frac >= 0.5 else "N"].setdefault(fc, []).append(e)
    out = []
    for g, by in groups.items():
        for fc, els in sorted(by.items()):
            out += [f"*ELSET, ELSET=S_BONE_{g}_S{fc}"] + [", ".join(map(str, c)) for c in _chunks(sorted(els))]
        out += [f"*SURFACE, TYPE=ELEMENT, NAME=S_BONE_{g}"] + [f"S_BONE_{g}_S{fc}, S{fc}" for fc in sorted(by)]
    return out


# ------------------------------------------------------------------------------------------------ 结果读取
_DAT_HEAD = re.compile(r"^\s*(displacements|forces|stresses|strains|internal energy|volume)\b.*?for\s*set (\S+) and time\s+(\S+)", re.I)
_FEXP = re.compile(r"(\d)([+-]\d{3})$")


def _fl(x: str) -> float:
    """Fortran 的 E 格式在指数 ≤ −100 时省掉 E（如 0.123456-100）。"""
    try:
        return float(x)
    except ValueError:
        return float(_FEXP.sub(r"\1E\2", x))


def read_dat(path: pathlib.Path) -> list[dict]:
    """ccx .dat → [{var, set, time, rows: ndarray}]（按出现顺序）。"""
    blocks, cur = [], None
    with open(path) as fh:
        for ln in fh:
            mm = _DAT_HEAD.match(ln)
            if mm:
                cur = {"var": mm.group(1).lower(), "set": mm.group(2).upper(), "time": float(mm.group(3)), "rows": []}
                blocks.append(cur)
                continue
            s = ln.split()
            if cur is None or not s:
                continue
            try:
                cur["rows"].append([_fl(x) for x in s])
            except ValueError:
                cur = None
    for b in blocks:
        b["rows"] = np.array(b["rows"]) if b["rows"] else np.zeros((0, 0))
    return blocks


def read_frd_contact(path: pathlib.Path) -> list[dict]:
    """ccx .frd 的 CONTACT 结果块 → [{time, step, comps, node, val}]。"""
    out, cur = [], None
    t = stp = None
    with open(path) as fh:
        for ln in fh:
            if ln.startswith("  100C"):
                t = float(ln.split()[2])
                continue
            if ln.startswith(" -4"):
                name = ln[3:13].strip()
                cur = {"name": name, "time": t, "step": stp, "comps": [], "node": [], "val": []} if name == "CONTACT" else None
                if cur is not None:
                    out.append(cur)
                continue
            if cur is None:
                continue
            if ln.startswith(" -5"):
                c = ln[3:13].strip()
                if c.upper() != "ALL":
                    cur["comps"].append(c)
            elif ln.startswith(" -1"):
                x = ln.rstrip("\n")
                nv = len(cur["comps"])
                cut = len(x) - 12 * nv
                cur["node"].append(int(x[3:cut]))
                cur["val"].append([_fl(x[cut + 12 * j:cut + 12 * j + 12]) for j in range(nv)])
            elif ln.startswith(" -3"):
                cur = None
    for b in out:
        b["node"], b["val"] = np.array(b["node"], int), np.array(b["val"])
    return out


def _step_index(times: list[float]) -> list[int]:
    """各输出块属于第几步（每步时长 1）。总时间（单调增、超过 1）按 ceil(t) − 1；步时间（每步从头计）按时间回落分段。"""
    if not times:
        return []
    if max(times) > 1.0 + 1e-9:
        return [int(np.ceil(t - 1e-9)) - 1 for t in times]
    k, out = 0, []
    for i, t in enumerate(times):
        if i and t < times[i - 1] - 1e-12:
            k += 1
        out.append(k)
    return out


def _at_step_end(blocks, n_steps):
    """每个分析步末（时间到整数）的输出块；某步没走完则为 None。"""
    res = [None] * n_steps
    for b, k in zip(blocks, _step_index([b["time"] for b in blocks])):
        if 0 <= k < n_steps and b["time"] > 0 and abs(b["time"] - round(b["time"])) < 1e-6:
            res[k] = b
    return res


def _last_per_step(blocks, var, sset, n_steps):
    return _at_step_end([b for b in blocks if b["var"] == var and b["set"] == sset], n_steps)


def _write_csv(path, header, rows):
    with open(path, "w") as fh:
        fh.write(",".join(header) + "\n")
        for r in rows:
            fh.write(",".join(repr(float(x)) if not isinstance(x, (int, np.integer, str)) else str(x) for x in r) + "\n")


def _ip_mean(rows):
    """积分点表 [elem, ip, c1..c6] → 单元号、6 分量平均。"""
    el = rows[:, 0].astype(int)
    u, inv = np.unique(el, return_inverse=True)
    s = np.zeros((len(u), rows.shape[1] - 2))
    np.add.at(s, inv, rows[:, 2:])
    cnt = np.bincount(inv)
    return u, s / cnt[:, None]


def _mises(s):
    sx, sy, sz, sxy, sxz, syz = s.T
    return np.sqrt(0.5 * ((sx - sy) ** 2 + (sy - sz) ** 2 + (sz - sx) ** 2) + 3 * (sxy ** 2 + sxz ** 2 + syz ** 2))


def _principal(e):
    T = np.zeros((len(e), 3, 3))
    T[:, 0, 0], T[:, 1, 1], T[:, 2, 2] = e[:, 0], e[:, 1], e[:, 2]
    T[:, 0, 1] = T[:, 1, 0] = e[:, 3]; T[:, 0, 2] = T[:, 2, 0] = e[:, 4]; T[:, 1, 2] = T[:, 2, 1] = e[:, 5]
    w = np.linalg.eigvalsh(T)
    return w[:, ::-1]


# C3D10 形函数导数（自然坐标 ξ, η, ζ；节点 1 在原点，2 在 ξ=1，3 在 η=1，4 在 ζ=1）与 4 点积分
_IP = np.array([[0.1381966011250105] * 3, [0.5854101966249685, 0.1381966011250105, 0.1381966011250105],
                [0.1381966011250105, 0.5854101966249685, 0.1381966011250105], [0.1381966011250105, 0.1381966011250105, 0.5854101966249685]])


def _dN(xi, eta, zeta):
    L1 = 1 - xi - eta - zeta
    d = np.zeros((10, 3))
    dL = np.array([[-1, -1, -1], [1, 0, 0], [0, 1, 0], [0, 0, 1]], float)
    L = [L1, xi, eta, zeta]
    for a in range(4):
        d[a] = (4 * L[a] - 1) * dL[a]
    for k, (a, b) in enumerate(((0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3))):
        d[4 + k] = 4 * (L[a] * dL[b] + L[b] * dL[a])
    return d


_DN = np.stack([_dN(*p) for p in _IP])                                  # (4, 10, 3)


def stem_nodal_forces(X: dict, U: np.ndarray, conn: np.ndarray, E: float, nu: float) -> dict:
    """柄单元内力 f = Σ_ip w·detJ·(∂N/∂x)·σ，线弹性。X: 节点号 → 坐标；U: (n+1, 3) 位移表。返回 节点号 → 力。"""
    lam_, G = E * nu / ((1 + nu) * (1 - 2 * nu)), E / (2 * (1 + nu))
    Xe = np.stack([np.stack([X[int(n)] for n in c]) for c in conn])       # (ne, 10, 3)
    Ue = U[conn]                                                         # (ne, 10, 3)
    F = np.zeros((len(conn), 10, 3))
    for q in range(4):
        Jm = np.einsum("eai,aj->eij", Xe, _DN[q])                       # J_ij = Σ_a x_ai dN_a/dξ_j
        Ji = np.linalg.inv(Jm)
        dx = np.einsum("aj,eji->eai", _DN[q], Ji)                       # ∂N_a/∂x_i
        gu = np.einsum("eai,eaj->eij", Ue, dx)                          # ∂u_i/∂x_j
        eps = 0.5 * (gu + gu.transpose(0, 2, 1))
        tr = np.trace(eps, axis1=1, axis2=2)
        sig = 2 * G * eps + lam_ * tr[:, None, None] * np.eye(3)
        F += np.einsum("e,eaj,eij->eai", np.linalg.det(Jm) / 24.0, dx, sig)
    out = {}
    flat_n, flat_f = conn.ravel(), F.reshape(-1, 3)
    u, inv = np.unique(flat_n, return_inverse=True)
    acc = np.zeros((len(u), 3)); np.add.at(acc, inv, flat_f)
    return dict(zip(u.tolist(), acc))


def convert(d: pathlib.Path, name: str, kind: str, rec: dict, mat: dict | None = None) -> dict:
    """ccx 结果 → <name>_csv/ 下与 odb_export 相同的 CSV。"""
    out = d / f"{name}_csv"
    out.mkdir(exist_ok=True)
    blocks = read_dat(d / f"ccx_{name}.dat")
    steps = rec["steps"]
    ns = len(steps)
    info = {"n_dat_blocks": len(blocks), "dat_times": sorted({b["time"] for b in blocks})[:40]}
    if kind in ("fric", "lame"):
        Ub = _last_per_step(blocks, "displacements", "NALL", ns)
        Sb = _last_per_step(blocks, "stresses", "EALL", ns)
        Eb = _last_per_step(blocks, "strains", "EALL", ns)
        Rb = _last_per_step(blocks, "forces", "NRF", ns)
        frd = read_frd_contact(d / f"ccx_{name}.frd")
        Cb = _at_step_end(frd, ns)
        info["n_contact_blocks"] = len(frd)
        info["contact_comps"] = frd[0]["comps"] if frd else None
        m = dict(np.load(d / "mesh3d.npz"))
        mu = rec.get("friction", {}).get("mu", 0.0)
        for k, s in enumerate(steps):
            if Ub[k] is None:
                raise RuntimeError(f"no displacement output at the end of step {s}")
            u = Ub[k]["rows"]
            _write_csv(out / f"{s}_U.csv", ["node", "u1", "u2", "u3"], [(int(r[0]), r[1], r[2], r[3]) for r in u])
            if Rb[k] is not None:
                rr = Rb[k]["rows"]
                _write_csv(out / f"{s}_RF.csv", ["node", "rf1", "rf2", "rf3"],
                           [(int(r[0]), r[1], r[2], r[3]) for r in rr if np.abs(r[1:4]).max() > 0])
            if Sb[k] is not None:
                el, sm = _ip_mean(Sb[k]["rows"])
                _write_csv(out / f"{s}_S.csv", ["elem", "mises", "s11", "s22", "s12"],
                           [(int(e), v, a[0], a[1], a[3]) for e, v, a in zip(el, _mises(sm), sm)])
            if Eb[k] is not None:
                el, em = _ip_mean(Eb[k]["rows"])
                pr = _principal(em)
                _write_csv(out / f"{s}_E.csv", ["elem", "e_max", "e_mid", "e_min"], [(int(e), *p) for e, p in zip(el, pr)])
            if Cb[k] is not None:
                c = Cb[k]
                comp = [x.upper() for x in c["comps"]]
                col = {n: comp.index(n) for n in ("COPEN", "CSLIP1", "CSLIP2", "CPRESS", "CSHEAR1", "CSHEAR2") if n in comp}
                rows = []
                for n, v in zip(c["node"], c["val"]):
                    for f, j in col.items():
                        rows.append((f, int(n), v[j]))
                    p, tau = v[col["CPRESS"]], np.hypot(v[col["CSHEAR1"]], v[col["CSHEAR2"]])
                    status = 0.0 if p <= 0 else (1.0 if (mu > 0 and tau >= 0.999 * mu * p) else 2.0)
                    rows.append(("CSTATUS", int(n), status))
                _write_csv(out / f"{s}_CONTACT.csv", ["field", "node", "value"], rows)
            if kind == "fric" and mat is not None:                     # 节点接触力：柄单元内力在界面孪生节点上
                n = int(m["node_labels"].max())
                U = np.zeros((n + 1, 3)); U[u[:, 0].astype(int)] = u[:, 1:4]
                X = {int(a): b for a, b in zip(m["node_labels"], m["nodes"])}
                if rec["interference"] and rec["interference"]["mode"] == "offset":
                    for t, vv, dd in zip(m["pair_stem"], m["pair_normal"], m["pair_interf"]):
                        if dd > 0:
                            X[int(t)] = X[int(t)] + dd * vv
                fs = stem_nodal_forces(X, U, m["stem_conn"], mat["E"], mat["nu"])
                rows = []
                for b, t in zip(m["pair_bone"], m["pair_stem"]):
                    f = -fs.get(int(t), np.zeros(3))                   # 柄对骨的力 = −(骨对柄的力)
                    rows.append(("CNORMF", int(b), f[0], f[1], f[2]))
                _write_csv(out / f"{s}_CFORCE.csv", ["field", "node", "f1", "f2", "f3"], rows)
    else:
        Sb = _last_per_step(blocks, "stresses", "EALL", ns)[-1]
        Eb = _last_per_step(blocks, "internal energy", "EALL", ns)[-1]
        Vb = _last_per_step(blocks, "volume", "EALL", ns)[-1]
        s = steps[-1]
        if Sb is None or Eb is None or Vb is None:
            raise RuntimeError("missing S / ELSE / EVOL output in the last step")
        el, sm = _ip_mean(Sb["rows"])
        _write_csv(out / f"{s}_S.csv", ["elem", "mises", "s11", "s22", "s12"],
                   [(int(e), v, a[0], a[1], a[3]) for e, v, a in zip(el, _mises(sm), sm)])
        ev = dict(zip(Vb["rows"][:, 0].astype(int), Vb["rows"][:, 1]))
        _write_csv(out / f"{s}_ENER.csv", ["elem", "else", "evol"], [(int(r[0]), r[1], ev[int(r[0])]) for r in Eb["rows"]])
    return info


# ------------------------------------------------------------------------------------------------ 求解
def run_ccx(d: pathlib.Path, name: str, cpus: int, timeout: float) -> dict:
    env = {**os.environ, "OMP_NUM_THREADS": str(cpus), "CCX_NPROC_EQUATION_SOLVER": str(cpus)}
    t0 = time.time()
    with open(d / f"ccx_{name}.log", "w") as log:
        try:
            p = subprocess.run([str(CCX), "-i", f"ccx_{name}"], cwd=d, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
            rc = p.returncode
        except subprocess.TimeoutExpired:
            return {"status": "L4", "reason": f"timeout {timeout:.0f} s", "wall_s": time.time() - t0}
    txt = (d / f"ccx_{name}.log").read_text(errors="replace")
    err = [ln for ln in txt.splitlines() if "*ERROR" in ln]
    ok = rc == 0 and not err and "Job finished" in txt
    return {"status": "OK" if ok else "L4", "reason": "" if ok else (err[0] if err else f"rc={rc}; " + txt[-300:]),
            "wall_s": time.time() - t0, "warnings": sum("*WARNING" in ln for ln in txt.splitlines())}


def _materials(inp: pathlib.Path) -> dict:
    B = _blocks(inp.read_text().splitlines())
    mats, cur = {}, None
    for h, dta in B:
        if _kw(h) == "*MATERIAL":
            cur = _param(h, "NAME")
        elif _kw(h) == "*ELASTIC" and cur:
            e, nu = [float(x) for x in dta[0].split(",")[:2]]
            mats[cur.upper()] = {"E": e, "nu": nu}
    return mats


def stick_slope(cpress_p50: float, mu: float) -> float:
    """与 Abaqus 罚摩擦等效的粘着刚度：Abaqus 在压力 p 时的切向罚刚度 = μp/γ_crit（γ_crit ≈ 0.5 µm）。"""
    return float(mu * cpress_p50 / GAMMA_ABQ)


def solve_job(d: pathlib.Path, cpus: int, opts: dict) -> dict:
    """d 里有 Abaqus 的 *.inp（jobs.prep 生成）→ 翻译、求解、转换 → solve.json；全部成功写 SOLVED。"""
    res = {}
    for inp in sorted(d.glob("*.inp"), key=lambda p: (not p.stem.endswith("fric"), p.name)):
        if inp.name.startswith("ccx_"):
            continue
        name = inp.stem
        kind = "lame" if name.startswith("lame") else ("fric" if name.endswith("fric") else ("intact" if name == "intact" else "bond"))
        try:
            rec = translate(inp, d / f"ccx_{name}.inp", kind, d / "mesh3d.npz", opts)
            r = run_ccx(d, name, cpus, opts["timeout"])
            r["translate"] = rec
            if r["status"] == "OK":
                mats = _materials(inp)
                r["convert"] = convert(d, name, kind, rec, mats.get("TI6AL4V"))
                for ext in (".frd", ".dat", ".inp", ".12d"):
                    (d / f"ccx_{name}{ext}").unlink(missing_ok=True)
                (d / "spooles.out").unlink(missing_ok=True)
        except Exception as e:                                              # noqa: BLE001
            r = {"status": "L5", "reason": f"{type(e).__name__}: {e}\n{traceback.format_exc()[-1200:]}"}
        res[name] = r
        if r["status"] != "OK":
            break
    (d / "solve.json").write_text(json.dumps(res, indent=1, default=float))
    if all(v["status"] == "OK" for v in res.values()) and res:
        (d / "SOLVED").write_text(time.strftime("%Y-%m-%d %H:%M:%S"))
    return res


# ------------------------------------------------------------------------------------------------ 队列（复用 jobs.prep / jobs.post）
def _use_ccx_queue():
    J.QROOT, J.RESULTS = CQ, CRES
    CQ.mkdir(parents=True, exist_ok=True); CRES.mkdir(parents=True, exist_ok=True)


def setup(jids: list[str]) -> list[str]:
    """复制原作业的 spec.json 到 ccx 队列（同一 job_id）。完整股骨参照用原设计作业所用的那一个。"""
    _use_ccx_queue()
    src = pathlib.Path.home() / "mobo_toy_v2" / "queue"
    need = set(jids)
    for j in jids:
        r = json.loads((src / j / "result.json").read_text())
        if r.get("intact_job"):
            need.add(r["intact_job"])
    for j in sorted(need):
        (CQ / j).mkdir(exist_ok=True)
        if not (CQ / j / "spec.json").exists():
            shutil.copy2(src / j / "spec.json", CQ / j / "spec.json")
    return sorted(need)


def mesh_check(j: str) -> dict:
    """重建的网格与原作业对照：各区四面体数、界面节点对数、界面面积。"""
    src = pathlib.Path.home() / "mobo_toy_v2" / "queue" / j / "prep.json"
    new = CQ / j / "prep.json"
    if not src.exists() or not new.exists():
        return {"checked": False}
    a, b = json.loads(src.read_text()), json.loads(new.read_text())
    keys = ("n_tet", "n_pairs", "interface_area_mm2", "n_nodes")
    same = all(a.get(k) == b.get(k) for k in keys)
    return {"checked": True, "identical": same, **{k: [a.get(k), b.get(k)] for k in keys if a.get(k) != b.get(k)},
            "code_hash": [a.get("code_hash"), b.get("code_hash")]}         # 完整股骨参照建于更早的代码，模型本身没变


def _same_intact(j: str) -> None:
    """后处理用与原作业相同的完整股骨参照（ccx 算的那一份），不按"最新的参照"自动挑。"""
    src = pathlib.Path.home() / "mobo_toy_v2" / "queue" / j / "result.json"
    rid = json.loads(src.read_text()).get("intact_job") if src.exists() else None
    if not rid:
        return

    def ref(h_int, E_canc=None):
        p = CQ / rid / "result.json"
        if not p.exists():
            raise FileNotFoundError(f"CalculiX intact reference {rid} not DONE")
        r = json.loads(p.read_text())
        r["intact_job"], r["intact_substituted_h"] = rid, None
        return r
    J.intact_ref = ref


def run(jids: list[str], cpus: int, opts: dict) -> None:
    _use_ccx_queue()
    if (CQ / "opts.json").exists():                                     # 变体目录的求解参数覆盖
        ov = json.loads((CQ / "opts.json").read_text())
        opts = {**opts, **{k: (tuple(v) if k == "normal" else v) for k, v in ov.items()}}
    for j in jids:
        d = CQ / j
        t0 = time.time()
        _same_intact(j)
        st = J.prep(j)
        mc = mesh_check(j)
        (d / "mesh_check.json").write_text(json.dumps(mc))
        if st == "READY":
            spec = json.loads((d / "spec.json").read_text())
            o = {**opts, "stick_slope": opts.get("stick_slope") or stick_slope(P50_ABQ, float(spec.get("mu") or 0.3))}
            r = solve_job(d, cpus, o)
            st = J.post(j) if (d / "SOLVED").exists() else "SOLVE-FAILED"
            if st == "SOLVE-FAILED":
                k, v = next((k, v) for k, v in r.items() if v["status"] != "OK")
                J._fail(d, v["status"], "solve", f"{k}: {v.get('reason', '')}")
        print(time.strftime("%H:%M:%S"), j, st, f"{time.time() - t0:.0f} s", json.dumps(mc), flush=True)


PHASES = (5, 6, 1, 2, 3)                    # 新两阶段 → 原两阶段 → 联合


def phase_jobs(phases) -> list[str]:
    """各优化阶段记录里的作业（按评估顺序，去重；只取原作业有 result.json 的）。"""
    out = []
    for k in phases:
        st = json.loads((pathlib.Path.home() / "mobo_toy_v2" / "results" / f"neckopt_p{k}.json").read_text())
        for r in st["records"]:
            j = r["job_id"]
            if j not in out and (pathlib.Path.home() / "mobo_toy_v2" / "queue" / j / "result.json").exists():
                out.append(j)
    return out


# ------------------------------------------------------------------------------------------------ 调度（只用 Linux，资源受控，可随时暂停）
CTL = BASE / "control.json"
STATUS = BASE / "status.json"
MANIFEST = BASE / "batch.json"
# 资源规则（用户 2026-10-05：存储与内存不过载、留核心给日常使用、可随时暂停）
#   CPU   只用物理核 2–5（逻辑 CPU 4–11），物理核 0–1（逻辑 0–3）完全空出；作业进程 nice 19，日常程序始终优先
#   内存  每个作业进程地址空间上限 mem_limit_gb；可用内存 < min_avail_gb 不派新作业；< kill_below_gb 终止最新的作业并放回队列
#   磁盘  剩余 < min_disk_gb 不派新作业；每个作业完成后删掉 .frd/.dat 和翻译后的 .inp，只留 CSV、mesh3d.npz、结果与日志
#   暂停  ctl pause：所有作业进程组 SIGSTOP（CPU 立即归零，内存保留）；ctl resume：SIGCONT 接着算
DEFAULT_CTL = {"paused": False, "stop": False, "stop_now": False, "slots": [[4, 5, 6, 7], [8, 9, 10, 11]], "threads": 2,
               "nice": 19, "mem_limit_gb": 12, "min_avail_gb": 10, "kill_below_gb": 3, "min_disk_gb": 30}


def ctl_read() -> dict:
    c = dict(DEFAULT_CTL)
    try:
        c.update(json.loads(CTL.read_text()))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return c


def ctl_write(**kw) -> dict:
    BASE.mkdir(parents=True, exist_ok=True)
    c = ctl_read()
    c.update(kw)
    tmp = CTL.with_suffix(".tmp")
    tmp.write_text(json.dumps(c, indent=1))
    tmp.replace(CTL)
    return c


def _mem_avail_gb() -> float:
    for ln in open("/proc/meminfo"):
        if ln.startswith("MemAvailable:"):
            return int(ln.split()[1]) / 2 ** 20
    return float("nan")


def _disk_free_gb() -> float:
    return shutil.disk_usage(BASE).free / 1e9


def _requeue_clean(d: pathlib.Path) -> None:
    """被终止的作业放回队列：删掉求解的中间与输出文件，保留已建好的模型（READY 与 Abaqus .inp），重跑时不再建模。"""
    for f in list(d.glob("ccx_*")) + [d / "spooles.out", d / "solve.json", d / "SOLVED", d / "FAILED.json"]:
        if f.name != "ccx_run.log":
            f.unlink(missing_ok=True)
    for c in d.glob("*_csv"):
        shutil.rmtree(c, ignore_errors=True)


def _spawn(e: str, cpus: list[int], c: dict, opt_args: list[str]) -> subprocess.Popen:
    j, d, extra = _entry(e)
    def pre():
        import resource
        os.setsid()                                         # 自成进程组：暂停 / 终止时连同 ccx 子进程一起
        os.sched_setaffinity(0, cpus)
        os.nice(int(c["nice"]))
        lim = int(c["mem_limit_gb"] * 2 ** 30)
        resource.setrlimit(resource.RLIMIT_AS, (lim, lim))
    d.mkdir(parents=True, exist_ok=True)
    log = open(d / "ccx_run.log", "a")
    return subprocess.Popen([sys.executable, str(HERE / "ccx_port.py"), "run", j, "--cpus", str(c["threads"])] + opt_args + extra,
                            cwd=str(HERE.parent), stdout=log, stderr=subprocess.STDOUT, preexec_fn=pre)


def batch(jids: list[str], opt_args: list[str]) -> None:
    """按给定顺序复算（先完整股骨参照）。可续跑（DONE / FAILED 跳过）。
    控制：ctl pause | resume | stop（跑完在算的就停）| stop-now（立即终止，作业放回队列）| set key=value | status。"""
    need = setup([e.partition("@")[0] for e in jids])
    intact = [j for j in need if j.startswith("ref_intact")]
    for e in jids:                                                      # 变体目录：规格与（线性、与变体无关的）完整股骨参照
        j, d, _ = _entry(e)
        if d.parent != CQ:
            d.parent.mkdir(parents=True, exist_ok=True)
            if not (d / "spec.json").exists():
                d.mkdir(exist_ok=True)
                shutil.copy2(CQ / j / "spec.json", d / "spec.json")
            for i in intact:
                if not (d.parent / i).exists() and (CQ / i / "DONE").exists():
                    shutil.copytree(CQ / i, d.parent / i)
    order = intact + [j for j in jids if j not in intact]
    MANIFEST.write_text(json.dumps({"jobs": order, "intact": intact, "opt_args": opt_args,
                                    "created": time.strftime("%Y-%m-%d %H:%M:%S")}, indent=1))
    queue = [e for e in order if J.state(_entry(e)[1]) not in ("DONE", "FAILED")]
    ctl_write(stop=False, stop_now=False)

    def log(*x):
        print(time.strftime("%m-%d %H:%M:%S"), *x, flush=True)
    log(f"batch: {len(order)} jobs ({len(intact)} intact), {len(queue)} to do")
    running: dict[int, tuple[str, subprocess.Popen, float]] = {}
    stopped, last_block = False, None
    while True:
        c = ctl_read()
        for s, (j, p, t0) in list(running.items()):                         # 收尾
            if p.poll() is not None:
                log(f"slot {s} {j}: {J.state(_entry(j)[1])} ({(time.time() - t0) / 60:.1f} min)")
                del running[s]
        mem, disk = _mem_avail_gb(), _disk_free_gb()
        if c["stop_now"] or (running and mem < c["kill_below_gb"]):          # 立即终止 / 内存告急
            victims = list(running) if c["stop_now"] else [max(running, key=lambda k: running[k][2])]
            for s in victims:
                j, p, _ = running.pop(s)
                os.killpg(p.pid, signal.SIGCONT)
                os.killpg(p.pid, signal.SIGTERM)
                try:
                    p.wait(60)
                except subprocess.TimeoutExpired:
                    os.killpg(p.pid, signal.SIGKILL)
                    p.wait()
                _requeue_clean(_entry(j)[1])
                queue.insert(0, j)
                log(f"slot {s} {j}: terminated and requeued ({'stop-now' if c['stop_now'] else f'MemAvailable {mem:.1f} GB'})")
            if c["stop_now"]:
                c = ctl_write(stop_now=False, stop=True)
        want = bool(c["paused"])
        if want != stopped:                                                   # 暂停 / 继续
            for j, p, _ in running.values():
                os.killpg(p.pid, signal.SIGSTOP if want else signal.SIGCONT)
            stopped = want
            log("paused (SIGSTOP)" if want else "resumed (SIGCONT)")
        if not stopped and not c["stop"]:                                     # 派作业
            for s in [k for k in range(len(c["slots"])) if k not in running]:
                if not queue:
                    break
                block = "memory" if mem < c["min_avail_gb"] else ("disk" if disk < c["min_disk_gb"] else None)
                if not block and queue[0] not in intact and any(J.state(CQ / i) != "DONE" for i in intact):
                    block = "intact reference not done"
                if block:
                    if block != last_block:
                        log(f"dispatch held: {block} (MemAvailable {mem:.1f} GB, disk free {disk:.0f} GB)")
                    last_block = block
                    break
                last_block = None
                j = queue.pop(0)
                running[s] = (j, _spawn(j, c["slots"][s], c, opt_args), time.time())
                log(f"slot {s} {j}: started on CPUs {c['slots'][s]} ({c['threads']} threads, nice {c['nice']})")
        STATUS.write_text(json.dumps({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "paused": stopped, "stop": c["stop"],
                                      "queue": queue, "running": {s: [j, round((time.time() - t) / 60, 1)] for s, (j, _, t) in running.items()},
                                      "mem_avail_gb": round(mem, 1), "disk_free_gb": round(disk, 1)}, indent=1))
        if not running and (not queue or c["stop"]):
            log("batch finished" if not queue else "batch stopped")
            break
        time.sleep(10)


def status() -> dict:
    """进度与资源（只读）。"""
    m = json.loads(MANIFEST.read_text())
    st = {}
    for j in m["jobs"]:
        st.setdefault(J.state(_entry(j)[1]), []).append(j)
    walls = {}
    for j in st.get("DONE", []):
        sj = json.loads((_entry(j)[1] / "solve.json").read_text())
        walls[j] = {k: round(v.get("wall_s", 0) / 60, 1) for k, v in sj.items()}
    live = json.loads(STATUS.read_text()) if STATUS.exists() else {}
    c = ctl_read()
    return {"counts": {k: len(v) for k, v in st.items()}, "failed": st.get("FAILED", []), "solve_min": walls, "live": live,
            "control": {k: c[k] for k in ("paused", "stop", "slots", "threads", "nice", "mem_limit_gb", "min_avail_gb", "min_disk_gb")}}


def lame(opts: dict, cpus: int = 4) -> dict:
    """Lamé 对照：与 Abaqus 的 m1_lame.json 同设置（h 2，δ 0.10，μ 0），压力由套筒外表面膨胀反推。"""
    import model3d_m1 as M1
    import post_m1 as PM1
    d = BASE / f"lame_{opts['interference']}"
    shutil.rmtree(d, ignore_errors=True)
    M1.build_lame(d, "lame", h=2.0, delta=0.10, mu=0.0, interference="clearance")
    o = {**opts, "stick_slope": opts.get("stick_slope") or 1.0}
    r = solve_job(d, cpus, o)
    out = {"solve": r}
    if (d / "SOLVED").exists():
        out["lame"] = PM1.lame(d)
    return out


def compare(jids: list[str]) -> list[dict]:
    keys = ("f1_p95_um", "f1_all_p95_um", "f1_closed_p95_um", "f1_first_p95_um", "open_frac_load2", "area_frac_gt40",
            "collar_force_share_load2", "collar_open_frac_load2", "cpress_release_p50", "f2_g7_loss_pct", "f2_g1_loss_pct", "vm_p99")
    rows = []
    for j in jids:
        pa = pathlib.Path.home() / "mobo_toy_v2" / "queue" / j / "result.json"
        pb = CQ / j / "result.json"
        if not (pa.exists() and pb.exists()):
            rows.append({"job": j, "state": "missing"}); continue
        a, b = json.loads(pa.read_text()), json.loads(pb.read_text())
        rows.append({"job": j, **{k: [a.get(k), b.get(k)] for k in keys},
                     "wall_ccx_s": {k: v.get("wall_s") for k, v in b.get("solve", {}).items()},
                     "wall_abq_s": {k: v.get("wall_s") for k, v in a.get("solve", {}).items()}})
    return rows


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["lame", "setup", "run", "batch", "compare", "ctl"])
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--cpus", type=int, default=4)
    ap.add_argument("--phases", default=None, help="不给 ids 时按优化阶段取全部设计，如 5,6,1,2,3")
    ap.add_argument("--interference", choices=["offset", "split"], default=OPTS["interference"])
    ap.add_argument("--normal", default="50000,0.005", help="K,sigma_inf（LINEAR）")
    ap.add_argument("--stick", type=float, default=None)
    ap.add_argument("--queue", default="queue", help="作业目录名（变体：queue_<变体>）")
    a = ap.parse_args()
    _set_queue(a.queue)
    opts = {**OPTS, "interference": a.interference, "stick_slope": a.stick, "normal": tuple(float(x) for x in a.normal.split(","))}
    if a.cmd == "lame":
        print(json.dumps(lame(opts, a.cpus), indent=1, default=float))
    elif a.cmd == "setup":
        print(json.dumps(setup(a.ids)))
    elif a.cmd == "run":
        run(a.ids, a.cpus, opts)
    elif a.cmd == "batch":
        oa = ["--interference", a.interference, "--normal", a.normal] + (["--stick", str(a.stick)] if a.stick else [])
        batch(a.ids or phase_jobs(tuple(int(x) for x in a.phases.split(","))), oa)
    elif a.cmd == "ctl":
        cmd = a.ids[0] if a.ids else "status"
        if cmd == "pause":
            print(ctl_write(paused=True))
        elif cmd == "resume":
            print(ctl_write(paused=False, stop=False))
        elif cmd == "stop":
            print(ctl_write(stop=True))
        elif cmd == "stop-now":
            print(ctl_write(stop_now=True))
        elif cmd == "set":
            print(ctl_write(**{k: json.loads(v) for k, v in (x.split("=", 1) for x in a.ids[1:])}))
        else:
            print(json.dumps(status(), indent=1, default=float))
    else:
        for r in compare(a.ids):
            print(json.dumps(r, default=float))
