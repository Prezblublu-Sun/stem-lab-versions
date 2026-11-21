"""M1 界面模型验证的结果汇总（在 Linux 上跑）：直接读队列里的作业结果，不依赖各阶段驱动是否已结束。

    python v2/report_m1.py     → results/m1_report/{summary.json, F1_delta.png, F2_compare.png, F3_noise.png}
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import psv2  # noqa: E402,F401
import plotstyle as ps  # noqa: E402
import geom3d as G  # noqa: E402
import jobs as J  # noqa: E402
import post_m1 as PM  # noqa: E402

plt = ps.plt
OUT = J.RESULTS / "m1_report"
KEYS = ("f1_p95_um", "f1_rev_p50_um", "f1_first_p95_um", "f1_closed_p95_um", "f1_canc_p95_um", "f1_cslip_p95_um", "normal_rev_p95_um",
        "area_frac_gt40", "area_frac_gt150", "open_frac_release", "open_frac_load2", "gap_p95_release_um", "cpress_release_p50",
        "cpress_release_p95", "status_frac_stick", "status_frac_slip", "status_frac_open", "stick_cslip_p95_um",
        "stick_cslip_max_um", "f2_g7_loss_pct", "vm_p99", "cortex_area_frac", "n_pairs", "interface_area", "intact_substituted_h")
FLOOR = 1.0            # µm，数值地板（2 × slip tolerance × 单元尺寸）
COL = {"base": ps.DORR["A"], "readout": ps.DORR["C"], "short": ps.DORR["B"]}
NAME = {"base": "base (L 60, α 20°)", "readout": "former read-out (L 53, α 39°)", "short": "short (L 25, α 37°)"}


def gap_fracs(d: pathlib.Path) -> dict:
    """压配后（RELEASE 步末）界面间隙超过 1 / 5 µm 的面积比例，以及其中皮质相邻节点所占份额。"""
    p = PM.pairs(d)
    U = PM._utab(d / "m_fric_csv" / "RELEASE_U.csv", p["n"])
    rel = U[p["pair_stem"]] - U[p["pair_bone"]]
    gap = -(p["pair_interf"] + (rel * p["pair_normal"]).sum(1)) * 1e3
    w, c = p["pair_area"], p["pair_cortex"]
    o5 = gap > 5.0
    return {"open1_frac_release": float(w[gap > 1.0].sum() / w.sum()), "open5_frac_release": float(w[o5].sum() / w.sum()),
            "open5_cortex_share": float(w[o5 & c].sum() / w[o5].sum()) if o5.any() else 0.0}


def collect() -> list[dict]:
    rows = []
    for d in sorted(J.QROOT.glob("m1_*")):
        sp = d / "spec.json"
        if not sp.exists():
            continue
        spec = json.loads(sp.read_text())
        if spec.get("kind") != "design":
            continue
        dsg = G.design_of_spec(spec)
        r = J.result(d.name)
        row = {"job_id": d.name, "state": J.state(d), "label": spec["tag"].split("_h")[0], "h": spec["h_int"],
               "slip_tol": spec.get("slip_tol"), "lagrange": bool(spec.get("lagrange", False)),
               "delta": spec.get("delta", 0.10), "mu": spec.get("mu", 0.3), "torque": spec.get("torque", True),
               "L": dsg["L"], "alpha": dsg["alpha"], "m": dsg["m"], "h_cut": spec.get("h_cut", 25.0)}
        if r and "failed" in r:
            row["failed"] = {"level": r["failed"]["level"], "reason": r["failed"]["reason"][:200]}
        elif r:
            row.update({k: r[k] for k in KEYS if k in r})
            row["A0"] = (r.get("templating") or {}).get("A0")
            row["wall_fric_s"] = r["solve"]["m_fric"].get("wall_s")
            row["wall_bond_s"] = r["solve"]["m_bond"].get("wall_s")
            row["n_tet"] = r.get("n_tet")
            row.update(gap_fracs(d))
        rows.append(row)
    return rows


def old_results(suffixes) -> dict:
    out = {}
    for d in J.QROOT.glob("*"):
        if d.name.startswith("m1") or d.name[-8:] not in suffixes or not (d / "result.json").exists():
            continue
        r = json.loads((d / "result.json").read_text())
        out[d.name[-8:]] = {"job_id": d.name, "f1_p95_um": r["f1_p95_um"], "frac_open": r.get("frac_open"),
                            "f2_g7_loss_pct": r["f2_g7_loss_pct"], "vm_p99": r["vm_p99"],
                            "wall_fric_s": r["solve"]["m_fric"].get("wall_s")}
    return out


def std(rows, **kw):
    """生产设置（罚函数 2.5e-4、μ 0.3、带扭转）下满足条件的已完成作业。"""
    out = []
    for r in rows:
        if "f1_p95_um" not in r or r["lagrange"] or r["slip_tol"] != 0.00025 or r["mu"] != 0.3 or not r["torque"]:
            continue
        if all(abs(r[k] - v) < 1e-9 if isinstance(v, float) else r[k] == v for k, v in kw.items()):
            out.append(r)
    return out


def fig_delta(rows):
    fig, axes = ps.new_figure("double", 70, 1, 2, sharey=True)
    for lab in ("base", "readout", "short"):
        rr = sorted(std(rows, label=lab, h=2.0), key=lambda r: r["delta"])
        if not rr:
            continue
        x = [r["delta"] for r in rr]
        axes[0].plot(x, [r["f1_p95_um"] for r in rr], "o-", color=COL[lab], ms=3, lw=0.9, label=NAME[lab])
        axes[1].plot(x, [r["f1_first_p95_um"] for r in rr], "o-", color=COL[lab], ms=3, lw=0.9, label=NAME[lab])
    for ax, ttl in ((axes[0], "reversible, second load cycle"), (axes[1], "first loading (includes seating)")):
        ax.set_yscale("log")
        ps.plain_log(ax, "y")
        for t in (40.0, 150.0):
            ax.axhline(t, color="black", lw=0.5, ls="--")
        ax.axhspan(0.05, FLOOR, color=ps.LIGHT, alpha=0.35, lw=0)
        ax.set_xlabel("prescribed interference δ (mm)")
        ax.set_title(ttl, fontsize=7)
        ax.set_ylim(0.2, 400)
    axes[0].set_ylabel("micromotion P95 (µm)")
    axes[0].legend(fontsize=6, loc="upper right")
    axes[0].text(0.098, 0.27, "below numerical floor (1 µm)", fontsize=6, ha="right")
    fig.savefig(OUT / "F1_delta.png", dpi=220)
    plt.close(fig)


def fig_compare(rows, old):
    rr = [r for r in std(rows, h=2.0, delta=0.05) if r["label"].startswith("cmp") and r["label"][3:] in old]
    if len(rr) < 3:
        return None
    from scipy.stats import spearmanr
    a = np.array([old[r["label"][3:]]["f1_p95_um"] for r in rr])
    out = {"n": len(rr)}
    fig, axes = ps.new_figure("double", 70, 1, 2)
    for ax, key, lab in ((axes[0], "f1_p95_um", "new interface: reversible micromotion P95 (µm)"),
                         (axes[1], "f1_first_p95_um", "new interface: first-loading micromotion P95 (µm)")):
        b = np.array([r[key] for r in rr])
        sc = ax.scatter(a, b, c=[r["L"] for r in rr], s=14, cmap="viridis", lw=0)
        lo, hi = 0.3, 400.0
        ax.plot([lo, hi], [lo, hi], color="black", lw=0.5, ls="--")
        ax.set_xscale("log")
        ax.set_yscale("log")
        ps.plain_log(ax, "x")
        ps.plain_log(ax, "y")
        ax.set_xlim(3, 200)
        ax.set_ylim(lo, hi)
        ax.set_xlabel("old interface: slip-increment P95 (µm)")
        ax.set_ylabel(lab)
        out[f"spearman_{key}"] = float(spearmanr(a, b)[0])
        out[f"median_ratio_{key}"] = float(np.median(b / a))
    axes[0].axhspan(lo, FLOOR, color=ps.LIGHT, alpha=0.35, lw=0)
    fig.colorbar(sc, ax=axes, shrink=0.8, pad=0.02).set_label("stem length L (mm)", fontsize=6)
    fig.savefig(OUT / "F2_compare.png", dpi=220)
    plt.close(fig)
    return out


def noise_table(rows):
    out = {}
    hs = (1.94, 1.97, 2.0, 2.03, 2.06)
    for lab in ("base", "readout", "short"):
        rr = [r for r in std(rows, label=lab, delta=0.10) if any(abs(r["h"] - h) < 1e-9 for h in hs)]
        if len(rr) < 3:
            out[lab] = {"n": len(rr)}
            continue
        o = {"n": len(rr), "h": sorted(r["h"] for r in rr)}
        for q in ("f1_p95_um", "f1_first_p95_um", "f1_cslip_p95_um", "f2_g7_loss_pct", "vm_p99", "open_frac_release"):
            v = np.array([r[q] for r in sorted(rr, key=lambda r: r["h"])], float)
            o[q] = {"values": v.tolist(), "mean": float(v.mean()), "sd": float(v.std(ddof=1)),
                    "cv_pct": float(100 * v.std(ddof=1) / abs(v.mean())), "range": [float(v.min()), float(v.max())]}
        out[lab] = o
    return out


def fig_noise(nz):
    labs = [k for k in ("base", "readout", "short") if nz.get(k, {}).get("n", 0) >= 3]
    if not labs:
        return
    fig, axes = ps.new_figure("double", 62, 1, 2)
    for ax, q, yl in ((axes[0], "f1_p95_um", "reversible micromotion P95 (µm)"), (axes[1], "f1_first_p95_um", "first-loading micromotion P95 (µm)")):
        for lab in labs:
            ax.plot(nz[lab]["h"], nz[lab][q]["values"], "o-", color=COL[lab], ms=3, lw=0.8,
                    label=f"{NAME[lab]}: CV {nz[lab][q]['cv_pct']:.1f}%")
        ax.set_yscale("log")
        ps.plain_log(ax, "y")
        ax.set_xlabel("interface element size (mm)")
        ax.set_ylabel(yl)
        ax.legend(fontsize=6)
    fig.savefig(OUT / "F3_noise.png", dpi=220)
    plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = collect()
    old = old_results({r["label"][3:] for r in rows if r["label"].startswith("cmp")} | {"e265f0bf", "62bbf792", "92712f81"})
    fig_delta(rows)
    cmp_ = fig_compare(rows, old)
    nz = noise_table(rows)
    fig_noise(nz)
    lame = json.loads((J.RESULTS / "m1_lame.json").read_text()) if (J.RESULTS / "m1_lame.json").exists() else None
    summ = {"rows": rows, "old": old, "compare": cmp_, "noise": nz, "lame": lame,
            "states": {s: sum(r["state"] == s for r in rows) for s in sorted({r["state"] for r in rows})}}
    (OUT / "summary.json").write_text(json.dumps(summ, indent=1, default=float))
    print(json.dumps({"states": summ["states"], "compare": cmp_, "noise": {k: {q: (v[q]["cv_pct"] if isinstance(v.get(q), dict) else None)
                                                                                for q in ("f1_p95_um", "f1_first_p95_um", "f2_g7_loss_pct", "vm_p99")} | {"n": v.get("n")}
                                                                            for k, v in nz.items()}}, indent=1, default=float))


if __name__ == "__main__":
    main()
