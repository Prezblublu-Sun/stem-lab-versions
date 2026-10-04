"""两阶段怎么分（用户 2026-10-04 12:10）：用已有的 225 个 FE 结果，量各变量的主效应、总效应和两两交互，据此给出分组。0 次 FE。

函数
    微动：E1 模拟器（GP 均值）与 E2 模拟器的 5 条后验样本路径（emulator.py；E2 是校准里唯一像真函数的）
    骨量损失：候选池 23945 点（模板化精确值）上拟合的树集成（留出 R² 打印出来）
指标（Saltelli / Jansen 估计，N 个基样本，评估 N(2d+2) 次）
    S1  一阶（主效应）；ST 总效应；ST − S1 = 该变量参与的交互；S2_ij 两两交互
范围
    global = 整个 14 维盒子；local = 已知前沿设计的包络盒（各维外扩 0.05，单位坐标）——优化真正在意的区域
可行性耦合
    候选池（可行点）在 (变量 i, 变量 j) 网格上的密度 对 均匀密度：哪些变量放不放得进去是相互牵连的
分组
    枚举 14 个变量的全部二分（第一阶段 3–7 个），按"跨阶段交互之和"排序；第一阶段必须含总效应最大的两个变量
    交互权重 w_ij = max(微动 S2_ij（E2 五条路径的均值）, 骨量 S2_ij, 可行性耦合)

    python v2/split_analysis.py [--n 4096]      → results/split/split.json
"""
from __future__ import annotations

import itertools
import json
import pathlib
import sys
import time

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import emulator as EM  # noqa: E402
import jobs as J  # noqa: E402

OUT = J.RESULTS / "split"
VARS = EM.PH3.vars
D = len(VARS)
CURRENT = {"stage1": ["L", "alpha", "collar_w", "h_cut"]}


def sobol(f, n, lo, hi, rng, boot=200):
    A = lo + (hi - lo) * rng.random((n, D))
    B = lo + (hi - lo) * rng.random((n, D))
    fA, fB = f(A), f(B)
    fAB, fBA = np.empty((D, n)), np.empty((D, n))
    for i in range(D):
        Ai = A.copy(); Ai[:, i] = B[:, i]; fAB[i] = f(Ai)
        Bi = B.copy(); Bi[:, i] = A[:, i]; fBA[i] = f(Bi)

    def est(idx):
        a, b, ab, ba = fA[idx], fB[idx], fAB[:, idx], fBA[:, idx]
        V = np.var(np.r_[a, b])
        S1 = np.mean(b * (ab - a), axis=1) / V
        ST = 0.5 * np.mean((a - ab) ** 2, axis=1) / V
        S2 = np.zeros((D, D))
        for i in range(D):
            for j in range(i + 1, D):
                Vij = np.mean(ba[i] * ab[j] - a * b) / V
                S2[i, j] = S2[j, i] = Vij - S1[i] - S1[j]
        return S1, ST, S2

    S1, ST, S2 = est(np.arange(n))
    bs = [est(rng.integers(0, n, n)) for _ in range(boot)]
    ci = lambda k: (np.percentile([b[k] for b in bs], 5, axis=0), np.percentile([b[k] for b in bs], 95, axis=0))  # noqa: E731
    return {"S1": S1, "ST": ST, "S2": S2, "S1_ci": ci(0), "ST_ci": ci(1), "S2_ci": ci(2)}


def coupling(U):
    """可行性耦合：可行点在 (i, j) 5×5 网格上的计数 对 期望（均匀）——相对偏差的标准差，减去单变量边缘造成的部分。"""
    n = len(U)
    bins = np.minimum((U * 5).astype(int), 4)
    C = np.zeros((D, D))
    for i in range(D):
        pi = np.bincount(bins[:, i], minlength=5) / n
        for j in range(i + 1, D):
            pj = np.bincount(bins[:, j], minlength=5) / n
            joint = np.zeros((5, 5))
            np.add.at(joint, (bins[:, i], bins[:, j]), 1.0 / n)
            C[i, j] = C[j, i] = float(np.sqrt(np.mean((joint - np.outer(pi, pj)) ** 2)) / np.mean(np.outer(pi, pj)))
    return C


