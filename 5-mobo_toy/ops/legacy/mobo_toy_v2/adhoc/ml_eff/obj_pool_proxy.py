"""Template-time geometric descriptors for the phase-10 candidate pool (no FE): re-runs the neck_in_shoulder templating
for each feasible pool point and computes the same g_* descriptors as features.py.  READ-ONLY on results/ and code/.
usage: pool_proxy.py [max_points]
"""
from __future__ import annotations

import csv
import importlib.util
import json
import pathlib
import sys
import time
from multiprocessing import Pool

import numpy as np

HOME = pathlib.Path.home() / 'mobo_toy_v2'
sys.path.insert(0, str(HOME / 'code'))
sys.path.insert(0, str(HOME / 'code' / 'v2'))
spec = importlib.util.spec_from_file_location('feat', str(HOME / 'adhoc' / 'ml_eff' / 'obj_features.py'))
FT = importlib.util.module_from_spec(spec)
spec.loader.exec_module(FT)
import geom3d as G  # noqa: E402
import stage_neckopt as SN  # noqa: E402
import stage_v2a as S  # noqa: E402

OUT = HOME / 'deck' / 'ml_eff' / 'objectives'
_PH = {}


def one(arg):
    idx, u = arg
    try:
        if 'ph' not in _PH:
            _PH['ph'] = SN.Phase(10)
        ph = _PH['ph']
        d, h = ph.design_of(u)
        fm = FT.femur(h)
        st = G.Stem3D(**d)
        r = ph.template(st, fm)
        if not (r.get('fit') and r['A0'] >= S.MIN_A0):
            return {'pool_idx': idx, 'fit': False}
        pose = fm.pose(r['alpha'], r['e'])
        P0, dax, e_ml, e_ap = pose
        dax = dax / np.linalg.norm(dax)
        cen, area, nrm, loc = FT.surface_cells(st, r['A0'], pose)
        ins = fm.below_cut(cen) & (fm.outer_sdf(cen) <= 0)
        cen, area, nrm, loc = cen[ins], area[ins], nrm[ins], loc[ins]
        t = -fm.canal_sdf(cen)
        out = {'pool_idx': idx, 'fit': True, **{k: d[k] for k in ('L', 'alpha', 'm', 'rho_tip', 'q', 'lam', 'g_ml', 'g_ap', 'n_a', 'n_p',
                                                                 'tau_a', 'tau_p')}, 'h_cut': h,
               'tpl_A0': r['A0'], 'tpl_e': r['e'], 'tpl_volume': r['volume'], 'bone_total_mm3': fm.resected_volume() + r['volume']}
        out.update(FT.descriptors('g_', cen, area, nrm, t, loc, st.L, float(r.get('margin', st.m)), np.asarray(fm.H, float),
                                  FT.load_vector(fm.cfg), P0, dax))
        return out
    except Exception as e:  # noqa: BLE001
        return {'pool_idx': idx, 'fit': False, 'err': f'{type(e).__name__}: {e}'[:160]}


def main():
    z = np.load(HOME / 'results' / 'neckopt_p10_pool_live.npz')
    print('live pool keys', {k: z[k].shape for k in z.files}, flush=True)
    U = z['U'] if 'U' in z.files else z[z.files[0]]
    nmax = int(sys.argv[1]) if len(sys.argv) > 1 else len(U)
    args = [(i, U[i]) for i in range(min(nmax, len(U)))]
    t0 = time.time()
    res = []
    with Pool(3) as p:
        for k, r in enumerate(p.imap_unordered(one, args, chunksize=8)):
            res.append(r)
            if (k + 1) % 200 == 0:
                print(f'{k + 1}/{len(args)} {time.time() - t0:.0f}s', flush=True)
    ok = [r for r in res if r.get('fit')]
    keys = []
    for r in ok:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(OUT / 'pool10_proxies.csv', 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for r in sorted(ok, key=lambda r: r['pool_idx']):
            w.writerow(r)
    meta = {'n_args': len(args), 'n_fit': len(ok), 'n_err': sum(1 for r in res if 'err' in r),
            'errs': [r for r in res if 'err' in r][:10], 'elapsed_s': time.time() - t0}
    (OUT / 'pool10_proxies_meta.json').write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta), flush=True)


if __name__ == '__main__':
    main()
