"""Read-only: Stem3D defaults, neckopt_p*.json structure, code hashes by creation date."""
import collections
import dataclasses
import json
import pathlib
import sys
import time

HOME = pathlib.Path.home() / 'mobo_toy_v2'
sys.path.insert(0, str(HOME / 'code'))
sys.path.insert(0, str(HOME / 'code' / 'v2'))
import geom3d as G  # noqa: E402
import jobs as J  # noqa: E402

print('code_hash now', J.code_hash())
print('ELLIPSE', getattr(G, 'ELLIPSE', None), 'M_LEGACY', getattr(G, 'M_LEGACY', None), 'CAP_FLAT', getattr(G, 'CAP_FLAT', None),
      'COLLAR_T', getattr(G, 'COLLAR_T', None))
if dataclasses.is_dataclass(G.Stem3D):
    for f in dataclasses.fields(G.Stem3D):
        print('Stem3D field', f.name, f.default)
else:
    import inspect
    print(inspect.signature(G.Stem3D))
print('design_of_spec' in dir(G))

for p in sorted(J.RESULTS.glob('neckopt_p*.json')):
    t0 = time.time()
    r = json.loads(p.read_text())
    print('==', p.name, type(r).__name__, list(r.keys())[:20] if isinstance(r, dict) else len(r))
    recs = r.get('records') if isinstance(r, dict) else None
    if recs:
        print('  n rec', len(recs), 'keys', list(recs[0].keys()))
        print('  rec0', json.dumps(recs[0], default=str)[:600])
        rounds = collections.Counter(str(x.get('round')) for x in recs)
        print('  rounds', sorted(rounds.items())[:40])
    meta = r.get('meta') if isinstance(r, dict) else None
    if meta:
        print('  meta keys', list(meta.keys()))

# code hash by creation date
eras = collections.defaultdict(list)
cur = J.code_hash()
match = collections.Counter()
for d in sorted(J.QROOT.iterdir()):
    sp = d / 'spec.json'
    pp = d / 'prep.json'
    if not sp.exists():
        continue
    s = json.loads(sp.read_text())
    ch = json.loads(pp.read_text()).get('code_hash') if pp.exists() else None
    eras[ch].append(s.get('created'))
    try:
        jid = J.job_id({**s, 'created': ''})
    except Exception as e:  # noqa: BLE001
        jid = 'ERR' + str(e)
    match[(jid == d.name, ch == cur)] += 1
for ch, cr in sorted(eras.items(), key=lambda kv: min(x or '' for x in kv[1])):
    cr = [c for c in cr if c]
    print('era', ch, len(cr), min(cr) if cr else None, max(cr) if cr else None)
print('id-match vs prep-hash-current', match)
