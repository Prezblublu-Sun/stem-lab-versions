"""Z1 fracture screening, read-only on the queue, 0 FE. Friction model output of every DONE row: principal tensile strain e_max and Mises in the cortex, after release and at the last load.
Neck band = cortex elements 0 to 10, 20 or 30 mm below the row's own cut plane, measured along the cut normal u3. Volume-weighted P99 and element maximum, with the location of the maximum.
usage (from ~/mobo_toy_v2/code/v2): ../../run.sh z1_neck_strain.py <jobs.txt> <out.jsonl> [workers] [--limit N]"""
import json, multiprocessing as mp, pathlib, sys, time
sys.path[:0] = [".", ".."]
import numpy as np
import jobs as J
import tpl_record as TR

BANDS = (10.0, 20.0, 30.0)
STRAIN_LIMIT = 106.0 / 16800.0
FEM = {}


def wq(x, w, q):
    i = np.argsort(x)
    c = np.cumsum(w[i])
    return float(x[i][np.searchsorted(c, q * c[-1])])


def femur(spec):
    h = spec.get("h_cut")
    k = None if h is None else round(float(h), 6)
    if k not in FEM:
        rule = TR.spec_rule(spec)
        fm = TR.base_femur(rule.femur_id, rule.neck_axis)
        FEM[k] = fm if h is None else fm.with_cut(float(h))
    return FEM[k]


def one(job):
    d = J.QROOT / job
    out = {"job_id": job}
    try:
        spec = json.load(open(d / "spec.json"))
        f = d / "m_fric_csv"
        if not (f / "LOAD2_E.csv").exists() or not (f / "RELEASE_E.csv").exists():
            out["skip"] = "no friction E output"
            return out
        z = np.load(d / "mesh3d.npz", allow_pickle=True)
        labs, nodes = z["node_labels"].astype(int), z["nodes"]
        idx = np.zeros(labs.max() + 1, dtype=int)
        idx[labs] = np.arange(len(labs))
        P = nodes[idx[z["cortex_conn"][:, :4].astype(int)]]
        cen = P.mean(1)
        vol = np.abs(np.einsum("ij,ij->i", P[:, 1] - P[:, 0], np.cross(P[:, 2] - P[:, 0], P[:, 3] - P[:, 0]))) / 6
        el = z["cortex_elab"].astype(int)
        fm = femur(spec)
        rel = cen - fm.C03
        depth = -(rel @ fm.u3)
        side = rel @ fm.n3                                     # + = medial-inferior (calcar side), - = superior-lateral
        ap = rel[:, 1]
        out["n_cortex"] = int(len(el))
        for st in ("RELEASE", "LOAD2"):
            E = np.loadtxt(f / f"{st}_E.csv", delimiter=",", skiprows=1, usecols=(0, 1))
            S = np.loadtxt(f / f"{st}_S.csv", delimiter=",", skiprows=1, usecols=(0, 1))
            ne, ns = np.full(int(E[:, 0].max()) + 1, np.nan), np.full(int(S[:, 0].max()) + 1, np.nan)
            ne[E[:, 0].astype(int)] = E[:, 1]
            ns[S[:, 0].astype(int)] = S[:, 1]
            e, s = ne[el], ns[el]
            if np.isnan(e).any() or np.isnan(s).any():
                out["error"] = f"{st}: cortex elements without a value"
                return out
            r = {"whole_emax": float(e.max()), "whole_e_p99": wq(e, vol, 0.99), "whole_s_max": float(s.max()), "whole_s_p99": wq(s, vol, 0.99)}
            for b in BANDS:
                m = (depth >= 0.0) & (depth <= b)
                if not m.any():
                    continue
                i = np.flatnonzero(m)[int(e[m].argmax())]
                r[f"n{b:g}"] = {"n": int(m.sum()), "vol": float(vol[m].sum()), "emax": float(e[i]), "e_p99": wq(e[m], vol[m], 0.99), "e_p95": wq(e[m], vol[m], 0.95),
                                "s_max": float(s[m].max()), "s_p99": wq(s[m], vol[m], 0.99), "at_depth": float(depth[i]), "at_side": float(side[i]), "at_ap": float(ap[i]),
                                "over_vol_frac": float(vol[m][e[m] > STRAIN_LIMIT].sum() / vol[m].sum())}
            out[st] = r
    except Exception as ex:                                     # noqa: BLE001
        out["error"] = f"{type(ex).__name__}: {str(ex)[:200]}"
    return out


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    lim = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
    if lim is not None:
        a = [x for x in a if x != str(lim)]
    jobs_ = [l.strip() for l in open(a[0]) if l.strip()]
    jobs_ = [j for j in jobs_ if (J.QROOT / j / "DONE").exists()]
    if lim:
        jobs_ = jobs_[:lim]
    out = pathlib.Path(a[1])
    if out.exists():
        raise SystemExit(f"{out} exists")
    w = int(a[2]) if len(a) > 2 else 4
    t0 = time.time()
    with mp.get_context("fork").Pool(w) as pool, open(out, "w") as fo:
        for k, r in enumerate(pool.imap(one, jobs_, chunksize=8)):
            fo.write(json.dumps(r) + "\n")
            if (k + 1) % 100 == 0:
                print(f"{k + 1}/{len(jobs_)} {time.time() - t0:.0f}s", flush=True)
    print(f"done {len(jobs_)} {time.time() - t0:.0f}s", flush=True)
