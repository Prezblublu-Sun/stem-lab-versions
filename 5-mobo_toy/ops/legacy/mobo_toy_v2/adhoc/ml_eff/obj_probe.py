"""Read-only probe: contact CSV layout, mesh3d keys, neckopt_p10.json structure."""
import json
import pathlib
import sys

import numpy as np

HOME = pathlib.Path.home() / 'mobo_toy_v2'
sys.path.insert(0, str(HOME / 'code'))
sys.path.insert(0, str(HOME / 'code' / 'v2'))
import jobs as J  # noqa: E402
import post_m1 as PM  # noqa: E402
import qoi  # noqa: E402

job = sys.argv[1] if len(sys.argv) > 1 else 'neck10_a0_2074bc29'
d = J.QROOT / job
m = np.load(d / 'mesh3d.npz')
print('mesh keys', {k: m[k].shape for k in m.files})
p = PM.pairs(d)
print('n pairs', len(p['pair_bone']), 'unique bone', len(np.unique(p['pair_bone'])), 'unique stem', len(np.unique(p['pair_stem'])))
print('n', p['n'], 'cortex pairs', int(p['pair_cortex'].sum()), 'collar', int(p['pair_collar'].sum()))
print('interf unique', np.unique(np.round(p['pair_interf'], 5))[:10])
t = qoi._csv(d / 'm_fric_csv' / 'LOAD2_CONTACT.csv')
node = t['node'].astype(int)
for f in np.unique(t['field']):
    k = t['field'] == f
    nn = node[k]
    print(f, 'rows', int(k.sum()), 'unique nodes', len(np.unique(nn)), 'in pair_bone', int(np.isin(nn, p['pair_bone']).sum()),
          'in pair_stem', int(np.isin(nn, p['pair_stem']).sum()))
# CPRESS duplicates
k = t['field'] == 'CPRESS'
nn, vv = node[k], t['value'][k]
o = np.argsort(nn, kind='stable')
nn, vv = nn[o], vv[o]
dup = nn[:-1] == nn[1:]
print('CPRESS duplicated pairs', int(dup.sum()))
a, b = vv[:-1][dup], vv[1:][dup]
print('CPRESS dup sample', np.c_[a[:8], b[:8]])
print('both nonzero', int(((np.abs(a) > 1e-9) & (np.abs(b) > 1e-9)).sum()), 'a nz', int((np.abs(a) > 1e-9).sum()), 'b nz', int((np.abs(b) > 1e-9).sum()))
# position in file of duplicates: first half vs second half
idx = np.nonzero(k)[0]
half = len(idx) // 2
n1, n2 = node[idx[:half]], node[idx[half:]]
print('first half unique', len(np.unique(n1)), 'second half unique', len(np.unique(n2)), 'same set', set(n1) == set(n2))
v1, v2 = t['value'][idx[:half]], t['value'][idx[half:]]
print('first half nz', int((np.abs(v1) > 1e-9).sum()), 'second half nz', int((np.abs(v2) > 1e-9).sum()))
print('first-half max', float(np.max(v1)), 'second-half max', float(np.max(v2)))
st = t['field'] == 'CSTATUS'
sv = t['value'][st]
print('CSTATUS values', np.unique(np.round(sv, 3), return_counts=True))
# result keys
r = json.loads((d / 'result.json').read_text())
print('solve', r.get('solve'))
p10 = json.loads((J.RESULTS / 'neckopt_p10.json').read_text())
print('p10 keys', list(p10.keys()))
recs = p10['records']
print('n records', len(recs), 'rec keys', list(recs[0].keys()))
print('rec0', {k: recs[0][k] for k in recs[0] if k not in ('design',)})
print('warm', len(p10.get('warm_start_ids') or []))
print('ref_point', p10.get('ref_point'), 'space', p10.get('space'))
p9 = json.loads((J.RESULTS / 'neckopt_p9.json').read_text())
print('p9 n records', len(p9['records']), 'p9 keys', list(p9.keys()))
print('p9 rec0', {k: p9['records'][0][k] for k in p9['records'][0] if k not in ('design',)})
