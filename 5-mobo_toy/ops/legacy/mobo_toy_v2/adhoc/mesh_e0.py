"""E0 网格收敛研究（用户 2026-10-05 批准，求解器 Abaqus）。
只读原作业的 spec.json，按原设置复制、只改网格（界面 h_int、远场 h_far）和随网格换算的滑移容差，
提交 kind = variant、stage = mesh 的新作业；不进任何优化数据集，不改仓库代码。

    run.sh adhoc/mesh_e0.py submit <group>   group: pilot | a14 | a10 | a07 | b | x
    run.sh adhoc/mesh_e0.py status
    run.sh adhoc/mesh_e0.py list

容差换算：Abaqus 的弹性滑移上限 = slip_tol × 特征单元长度。生产网格 2.0 mm 用 2.5e-4（约 0.5 µm）；
为了只看网格本身的影响，各级按"绝对弹性滑移不变"换算：1.4 mm → 3.57143e-4（与 A 段相同写法），1.0 → 5e-4，0.7 → 7.14286e-4。
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

CODE = pathlib.Path.home() / "mobo_toy_v2" / "code"
sys.path[:0] = [str(CODE / "v2"), str(CODE)]
import jobs as J  # noqa: E402

DESIGNS = {
    "a40": "neck3_a40_967145a2",    # 联合最优，柄身 0.99 µm
    "r11": "neck2_r11_0b9c7ed8",    # 原分法第二阶段最优，1.44 µm
    "r7": "neck5_r7_5df27b13",      # 新分法长柄，0.96 µm
    "r3": "neck3_r3_915160d1",      # 20 mm 短柄宽领，51 µm
    "r6": "neck1_r6_20136980",      # 截深 31.9 mm，4.77 µm
    "r1": "neck5_r1_0730dc8f",      # 松动设计，216 µm
    "a75": "neck3_a75_562c9b0f",    # A 段已有 1.4 mm（verify_mesh14_3_a75_…），1.23 µm
    "a83": "neck3_a83_4f3a1387",    # A 段已有 1.4 mm（verify_mesh14_3_a83_…），7.45 µm
}
EXISTING_14 = {"a75": "verify_mesh14_3_a75_562c9b0f_dfc1efe1", "a83": "verify_mesh14_3_a83_4f3a1387_74f5c00b"}
TOL = {2.0: 2.5e-4, 1.4: 0.000357143, 1.0: 5e-4, 0.7: 0.000714286}
IDS = J.RESULTS / "mesh_e0_ids.json"


def spec(name: str, h: float, h_far: float | None = None, tol: float | None = None, bond_only: bool = False) -> dict:
    base = json.loads((J.QROOT / DESIGNS[name] / "spec.json").read_text())
    tol = TOL[h] if tol is None else tol
    tag = f"e0_{name}_h{h:g}" + (f"_f{h_far:g}" if h_far else "") + (f"_t{tol:g}" if abs(tol - TOL[h]) > 1e-12 else "") + \
        ("_bond" if bond_only else "")
    s = {k: v for k, v in base.items() if k not in ("stage", "tag", "created", "kind")}
    s.update(kind="variant", stage="mesh", tag=tag, h_int=float(h), slip_tol=float(tol), source_job=DESIGNS[name])
    if h_far is not None:
        s["h_far"] = float(h_far)
    if bond_only:
        s["bond_only"] = True
    return s


def group(g: str) -> dict:
    out = {}
    if g == "pilot":
        for h in (1.0, 0.7):
            out[f"a40_h{h:g}"] = spec("a40", h)
    elif g == "a14":
        for n in DESIGNS:
            if n not in EXISTING_14:
                out[f"{n}_h1.4"] = spec(n, 1.4)
    elif g == "a10":
        for n in DESIGNS:
            if n != "a40":
                out[f"{n}_h1"] = spec(n, 1.0)
    elif g == "a07":
        for n in ("r6", "r3"):
            out[f"{n}_h0.7"] = spec(n, 0.7)
    elif g == "b":
        for h, hf in ((1.4, 4.2), (1.0, 3.0)):
            for n in DESIGNS:
                full = n in ("a40", "r6", "r3")
                out[f"{n}_h{h:g}_f{hf:g}" + ("" if full else "_bond")] = spec(n, h, h_far=hf, bond_only=not full)
    elif g == "x":
        for n in ("a40", "r3"):
            out[f"{n}_h1_t2.5e-4"] = spec(n, 1.0, tol=2.5e-4)
    else:
        raise SystemExit(f"unknown group {g}")
    return out


def submit(g: str) -> None:
    old = json.loads(IDS.read_text()) if IDS.exists() else {"jobs": {}, "groups": {}}
    sp = group(g)
    new = {k: J.submit(v) for k, v in sp.items()}
    old["jobs"].update(new)
    old["groups"][g] = sorted(new)
    old["existing_1.4"] = EXISTING_14
    old["designs"] = DESIGNS
    old["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    IDS.write_text(json.dumps(old, indent=1))
    print(json.dumps(new, indent=1))


def status() -> None:
    ids = json.loads(IDS.read_text())["jobs"]
    st = {}
    for k, j in sorted(ids.items()):
        s = J.state(J.QROOT / j)
        st.setdefault(s, []).append(k)
        if s == "FAILED":
            f = json.loads((J.QROOT / j / "FAILED.json").read_text())
            print("FAILED", k, f.get("level"), (f.get("reason") or "")[:200].replace("\n", " | "))
    print(json.dumps({k: v for k, v in st.items()}, indent=0))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "submit":
        submit(sys.argv[2])
    elif cmd == "status":
        status()
    elif cmd == "list":
        for g in ("pilot", "a14", "a10", "a07", "b", "x"):
            for k, v in group(g).items():
                print(g, k, v["h_int"], v.get("h_far"), v["slip_tol"], v.get("bond_only", False))
