"""柄长 20/40/60 × 截面（圆、椭圆 λ 1.3、非对称 = 基准截面）× 锥度 × 插入角 的可放置性（只模板化；adhoc，只读）。
平端（cap_h = CAP_FLAT）、余量 −0.25、截骨 25 mm。输出每个组合在每个 α 下的肩部面积，判定 ≥ 假体颈面积 154 mm² 为可行。"""
import json
import pathlib
import sys
from multiprocessing import Pool

import numpy as np

CODE = pathlib.Path.home() / "mobo_toy_v2" / "code"
sys.path.insert(0, str(CODE)); sys.path.insert(0, str(CODE / "v2"))
import femur_real as FR  # noqa: E402
import geom3d as G  # noqa: E402
import stage_v2a as S  # noqa: E402

OUT = pathlib.Path.home() / "mobo_toy_v2" / "adhoc" / "reffig2" / "out"
OUT.mkdir(parents=True, exist_ok=True)
TAPERS = {"neck (0.5, 1.0)": (0.5, 1.0), "V3 (0.3, 1.5)": (0.3, 1.5), "base (0.15, 2.5)": (0.15, 2.5)}
ALPHAS = np.arange(10.0, 45.01, 2.5)
_FM = {}


def section(sec, L, rho, q, a):
    if sec == "asym":
        d = {**S.BASE, "L": L, "rho_tip": rho, "q": q, "alpha": a, "m": G.M_LEGACY}
    else:
        d = G.ellipse_design(L, rho, q, 1.0 if sec == "circ" else 1.3, a)
    d["cap_h"] = G.CAP_FLAT
    return d


def work(args):
    sec, L, tk, a = args
    if "fm" not in _FM:
        _FM["fm"] = FR.build()
    rho, q = TAPERS[tk]
    st = G.Stem3D(**section(sec, L, rho, q, a))
    pl = G.template(st, _FM["fm"])
    return {"sec": sec, "L": L, "taper": tk, "alpha": a, "fit": bool(pl["fit"]), "A0": float(pl["A0"]) if pl["fit"] else None,
            "removal": float(pl["volume"]) if pl["fit"] else None}


if __name__ == "__main__":
    jobs = [(s, L, tk, float(a)) for s in ("circ", "ell", "asym") for L in (20.0, 40.0, 60.0) for tk in TAPERS for a in ALPHAS]
    with Pool(3) as p:
        rows = p.map(work, jobs, chunksize=4)
    (OUT / "taper_alpha.json").write_text(json.dumps(rows, indent=0))
    for tk in TAPERS:
        print("==", tk)
        for s in ("circ", "ell", "asym"):
            for L in (20.0, 40.0, 60.0):
                rr = [r for r in rows if r["taper"] == tk and r["sec"] == s and r["L"] == L]
                ok = [r for r in rr if r["fit"] and r["A0"] >= S.MIN_A0]
                best = max(ok, key=lambda r: r["A0"]) if ok else None
                rng = f"{min(r['alpha'] for r in ok):.1f}-{max(r['alpha'] for r in ok):.1f}" if ok else "none"
                print(f"  {s:5s} L{L:.0f}: feasible alpha {rng}; best alpha {best['alpha'] if best else '-'} "
                      f"A0 {round(best['A0']) if best else '-'} removal {round(best['removal'] / 1000, 1) if best else '-'} cm3", flush=True)
