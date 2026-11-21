"""A4 转动口径研究（0 FE，Linux 只读）：对每个作业重做首次加载的刚体拟合，比较四种拟合域，并加"虚拟台架"读数。

只读 ~/mobo_toy_v2/queue/<job>/{mesh3d.npz, spec.json, result.json, prep.json, m_fric_csv/*_U.csv}，
只写 ~/mobo_toy_v2/adhoc/ml_eff/a4/。不改 stability.py；拟合函数直接调用 stability.rigid_fit。

四种拟合域（都是柄身界面节点对的相对位移 r = u_柄 − u_骨，与 stability.stability 相同）：
  all   全柄身、面积加权（= stability.py 的生产口径，应逐位复现 metrics_all.csv 的 rot_*_first_deg）
  prox  近端半段：沿柄轴坐标 s = (X − P0)·ax ≤ 柄身节点对的中位数，面积加权（与 verify_rotfit.py 相同）
  dist  远端半段：s > 中位数，面积加权
  unw   全柄身、不加权
周向自转估计 spin_circ：面积加权的 Σ w·u_θ·r / Σ w·r²（与 verify_rotfit.py 相同），u_θ 为相对位移的周向分量。

虚拟台架（bench）读数——定义：
  h = (x − C03)·u3，C03 为截骨面中心，u3 为颈轴单位向量（指向头心）；h > 0 在截骨面以上（头侧）。
  柄颈标记集 S10 = 柄的全部节点（mesh3d.npz 的 stem_conn 中出现的节点，含孪生界面节点）中 0 < h ≤ 10 mm 者；
  骨环标记集 B5  = 界面节点对的骨侧节点（pair_bone）中 −5 mm ≤ h < 0 且不是 pair_collar 者；
  备选骨环 CX5   = 皮质单元（cortex_conn）的全部节点中 −5 mm ≤ h < 0 者（更接近在皮质外表面贴标记）。
  对每个标记集分别用其**绝对位移增量**做不加权刚体拟合 u ≈ t + ω × (x − c)（stability.rigid_fit, w=None）；
  读数 = ω_S10 − ω_B5（小转角相加），按柄轴 ax 分解为自转 |ω·ax| 与摆动 |ω − (ω·ax)ax|；
  柄肩相对骨的平动 = [t_S + ω_S×(P0−c_S)] − [t_B + ω_B×(P0−c_B)]，沿 ax 的分量为下沉（正 = 入骨）。
  诊断量：整个柄（stem_all）的绝对刚体转动、骨环的绝对转动、颈段相对整柄的弯曲 ω_S10 − ω_stem_all。
三段位移增量与 stability.py 相同：first = LOAD − RELEASE，rev = LOAD2 − UNLOAD，perm = UNLOAD − RELEASE。
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
import traceback

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "code"))
sys.path.insert(0, str(HOME / "code" / "v2"))
import numpy as np  # noqa: E402

import femur_real as FR  # noqa: E402
import jobs as J  # noqa: E402
import post_m1 as PM  # noqa: E402
import stability as ST  # noqa: E402

OUT = HOME / "adhoc" / "ml_eff" / "a4"
STEPS = ("RELEASE", "LOAD", "UNLOAD", "LOAD2")
SEGS = {"first": ("RELEASE", "LOAD"), "rev": ("UNLOAD", "LOAD2"), "perm": ("RELEASE", "UNLOAD")}
H_STEM = 10.0        # 柄颈标记：截骨面以上 0 < h ≤ 10 mm
H_BONE = 5.0         # 骨环标记：截骨面以下 −5 ≤ h < 0 mm
DEG = 180.0 / np.pi


def _assert_cache_ready():
    """FR.build() 在缓存缺失时会写 code/v2/cache；本研究不得写 code/，所以先确认缓存文件存在。"""
    cfg = FR.load_cfg()
    f = FR.CACHE / f"femur_real_{FR._cache_key(cfg)}.npz"
    if not f.exists():
        raise RuntimeError(f"femur cache missing: {f} (refusing to build/write under code/)")
    return str(f)


def split(om: np.ndarray, ax: np.ndarray):
    a = float(om @ ax)
    return float(np.linalg.norm(om)) * DEG, abs(a) * DEG, float(np.linalg.norm(om - a * ax)) * DEG


def fit(X, R, w):
    tr, om, c, rms = ST.rigid_fit(X, R, w)
    return tr, om, c, rms


def one(job: str) -> dict:
    t_start = time.time()
    d = J.QROOT / job
    m = np.load(d / "mesh3d.npz")
    p = PM.pairs(d)
    spec = json.loads((d / "spec.json").read_text())
    res = json.loads((d / "result.json").read_text()) if (d / "result.json").exists() else {}
    tpl = res.get("templating") or json.loads((d / "prep.json").read_text()).get("templating")
    fm = J.femur_for(spec)
    P0, ax, e_ml, e_ap = fm.pose(tpl["alpha"], tpl["e"])
    ax = ax / np.linalg.norm(ax)                                  # 柄轴，指向骨内（远端）
    C0 = np.asarray(fm.C03, float)
    u3 = np.asarray(fm.u3, float)
    u3 = u3 / np.linalg.norm(u3)                                  # 颈轴，指向头心；截骨面法向
    labels, nodes = p["node_labels"], p["nodes"]
    lut = {int(n): i for i, n in enumerate(labels)}

    def xyz(labs):
        return nodes[np.array([lut[int(n)] for n in labs])]

    X = xyz(p["pair_bone"])
    U = {s: PM._utab(d / "m_fric_csv" / f"{s}_U.csv", p["n"]) for s in STEPS}
    rel = {s: U[s][p["pair_stem"]] - U[s][p["pair_bone"]] for s in STEPS}
    body = ~p["pair_collar"]
    w = p["pair_area"]
    s_ax = (X - P0) @ ax
    med = float(np.median(s_ax[body]))
    dom = {"all": (body, True), "prox": (body & (s_ax <= med), True), "dist": (body & (s_ax > med), True),
           "unw": (body, False)}
    out = {"job": job, "stage": spec.get("stage"), "tag": spec.get("tag"), "h_cut": spec.get("h_cut"),
           "alpha": tpl["alpha"], "e": tpl["e"], "L": spec["design"].get("L"),
           "collar": bool(p["pair_collar"].any()), "n_pairs": int(len(X)), "n_body": int(body.sum()),
           "s_ax_med_mm": med, "s_ax_min_mm": float(s_ax[body].min()), "s_ax_max_mm": float(s_ax[body].max()),
           "ax_dot_u3": float(ax @ u3),
           "frame": {"P0": P0.tolist(), "C03": C0.tolist(), "ax": ax.tolist(), "u3": u3.tolist(),
                     "e_ml": np.asarray(e_ml, float).tolist(), "e_ap": np.asarray(e_ap, float).tolist()}}
    for name, (msk, wt) in dom.items():
        out[f"{name}_n"] = int(msk.sum())
        out[f"{name}_area_mm2"] = float(w[msk].sum())
    # 周向几何（自转估计用）
    q = X[body] - P0
    radial = q - (q @ ax)[:, None] * ax
    r = np.linalg.norm(radial, axis=1)
    e_th = np.cross(ax, radial / np.maximum(r, 1e-9)[:, None])
    wb = w[body]
    out["r_med_mm"] = float(np.median(r))
    for seg, (a, b) in SEGS.items():
        Rr = rel[b] - rel[a]
        for name, (msk, wt) in dom.items():
            tr, om, c, rms = fit(X[msk], Rr[msk], w[msk] if wt else None)
            t0 = tr + np.cross(om, P0 - c)
            tot, axl, tl = split(om, ax)
            out[f"{name}_rot_{seg}_deg"] = tot
            out[f"{name}_rot_axial_{seg}_deg"] = axl
            out[f"{name}_rot_tilt_{seg}_deg"] = tl
            out[f"{name}_rms_{seg}_um"] = rms * 1e3
            out[f"{name}_subsid_{seg}_um"] = float(t0 @ ax * 1e3)
            out[f"{name}_lateral_{seg}_um"] = float(np.linalg.norm(t0 - (t0 @ ax) * ax) * 1e3)
            out[f"{name}_omega_{seg}"] = [float(v) for v in om]       # 原始 ω（rad），便于事后换算
        ut = (Rr[body] * e_th).sum(1)
        spin = float((wb * ut * r).sum() / (wb * r * r).sum())
        out[f"spin_circ_{seg}_deg"] = abs(spin) * DEG
        out[f"spin_circ_signed_{seg}_deg"] = spin * DEG
        out[f"circ_arc_med_{seg}_um"] = float(np.median(np.abs(ut))) * 1e3
    # ---- 虚拟台架 ----
    stem_labs = np.unique(m["stem_conn"])
    cort_labs = np.unique(m["cortex_conn"]) if "cortex_conn" in m.files else np.array([], dtype=np.int64)
    Xs = xyz(stem_labs)
    hs = (Xs - C0) @ u3
    S10 = stem_labs[(hs > 0) & (hs <= H_STEM)]
    hb = (X - C0) @ u3
    mB = (hb >= -H_BONE) & (hb < 0) & body
    B5 = p["pair_bone"][mB]
    sets = {"S10": S10, "B5": B5, "stem_all": stem_labs}
    if len(cort_labs):
        Xc = xyz(cort_labs)
        hc = (Xc - C0) @ u3
        sets["CX5"] = cort_labs[(hc >= -H_BONE) & (hc < 0)]
    out.update({"bench_h_stem_mm": H_STEM, "bench_h_bone_mm": H_BONE, "stem_h_max_mm": float(hs.max()),
                "stem_h_min_mm": float(hs.min()), "n_stem_all": int(len(stem_labs)),
                **{f"n_{k}": int(len(v)) for k, v in sets.items()}})
    # 标记集的几何尺度（刚体拟合的杠杆臂）
    for k, labs in sets.items():
        if len(labs) >= 4:
            Xk = xyz(labs)
            out[f"{k}_extent_mm"] = [float(v) for v in (Xk.max(0) - Xk.min(0))]
    for seg, (a, b) in SEGS.items():
        dU = U[b] - U[a]
        fits = {}
        for k, labs in sets.items():
            if len(labs) < 4:
                continue
            Xk = xyz(labs)
            Uk = dU[labs]
            ok = np.isfinite(Uk).all(1)
            tr, om, c, rms = fit(Xk[ok], Uk[ok], None)
            fits[k] = (tr, om, c, rms)
            tot, axl, tl = split(om, ax)
            out[f"abs_{k}_rot_{seg}_deg"] = tot
            out[f"abs_{k}_rot_axial_{seg}_deg"] = axl
            out[f"abs_{k}_rot_tilt_{seg}_deg"] = tl
            out[f"abs_{k}_rms_{seg}_um"] = rms * 1e3
        for bk in ("B5", "CX5"):
            if "S10" not in fits or bk not in fits:
                continue
            tS, oS, cS, _ = fits["S10"]
            tB, oB, cB, _ = fits[bk]
            om = oS - oB
            tot, axl, tl = split(om, ax)
            tag = "bench" if bk == "B5" else "bench_cx"
            out[f"{tag}_rot_{seg}_deg"] = tot
            out[f"{tag}_rot_axial_{seg}_deg"] = axl
            out[f"{tag}_rot_tilt_{seg}_deg"] = tl
            out[f"{tag}_rot_neckaxis_{seg}_deg"] = abs(float(om @ u3)) * DEG        # 绕颈轴（截骨面法向）的分量
            vS = tS + np.cross(oS, P0 - cS)
            vB = tB + np.cross(oB, P0 - cB)
            v = vS - vB
            out[f"{tag}_subsid_{seg}_um"] = float(v @ ax * 1e3)
            out[f"{tag}_lateral_{seg}_um"] = float(np.linalg.norm(v - (v @ ax) * ax) * 1e3)
            out[f"{tag}_omega_{seg}"] = [float(x) for x in om]
        if "S10" in fits and "stem_all" in fits and "B5" in fits:
            # 颈段相对整柄的弯曲；整柄相对骨环的转动（标记放在柄身上的"理想台架"）
            om_bend = fits["S10"][1] - fits["stem_all"][1]
            out[f"neck_bend_{seg}_deg"] = float(np.linalg.norm(om_bend)) * DEG
            for bk in ("B5", "CX5"):
                if bk not in fits:
                    continue
                om_sb = fits["stem_all"][1] - fits[bk][1]
                tot, axl, tl = split(om_sb, ax)
                out[f"stemall_vs_{bk}_rot_{seg}_deg"] = tot
                out[f"stemall_vs_{bk}_rot_axial_{seg}_deg"] = axl
                out[f"stemall_vs_{bk}_rot_tilt_{seg}_deg"] = tl
    out["t_s"] = time.time() - t_start
    return out


def _worker(job):
    try:
        return one(job)
    except Exception as e:  # noqa: BLE001
        return {"job": job, "err": repr(e)[:400], "trace": traceback.format_exc()[-1500:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", required=True, help="JSON 文件：{'jobs': [...]} 或列表")
    ap.add_argument("--out", default="rotfit_rows.jsonl")
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    jl = json.loads(pathlib.Path(a.jobs).read_text())
    jobs = jl["jobs"] if isinstance(jl, dict) else jl
    if a.limit:
        jobs = jobs[: a.limit]
    cache = _assert_cache_ready()
    outp = OUT / a.out
    done = set()
    if outp.exists():
        for line in outp.read_text().splitlines():
            try:
                done.add(json.loads(line)["job"])
            except Exception:  # noqa: BLE001
                pass
    todo = [j for j in jobs if j not in done]
    meta = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "n_jobs": len(jobs), "n_todo": len(todo), "procs": a.procs,
            "femur_cache": cache, "code_version": (HOME / "code" / "VERSION").read_text() if (HOME / "code" / "VERSION").exists() else None,
            "jobs_code_hash": J.code_hash(), "H_STEM": H_STEM, "H_BONE": H_BONE, "pid": os.getpid(),
            "affinity": sorted(os.sched_getaffinity(0)), "nice": os.nice(0)}
    print(json.dumps(meta), flush=True)
    t0 = time.time()
    n_err = 0
    with outp.open("a") as fh:
        if a.procs <= 1:
            it = map(_worker, todo)
        else:
            import multiprocessing as mp
            pool = mp.get_context("fork").Pool(a.procs)
            it = pool.imap_unordered(_worker, todo)
        for k, row in enumerate(it, 1):
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            if "err" in row:
                n_err += 1
            print(f"[{k}/{len(todo)}] {row['job']} {'ERR ' + row['err'] if 'err' in row else f'{row['t_s']:.1f}s'}", flush=True)
        if a.procs > 1:
            pool.close()
            pool.join()
    meta.update(finished=time.strftime("%Y-%m-%d %H:%M:%S"), wall_s=time.time() - t0, n_err=n_err)
    (OUT / (pathlib.Path(a.out).stem + "_meta.json")).write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta), flush=True)


if __name__ == "__main__":
    main()
