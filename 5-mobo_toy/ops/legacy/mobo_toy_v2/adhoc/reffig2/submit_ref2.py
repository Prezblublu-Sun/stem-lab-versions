"""参考组图（20/40/60 mm 族）的有限元作业登记（adhoc，Linux）。用户 2026-10-02 要求图中给出微动与应力屏蔽数值。
设计取自 ref_figs2.py 的输出 ref2_figs.json（图一 9 个、图二的 b/c/d 6 个；图二的 a 与图一同一设计，共用作业）。
全部 kind = variant、stage = ref2：不进任何常规数据集；锥度 0.3 / 1.5 也不在颈部柄优化（stage_neckopt）的族内。
M1 界面模型，过盈 0.025 mm，slip_tol 2.5e-4，生产网格 2.0 mm —— 与领 / 颈部柄作业相同。

    run.sh ../adhoc/reffig2/submit_ref2.py submit | status
"""
import json
import pathlib
import sys

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "code")); sys.path.insert(0, str(HOME / "code" / "v2"))
import jobs as J  # noqa: E402
import stage_m1 as M1S  # noqa: E402

SRC = HOME / "adhoc" / "reffig2" / "out" / "ref2_figs.json"
IDS = HOME / "adhoc" / "reffig2" / "ref2_ids.json"
KEYS = ("L", "rho_tip", "q", "lam", "g_ml", "g_ap", "n_a", "n_p", "tau_a", "tau_p", "alpha", "m", "cap_h")


def spec_of(rec: dict, tag: str) -> dict:
    d = {k: float(rec["design"][k]) for k in KEYS}
    if rec["design"].get("collar_w", 0.0) > 1e-6:
        d.update(collar_w=float(rec["design"]["collar_w"]), collar_t=float(rec["design"]["collar_t"]))
    core = M1S.core_of(None)
    s = {"h_int": 2.0, "min_A0": core["min_A0"], "design": d, "kind": "variant", "stage": "ref2", "model": "m1",
         "slip_tol": 2.5e-4, "delta": 0.025, "tag": tag}
    if abs(rec["h_cut"] - 25.0) > 1e-9:
        s["h_cut"] = float(rec["h_cut"])
    return s


def submit():
    R = json.loads(SRC.read_text())
    ids = {}
    for k, rec in R["fig1"].items():
        ids[k] = J.submit(spec_of(rec, k.replace("-", "")))
    for k, rec in R["fig2"].items():
        if k.endswith("-a"):
            ids[k] = ids[k[:-2]]                                  # 与图一同一设计
            assert rec["design"] == R["fig1"][k[:-2]]["design"] and rec["h_cut"] == R["fig1"][k[:-2]]["h_cut"]
        else:
            ids[k] = J.submit(spec_of(rec, k.replace("-", "")))
    IDS.write_text(json.dumps(ids, indent=1))
    print(json.dumps(ids, indent=1))


def status():
    ids = json.loads(IDS.read_text())
    st = {}
    for k, j in ids.items():
        s = J.state(J.QROOT / j)
        st.setdefault(s, []).append(k)
        if s == "FAILED":
            f = json.loads((J.QROOT / j / "FAILED.json").read_text())
            print("FAILED", k, j, f.get("level"), (f.get("reason") or "")[:200].replace("\n", " | "))
    print(json.dumps({k: len(v) for k, v in st.items()}))
    for k, v in st.items():
        print(k, sorted(set(v)))


if __name__ == "__main__":
    {"submit": submit, "status": status}[sys.argv[1]]()
