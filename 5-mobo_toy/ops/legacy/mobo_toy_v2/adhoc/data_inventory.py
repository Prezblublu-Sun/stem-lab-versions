"""数据盘点（Linux，只读）：~/mobo_toy_v2/queue 里全部作业，按阶段族、状态统计；每类保存了哪些场文件（摩擦 / 粘接）、大小；
抽样看 *_U.csv 是全部节点还是只有界面节点、*_S / *_E 是全部单元还是部分；网格规模（四面体、界面节点对）；
结果字段（result.json）有哪些。输出 ~/mobo_toy_v2/deck/data_inventory.json 并打印摘要。"""
from __future__ import annotations

import collections
import json
import pathlib
import random
import re

HOME = pathlib.Path.home() / "mobo_toy_v2"
Q = HOME / "queue"


def state(d):
    for m, s in (("DONE", "DONE"), ("FAILED.json", "FAILED"), ("SOLVED", "SOLVED"), ("CLAIMED", "CLAIMED"), ("READY", "READY")):
        if (d / m).exists():
            return s
    return "NEW"


def family(name, spec):
    st = str(spec.get("stage", ""))
    m = re.match(r"(neck\d+|[a-z_]+?)(_|$)", st)
    return st if st.startswith("neck") else (m.group(1) if m else st) or name.split("_")[0]


def nlines(p):
    try:
        with open(p, "rb") as fh:
            return sum(1 for _ in fh) - 1
    except OSError:
        return None


if __name__ == "__main__":
    rows = []
    for d in Q.iterdir():
        if not d.is_dir() or not (d / "spec.json").exists():
            continue
        try:
            spec = json.loads((d / "spec.json").read_text())
        except Exception:                                               # noqa: BLE001
            continue
        rows.append({"job": d.name, "family": family(d.name, spec), "kind": spec.get("kind"), "state": state(d), "model": spec.get("model"),
                     "bond_only": bool(spec.get("bond_only")), "collar": bool((spec.get("design") or {}).get("collar_w")),
                     "rule": spec.get("collar_rule"), "cfg": bool(spec.get("cfg")), "h_int": spec.get("h_int"),
                     "has_fric_csv": (d / "m_fric_csv").exists(), "has_bond_csv": (d / "m_bond_csv").exists(), "has_mesh": (d / "mesh3d.npz").exists(),
                     "bytes": sum(f.stat().st_size for f in d.rglob("*") if f.is_file())})
    fam = collections.defaultdict(collections.Counter)
    for r in rows:
        fam[r["family"]][r["state"]] += 1
    done_design = [r for r in rows if r["state"] == "DONE" and r["kind"] in ("design", "variant") and r["model"] == "m1" and not r["bond_only"]]
    summ = {"n_jobs": len(rows), "by_state": dict(collections.Counter(r["state"] for r in rows)), "by_kind": dict(collections.Counter(r["kind"] for r in rows)),
            "total_GB": sum(r["bytes"] for r in rows) / 1e9, "m1_full_done": len(done_design),
            "m1_full_done_with_fric_csv": sum(r["has_fric_csv"] for r in done_design), "m1_full_done_with_mesh": sum(r["has_mesh"] for r in done_design),
            "m1_full_done_collar": sum(r["collar"] for r in done_design), "m1_full_done_rule": dict(collections.Counter(str(r["rule"]) for r in done_design)),
            "m1_full_done_cfg_override": sum(r["cfg"] for r in done_design), "m1_full_done_h_int": dict(collections.Counter(str(r["h_int"]) for r in done_design)),
            "families": {k: dict(v) for k, v in sorted(fam.items(), key=lambda kv: -sum(kv[1].values()))}}
    # 抽样看文件内容
    random.seed(1)
    samp = random.sample(done_design, min(6, len(done_design)))
    files = []
    for r in samp:
        d = Q / r["job"]
        import numpy as np
        m = np.load(d / "mesh3d.npz")
        info = {"job": r["job"], "npz_keys": {k: list(m[k].shape) for k in m.files}}
        for sub in ("m_fric_csv", "m_bond_csv"):
            if (d / sub).exists():
                info[sub] = {f.name: {"MB": round(f.stat().st_size / 1e6, 2), "rows": nlines(f)} for f in sorted((d / sub).iterdir())}
        hdr = {}
        for f in ("LOAD_U.csv", "LOAD_S.csv", "LOAD_E.csv", "LOAD_CONTACT.csv"):
            p = d / "m_fric_csv" / f
            if p.exists():
                hdr[f] = p.open().readline().strip()[:160]
        p = d / "m_bond_csv" / "LOAD_ENER.csv"
        if p.exists():
            hdr["bond/LOAD_ENER.csv"] = p.open().readline().strip()[:160]
        info["headers"] = hdr
        res = json.loads((d / "result.json").read_text()) if (d / "result.json").exists() else {}
        info["result_keys"] = sorted(res.keys())[:80]
        info["n_nodes"] = int(len(m["node_labels"])) if "node_labels" in m.files else None
        files.append(info)
    out = {"summary": summ, "samples": files}
    (HOME / "deck").mkdir(exist_ok=True)
    (HOME / "deck" / "data_inventory.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps(summ, indent=1, default=str))
    s0 = files[0]
    print("SAMPLE", s0["job"], "nodes", s0["n_nodes"])
    print(" npz", s0["npz_keys"])
    for sub in ("m_fric_csv", "m_bond_csv"):
        print(" ", sub, {k: v for k, v in (s0.get(sub) or {}).items()})
    print(" headers", json.dumps(s0["headers"], indent=0))
    print(" result keys", s0["result_keys"])