def main(n: int):
    OUT.mkdir(parents=True, exist_ok=True)
    X, y, c, loss, stage = EM.training_data()
    U, L = EM.pool_p3()
    # 骨量损失的代理（池上精确值）
    from sklearn.ensemble import ExtraTreesRegressor
    rng = np.random.default_rng(0)
    perm = rng.permutation(len(U)); tr, te = perm[:20000], perm[20000:]
    lm = ExtraTreesRegressor(n_estimators=300, min_samples_leaf=2, n_jobs=4, random_state=0).fit(U[tr], L[tr])
    r2_loss = EM.r2(L[te], lm.predict(U[te]))
    lm = ExtraTreesRegressor(n_estimators=300, min_samples_leaf=2, n_jobs=4, random_state=0).fit(U, L)
    print(f"bone-loss surrogate hold-out R² {r2_loss:.3f}", flush=True)
    funcs = {"mm_E1": EM.Emulator("E1", 0, X, y, c).y, "loss": lm.predict}
    for s in range(5):
        funcs[f"mm_E2_s{s}"] = EM.Emulator("E2", s, X, y, c).y
    # 已知前沿的包络（225 个设计里的两目标前沿）
    Y = np.c_[y, loss]
    fr = [i for i in range(len(Y)) if not any((Y[j] <= Y[i]).all() and (Y[j] < Y[i]).any() for j in range(len(Y)))]
    lo_loc = np.clip(X[fr].min(0) - 0.05, 0, 1); hi_loc = np.clip(X[fr].max(0) + 0.05, 0, 1)
    boxes = {"global": (np.zeros(D), np.ones(D)), "local": (lo_loc, hi_loc)}
    res = {"vars": VARS, "n": n, "bone_loss_surrogate_R2": r2_loss, "front_points": len(fr),
           "local_box": {v: [float(a), float(b)] for v, a, b in zip(VARS, lo_loc, hi_loc)}, "sobol": {}}
    for bname, (lo, hi) in boxes.items():
        for fname, f in funcs.items():
            t0 = time.time()
            r = sobol(f, n, lo, hi, np.random.default_rng(7))
            res["sobol"][f"{bname}:{fname}"] = {k: (v.tolist() if isinstance(v, np.ndarray) else [x.tolist() for x in v]) for k, v in r.items()}
            print(f"{bname:6} {fname:9} ({time.time() - t0:.0f} s) ST:", {v: round(float(x), 3) for v, x in zip(VARS, r["ST"])}, flush=True)
    C = coupling(U)
    res["feasibility_coupling"] = C.tolist()

    # ---------------- 汇总：E2 五条路径取均值
    def avg(box, key):
        return np.mean([np.array(res["sobol"][f"{box}:mm_E2_s{s}"][key]) for s in range(5)], axis=0)
    out_tab = {}
    for box in boxes:
        mm_S1, mm_ST, mm_S2 = avg(box, "S1"), avg(box, "ST"), avg(box, "S2")
        ls = res["sobol"][f"{box}:loss"]
        lS1, lST, lS2 = np.array(ls["S1"]), np.array(ls["ST"]), np.array(ls["S2"])
        out_tab[box] = {v: {"mm_S1": float(a), "mm_ST": float(b), "loss_S1": float(p), "loss_ST": float(q)}
                        for v, a, b, p, q in zip(VARS, mm_S1, mm_ST, lS1, lST)}
        W = np.maximum(np.maximum(np.clip(mm_S2, 0, None), np.clip(lS2, 0, None)), 0.0)
        res[f"W_{box}"] = W.tolist()
        T = np.maximum(mm_ST, lST)
        top2 = list(np.argsort(-T)[:2])
        parts = []
        for k in range(3, 8):
            for s1 in itertools.combinations(range(D), k):
                if not all(t in s1 for t in top2):
                    continue
                s2 = [i for i in range(D) if i not in s1]
                cut = float(W[np.ix_(s1, s2)].sum())
                cutC = float(C[np.ix_(s1, s2)].sum())
                parts.append({"stage1": [VARS[i] for i in s1], "cut_interaction": cut, "cut_feasibility": cutC,
                              "stage1_effect": float(T[list(s1)].sum()), "stage2_effect": float(T[s2].sum())})
        tot = float(W[np.triu_indices(D, 1)].sum())
        parts.sort(key=lambda p: (p["cut_interaction"], -p["stage1_effect"]))
        cur = [VARS.index(v) for v in CURRENT["stage1"]]
        cur_cut = float(W[np.ix_(cur, [i for i in range(D) if i not in cur])].sum())
        res[f"partitions_{box}"] = {"total_pairwise_interaction": tot, "current_split": {"stage1": CURRENT["stage1"], "cut_interaction": cur_cut,
                                    "cut_share": cur_cut / tot if tot else None}, "best": parts[:15]}
        print(f"\n[{box}] total pairwise interaction {tot:.3f}; current split cuts {cur_cut:.3f} ({100 * cur_cut / tot:.0f} %)")
        for p in parts[:8]:
            print(f"   cut {p['cut_interaction']:.3f} ({100 * p['cut_interaction'] / tot:.0f} %)  feas-cut {p['cut_feasibility']:.2f}  stage1 {p['stage1']}")
        pairs = sorted(((float(W[i, j]), VARS[i], VARS[j]) for i in range(D) for j in range(i + 1, D)), reverse=True)[:10]
        print("   strongest pairs:", [(a, b, round(w, 3)) for w, a, b in pairs])
    res["table"] = out_tab
    res["feas_pairs"] = sorted(((float(C[i, j]), VARS[i], VARS[j]) for i in range(D) for j in range(i + 1, D)), reverse=True)[:8]
    print("feasibility coupling, strongest pairs:", [(a, b, round(w, 2)) for w, a, b in res["feas_pairs"]])
    res["created"] = time.strftime("%Y-%m-%d %H:%M:%S")
    (OUT / "split.json").write_text(json.dumps(res, indent=1, default=float))


if __name__ == "__main__":
    import argparse
    import torch
    torch.set_num_threads(3)
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=4096)
    main(ap.parse_args().n)
