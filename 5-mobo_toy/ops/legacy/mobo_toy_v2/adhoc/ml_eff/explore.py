"""Read-only exploration of the queue: spec keys, result keys, solve.json shapes, prep.json keys."""
import collections
import json
import pathlib
import sys

HOME = pathlib.Path.home() / 'mobo_toy_v2'
sys.path.insert(0, str(HOME / 'code'))
sys.path.insert(0, str(HOME / 'code' / 'v2'))
Q = HOME / 'queue'

import os
for f in ('stability.py', 'jobs.py', 'stage_neckopt.py', 'geom3d.py', 'post_m1.py', 'femur_real.py', 'resorption.py'):
    p = HOME / 'code' / 'v2' / f
    print(f, os.path.getmtime(p))

spec_keys = collections.Counter()
res_keys = collections.Counter()
prep_keys = collections.Counter()
design_keys = collections.Counter()
solve_shapes = collections.Counter()
models = collections.Counter()
kinds = collections.Counter()
created = 0
n = 0
ex_solve = None
ex_spec = {}
for d in sorted(Q.iterdir()):
    sp = d / 'spec.json'
    if not sp.exists():
        continue
    s = json.loads(sp.read_text())
    n += 1
    spec_keys.update(s.keys())
    design_keys.update((s.get('design') or {}).keys())
    models[(s.get('model'), s.get('kind'), (d / 'DONE').exists(), bool(s.get('bond_only')))] += 1
    if 'created' in s:
        created += 1
    for k in s:
        ex_spec.setdefault(k, (d.name, s[k]))
    if (d / 'DONE').exists() and (d / 'result.json').exists() and s.get('model') == 'm1':
        r = json.loads((d / 'result.json').read_text())
        res_keys.update(r.keys())
        sv = r.get('solve') or {}
        solve_shapes[tuple(sorted(sv.keys()))] += 1
        if ex_solve is None and sv:
            ex_solve = (d.name, sv)
    if (d / 'prep.json').exists():
        p = json.loads((d / 'prep.json').read_text())
        prep_keys.update(p.keys())
print('n spec', n, 'with created', created)
print('spec keys', spec_keys.most_common())
print('design keys', design_keys.most_common())
print('model/kind/done/bond', models.most_common())
print('result keys', res_keys.most_common())
print('prep keys', prep_keys.most_common())
print('solve shapes', solve_shapes.most_common(10))
print('example solve', json.dumps(ex_solve, default=str)[:3000])
for k, v in ex_spec.items():
    print('EX', k, json.dumps(v, default=str)[:300])
