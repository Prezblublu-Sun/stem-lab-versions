"""db3406 主动学习的局部候选（0 FE；用户 2026-11-01 批准 AL-3）。AL-2 的选点说明固定候选池（6.5 万 Sobol + 4096 角落子盒）里离 FE
最好的设计都很远：去骨 ≤ 6 cm³ 的最好（AL-1 第 7 号 0.102°）比池里任何点的预测都好 7σ 以上，各上限问题的 P（改进）全部 < 1 %。
这里以导出里 FE 最好的设计为中心，在单位坐标里取扰动点；之后交 tpl_record batch 模板化、pool_area_features 补面积量，作为
stage_al 的一个候选来源（stage_al.LOCAL_SOURCES）。只读导出、面积量 json；只写 --out（.npy，N × 13）与 <out>.json。

    python v2/al_local.py <来源名> --export <版本目录> --tpl-area <json> --out results/db_pool/<来源名>_u13.npy [--per-center 200] [--seed S] [--m-min 1.0]
    --m-min（AL-3′）：中心只取 m ≥ m_min 的行，扰动点也必须 m ≥ m_min。

中心（训练行口径 = stage_al.load_training；基线条件、没有强制入口偏移的行）：
    去骨上限 5 / 6 / 8 / 10 cm³ 各取转动最小的 N_CAP 个设计；(log 转动 ↓, log 完全接触 ↑) 的 FE 前沿全部；
    稳健 g = max(楼梯, 起身 3839 N 的 log 转动) 最小的 N_ROB 个（两种条件都有 FE 行的设计）；按 design_key 去重，记下每个中心的全部理由。
扰动：每个中心 per_center 个点。14 维 scrambled Sobol（种子 seed + 中心序号）：前 13 维经标准正态分位数变成方向（单位化），第 14 维给半径
    r = R_MIN + (R_MAX − R_MIN) · v（单位坐标的欧氏距离）。落在单位立方体外的点丢掉（不裁剪：裁剪会改距离），不够就往后接着取 Sobol 点。
    R_MIN 0.03 > stage_al 的近重复门槛 0.02（EVAL_EXCL），所以中心本身附近的点不会全被去掉；R_MAX 0.20 ≈ 池里最近邻距离的量级以下。
记录（<out>.json）：来源名、导出目录与 scalars.csv sha256、面积量文件、中心表（job_id、design_key、理由、u13、三个目标）、参数、本文件 md5、
    点数；点的顺序 = 中心顺序 × 每中心的 Sobol 顺序。--out 已存在就拒绝（不覆盖）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import stage_al as AL  # noqa: E402
import stage_db as DB  # noqa: E402

CAPS_MM3 = (5000.0, 6000.0, 8000.0, 10000.0)
N_CAP, N_ROB = 3, 3
R_MIN, R_MAX = 0.03, 0.20
DIM = 13


def centers(rows: list, m_min: float | None = None) -> list:
    if m_min is not None:
        um = AL.u_of_m(m_min)
        rows = [r for r in rows if r["u13"][AL.U_M] >= um - 1e-12]
    base = [r for r in rows if AL.is_cond(r["cond"], AL.BASE) and r["forced_e"] is None]
    picks = {}

    def add(r, why):
        c = picks.setdefault(r["design_key"], {"job_id": r["job_id"], "design_key": r["design_key"], "u13": [float(x) for x in r["u13"]],
                                               "y": r["y"], "bone_mm3": r["bone"], "why": []})
        if r["y"][0] < c["y"][0]:                      # 同一设计多行：中心取转动最小的那一行（u13 同一个设计相同）
            c.update(job_id=r["job_id"], y=r["y"])
        c["why"].append(why)

    for cap in CAPS_MM3:
        ok = sorted((r for r in base if r["bone"] is not None and r["bone"] <= cap), key=lambda r: r["y"][0])
        for k, r in enumerate(ok[:N_CAP]):
            add(r, f"cap{cap:g}#{k + 1}")
    P = np.array([[r["y"][0], r["y"][1]] for r in base])
    front = AL.pareto_front(P)
    for r in base:
        if any(np.array_equal([r["y"][0], r["y"][1]], f) for f in front):
            add(r, "front")
    by_d = {}
    for r in rows:
        if r["forced_e"] is not None:
            continue
        for tag, ref in (("base", AL.BASE), ("sts", AL.STS)):
            if AL.is_cond(r["cond"], ref):
                d = by_d.setdefault(r["design_key"], {})
                if r["y"][0] < d.get(tag, (9e9, None))[0]:
                    d[tag] = (r["y"][0], r)
    rob = sorted(((max(v["base"][0], v["sts"][0]), v["base"][1]) for v in by_d.values() if "base" in v and "sts" in v), key=lambda t: t[0])
    for k, (_, r) in enumerate(rob[:N_ROB]):
        add(r, f"robust#{k + 1}")
    out = list(picks.values())
    for c in out:
        if np.any(np.asarray(c["u13"]) < 0) or np.any(np.asarray(c["u13"]) > 1):
            raise SystemExit(f"center {c['job_id']}: u13 outside the unit cube")
    return out


def perturb(c: np.ndarray, n: int, seed: int, u_m_min: float | None = None) -> np.ndarray:
    from scipy.stats import norm
    out, start = [], 0
    while len(out) < n:
        m = 1 << max(8, int(np.ceil(np.log2(4 * n))))
        S = DB.sobol(start + m, seed, DIM + 1)[start:]
        start += m
        d = norm.ppf(np.clip(S[:, :DIM], 1e-12, 1 - 1e-12))
        d /= np.linalg.norm(d, axis=1, keepdims=True)
        r = R_MIN + (R_MAX - R_MIN) * S[:, DIM]
        P = c[None, :] + d * r[:, None]
        keep = np.all((P >= 0) & (P <= 1), axis=1)
        if u_m_min is not None:
            keep &= P[:, AL.U_M] >= u_m_min
        out.extend(P[keep])
        if start > 64 * n:
            raise SystemExit(f"center {c}: fewer than {n} perturbations inside the unit cube after {start} Sobol points")
    return np.array(out[:n])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--export", required=True)
    ap.add_argument("--tpl-area", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--per-center", type=int, default=200)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--m-min", type=float)
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    if out.exists() or out.with_suffix(".json").exists():
        raise SystemExit(f"{out} (or its .json) exists; not overwriting")
    area = {k: v for k, v in json.load(open(a.tpl_area))["rows"].items() if v.get("ok")}
    rows, info = AL.load_training(pathlib.Path(a.export), area)
    cs = centers(rows, a.m_min)
    um = None if a.m_min is None else AL.u_of_m(a.m_min)
    U = np.concatenate([perturb(np.asarray(c["u13"]), a.per_center, a.seed + i, um) for i, c in enumerate(cs)])
    np.save(out, U)
    meta = {"tool": "al_local", "name": a.name, "export": {"dir": a.export, "scalars_sha256": DB._sha256_file(pathlib.Path(a.export) / "scalars.csv")},
            "tpl_area": a.tpl_area, "n_train": len(rows), "centers": cs, "per_center": a.per_center, "seed": a.seed, "m_min": a.m_min, "r_min": R_MIN, "r_max": R_MAX,
            "caps_mm3": CAPS_MM3, "n_cap": N_CAP, "n_rob": N_ROB, "n_points": int(len(U)), "u13_sha256": hashlib.sha256(U.tobytes()).hexdigest(),
            "al_local_md5": hashlib.md5(pathlib.Path(__file__).read_bytes()).hexdigest()}
    out.with_suffix(".json").write_text(json.dumps(meta, indent=1))
    print(f"{len(cs)} centers, {len(U)} points -> {out}")
    for c in cs:
        print(f"  {c['job_id']:40s} rot {10 ** c['y'][0]:.3f} deg  contact {10 ** c['y'][1]:.0f} mm2  bone {c['bone_mm3'] or 0:7.0f}  {','.join(c['why'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
