"""db3406 主动学习驱动（一周计划 2026-10-29 第 3 节 AL-1；规划 3406数据库规划_两天一周一月_2026-10-25.md 第 3.4 节）。0 FE。
只读：导出版本目录（scalars.csv）、面积量 json、6.5 万点池的模板化记录（POOL65K + 面积量 pool65k_area）、CR-T 名单；只写 results/db_al_<轮>.json。

    python v2/stage_al.py select al1 --export <版本目录> --tpl-area <json> [--seed 0] [--dry]
    python v2/stage_al.py show al1

训练行（导出 scalars.csv）：DONE、有摩擦模型、kind design / variant、h_int 2.0、E_canc 155、μ 与 slip_tol 为默认、cfg 覆盖只含 load；
    去掉 CR-T（selection corner_test，A2 的留出集，不进任何训练）；三个目标都有限；面积量缺失的行去掉并记数。
输入（回放 2026-10-26 的结论 "13 维 + 6 个模板量"）+ 条件：u13（导出的 u_*，与池的单位坐标逐位核对）、tpl_A0、tpl_e、tpl_volume、geo_area、
    near_area、mean_wall、log10 δ、R / 1000、α_front、α_sagit（23 维，按训练行标准化）。
目标：log10 首次转动、LOAD2 完全接触面积（建模时取 log10）、log10 柄身微动 p95。
代理：GP（常数 × Matérn 5/2 ARD + 白噪声，normalize_y，3 次重启）与 MLP 集成 × 5（高斯 NLL 头，MSE 预热，按 design_key 留 15 % 早停）。
校准：按 design_key 分 5 折交叉验证（折内 GP 只重启 1 次），每个模型、每个目标 s = |z| 的 90 % 分位 / 1.645（夹在 [0.5, 10]），σ 乘 s（回放发现区间偏窄）。
候选：池里可行、面积量可用的点；去掉离 CR-T 单位距离 < 0.05 的、离任何已算设计（导出里任何状态的行）< 0.02 的。
选点（48 = 19 优化导向 + 19 全局不确定 + 10 随机；配比 = 规划 3.4）：
    优化导向 19 = 稳健 6 + 去骨上限 6 / 8 / 10 cm³ 各 2 + 基线 7（按这个顺序选）：
        基线    (log 转动 ↓, log 完全接触 ↑) 的 FE 前沿（基线条件的行）；分数 = P(不被前沿 ε 支配) × 总不确定度（解析：前沿阶梯分条积分，
                GP 校准后的独立正态边缘）
        上限    去骨 ≤ 上限的候选；分数 = log 转动相对"该上限下 FE 最好 − ε"的期望改进 EI（GP；概率极小时仍能排序）
        稳健    g = max(楼梯, 起身 3839 N 的 log 转动)；FE 最好 = 两种条件都有 FE 行的设计里 g 最小的；分数 = P(g < 最好 − ε) × max(σ)，
                P = 两个条件的正态 CDF 之积（独立）；没有这样的设计时这 6 个并入基线
    全局 19     分数 = 3 个目标上 0.5 × [(σ_GP / σ_y)² + (σ_集成 / σ_y)²] 的平均（基线条件，校准后），只在 GP 预测转动 ≤ 2° 的候选里
                （更松的柄多半 L4 不收敛 = 物理松动）
    （10-29 试跑：MC 估计的概率在好设计附近全为 0，选点提前停在 41 个；改为解析。）
    批内多样性：每个新点离已选点的单位距离 ≥ DIV_R
    随机 10     其余候选里均匀抽（种子 seed + 7919），iid 流（候选已去掉已算设计的近邻，含排除集 E）
    ε = EPS_DEX = 0.012 dex（网格噪声，规划 3.4）。
记录：每个点的组、问题、分数、P、GP 与集成在基线条件下的均值与校准后 σ、GP 在起身 3839 N 下的均值与 σ、池下标、u13、x13、去骨量；模型版本
    （训练行作业号与目标的 sha256、本文件 md5、sklearn / torch 版本、超参数）、交叉验证指标与校准因子、各问题当前 FE 最好值。
冻结：文件已在且选点（组 + u13）不同 → 拒绝（SystemExit）；相同 → 不动。提交由 stage_db 的批次读这个文件。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import pathlib
import sys
import time
import warnings

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import jobs as J  # noqa: E402
import stage_db as DB  # noqa: E402

U_COLS = ["u_L", "u_alpha", "u_h_cut", "u_m", "u_rho_tip", "u_q", "u_lam", "u_g_ml", "u_g_ap", "u_n_a", "u_n_p", "u_tau_a", "u_tau_p"]
TPL_COLS = ("tpl_A0", "tpl_e", "tpl_volume")
AREA = ("geo_area_mm2", "near_area_mm2", "mean_wall_mm")
TARGETS = (("log_rot", "rot_first_deg"), ("log_contact", "contact_area_load2_mm2"), ("log_f1", "f1_p95_um"))
BASE = {"delta": 0.10, "R": 2391.0, "af": 20.0, "as": 18.0}
STS = {"delta": 0.10, "R": 3839.0, "af": 24.0, "as": 8.0}
EPS_DEX = 0.012
CRT_EXCL = 0.05
EVAL_EXCL = DB.CR_EXCL_R
DIV_R = 0.15
CAPS_MM3 = (6000.0, 8000.0, 10000.0)
PLAN = (("robust", None, 6), ("cap", 6000.0, 2), ("cap", 8000.0, 2), ("cap", 10000.0, 2), ("baseline", None, 7))
N_GLOBAL, N_RANDOM = 19, 10
GLOBAL_MAX_ROT_DEG = 2.0                    # 全局不确定只在 GP 预测转动 ≤ 2° 的候选里选（更松的柄多半 L4 不收敛 = 物理松动，FEA 设置核查第 5 节）
ENS_MEMBERS = 5
AREA_FILES = {"pool65k": "db_pool/pool65k_area_s51100.npz", "cr4096": "db_pool/db_cr4096_area_s52101.npz"}   # results/ 下：pool_area_features.py
CAL_CLIP = (0.5, 10.0)
OUT_NAME = "db_al_{}.json"


def f(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def cond_of(r: dict) -> dict | None:
    d = f(r["delta_mm"]) if f(r["delta_mm"]) is not None else f(r["delta_spec_mm"])
    c = {"delta": d, "R": f(r["load_R_N"]), "af": f(r["alpha_front_deg"]), "as": f(r["alpha_sagit_deg"])}
    return c if None not in c.values() else None


def is_cond(c: dict, ref: dict) -> bool:
    return all(abs(c[k] - ref[k]) <= 1e-6 * max(1.0, abs(ref[k])) for k in ref)


def load_training(export: pathlib.Path, area: dict) -> tuple[list, dict]:
    rows, drop = [], {}
    allrows = list(csv.DictReader(open(export / "scalars.csv", newline="", encoding="utf-8")))

    def no(why):
        drop[why] = drop.get(why, 0) + 1

    for r in allrows:
        if r["status"] != "DONE" or r["has_fric_model"] != "true" or r["kind"] not in ("design", "variant"):
            continue
        if f(r["h_int_mm"]) != 2.0 or f(r["E_canc_MPa"]) not in (None, 155.0) or f(r["mu"]) not in (None, 0.3) \
                or f(r["slip_tol"]) not in (None, 0.00025):
            no("model / mesh condition")
            continue
        if r["cfg_override"]:
            try:
                cfg = json.loads(r["cfg_override"])
            except ValueError:
                no("cfg_override unreadable")
                continue
            if set(cfg) - {"load"}:
                no("cfg_override other than load")
                continue
        if r["selection"] == "corner_test":
            no("CR-T holdout")
            continue
        c = cond_of(r)
        y = [f(r[col]) for _, col in TARGETS]
        if c is None or None in y or y[0] <= 0 or y[1] <= 0 or y[2] <= 0:
            no("condition / target missing")
            continue
        a = area.get(r["job_id"]) or {}
        x = [f(r[k]) for k in U_COLS] + [f(r[k]) for k in TPL_COLS] + [f(a.get(k)) for k in AREA]
        if None in x:
            no("u13 / templating / area feature missing")
            continue
        rows.append({"job_id": r["job_id"], "design_key": r["design_key"], "u13": x[:13], "tpl6": x[13:], "cond": c,
                     "y": [math.log10(y[0]), math.log10(y[1]), math.log10(y[2])], "bone": f(r["bone_total_mm3"]),
                     "forced_e": f(r["entry_offset_forced_mm"]), "in_E": r["in_E"] == "true", "source": r["source"]})
    evaluated = [[f(r[k]) for k in U_COLS] for r in allrows if r["kind"] in ("design", "variant") and None not in [f(r[k]) for k in U_COLS]]
    return rows, {"dropped": drop, "n_export_rows": len(allrows), "evaluated_u13": evaluated}


def feats(u13, tpl6, cond) -> list:
    return list(u13) + list(tpl6) + [math.log10(cond["delta"]), cond["R"] / 1000.0, cond["af"], cond["as"]]


# ------------------------------------------------------------------------------------------------ models
def gp_fit(X, y, seed, restarts=3):
    from sklearn.exceptions import ConvergenceWarning
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel
    k = ConstantKernel(1.0, (1e-3, 1e3)) * Matern(length_scale=np.ones(X.shape[1]), length_scale_bounds=(1e-2, 1e3), nu=2.5) \
        + WhiteKernel(1e-2, (1e-6, 1.0))
    gp = GaussianProcessRegressor(kernel=k, normalize_y=True, n_restarts_optimizer=restarts, random_state=seed)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConvergenceWarning)
        gp.fit(X, y)
    return gp


def ens_fit(X, Y, groups, seed):
    import torch
    torch.set_num_threads(4)
    rng = np.random.default_rng(seed)
    ug = np.unique(groups)
    val_g = set(rng.choice(ug, size=max(1, int(round(0.15 * len(ug)))), replace=False).tolist())
    va = np.array([g in val_g for g in groups])
    ym, ys = Y[~va].mean(0), Y[~va].std(0) + 1e-9
    T = lambda a: torch.tensor(a, dtype=torch.float32)                 # noqa: E731
    Xtr, Ytr, Xva, Yva = T(X[~va]), T((Y[~va] - ym) / ys), T(X[va]), T((Y[va] - ym) / ys)
    members = []
    for k in range(ENS_MEMBERS):
        torch.manual_seed(seed * 100 + k)
        body = torch.nn.Sequential(torch.nn.Linear(X.shape[1], 128), torch.nn.SiLU(), torch.nn.Linear(128, 128), torch.nn.SiLU(),
                                   torch.nn.Linear(128, 128), torch.nn.SiLU())
        head = torch.nn.Linear(128, 2 * Y.shape[1])
        params = list(body.parameters()) + list(head.parameters())
        opt = torch.optim.AdamW(params, lr=2e-3, weight_decay=1e-4)
        best, state, bad = float("inf"), None, 0
        for ep in range(3000):
            idx = torch.randperm(len(Xtr))
            for b in idx.split(64):
                o = head(body(Xtr[b]))
                mu, lv = o[:, :Y.shape[1]], o[:, Y.shape[1]:].clamp(-12, 6)
                loss = ((Ytr[b] - mu) ** 2).mean() if ep < 100 else 0.5 * (lv + (Ytr[b] - mu) ** 2 / lv.exp()).mean()
                opt.zero_grad()
                loss.backward()
                opt.step()
            with torch.no_grad():
                o = head(body(Xva))
                mu, lv = o[:, :Y.shape[1]], o[:, Y.shape[1]:].clamp(-12, 6)
                v = float(((Yva - mu) ** 2).mean()) if ep < 100 else float((0.5 * (lv + (Yva - mu) ** 2 / lv.exp())).mean())
            if ep >= 100 and v < best - 1e-5:
                best, bad = v, 0
                state = ([p.detach().clone() for p in body.parameters()], [p.detach().clone() for p in head.parameters()])
            elif ep >= 100:
                bad += 1
                if bad > 300:
                    break
        with torch.no_grad():
            for p, q in zip(list(body.parameters()) + list(head.parameters()), state[0] + state[1]):
                p.copy_(q)
        members.append((body, head))
    return {"members": members, "ym": ym, "ys": ys, "n_out": Y.shape[1]}


def ens_predict(ens, X):
    import torch
    with torch.no_grad():
        Xt = torch.tensor(X, dtype=torch.float32)
        mus, vs = [], []
        for body, head in ens["members"]:
            o = head(body(Xt))
            n = ens["n_out"]
            mus.append(o[:, :n].numpy())
            vs.append(o[:, n:].clamp(-12, 6).exp().numpy())
    mus, vs = np.stack(mus), np.stack(vs)
    mu = mus.mean(0)
    sd = np.sqrt(vs.mean(0) + mus.var(0))
    return mu * ens["ys"] + ens["ym"], sd * ens["ys"]


def calibrate(z: np.ndarray) -> float:
    return float(np.clip(np.quantile(np.abs(z), 0.9) / 1.645, *CAL_CLIP))


def cv_calibration(X, Y, groups, seed, log):
    from sklearn.model_selection import GroupKFold
    n, t = Y.shape
    gp_mu, gp_sd, en_mu, en_sd = (np.zeros((n, t)) for _ in range(4))
    for fold, (tr, te) in enumerate(GroupKFold(n_splits=5).split(X, Y, groups)):
        for j in range(t):
            g = gp_fit(X[tr], Y[tr, j], seed, restarts=1)
            gp_mu[te, j], gp_sd[te, j] = g.predict(X[te], return_std=True)
        e = ens_fit(X[tr], Y[tr], groups[tr], seed + fold + 1)
        en_mu[te], en_sd[te] = ens_predict(e, X[te])
        log(f"cv fold {fold + 1}/5 done")
    out = {}
    for name, mu, sd in (("gp", gp_mu, gp_sd), ("ens", en_mu, en_sd)):
        out[name] = {}
        for j, (tn, _) in enumerate(TARGETS):
            y = Y[:, j]
            z = (y - mu[:, j]) / np.maximum(sd[:, j], 1e-12)
            s = calibrate(z)
            ss = ((y - y.mean()) ** 2).sum()
            out[name][tn] = {"r2": float(1 - ((y - mu[:, j]) ** 2).sum() / ss), "rmse": float(np.sqrt(((y - mu[:, j]) ** 2).mean())),
                             "cov90_raw": float((np.abs(z) <= 1.645).mean()), "scale": s, "cov90_cal": float((np.abs(z) <= 1.645 * s).mean())}
    return out


# ------------------------------------------------------------------------------------------------ fronts and scores
def pareto_front(P: np.ndarray) -> np.ndarray:
    """P[:, 0] 越小越好、P[:, 1] 越大越好：非支配点。"""
    keep = []
    for i, (a, b) in enumerate(P):
        if not np.any((P[:, 0] <= a) & (P[:, 1] >= b) & ((P[:, 0] < a) | (P[:, 1] > b))):
            keep.append(i)
    return P[keep]


def phi(x):
    from scipy.stats import norm
    return norm.cdf(x)


def pdf(x):
    from scipy.stats import norm
    return norm.pdf(x)


def p_not_eps_dominated(mu_r, sd_r, mu_c, sd_c, front) -> np.ndarray:
    """解析（r、c 独立正态）：不被前沿上任何点 ε 支配（f.r ≤ r + ε 且 f.c ≥ c − ε）的概率。支配区 = ∪_f {r ≥ f.r − ε, c ≤ f.c + ε}；
    按 r' = f.r − ε 升序，r ∈ [r'_i, r'_{i+1}) 的竖条里 c ≤ max_{j ≤ i}(f.c + ε)，各条概率相加。不会因抽样变成 0（MC 在好设计附近会）。"""
    F = front[np.argsort(front[:, 0], kind="stable")]
    rp, cp = F[:, 0] - EPS_DEX, np.maximum.accumulate(F[:, 1] + EPS_DEX)
    Pr = phi((np.r_[rp, np.inf][None, :] - mu_r[:, None]) / sd_r[:, None])
    Pc = phi((cp[None, :] - mu_c[:, None]) / sd_c[:, None])
    return np.clip(1.0 - ((Pr[:, 1:] - Pr[:, :-1]) * Pc).sum(1), 0.0, 1.0)


