"""Load-induced bearing measures for the collarless (neck_in_shoulder) current-code jobs (READ-ONLY on the queue).

CPRESS at LOAD2 is mostly the press-fit pre-stress (interference 0.025 mm); the part carried because of the hip load is
dp = CPRESS(LOAD2) - CPRESS(UNLOAD) (same contact state history, second cycle).  Per job (stem-body pairs, bone side):
  bear_Fn_dp_N           sum(area * max(dp, 0))                      load-induced normal force (N)
  bear_A_dp_gt{0.1,0.5,1} area where dp > threshold (MPa)            "load-bearing area"
  bear_Aeff_dp           (sum w dp+)^2 / sum(w dp+^2)               participation area of the load-induced pressure
  bear_share_dp_t_le{1,2} share of bear_Fn_dp_N within cancellous thickness t <= 1 / 2 mm
  bear_Aeff_load2_cap    participation area of CPRESS(LOAD2) with values capped at the job's area-weighted P99 (robust)
  bear_A_closed_load_and_load2  closed (gap <= 1 um) at both peaks
  bear_A_closed_unload   closed after unloading
writes ~/mobo_toy_v2/deck/ml_eff/objectives/bearing_collarless.csv
"""
from __future__ import annotations

import csv
import json
import pathlib
import sys
import time
from multiprocessing import Pool

import numpy as np

HOME = pathlib.Path.home() / 'mobo_toy_v2'
sys.path.insert(0, str(HOME / 'code'))
sys.path.insert(0, str(HOME / 'code' / 'v2'))
import femur_real as FR  # noqa: E402
import jobs as J  # noqa: E402
import post_m1 as PM  # noqa: E402

OUT = HOME / 'deck' / 'ml_eff' / 'objectives'
TABLE = HOME / 'deck' / 'ml_eff' / 'data' / 'metrics_all.csv'
_FM = {}


def femur(h):
    if 'b' not in _FM:
        _FM['b'] = FR.build()
    return _FM['b'] if h is None else _FM['b'].with_cut(float(h))


def wq(x, w, q):
    o = np.argsort(x)
    x, w = x[o], w[o]
    c = (np.cumsum(w) - 0.5 * w) / w.sum()
    return float(np.interp(q, c, x))


def one(job):
    d = J.QROOT / job
    try:
        spec = json.loads((d / 'spec.json').read_text())
        fm = femur(spec.get('h_cut'))
        p = PM.pairs(d)
        n = p['n']
        lut = np.full(int(p['node_labels'].max()) + 1, -1)
        lut[p['node_labels'].astype(int)] = np.arange(len(p['node_labels']))
        X = p['nodes'][lut[p['pair_bone'].astype(int)]]
        body = ~p['pair_collar']
        w = p['pair_area'][body]
        t = -fm.canal_sdf(X)[body]
        pb = p['pair_bone'][body]
        P = {}
        for s in ('LOAD2', 'UNLOAD'):
            c = PM._ctab(d / 'm_fric_csv' / f'{s}_CONTACT.csv', n)['CPRESS'][pb]
            P[s] = np.where(np.isfinite(c), np.maximum(c, 0.0), 0.0)
        dp = P['LOAD2'] - P['UNLOAD']
        dpp = np.maximum(dp, 0.0)
        out = {'job': job}
        Fn = float((w * dpp).sum())
        out['bear_Fn_dp_N'] = Fn
        out['bear_Fn_dp_neg_N'] = float((w * np.minimum(dp, 0.0)).sum())
        for lv in (0.1, 0.5, 1.0):
            out[f'bear_A_dp_gt{lv:g}'] = float(w[dp > lv].sum())
        out['bear_Aeff_dp'] = float(Fn ** 2 / max((w * dpp ** 2).sum(), 1e-12))
        for lv in (1.0, 2.0):
            out[f'bear_share_dp_t_le{lv:g}'] = float((w * dpp)[t <= lv].sum() / max(Fn, 1e-12))
        p2 = P['LOAD2']
        cap = wq(p2, w, 0.99)
        pc = np.minimum(p2, cap)
        out['bear_p99_load2'] = cap
        out['bear_Aeff_load2_cap'] = float((w * pc).sum() ** 2 / max((w * pc ** 2).sum(), 1e-12))
        U = {s: PM._utab(d / 'm_fric_csv' / f'{s}_U.csv', n) for s in ('LOAD', 'UNLOAD', 'LOAD2')}
        nm, di = p['pair_normal'], p['pair_interf']
        gap = {s: (-(di + ((U[s][p['pair_stem']] - U[s][p['pair_bone']]) * nm).sum(1)) * 1e3)[body] for s in U}
        out['bear_A_closed_load_and_load2'] = float(w[(gap['LOAD'] <= PM.OPEN_UM) & (gap['LOAD2'] <= PM.OPEN_UM)].sum())
        out['bear_A_closed_unload'] = float(w[gap['UNLOAD'] <= PM.OPEN_UM].sum())
        out['bear_A_closed_load2'] = float(w[gap['LOAD2'] <= PM.OPEN_UM].sum())
        return out
    except Exception as e:  # noqa: BLE001
        return {'job': job, 'err': f'{type(e).__name__}: {e}'[:200]}


def main():
    rows = list(csv.DictReader(open(TABLE, newline='')))
    sel = [r['job'] for r in rows if r['current_code'] == 'True' and r['variant_class'] == 'none' and r['collar_rule'] == 'neck_in_shoulder']
    print(len(sel), 'jobs', flush=True)
    t0 = time.time()
    with Pool(3) as pool:
        res = list(pool.imap_unordered(one, sel, chunksize=4))
    ok = [r for r in res if 'err' not in r]
    keys = list(ok[0])
    with open(OUT / 'bearing_collarless.csv', 'w', newline='') as fh:
        wr = csv.DictWriter(fh, fieldnames=keys)
        wr.writeheader()
        wr.writerows(ok)
    print(json.dumps({'n_ok': len(ok), 'errs': [r for r in res if 'err' in r][:5], 'elapsed_s': time.time() - t0}), flush=True)


if __name__ == '__main__':
    main()
