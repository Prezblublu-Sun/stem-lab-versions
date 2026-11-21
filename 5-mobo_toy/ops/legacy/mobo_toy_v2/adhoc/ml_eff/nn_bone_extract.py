"""ml_eff / nn pilot (b2): bone strain-energy field on the FIXED resorption sampling grid (no remeshing problem).

resorption.py already maps every job's bonded-model element SED (LOAD) onto one fixed 1.5 mm grid inside the femur
(nearest element centroid of the same tissue). The calcar metric sed_chg_pct is the G7-cortex mean of that grid
(fixed zones, below the design cut, outside the stem) relative to the standard intact femur. Here the grid values of
the proximal region (z >= Z_MIN) are exported for every clean unique job, so that a network can learn the SED field
and the calcar metric can be recomputed from its predicted field.

Output deck/ml_eff/nn/bone/pack.npz:
  P [M,3] f32, canc [M], gi_log [M] (log intact SED), g7 [M] (fixed G7 mask), code [M] (fixed zone 1..7)
  keep [J,M] bool  kept points per job: below the design cut, outside the stem, finite, intact SED > 0 (FE-free mask)
  off [J+1]; per kept point (job-major, ascending grid index):
     lr f32 = log(SED_implant / SED_intact) (implant SED floored at 1e-4 x intact), rex f16 = stem_radial_excess (mm),
     dpair f16 = distance to the nearest interface bone node (mm), cpair i1 = its cortex flag
  pose [J,4,3] (P0, d, e_ml, e_ap) to rebuild stem-frame coordinates; G [J,23] (nn_scalar 'DT'), jobs, family, rule,
  collar, foldA, y_sed (metrics_all), chk_sed (recomputed G7 cortex sed_chg from the exported points)

    ~/mobo_toy_v2/run.sh ../adhoc/ml_eff/nn_bone_extract.py [--workers 3] [--probe]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import pathlib
import sys
import time
import traceback
from multiprocessing import get_context

os.environ['OMP_NUM_THREADS'] = '1'
HOME = pathlib.Path.home() / 'mobo_toy_v2'
sys.path.insert(0, str(HOME / 'code'))
sys.path.insert(0, str(HOME / 'code' / 'v2'))
import numpy as np  # noqa: E402
from scipy.spatial import cKDTree  # noqa: E402

OUT = HOME / 'deck' / 'ml_eff' / 'nn' / 'bone'
Z_MIN = -40.0
FLOOR = 1e-4
_C = {}


def init():
    import resorption as RS
    RS._init(1)
    P, canc, gi = RS._CTX['P'], RS._CTX['canc'], RS._CTX['gi']['sed']
    reg = P[:, 2] >= Z_MIN
    zf = RS.zones_fixed(P)
    code = np.zeros(len(P), np.int8)
    for k, z in enumerate(RS.ZONES):
        code[zf[z]] = k + 1
    _C.update(RS=RS, fm=RS._CTX['fm'], P=P[reg], canc=canc[reg], gi=gi[reg], g7=zf['G7'][reg], code=code[reg])


def one(job):
    t0 = time.time()
    try:
        import jobs as J
        import geom3d as G
        import shielding as SH
        RS, fm, P, canc, gi = _C['RS'], _C['fm'], _C['P'], _C['canc'], _C['gi']
        d = J.QROOT / job
        spec = json.loads((d / 'spec.json').read_text())
        res = J.result(job)
        t = res['templating']
        stem = G.Stem3D(**spec['design'])
        h = float(spec.get('h_cut', 25.0))
        fh = fm.with_cut(h)
        pose = fh.pose(t['alpha'], t['e'])
        loc = SH.local(P, pose)
        rex = G.stem_radial_excess(stem, t['A0'], loc)
        inside = G.inside_stem(stem, t['A0'], loc)
        ga = RS.to_grid(SH.load_fields(d), P, canc, 1)['sed']
        keep = fh.below_cut(P) & ~inside & np.isfinite(ga) & np.isfinite(gi) & (gi > 0)
        m = dict(np.load(d / 'mesh3d.npz'))
        lab, X = m['node_labels'], m['nodes']
        lut = np.full(int(lab.max()) + 1, -1)
        lut[lab] = np.arange(len(lab))
        pn = X[lut[m['pair_bone']]]
        idx = np.where(keep)[0]
        dist, ii = cKDTree(pn).query(P[idx], k=1)
        sa, sb = ga[idx], gi[idx]
        g = _C['g7'][idx] & ~canc[idx]
        chk = 100.0 * (sa[g].mean() / sb[g].mean() - 1.0) if g.sum() * RS.HG ** 3 >= RS.MIN_VOL else float('nan')
        lr = np.log(np.maximum(sa, FLOOR * sb) / sb)
        return {'job': job, 'keep': keep, 'lr': lr.astype(np.float32), 'rex': rex[idx].astype(np.float16),
                'dpair': dist.astype(np.float16), 'cpair': m['pair_cortex'][ii].astype(np.int8),
                'pose': np.stack([np.asarray(p, float) for p in pose]).astype(np.float32),
                'n_floor': int((sa < FLOOR * sb).sum()), 'chk': float(chk), 't': time.time() - t0}
    except Exception as e:  # noqa: BLE001
        return {'job': job, 'error': f'{type(e).__name__}: {e}', 'tb': traceback.format_exc()[-800:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workers', type=int, default=3)
    ap.add_argument('--probe', action='store_true')
    a = ap.parse_args()
    import nn_scalar as NS
    X, Y, meta, _ = NS.load()
    jobs = list(meta['job'][:6]) if a.probe else list(meta['job'])
    J_ = len(jobs)
    folds = NS.kfold(np.arange(len(meta['job'])), 5, 0)
    foldA = np.zeros(len(meta['job']), np.int8)
    for i, f in enumerate(folds):
        foldA[f] = i
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    init()
    print('region points', len(_C['P']), 'G7 cortex', int((_C['g7'] & ~_C['canc']).sum()), f'init {time.time() - t0:.0f}s',
          flush=True)
    res = {}
    with get_context('fork').Pool(a.workers) as pool:
        for k, o in enumerate(pool.imap_unordered(one, jobs, chunksize=2)):
            res[o['job']] = o
            if 'error' in o:
                print('ERR', o['job'], o['error'], o['tb'], flush=True)
            if k % 100 == 0:
                print(k, J_, f'{time.time() - t0:.0f}s', flush=True)
    bad = [j for j in jobs if 'error' in res[j]]
    if bad:
        print('errors', len(bad), bad[:5])
        return
    O = [res[j] for j in jobs]
    off = np.zeros(J_ + 1, np.int64)
    off[1:] = np.cumsum([len(o['lr']) for o in O])
    ref = {r['job']: r for r in csv.DictReader(open(NS.TAB, newline=''))}
    y_sed = np.array([float(ref[j]['sed_chg_pct']) for j in jobs])
    chk = np.array([o['chk'] for o in O])
    sel = np.arange(J_)
    np.savez(OUT / 'pack.npz', P=_C['P'].astype(np.float32), canc=_C['canc'],
             gi_log=np.log(np.where(_C['gi'] > 0, _C['gi'], np.nan)).astype(np.float32), g7=_C['g7'], code=_C['code'],
             keep=np.stack([o['keep'] for o in O]), off=off, lr=np.concatenate([o['lr'] for o in O]),
             rex=np.concatenate([o['rex'] for o in O]), dpair=np.concatenate([o['dpair'] for o in O]),
             cpair=np.concatenate([o['cpair'] for o in O]), pose=np.stack([o['pose'] for o in O]),
             G=X['DT'][sel].astype(np.float32), jobs=np.array(jobs), family=np.array(meta['family'])[sel],
             rule=np.array(meta['rule'])[sel], collar=np.asarray(meta['collar'])[sel], foldA=foldA[sel], y_sed=y_sed,
             chk_sed=chk)
    info = {'n_jobs': J_, 'region_points': int(len(_C['P'])), 'z_min': Z_MIN,
            'g7_cortex_grid_points': int((_C['g7'] & ~_C['canc']).sum()),
            'kept_points_per_job': [int(np.min(np.diff(off))), float(np.median(np.diff(off))), int(np.max(np.diff(off)))],
            'n_points_total': int(off[-1]), 'n_floored': int(sum(o['n_floor'] for o in O)),
            'max_abs_err_sed_chg_pct': float(np.nanmax(np.abs(chk - y_sed))),
            'lr_quantiles': np.quantile(np.concatenate([o['lr'] for o in O]), [0.01, 0.1, 0.5, 0.9, 0.99]).tolist(),
            'median_t_s': float(np.median([o['t'] for o in O])), 'pack_MB': (OUT / 'pack.npz').stat().st_size / 1e6,
            'wall_s': time.time() - t0, 'when': time.strftime('%Y-%m-%d %H:%M:%S')}
    json.dump(info, open(OUT / 'pack_info.json', 'w'), indent=1)
    print(json.dumps(info, indent=1))


if __name__ == '__main__':
    main()
