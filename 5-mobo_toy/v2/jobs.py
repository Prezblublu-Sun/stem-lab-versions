"""V2A 作业队列（Linux 侧）。每个作业一个目录 ~/mobo_toy_v2/queue/<job_id>/，状态用标记文件表示：

    spec.json        作业说明（kind = design | intact | variant；设计向量、网格尺寸、变体、所属阶段）
                     variant（2026-09-29）：与 design 同样建模，但不进任何常规数据集。可带
                       cfg        对配置的覆盖，如 {"load": {...}} 或 {"materials": {"titanium": {"E": 55000}}}
                       bond_only  只解粘接模型（应力屏蔽用），不解摩擦模型
                       bond_collar  粘接模型的领：tied（共节点，默认）/ contact（只受压、可掀起）；见 bond_collar.py
                       collar_rule  wrap_fit = 领包住假体颈、整圈落在骨截面上（放不下就换号或换入口偏移）；见 collar_rule.py
                       intact_job 指定完整股骨参照的作业 id（载荷或网格与标准参照不同时必须给）
                     intact 作业同样可带 cfg；带 cfg 的参照一律用 stage ≠ "ref"，不会被 intact_ref 选中
    READY            .inp 已生成，等待本机求解            ← prep 写
    CLAIMED          本机 worker 已认领（mv READY CLAIMED，原子）
    SOLVED           本机已推回 <name>_csv/ 与 solve.json    ← worker 写
    DONE             后处理完成，result.json 已写           ← post 写
    FAILED.json      任一阶段失败：{"level": L1–L5, "stage": prep|solve|post, "reason": …}

本机只做求解；建模、后处理、判定都在这里。所有步骤幂等：已有 DONE / FAILED.json 的作业不再处理。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import sys
import time
import traceback

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import femur_real as FR  # noqa: E402
import geom3d as G  # noqa: E402

QROOT = pathlib.Path.home() / "mobo_toy_v2" / "queue"
RESULTS = pathlib.Path.home() / "mobo_toy_v2" / "results"
KEEP_CSV = {"fric": ["RELEASE_CONTACT.csv", "LOAD_CONTACT.csv"], "bond": ["LOAD_ENER.csv", "LOAD_S.csv"],
            "intact": ["LOAD_ENER.csv"]}


def code_hash() -> str:
    h = hashlib.sha256()
    for f in ("femur_real.py", "geom3d.py", "fe3d_geom.py", "model3d_v2.py", "post.py", "config_v2a.yaml",
              "model3d_m1.py", "post_m1.py"):
        h.update((HERE / f).read_bytes())
    return h.hexdigest()[:10]


def job_id(spec: dict) -> str:
    """同一设计 + 同一变体 + 同一网格 + 同一代码 → 同一 id（缓存）。"""
    core = {k: spec[k] for k in sorted(spec) if k not in ("stage", "tag", "created")}
    core["code"] = code_hash()
    h = hashlib.sha1(json.dumps(core, sort_keys=True, default=float).encode()).hexdigest()[:8]
    return f"{spec.get('stage', 'x')}_{spec.get('tag', 'j')}_{h}"


def state(d: pathlib.Path) -> str:
    for s in ("DONE", "FAILED.json", "SOLVED", "CLAIMED", "READY"):
        if (d / s).exists():
            return s.replace(".json", "")
    return "NEW" if (d / "spec.json").exists() else "MISSING"


def submit(spec: dict) -> str:
    """登记一个作业（不建模）；已存在则直接返回其 id。"""
    spec = {**spec, "created": time.strftime("%Y-%m-%d %H:%M:%S")}
    jid = job_id(spec)
    d = QROOT / jid
    if not (d / "spec.json").exists():
        d.mkdir(parents=True, exist_ok=True)
        (d / "spec.json").write_text(json.dumps(spec, indent=1, default=float))
    return jid


def _fail(d: pathlib.Path, level: str, stage: str, reason: str) -> None:
    (d / "FAILED.json").write_text(json.dumps({"level": level, "stage": stage, "reason": reason[-3000:],
                                               "time": time.strftime("%Y-%m-%d %H:%M:%S")}))


def _merge(a: dict, b: dict) -> None:
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            _merge(a[k], v)
        else:
            if k not in a:
                raise KeyError(f"cfg override: unknown key {k!r}")
            a[k] = v


def femur_for(spec: dict):
    """该作业用的股骨对象：截骨高度（V3 设计变量）与配置覆盖（变体作业）。覆盖只作用于本作业的副本。"""
    import copy
    fm = FR.build()
    if spec.get("h_cut") is not None:
        fm = fm.with_cut(spec["h_cut"])
    if spec.get("cfg"):
        fm = copy.copy(fm)
        fm.cfg = copy.deepcopy(fm.cfg)
        _merge(fm.cfg, spec["cfg"])
    return fm


def explicit_ref(spec: dict) -> dict | None:
    """变体作业指定的完整股骨参照；没指定返回 None。参照未完成抛 FileNotFoundError。"""
    rid = spec.get("intact_job")
    if not rid:
        return None
    p = QROOT / rid / "result.json"
    if not p.exists():
        raise FileNotFoundError(f"intact reference {rid} not DONE")
    r = json.loads(p.read_text())
    r["intact_job"] = rid
    r["intact_substituted_h"] = spec.get("intact_substituted_h")
    return r


def prep(jid: str) -> str:
    """模板化 + 建模 → READY；失败 → FAILED.json。返回最终状态。"""
    import model3d_v2 as M
    import model3d_m1 as M1
    d = QROOT / jid
    st0 = state(d)
    if st0 not in ("NEW",):
        return st0
    spec = json.loads((d / "spec.json").read_text())
    try:
        fm = femur_for(spec)
        if spec["kind"] == "bench":                          # Lamé 压配对照（M1 界面代码路径）
            info = M1.build_lame(d, "lame", **{k: spec[k] for k in ("h", "delta", "mu", "slip_tol", "lagrange",
                                                                    "interference") if k in spec})
            info["templating"] = None
        elif spec["kind"] == "intact":
            info = M.build_intact(fm, d, "intact", h_roi=spec["h_int"], h_far=spec.get("h_far", 6.0),
                                  E_canc=spec.get("E_canc"))
            info["templating"] = None
        else:
            if spec.get("collar_rule") == "wrap_fit":              # 领包住假体颈、整圈落在骨截面上（collar_rule.py，只替换本建模进程）
                import collar_rule as CR
                CR.install(min_A0=float(spec.get("min_A0", 0.0)))
            st = G.Stem3D(**spec["design"])
            pl = G.template(st, fm, margin=spec.get("margin"))     # None → 设计自带的 m
            if not pl["fit"]:
                _fail(d, "L1", "prep", f"templating: {pl['reason']}")
                return "FAILED"
            if pl["A0"] < spec.get("min_A0", 0.0):
                _fail(d, "L1", "prep", f"shoulder {pl['A0']:.0f} mm² < prosthetic neck {spec['min_A0']:.0f} mm²")
                return "FAILED"
            if spec.get("model") == "m1":
                info = M1.build(st, fm, pl, d, "m", h_int=spec["h_int"], h_far=spec.get("h_far"),
                                delta=spec.get("delta"), mu=spec.get("mu"), torque=spec.get("torque", True),
                                E_canc=spec.get("E_canc"), slip_tol=spec.get("slip_tol"), lagrange=spec.get("lagrange"),
                                interference=spec.get("interference"), cycles=spec.get("cycles"))
                if spec.get("bond_collar") is not None:          # 粘接模型的领：tied（默认）/ contact（只受压、可掀起），见 bond_collar.py
                    import bond_collar as BC
                    info.update(BC.apply(d, spec, fm.cfg))
            else:
                if st.has_collar:
                    _fail(d, "L1", "prep", "collar is implemented only in the M1 interface model (spec model = m1)")
                    return "FAILED"
                info = M.build(st, fm, pl, d, "m", h_int=spec["h_int"], h_far=spec.get("h_far"),
                               delta=spec.get("delta"), mu=spec.get("mu"), torque=spec.get("torque", True),
                               E_canc=spec.get("E_canc"))
            info["templating"] = {k: pl[k] for k in ("alpha", "e", "A0", "contact", "s_bind", "volume", "margin")}
            resected = fm.resected_volume()
            info["bone_loss"] = {"h_cut_mm": fm.cut_from_head_mm, "resected_mm3": resected, "reamed_mm3": pl["volume"],
                                 "total_mm3": resected + pl["volume"]}
            if spec.get("bond_only"):
                (d / "m_fric.inp").unlink()
                info["bond_only"] = True
        if spec.get("keep_odb"):                                  # 演示作业：本机 worker 求解后把 odb 留在 v2/demo_odb/<作业>/
            kj = d / "keep.json"
            k = json.loads(kj.read_text()) if kj.exists() else {}
            k["keep_odb"] = True
            kj.write_text(json.dumps(k))
        info["cfg_override"] = spec.get("cfg")
        info["code_hash"] = code_hash()
        (d / "prep.json").write_text(json.dumps({k: v for k, v in info.items() if k != "slave"}, default=float))
        (d / "READY").write_text(time.strftime("%Y-%m-%d %H:%M:%S"))
        return "READY"
    except Exception as e:                                                  # noqa: BLE001
        level = getattr(e, "level", "L3")
        _fail(d, level, "prep", f"{type(e).__name__}: {e}\n{traceback.format_exc()[-1500:]}")
        return "FAILED"


def intact_ref(h_int: float, E_canc: float | None = None) -> dict:
    """该网格档的完整股骨 Gruen 区 SED：取同一 h、同一松质骨模量变体的最新 DONE 完整股骨作业。
    E_canc=None 只匹配标准材料的参照；给定 E_canc（敏感性变体）必须有同 h 的同变体参照，不作网格代替。

    不按全局代码哈希找：建柄模型的修正（退化单元门槛、假体颈起点）会改变哈希，但完整股骨模型（femur_real +
    model3d_v2.build_intact + 配置）没变，结果逐位相同；按哈希找会让新作业卡在等参照。所用参照的 id 写进结果。"""
    def _same_variant(d):
        sp = json.loads((d / "spec.json").read_text()) if (d / "spec.json").exists() else {}
        return sp.get("E_canc") == E_canc
    cands = []
    for d in QROOT.glob(f"ref_intact_h{h_int:g}_*"):
        if (d / "result.json").exists() and _same_variant(d):
            cands.append((d.stat().st_mtime, d))
    substituted = None
    if not cands and E_canc is not None:
        raise FileNotFoundError(f"no DONE intact reference for h_int={h_int}, E_canc={E_canc}")
    if not cands:
        # 1.0 mm 的完整股骨超内存（直接解法要约 90 GB，本机上限约 50 GB），两次都 L4。完整股骨的 Gruen 区 SED
        # 从 2.0 到 1.4 mm 只变 +1.6%（G7）/ +2.0%（G1），外推到 1.0 mm 约再变 < 1%，所以用已完成的最细一档
        # （比要求的粗、且最接近者）代替，并在结果里记 intact_substituted_h，报告里写明。
        done = []
        for d in QROOT.glob("ref_intact_h*"):
            if (d / "result.json").exists() and _same_variant(d):
                hh = float(d.name.split("_h", 1)[1].split("_")[0])
                # 优先取比要求粗且最接近的一档；没有更粗的（如噪声底研究里的 2.03、2.06 mm）就取最接近的一档
                done.append((0 if hh >= h_int else 1, abs(hh - h_int), -d.stat().st_mtime, hh, d))
        if not done:
            raise FileNotFoundError(f"no DONE intact reference for h_int={h_int}")
        _, _, _, hh, d = min(done)
        substituted = hh
    else:
        d = max(cands)[1]
    r = json.loads((d / "result.json").read_text())
    r["intact_job"] = d.name
    r["intact_substituted_h"] = substituted
    return r


def post(jid: str) -> str:
    """SOLVED → 算 QoI → DONE（或 FAILED）。"""
    import post as P
    import post_m1 as PM1
    d = QROOT / jid
    st0 = state(d)
    if st0 != "SOLVED":
        return st0
    spec = json.loads((d / "spec.json").read_text())
    solve = json.loads((d / "solve.json").read_text())
    bad = {k: v for k, v in solve.items() if v.get("status") != "OK"}
    if bad:
        k, v = next(iter(bad.items()))
        _fail(d, v.get("status", "L4"), "solve", f"{k}: {v.get('reason', '')}")
        return "FAILED"
    try:
        fm = femur_for(spec)
        R = d
        if spec["kind"] == "bench":
            res = PM1.lame(R)
        elif spec["kind"] == "intact":
            res = P.zone_sed(R, "intact", fm)
        else:
            ref = explicit_ref(spec) or intact_ref(spec["h_int"], spec.get("E_canc"))
            if spec.get("bond_only"):
                zs = P.zone_sed(R, "m_bond", fm)
                res = {**P.stem_vm(R, "m_bond", fm), "sed_gruen7": zs["gruen7"], "sed_gruen1": zs["gruen1"],
                       "f2_g7_loss_pct": 100.0 * (1.0 - zs["gruen7"] / ref["gruen7"]),
                       "f2_g1_loss_pct": 100.0 * (1.0 - zs["gruen1"] / ref["gruen1"]), "bond_only": True}
            else:
                res = PM1.evaluate(R, "m", fm, ref) if spec.get("model") == "m1" else P.evaluate(R, "m", fm, ref)
            res["intact_job"] = ref.get("intact_job")
            res["intact_substituted_h"] = ref.get("intact_substituted_h")
            prep = json.loads((d / "prep.json").read_text())
            res["templating"] = prep.get("templating")
            res["n_tet"] = prep.get("n_tet")
            res["bone_loss"] = prep.get("bone_loss")
            res["h_cut_mm"] = fm.cut_from_head_mm
        res["solve"] = solve
        res["spec"] = spec
        res["job_id"] = jid
        (d / "result.json").write_text(json.dumps(res, indent=1, default=float))
        (d / "DONE").write_text(time.strftime("%Y-%m-%d %H:%M:%S"))
        RESULTS.mkdir(parents=True, exist_ok=True)
        with open(RESULTS / "runs_v2a.jsonl", "a") as fh:
            fh.write(json.dumps({"job_id": jid, "stage": spec.get("stage"), "kind": spec["kind"],
                                 **{k: v for k, v in res.items() if k not in ("spec", "solve")},
                                 "design": spec.get("design"), "h_int": spec.get("h_int"),
                                 "variant": {k: spec.get(k) for k in ("delta", "mu", "torque", "E_canc", "model", "slip_tol", "lagrange",
                                                                  "interference", "cfg", "bond_only", "h_far", "intact_job")}},
                                default=float) + "\n")
        # 大文件不再需要：保留 result、spec、prep 与 CSV
        for f in ("m_fric.inp", "m_bond.inp", "intact.inp", "lame_fric.inp"):
            if (d / f).exists():
                (d / f).unlink()
        return "DONE"
    except Exception as e:                                                  # noqa: BLE001
        _fail(d, "L5", "post", f"{type(e).__name__}: {e}\n{traceback.format_exc()[-1500:]}")
        return "FAILED"


def result(jid: str) -> dict | None:
    d = QROOT / jid
    if (d / "result.json").exists():
        return json.loads((d / "result.json").read_text())
    if (d / "FAILED.json").exists():
        return {"failed": json.loads((d / "FAILED.json").read_text()), "job_id": jid}
    return None


def summary() -> dict:
    out = {}
    for d in sorted(QROOT.glob("*")):
        s = state(d)
        out[s] = out.get(s, 0) + 1
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["summary", "prep", "post", "reset-claimed"])
    ap.add_argument("ids", nargs="*")
    a = ap.parse_args()
    if a.cmd == "summary":
        print(json.dumps(summary()))
    elif a.cmd == "prep":
        for j in a.ids:
            print(j, prep(j))
    elif a.cmd == "post":
        for j in a.ids:
            print(j, post(j))
    elif a.cmd == "reset-claimed":                  # worker 中断后，把未完成的认领放回队列
        for d in QROOT.glob("*"):
            if (d / "CLAIMED").exists() and not (d / "SOLVED").exists():
                (d / "CLAIMED").rename(d / "READY")
                print("requeued", d.name)
