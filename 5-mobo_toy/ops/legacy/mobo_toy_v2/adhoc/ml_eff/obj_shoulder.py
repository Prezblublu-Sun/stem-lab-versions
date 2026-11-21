"""Where does the stem surface come closer to the cortex than the design margin m?  (mesh-level, from node_table.npz)

Templating (geom3d.penetration via Stem3D.local_surface) samples the shoulder prism above s = 0 only at s = -7.5, -15, ...
so the strip of prism between the cut plane and the shoulder ring (s in about -6..0 mm) is not checked against the margin.
This script measures, per job, the cancellous-layer thickness t (= -canal_sdf at the bone-side interface node) separately for
s < 0 (prism above the shoulder ring, below the cut) and s >= 0 (tapered body), and the interface area / closed area that is
closer than m - 0.1 mm, closer than 0 (inside the analytic cortex), and flagged cortex in the mesh (pair_cortex).
READ-ONLY; writes ~/mobo_toy_v2/deck/ml_eff/objectives/shoulder_margin.csv
"""
from __future__ import annotations

import csv
import json
import pathlib

import numpy as np

HOME = pathlib.Path.home() / 'mobo_toy_v2'
OUT = HOME / 'deck' / 'ml_eff' / 'objectives'


def main():
    z = np.load(OUT / 'node_table.npz', allow_pickle=True)
    X, jidx, jobs, cols = z['X'], z['job_idx'], z['jobs'], list(z['cols'])
    ci = {c: i for i, c in enumerate(cols)}
    sL, t, cort, area, cl, m, L = (X[:, ci[k]].astype(np.float64) for k in ('s_over_L', 't_canc', 'cortex', 'area', 'closed_load2', 'm', 'L'))
    s = sL * L
    rows = []
    order = np.argsort(jidx, kind='stable')
    bounds = np.searchsorted(jidx[order], np.arange(len(jobs) + 1))
    for k, job in enumerate(jobs):
        ii = order[bounds[k]:bounds[k + 1]]
        if not len(ii):
            continue
        mm = float(m[ii][0])
        up = ii[s[ii] < 0]
        lo = ii[s[ii] >= 0]
        r = {'job': str(job), 'm': mm, 'n_nodes': len(ii), 'area_body': float(area[ii].sum()),
             'area_s_lt0': float(area[up].sum()),
             't_min_s_lt0': float(t[up].min()) if len(up) else np.nan,
             't_min_s_ge0': float(t[lo].min()) if len(lo) else np.nan,
             's_min_mm': float(s[ii].min())}
        for tag, sel in (('below_m', t[ii] < mm - 0.1), ('in_cortex', t[ii] < 0.0), ('flag_cortex', cort[ii] > 0.5)):
            r[f'area_{tag}'] = float(area[ii][sel].sum())
            r[f'closed_area_{tag}'] = float((area[ii] * cl[ii])[sel].sum())
            r[f'area_{tag}_s_lt0'] = float(area[ii][sel & (s[ii] < 0)].sum())
        rows.append(r)
    with open(OUT / 'shoulder_margin.csv', 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    a = np.array([[r['t_min_s_lt0'] - r['m'], r['t_min_s_ge0'] - r['m']] for r in rows])
    print(json.dumps({'n_jobs': len(rows),
                      'median t_min(s<0) - m': float(np.nanmedian(a[:, 0])), 'median t_min(s>=0) - m': float(np.nanmedian(a[:, 1])),
                      'n with t_min(s<0) < m - 0.2': int((a[:, 0] < -0.2).sum()), 'n with t_min(s>=0) < m - 0.2': int((a[:, 1] < -0.2).sum()),
                      'n with any area in analytic cortex': int(sum(r['area_in_cortex'] > 0 for r in rows)),
                      'n with any cortex-flagged pair': int(sum(r['area_flag_cortex'] > 0 for r in rows))}, indent=1))


if __name__ == '__main__':
    main()