def expected_improvement(mu, sd, target) -> np.ndarray:
    """最小化：EI = (t − μ) Φ(z) + σ φ(z)，z = (t − μ) / σ（解析，概率极小时仍能排序）。"""
    z = (target - mu) / sd
    return (target - mu) * phi(z) + sd * pdf(z)


def check_area_consistency(rows, area, srcs, ars, pool) -> dict:
    """训练行里的 CR-1（db_cr_c<下标>）与 SF-1（db_sf_p<池下标>）作业：按自己 prep 位姿算的面积量（tpl-area json）必须等于候选来源按
    模板化位姿算的（CR4096 那一行；6.5 万点池里 u13 逐位相同的那一行）。返回核对个数与最大相对差。"""
    tp65 = srcs["pool65k"][0]
    head = tp65["u13"][:DB.POOL_N]
    worst, n = 0.0, {"cr4096": 0, "pool65k": 0}
    for r in rows:
        j = r["job_id"]
        a = area.get(j)
        if not a:
            continue
        if j.startswith("db_cr_c"):
            name, t = "cr4096", int(j.split("_")[2][1:])
        elif j.startswith("db_sf_p"):
            u = pool["U"][int(j.split("_")[2][1:])]
            hit = np.flatnonzero((head == u).all(1))
            if len(hit) != 1:
                continue
            name, t = "pool65k", int(hit[0])
        else:
            continue
        n[name] += 1
        for k in AREA:
            v, w = float(a[k]), float(ars[name][k][t])
            worst = max(worst, abs(v - w) / max(abs(w), 1e-12))
    return {"n_checked": n, "max_rel": worst}


