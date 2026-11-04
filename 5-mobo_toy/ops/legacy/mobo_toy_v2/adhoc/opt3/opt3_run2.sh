#!/usr/bin/env bash
# Fast geometry for every feasible pool point with m >= 1 (pool65k, loc_al3m, loc_al4m), at the e and size already templated. Read only; writes under adhoc/opt3.
cd ~/mobo_toy_v2/code || exit 1
A=~/mobo_toy_v2/adhoc/opt3
P=~/mobo_toy_v2/results/db_pool
python3 - <<'EOF'
import numpy as np, os
P = os.path.expanduser("~/mobo_toy_v2/results/db_pool/"); A = os.path.expanduser("~/mobo_toy_v2/adhoc/opt3/")
for n, k in (("pool65k", "pool65k_s51100"), ("loc_al3m", "db_loc_al3m_s53401"), ("loc_al4m", "db_loc_al4m_s53501")):
    z = np.load(P + k + ".npz")
    names = [str(s) for s in z["var_names"]]
    idx = np.flatnonzero(z["feasible"] & (z["x13"][:, names.index("m")] >= 1.0))
    np.save(A + f"idx_{n}.npy", idx)
    print(n, len(idx))
EOF
for s in "pool65k pool65k_s51100" "loc_al3m db_loc_al3m_s53401" "loc_al4m db_loc_al4m_s53501"; do
  set -- $s
  OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 taskset -c 4-11 nice -n 19 ../run.sh $A/opt3_geom.py pool $P/$2.npz $A/idx_$1.npy $A/geom_$1.npz 8 2>&1 | tail -n 1 | cut -c1-400
done
echo finished
