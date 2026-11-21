"""ml_eff / data: one uniform per-job table for all later analyses (READ-ONLY on queue/results/code).

Selection for metrics_all.csv: every job dir in ~/mobo_toy_v2/queue with state DONE (jobs.state), spec model == 'm1',
kind in ('design', 'variant'), not bond_only.
Also writes failures.csv (every job dir with FAILED.json, any kind), groups_counts.csv, run_meta.json.

    ~/mobo_toy_v2/run.sh ../adhoc/ml_eff/build_table.py [--workers 4] [--limit N] [--only job1,job2]
Outputs: ~/mobo_toy_v2/deck/ml_eff/data/
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import csv
import io
import json
import math
import os
import pathlib
import resource
import sys
import time
import traceback
from multiprocessing import Pool

HOME = pathlib.Path.home() / 'mobo_toy_v2'
sys.path.insert(0, str(HOME / 'code'))
sys.path.insert(0, str(HOME / 'code' / 'v2'))
import numpy as np  # noqa: E402

import jobs as J  # noqa: E402

OUT = HOME / 'deck' / 'ml_eff' / 'data'
Q = J.QROOT

DESIGN = ('L', 'alpha', 'collar_w', 'h_cut', 'm', 'rho_tip', 'q', 'lam', 'g_ml', 'g_ap', 'n_a', 'n_p', 'tau_a', 'tau_p',
          'cap_h', 'collar_t')
# defaults = geom3d.Stem3D dataclass defaults (checked 2026-10-22): m = M_LEGACY -0.25, collar_w 0, collar_t 2.5, cap_h -1 (dome)
DEFAULTS = {'collar_w': 0.0, 'collar_t': 2.5, 'cap_h': -1.0, 'm': -0.25}
# code hash (prep.json) -> model version; from adhoc/deck_master.py (2026-10-05) + hashes seen in the queue
VERSION = {'45a3906c22': 'M1 v1 (09-29, d227168)', '43be8692bf': 'M1 + exports (09-29, 2d2ede6)',
           '84cdf2dab5': 'collar (10-02, 1d36c78)', '4f5d99f453': 'flat-tip option (10-02, 120dc38)',
           '6d7af243d0': 'current: unified cut plane (10-02, 6ced235)'}
TPL = ('alpha', 'e', 'A0', 'contact', 's_bind', 'volume', 'margin')
PROD = {'delta': 0.025, 'slip_tol': 2.5e-4, 'h_int': 2.0, 'mu': 0.3}
SPEC_EXTRA = ('delta', 'mu', 'E_canc', 'interference', 'cycles', 'torque', 'lagrange', 'slip_tol', 'bond_collar',
              'entry_offset', 'import_stem', 'import_e', 'h_far', 'margin', 'min_A0', 'intact_job', 'load_case', 'jitter',
              'source_job', 'deck_code', 'sweep_mode', 'rep', 'keep_odb', 'collar_w_original', 'export')

NK = {}            # job -> neckopt info (built in main before fork)
STD_INTACT = None  # name of the standard intact reference used by resorption (shielding.intact_job(True))


# ------------------------------------------------------------------------------------------------ helpers
def jread(p: pathlib.Path):
    try:
        return json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        return None


def scalar(v):
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (int, float, np.integer, np.floating)):
        v = float(v)
        return v if math.isfinite(v) else None
    if isinstance(v, str):
        return v
    return None


def short(v, n=160):
    if v is None:
        return None
    s = json.dumps(v, sort_keys=True, default=str, separators=(',', ':'))
    return s if len(s) <= n else s[:n - 3] + '...'


def tstamp(p: pathlib.Path):
    """content 'YYYY-mm-dd HH:MM:SS' if present, else file mtime; None if missing."""
    if not p.exists():
        return None
    try:
        s = p.read_text().strip()
        if len(s) >= 19:
            return time.mktime(time.strptime(s[:19], '%Y-%m-%d %H:%M:%S'))
    except Exception:  # noqa: BLE001
        pass
    return p.stat().st_mtime


def fmt_t(t):
    return None if t is None else time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t))


def design_full(spec: dict, res: dict | None):
    """uniform design vector with defaults; returns (dict, sources dict)."""
    d = dict(spec.get('design') or {})
    out, src = {}, {}
    for k in DESIGN:
        if k == 'h_cut':
            if spec.get('h_cut') is not None:
                out[k], src[k] = float(spec['h_cut']), 'spec'
            elif res and res.get('h_cut_mm') is not None:
                out[k], src[k] = float(res['h_cut_mm']), 'result_h_cut_mm'
            else:
                out[k], src[k] = 25.0, 'default25'
            continue
        if k == 'm' and k not in d:
            if spec.get('margin') is not None:
                out[k], src[k] = float(spec['margin']), 'spec_margin'
            else:
                out[k], src[k] = DEFAULTS['m'], 'default'
            continue
        if k in d:
            out[k], src[k] = float(d[k]), 'design'
        elif k in DEFAULTS:
            out[k], src[k] = DEFAULTS[k], 'default'
        else:
            out[k], src[k] = None, 'missing'
    return out, src


def classify(spec: dict, prep: dict) -> dict:
    """override flags. model variants change FE-model assumptions; design variants change templating/geometry rules."""
    cfg = spec.get('cfg') or {}
    model_k, design_k = [], []

    def val(k):
        if spec.get(k) is not None:
            return spec.get(k)
        return prep.get(k)
    dl = val('delta')
    if dl is not None and abs(float(dl) - PROD['delta']) > 1e-12:
        model_k.append(f'delta={dl:g}')
    st = val('slip_tol')
    if st is not None and abs(float(st) - PROD['slip_tol']) > 1e-12:
        model_k.append(f'slip_tol={st:g}')
    mu = val('mu')
    if mu is not None and abs(float(mu) - PROD['mu']) > 1e-12:
        model_k.append(f'mu={mu:g}')
    for k in ('E_canc', 'interference', 'cycles', 'h_far'):
        if spec.get(k) is not None:
            model_k.append(f'{k}={spec[k]}')
    if spec.get('torque') is not None and spec.get('torque') is not True:
        model_k.append(f"torque={spec['torque']}")
    if spec.get('lagrange'):
        model_k.append('lagrange')
    if spec.get('import_stem'):
        model_k.append(f"import_stem={spec['import_stem']}")
    for k in cfg:
        if k != 'load':
            model_k.append(f'cfg.{k}')
    if spec.get('margin') is not None:
        design_k.append(f"margin={spec['margin']:g}")
    if spec.get('entry_offset') is not None:
        design_k.append(f"entry_offset={spec['entry_offset']:g}")
    load = 'load' in cfg or spec.get('load_case') is not None
    hint = spec.get('h_int')
    mesh = hint is not None and abs(float(hint) - PROD['h_int']) > 1e-9
    sed = spec.get('bond_collar') not in (None, 'tied')
    parts = []
    if load:
        parts.append('load')
    if model_k:
        parts.append('model')
    if mesh:
        parts.append('mesh')
    if design_k:
        parts.append('design')
    if sed:
        parts.append('sed')
    return {'cfg_override': bool(cfg), 'cfg_desc': short(cfg) if cfg else None,
            'load_override': load, 'model_override_keys': ';'.join(model_k) or None,
            'design_override_keys': ';'.join(design_k) or None, 'mesh_override': mesh, 'sed_override': sed,
            'variant_class': '+'.join(parts) or 'none'}


# ------------------------------------------------------------------------------------------------ per job
def common(d: pathlib.Path, spec: dict, prep: dict, res: dict | None) -> dict:
    job = d.name
    h = prep.get('code_hash')
    try:
        cur = J.job_id({**spec, 'created': ''}) == job
    except Exception:  # noqa: BLE001
        cur = None
    dsg, src = design_full(spec, res)
    collar_w = dsg['collar_w'] or 0.0
    stage = str(spec.get('stage', ''))
    nk = NK.get(job, {})
    row = {'job': job, 'family': stage, 'family_root': stage.split('_')[0], 'tag': spec.get('tag'), 'kind': spec.get('kind'),
           'model': spec.get('model'), 'created': spec.get('created'),
           'current_code': cur, 'prep_code_hash': h, 'prep_hash_is_current': (h == CUR_HASH) if h else None,
           'model_version': VERSION.get(h, h), 'cut_plane': None if not h else ('unified' if h == '6d7af243d0' else 'old (4.1 deg off)'),
           **{f'nk_{k}': nk.get(k) for k in ('phase', 'round', 'pool_idx', 'metric', 'y1', 'y2', 'c', 'ok', 'in_records', 'warm_in')},
           'collar': bool(collar_w > 1e-6), 'collar_rule': spec.get('collar_rule') or 'None',
           **classify(spec, prep), 'h_int': spec.get('h_int'), 'bond_only': bool(spec.get('bond_only')),
           'tip': 'flat' if (dsg['cap_h'] is not None and dsg['cap_h'] >= 0) else 'dome'}
    for k in SPEC_EXTRA:
        v = spec.get(k)
        row[f'spec_{k}'] = scalar(v) if not isinstance(v, (dict, list)) else short(v)
    of = spec.get('ofat') or {}
    row.update({'ofat_factor': of.get('factor'), 'ofat_level': scalar(of.get('level')), 'ofat_baseline': of.get('baseline'),
                'ofat_rule': of.get('rule')})
    row.update(dsg)
    row['design_default_keys'] = ';'.join(k for k in DESIGN if src[k] not in ('design', 'spec')) or None
    row['m_src'], row['h_cut_src'] = src['m'], src['h_cut']
    return row


def prep_cols(prep: dict) -> dict:
    out = {}
    skip = {'name', 'templating', 'bone_loss', 'code_hash', 'cfg_override', 'slave'}
    for k, v in prep.items():
        if k in skip:
            continue
        if isinstance(v, dict):
            for k2, v2 in v.items():
                s = scalar(v2)
                if s is not None and not isinstance(v2, (dict, list)):
                    out[f'prep_{k}_{k2}'] = s
        elif isinstance(v, list):
            if all(isinstance(x, (str, int, float)) for x in v) and len(v) <= 12:
                out[f'prep_{k}'] = ';'.join(str(x) for x in v)
            else:
                out[f'prep_{k}_len'] = len(v)
        else:
            s = scalar(v)
            if s is not None:
                out[f'prep_{k}'] = s
    return out


def solve_cols(d: pathlib.Path, res: dict) -> dict:
    sv = jread(d / 'solve.json') or res.get('solve') or {}
    out = {}
    for m, pre in (('m_fric', 'fric'), ('m_bond', 'bond')):
        s = sv.get(m)
        if not s:
            continue
        out[f'{pre}_status'] = s.get('status')
        out[f'{pre}_wall_s'] = scalar(s.get('wall_s'))
        out[f'{pre}_tries'] = scalar(s.get('tries'))
        steps = ((s.get('odb_meta') or {}).get('steps')) or []
        if steps:
            out[f'{pre}_frames'] = '/'.join(f"{st.get('name')}:{st.get('n_frames')}" for st in steps)
            out[f'{pre}_frames_total'] = int(sum(int(st.get('n_frames') or 0) for st in steps))
    return out


def time_cols(d: pathlib.Path, spec: dict) -> dict:
    tc = None
    try:
        tc = time.mktime(time.strptime(spec['created'][:19], '%Y-%m-%d %H:%M:%S'))
    except Exception:  # noqa: BLE001
        pass
    tr = tstamp(d / 'CLAIMED') or tstamp(d / 'READY')
    if tr is None and (d / 'prep.json').exists():
        tr = (d / 'prep.json').stat().st_mtime
    ts = (d / 'SOLVED').stat().st_mtime if (d / 'SOLVED').exists() else None
    td = tstamp(d / 'DONE')
    return {'t_ready': fmt_t(tr), 't_solved': fmt_t(ts), 't_done': fmt_t(td),
            'prep_wall_upper_s': None if (tc is None or tr is None) else tr - tc,
            'created_to_done_s': None if (tc is None or td is None) else td - tc}


def row_of(job: str):
    t0 = time.time()
    d = Q / job
    spec = jread(d / 'spec.json') or {}
    res = jread(d / 'result.json') or {}
    prep = jread(d / 'prep.json') or {}
    row = common(d, spec, prep, res)
    t = res.get('templating') or prep.get('templating') or {}
    row.update({f'tpl_{k}': scalar(t.get(k)) for k in TPL})
    bl = res.get('bone_loss') or prep.get('bone_loss') or {}
    row.update({'bone_total_mm3': scalar(bl.get('total_mm3')), 'bone_resected_mm3': scalar(bl.get('resected_mm3')),
                'bone_reamed_mm3': scalar(bl.get('reamed_mm3')), 'bone_h_cut_mm': scalar(bl.get('h_cut_mm'))})
    for k, v in res.items():
        if k in ('spec', 'solve', 'templating', 'bone_loss', 'job_id'):
            continue
        if isinstance(v, (dict, list)):
            continue
        s = scalar(v)
        row[f'r_{k}' if k in row else k] = s
    nt = res.get('n_tet') if res.get('n_tet') is not None else prep.get('n_tet')
    if isinstance(nt, dict):
        row['n_tet'] = int(sum(int(v) for v in nt.values() if isinstance(v, (int, float))))
    elif nt is not None:
        row['n_tet'] = scalar(nt)
    row['intact_is_std'] = (res.get('intact_job') == STD_INTACT) if res.get('intact_job') else None
    row.update(prep_cols(prep))
    row.update(solve_cols(d, res))
    row.update(time_cols(d, spec))
    # calcar via stage_neckopt._calcar (standard intact reference, same as the optimiser)
    t1 = time.time()
    import stage_neckopt as NO
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ssi, sedc = NO._calcar(job)
    row['ssi_pct'], row['sed_chg_pct'] = ssi, sedc
    row['calcar_err'] = buf.getvalue().strip()[-200:] or None
    # own intact reference (load / material variants): same G7 fixed cortex zone vs the job's own intact_job
    if res.get('intact_job') and res.get('intact_job') != STD_INTACT:
        try:
            import resorption as RS
            rows, _ = RS.design_rows(job, res.get('intact_job'))
            g7 = next((r for r in rows if r['scheme'] == 'fixed' and r['zone'] == 'G7' and r['tissue'] == 'cortex'), {})
            row['ssi_pct_ownref'] = scalar(g7.get('ssi_pct'))
            row['sed_chg_pct_ownref'] = scalar(g7.get('sed_chg_pct'))
        except Exception as e:  # noqa: BLE001
            row['calcar_ownref_err'] = f'{type(e).__name__}: {e}'[:200]
    t2 = time.time()
    try:
        import stability as ST
        st = ST.stability(d)
        row.update({k: scalar(v) for k, v in st.items()})
        row['stab_err'] = None
    except Exception as e:  # noqa: BLE001
        row['stab_err'] = f'{type(e).__name__}: {e}'[:200]
    t3 = time.time()
    row['_t_calcar_s'], row['_t_stab_s'], row['_t_total_s'] = t2 - t1, t3 - t2, t3 - t0
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    return row, rss


def safe_row(job: str):
    try:
        return row_of(job)
    except Exception as e:  # noqa: BLE001
        return {'job': job, 'row_err': f'{type(e).__name__}: {e} | {traceback.format_exc()[-400:]}'}, 0.0


# ------------------------------------------------------------------------------------------------ failures
def reason_class(f: dict) -> str:
    r = (f.get('reason') or '').lower()
    st = f.get('stage')
    if 'overlapping facets' in r or 'invalid boundary mesh' in r:
        return 'mesh: overlapping facets'
    if 'shoulder' in r and 'prosthetic neck' in r:
        return 'templating: shoulder < prosthetic neck'
    if r.startswith('templating') or 'templating:' in r:
        return 'templating: no fit'
    if 'collar' in r and st == 'prep':
        return 'prep: collar'
    if st == 'prep' and ('gmsh' in r or 'mesh' in r):
        return 'mesh: other'
    if st == 'prep':
        return 'prep: other'
    if st == 'solve':
        return f"solve {f.get('level')}"
    if st == 'post':
        return 'post'
    return 'other'


def failures() -> list[dict]:
    rows = []
    for d in sorted(Q.iterdir()):
        if not (d / 'FAILED.json').exists():
            continue
        spec = jread(d / 'spec.json') or {}
        prep = jread(d / 'prep.json') or {}
        f = jread(d / 'FAILED.json') or {}
        row = common(d, spec, prep, None)
        row['state'] = J.state(d)
        row.update({'fail_level': f.get('level'), 'fail_stage': f.get('stage'), 'fail_time': f.get('time'),
                    'fail_reason': (f.get('reason') or '').replace('\n', ' | ')[:200], 'fail_class': reason_class(f),
                    'has_prep': bool(prep), 'has_design': bool(spec.get('design'))})
        t = prep.get('templating') or {}
        row.update({f'tpl_{k}': scalar(t.get(k)) for k in TPL})
        for k in ('n_tet', 'n_nodes', 'mesh_attempt', 'n_pairs', 'interface_area_mm2', 'stem_volume_mm3', 'A0'):
            row[f'prep_{k}'] = scalar(prep.get(k))
        bl = prep.get('bone_loss') or {}
        row['bone_total_mm3'] = scalar(bl.get('total_mm3'))
        rows.append(row)
    return rows


# ------------------------------------------------------------------------------------------------ io
FRONT = ('job', 'family', 'family_root', 'tag', 'kind', 'model', 'created', 'current_code', 'prep_code_hash', 'prep_hash_is_current',
         'model_version', 'cut_plane', 'nk_phase', 'nk_round', 'nk_pool_idx', 'nk_metric', 'nk_y1', 'nk_y2', 'nk_c', 'nk_ok',
         'nk_in_records', 'nk_warm_in', 'collar', 'collar_rule', 'variant_class', 'cfg_override', 'cfg_desc', 'load_override',
         'model_override_keys', 'design_override_keys', 'mesh_override', 'sed_override', 'h_int', 'tip', *DESIGN,
         'design_default_keys', 'm_src', 'h_cut_src', *[f'tpl_{k}' for k in TPL],
         'bone_total_mm3', 'bone_resected_mm3', 'bone_reamed_mm3', 'bone_h_cut_mm',
         'f1_p95_um', 'f1_all_p95_um', 'f1_first_p95_um', 'open_frac_load2', 'interface_area', 'cortex_area_frac', 'vm_p99', 'n_tet',
         'collar_force_share_load2', 'ssi_pct', 'sed_chg_pct', 'ssi_pct_ownref', 'sed_chg_pct_ownref',
         'rot_first_deg', 'rot_tilt_first_deg', 'rot_axial_first_deg', 'rot_rev_deg', 'rot_perm_deg',
         'subsid_first_um', 'subsid_perm_um', 'lateral_first_um', 'slip_axial_p95_um', 'slip_circ_p95_um',
         'contact_area_load_mm2', 'contact_frac_load', 'contact_area_load2_mm2', 'contact_frac_load2', 'body_interface_mm2',
         'fric_wall_s', 'bond_wall_s', 'fric_tries', 'bond_tries', 'fric_frames_total', 'prep_wall_upper_s', 'created_to_done_s')


def write_csv(path: pathlib.Path, rows: list[dict], front=FRONT):
    cols = [c for c in front if any(c in r for r in rows)]
    rest = sorted({k for r in rows for k in r} - set(cols))
    tail = [c for c in rest if c.startswith('_') or c.endswith('_err')]
    cols += [c for c in rest if c not in tail] + tail
    with open(path, 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction='ignore')
        w.writeheader()
        for r in rows:
            w.writerow({k: ('' if v is None else v) for k, v in r.items()})
    return cols


def build_nk() -> dict:
    nk = collections.defaultdict(dict)
    for p in sorted(J.RESULTS.glob('neckopt_p*.json')):
        if p.stem.endswith('_ref'):
            continue
        try:
            r = json.loads(p.read_text())
        except Exception:  # noqa: BLE001
            continue
        ph = int(r.get('phase', p.stem.split('_p')[1]))
        for rec in r.get('records') or []:
            j = rec.get('job_id')
            if not j:
                continue
            e = nk[j]
            e.setdefault('_in', []).append(ph)
            own = j.startswith(f'neck{ph}_')
            if own or 'phase' not in e:
                y = rec.get('y') or [None, None]
                c = rec.get('c') or [None]
                e.update(phase=ph, round=rec.get('round'), pool_idx=rec.get('pool_idx'), metric=rec.get('metric', 'v1'),
                         y1=scalar(y[0]) if len(y) > 0 else None, y2=scalar(y[1]) if len(y) > 1 else None,
                         c=scalar(c[0]) if c else None, ok=rec.get('ok'))
        for j in r.get('warm_start_ids') or []:
            nk[j].setdefault('_warm', []).append(ph)
    for j, e in nk.items():
        e['in_records'] = ';'.join(str(x) for x in sorted(set(e.pop('_in', [])))) or None
        e['warm_in'] = ';'.join(str(x) for x in sorted(set(e.pop('_warm', [])))) or None
    return dict(nk)


def main():
    global NK, STD_INTACT, CUR_HASH
    ap = argparse.ArgumentParser()
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--only', default='')
    ap.add_argument('--out', default=str(OUT))
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    NK = build_nk()
    try:
        import shielding as SH
        STD_INTACT = SH.intact_job(True).name
    except Exception as e:  # noqa: BLE001
        print('std intact:', e)
    sel = []
    for d in sorted(Q.iterdir()):
        sp = d / 'spec.json'
        if not sp.exists():
            continue
        s = jread(sp) or {}
        if s.get('model') == 'm1' and s.get('kind') in ('design', 'variant') and not s.get('bond_only') and J.state(d) == 'DONE':
            sel.append((s.get('created') or '', d.name))
    sel = [j for _, j in sorted(sel)]
    if a.only:
        sel = [j for j in a.only.split(',') if j]
    if a.limit:
        step = max(1, len(sel) // a.limit)
        sel = sel[::step][:a.limit]
    print(f'[data] code_hash {CUR_HASH}  std intact {STD_INTACT}  selected {len(sel)}  neckopt-mapped {len(NK)}', flush=True)
    rows, rss_max = [], 0.0
    with Pool(a.workers, maxtasksperchild=150) as pool:
        for i, (r, rss) in enumerate(pool.imap_unordered(safe_row, sel, chunksize=2), 1):
            rows.append(r)
            rss_max = max(rss_max, rss)
            if i % 50 == 0 or i == len(sel):
                el = time.time() - t0
                print(f'[data] {i}/{len(sel)}  {el/60:.1f} min  worker maxrss {rss_max:.0f} MB', flush=True)
    order = {j: i for i, j in enumerate(sel)}
    rows.sort(key=lambda r: order.get(r['job'], 1e9))
    name = 'metrics_all.csv' if not (a.limit or a.only) else 'metrics_test.csv'
    cols = write_csv(out / name, rows)
    # failures
    fr = failures()
    fcols = write_csv(out / 'failures.csv', fr, front=('job', 'family', 'family_root', 'tag', 'kind', 'model', 'created', 'state',
                                                        'fail_level', 'fail_stage', 'fail_class', 'fail_time', 'fail_reason',
                                                        'current_code', 'prep_code_hash', 'model_version', 'nk_phase', 'nk_round',
                                                        'collar', 'collar_rule', 'variant_class', 'cfg_override', 'h_int', 'bond_only',
                                                        *DESIGN, 'design_default_keys', 'has_prep', 'has_design',
                                                        *[f'tpl_{k}' for k in TPL]))
    # group counts
    g = collections.Counter((r.get('family'), r.get('current_code'), r.get('collar'), r.get('collar_rule'), r.get('variant_class'))
                            for r in rows if 'row_err' not in r)
    with open(out / ('groups_counts.csv' if name == 'metrics_all.csv' else 'groups_test.csv'), 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['family', 'current_code', 'collar', 'collar_rule', 'variant_class', 'n'])
        for k, n in sorted(g.items(), key=lambda kv: tuple(str(x) for x in kv[0])):
            w.writerow([*k, n])
    def cnt(key):
        return sum(1 for r in rows if r.get(key))
    meta = {'when': time.strftime('%Y-%m-%d %H:%M:%S'), 'code_hash_now': CUR_HASH, 'std_intact': STD_INTACT,
            'n_rows': len(rows), 'n_cols': len(cols), 'n_failures_rows': len(fr), 'row_err': cnt('row_err'),
            'stab_err': cnt('stab_err'), 'calcar_err': cnt('calcar_err'), 'calcar_ownref_err': cnt('calcar_ownref_err'),
            'sed_missing': sum(1 for r in rows if r.get('sed_chg_pct') is None),
            'rot_missing': sum(1 for r in rows if r.get('rot_first_deg') is None),
            'elapsed_min': (time.time() - t0) / 60, 'worker_maxrss_mb': rss_max,
            't_calcar_med_s': float(np.median([r['_t_calcar_s'] for r in rows if '_t_calcar_s' in r] or [math.nan])),
            't_stab_med_s': float(np.median([r['_t_stab_s'] for r in rows if '_t_stab_s' in r] or [math.nan])),
            'fail_class': collections.Counter(r['fail_class'] for r in fr).most_common(),
            'fail_state': collections.Counter(r['state'] for r in fr).most_common()}
    (out / ('run_meta.json' if name == 'metrics_all.csv' else 'run_meta_test.json')).write_text(json.dumps(meta, indent=1, default=str))
    print(json.dumps(meta, default=str), flush=True)
    errs = [r for r in rows if r.get('row_err') or r.get('stab_err') or r.get('calcar_err') or r.get('calcar_ownref_err')]
    for r in errs[:15]:
        print('ERR', r['job'], (r.get('row_err') or '')[:200], (r.get('stab_err') or '')[:150], (r.get('calcar_err') or '')[:150],
              (r.get('calcar_ownref_err') or '')[:150])


CUR_HASH = J.code_hash()

if __name__ == '__main__':
    main()