# ------------------------------------------------------------------------------------------------ select
def select(rnd: str, export: pathlib.Path, area_path: pathlib.Path, seed: int, log) -> dict:
    t0 = time.time()
    area = {k: v for k, v in json.load(open(area_path))["rows"].items() if v.get("ok")}
    rows, info = load_training(export, area)
    if len(rows) < 50:
        raise SystemExit(f"only {len(rows)} training rows")
    ph = DB.b2_phase()
    # 训练行的 u13 与池的单位坐标同一空间：SF-1 行与池点逐位核对
    pool = DB.load_pool()
    sf = [r for r in rows if r["job_id"].startswith("db_sf_p")]
    worst = 0.0
    for r in sf:
        pi = int(r["job_id"].split("_")[2][1:])
        worst = max(worst, float(np.max(np.abs(np.asarray(r["u13"]) - pool["U"][pi]))))
    if worst > 1e-9:
        raise SystemExit(f"export u_* and the pool unit coordinates differ (max {worst:.3g} over {len(sf)} SF rows)")
    X = np.array([feats(r["u13"], r["tpl6"], r["cond"]) for r in rows])
    Y = np.array([r["y"] for r in rows])
    groups = np.array([r["design_key"] for r in rows])
    xm, xs = X.mean(0), X.std(0)
    xs[xs < 1e-12] = 1.0
    Xn = (X - xm) / xs
    log(f"training rows {len(rows)} ({len(np.unique(groups))} designs); dropped {info['dropped']}")
    cv = cv_calibration(Xn, Y, groups, seed, log)
    gps = [gp_fit(Xn, Y[:, j], seed) for j in range(Y.shape[1])]
    ens = ens_fit(Xn, Y, groups, seed)
    log("final models fitted")
    # ---- 候选：6.5 万点池 + 角落子盒 CR4096（两者都已 0-FE 模板化、补了面积量）
    srcs = {"pool65k": (DB.load_tpl(DB.POOL65K, np.load(J.RESULTS / DB.U65K)), AREA_FILES["pool65k"]),
            "cr4096": (DB.load_tpl(DB.CR_TPL, DB.cr_points()), AREA_FILES["cr4096"])}
    ars = {}
    for name, (tp_, af) in srcs.items():
        with np.load(J.RESULTS / af, allow_pickle=False) as z:
            ars[name] = {k: z[k] for k in z.files}
        if not np.array_equal(np.asarray(ars[name]["feasible"], bool), np.asarray(tp_["feasible"], bool)):
            raise SystemExit(f"{af}: its feasible flags differ from the templating record of {name}")
    area_check = check_area_consistency(rows, area, srcs, ars, pool)
    if area_check["max_rel"] > 1e-9:
        raise SystemExit(f"area features of training jobs (prep pose) and of the candidate sources (templating pose) differ: {area_check}")
    crt = json.loads(DB.crt_file_path().read_text())["crt"]
    Ucrt = np.array([x["u13"] for x in crt])
    Uev = np.array(info["evaluated_u13"])

    def mind(A, B):
        out = np.full(len(A), np.inf)
        for i0 in range(0, len(B), 64):
            out = np.minimum(out, np.min(np.linalg.norm(A[:, None, :] - B[None, i0:i0 + 64, :], axis=2), axis=1))
        return out

    parts, n_feas = [], {}
    for name, (tp_, _) in srcs.items():
        a_ = ars[name]
        idx = np.flatnonzero(np.asarray(tp_["feasible"], bool) & np.asarray(a_["area_ok"], bool))
        keep = idx[(mind(tp_["u13"][idx], Ucrt) >= CRT_EXCL) & (mind(tp_["u13"][idx], Uev) >= EVAL_EXCL)]
        n_feas[name] = [int(len(idx)), int(len(keep))]
        parts.append({"src": np.array([name] * len(keep)), "sidx": keep, "U": tp_["u13"][keep],
                      "tpl6": np.c_[tp_["A0_star"][keep], tp_["e_star"][keep], tp_["volume_star"][keep], a_["geo_area_mm2"][keep],
                                    a_["near_area_mm2"][keep], a_["mean_wall_mm"][keep]],
                      "bone": np.asarray(tp_["bone_mm3"][keep], float), "e_star": np.asarray(tp_["e_star"][keep], float),
                      "A0_star": np.asarray(tp_["A0_star"][keep], float)})
    C = {k: np.concatenate([p_[k] for p_ in parts]) for k in parts[0]}
    Uc, tpl6, bone = C["U"], C["tpl6"], C["bone"]
    # 两个来源之间的近重复（子盒点落在池点旁边）：只留池里的那个
    dup = np.zeros(len(Uc), bool)
    is_cr = C["src"] == "cr4096"
    if is_cr.any() and (~is_cr).any():
        dup[is_cr] = mind(Uc[is_cr], Uc[~is_cr]) < EVAL_EXCL
    for k in C:
        C[k] = C[k][~dup]
    Uc, tpl6, bone = C["U"], C["tpl6"], C["bone"]
    cand = np.arange(len(Uc))
    log(f"candidates (feasible with area features -> after the CR-T {CRT_EXCL} / evaluated {EVAL_EXCL} exclusions): {n_feas}; "
        f"{int(dup.sum())} sub-box points next to a pool point dropped; total {len(cand)}")

    def predict(cond):
        Xc = (np.array([feats(u, t6, cond) for u, t6 in zip(Uc, tpl6)]) - xm) / xs
        g = [m.predict(Xc, return_std=True) for m in gps]
        gm = np.stack([a for a, _ in g], 1)
        gs = np.stack([b for _, b in g], 1) * np.array([cv["gp"][tn]["scale"] for tn, _ in TARGETS])
        em, es = ens_predict(ens, Xc)
        es = es * np.array([cv["ens"][tn]["scale"] for tn, _ in TARGETS])
        return gm, gs, em, es

    gm, gs, em, es = predict(BASE)
    sm, ss_, _, _ = predict(STS)
    sy = Y.std(0)
    unc = (0.5 * ((gs / sy) ** 2 + (es / sy) ** 2)).mean(1)
    # ---- 当前 FE 最好值
    base_rows = [r for r in rows if is_cond(r["cond"], BASE) and r["forced_e"] is None]
    front = pareto_front(np.array([[r["y"][0], r["y"][1]] for r in base_rows]))
    best_cap = {}
    for cap in CAPS_MM3:
        v = [r["y"][0] for r in base_rows if r["bone"] is not None and r["bone"] <= cap]
        best_cap[cap] = min(v) if v else None
    by_d = {}
    for r in rows:
        if r["forced_e"] is not None:
            continue
        if is_cond(r["cond"], BASE):
            by_d.setdefault(r["design_key"], {})["base"] = min(r["y"][0], by_d.get(r["design_key"], {}).get("base", 9e9))
        elif is_cond(r["cond"], STS):
            by_d.setdefault(r["design_key"], {})["sts"] = min(r["y"][0], by_d.get(r["design_key"], {}).get("sts", 9e9))
    both = {k: max(v["base"], v["sts"]) for k, v in by_d.items() if "base" in v and "sts" in v}
    best_rob = min(both.values()) if both else None
    # ---- 分数（全部解析）
    probs = {"baseline": p_not_eps_dominated(gm[:, 0], gs[:, 0], gm[:, 1], gs[:, 1], front)}
    scores = {"baseline": probs["baseline"] * unc}
    for cap in CAPS_MM3:
        ok_c = bone <= cap
        if best_cap[cap] is None:
            p = ei = np.zeros(len(cand))
        else:
            t = best_cap[cap] - EPS_DEX
            p, ei = phi((t - gm[:, 0]) / gs[:, 0]), expected_improvement(gm[:, 0], gs[:, 0], t)
        probs[f"cap{cap:g}"], scores[f"cap{cap:g}"] = np.where(ok_c, p, 0.0), np.where(ok_c, ei, 0.0)
    if best_rob is not None:
        t = best_rob - EPS_DEX
        probs["robust"] = phi((t - gm[:, 0]) / gs[:, 0]) * phi((t - sm[:, 0]) / ss_[:, 0])   # P(max(楼梯, 起身) < t)，两者独立
        scores["robust"] = probs["robust"] * np.maximum(gs[:, 0], ss_[:, 0])
    unc_g = np.where(gm[:, 0] <= math.log10(GLOBAL_MAX_ROT_DEG), unc, 0.0)
    plan = [(p, c, n) for p, c, n in PLAN if not (p == "robust" and best_rob is None)]
    if best_rob is None:
        plan = [(p, c, n + 6 if p == "baseline" else n) for p, c, n in plan]
        log("robust: no design has both a stair and a sit-to-stand 3839 N FE row -> its 6 picks go to the baseline problem")
    picks = []

    def take(score, group, problem, n, prob=None):
        order = np.argsort(-score, kind="stable")
        got = 0
        for i in order:
            if got >= n:
                break
            if any(np.linalg.norm(Uc[i] - Uc[p["_i"]]) < DIV_R for p in picks):
                continue
            if score[i] <= 0 and group != "random":
                break
            picks.append({"_i": int(i), "group": group, "problem": problem, "score": float(score[i]),
                          "p_improve": None if prob is None else float(prob[i])})
            got += 1
        if got < n:
            log(f"WARNING {group}/{problem}: only {got} of {n} picks (scores <= 0 or diversity)")

    for p, cap, n in plan:
        key = p if cap is None else f"cap{cap:g}"
        take(scores[key], "opt", key, n, probs[key])
    take(unc_g, "global", "uncertainty", N_GLOBAL)
    rest = [i for i in range(len(cand)) if i not in {q["_i"] for q in picks}]
    rr = np.random.default_rng(seed + 7919)
    for i in rr.choice(rest, size=N_RANDOM, replace=False):
        picks.append({"_i": int(i), "group": "random", "problem": "iid", "score": None, "p_improve": None})
    # ---- 记录
    out_p = []
    for rank, q in enumerate(picks, start=1):
        i = q.pop("_i")
        d_, h_ = ph.design_of(Uc[i])
        out_p.append({"rank": rank, **q, "source": str(C["src"][i]), "source_idx": int(C["sidx"][i]), "u13": [float(x) for x in Uc[i]],
                      "x13": [float(h_) if k == "h_cut" else float(d_[k]) for k in ph.vars], "bone_mm3": float(bone[i]),
                      "e_star": float(C["e_star"][i]), "A0_star": float(C["A0_star"][i]),
                      "pred_base": {tn: {"gp": [float(gm[i, j]), float(gs[i, j])], "ens": [float(em[i, j]), float(es[i, j])]}
                                    for j, (tn, _) in enumerate(TARGETS)},
                      "pred_sts3839_gp": {tn: [float(sm[i, j]), float(ss_[i, j])] for j, (tn, _) in enumerate(TARGETS)}})
    train_sha = hashlib.sha256(json.dumps([[r["job_id"], r["y"]] for r in rows]).encode()).hexdigest()
    import sklearn
    import torch
    doc = {"round": rnd, "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "seed": seed,
           "export": {"dir": str(export), "scalars_sha256": DB._sha256_file(export / "scalars.csv")}, "tpl_area": str(area_path),
           "model_version": {"train_sha256": train_sha, "stage_al_md5": hashlib.md5(pathlib.Path(__file__).read_bytes()).hexdigest(),
                             "sklearn": sklearn.__version__, "torch": torch.__version__, "gp": "C*Matern52(ARD)+White, normalize_y, 3 restarts",
                             "ens": f"{ENS_MEMBERS} x MLP 3x128 SiLU, Gaussian NLL, MSE warm-up 100, early stop 15 % designs"},
           "n_train": len(rows), "n_designs": int(len(np.unique(groups))), "dropped": info["dropped"], "u13_pool_check_max": worst,
           "features": U_COLS + list(TPL_COLS) + list(AREA) + ["log10_delta", "R_kN", "alpha_front", "alpha_sagit"],
           "cv": cv, "eps_dex": EPS_DEX, "div_r": DIV_R, "crt_excl": CRT_EXCL, "eval_excl": EVAL_EXCL,
           "n_candidates": int(len(cand)), "candidates_by_source": n_feas, "area_check": area_check, "front_baseline": front.tolist(), "best_cap_log_rot": {f"{k:g}": v for k, v in best_cap.items()},
           "best_robust_log_rot": best_rob, "n_designs_both_conditions": len(both), "plan": [list(x) for x in plan],
           "picks": out_p, "wall_s": round(time.time() - t0, 1)}
    doc["essence_sha256"] = essence(doc)
    return doc


def essence(doc: dict) -> str:
    return hashlib.sha256(json.dumps([[p["group"], p["problem"], p["u13"]] for p in doc["picks"]]).encode()).hexdigest()


def out_path(rnd: str) -> pathlib.Path:
    return J.RESULTS / OUT_NAME.format(rnd)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["select", "show"])
    ap.add_argument("round")
    ap.add_argument("--export")
    ap.add_argument("--tpl-area")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--dry", action="store_true", help="select: print only, write nothing")
    a = ap.parse_args()
    p = out_path(a.round)
    if a.cmd == "show":
        doc = json.loads(p.read_text())
        for q in doc["picks"]:
            pb = q["pred_base"]
            print(f"{q['rank']:2d} {q['group']:6s} {q['problem']:11s} {q['source']:7s} {q['source_idx']:5d} bone {q['bone_mm3']:7.0f} "
                  f"rot {10 ** pb['log_rot']['gp'][0]:.3f} deg (sd {pb['log_rot']['gp'][1]:.3f} dex) P {q['p_improve']}")
        return 0
    if not (a.export and a.tpl_area):
        raise SystemExit("select needs --export and --tpl-area")
    log = lambda m: print(f"{time.strftime('%H:%M:%S')} {m}", flush=True)   # noqa: E731
    doc = select(a.round, pathlib.Path(a.export), pathlib.Path(a.tpl_area), a.seed, log)
    print(json.dumps({k: doc[k] for k in ("n_train", "n_designs", "dropped", "n_candidates", "best_cap_log_rot", "best_robust_log_rot",
                                          "n_designs_both_conditions", "wall_s")}, indent=1))
    for m, d in doc["cv"].items():
        for tn, x in d.items():
            print(f"cv {m:3s} {tn:12s} R2 {x['r2']:.3f} RMSE {x['rmse']:.4f} cov90 {x['cov90_raw']:.2f} -> scale {x['scale']:.2f} -> {x['cov90_cal']:.2f}")
    for q in doc["picks"]:
        pb = q["pred_base"]
        print(f"{q['rank']:2d} {q['group']:6s} {q['problem']:11s} {q['source']:7s} {q['source_idx']:5d} bone {q['bone_mm3']:7.0f} "
              f"rot {10 ** pb['log_rot']['gp'][0]:.3f} deg (sd {pb['log_rot']['gp'][1]:.3f}) P {q['p_improve']}")
    if a.dry:
        print("dry: nothing written")
        return 0
    if p.exists():
        old = json.loads(p.read_text())
        if old.get("essence_sha256") != doc["essence_sha256"]:
            raise SystemExit(f"{p} exists with a different selection; not overwriting (move it away only if no batch has used it)")
        print(f"{p} exists with the same selection; unchanged")
        return 0
    p.write_text(json.dumps(doc, indent=1))
    print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
