#!/usr/bin/env bash
# Fast F on the 581 rows that exist. Read only on the queue; writes under adhoc/opt3.
cd ~/mobo_toy_v2/code || exit 1
A=~/mobo_toy_v2/adhoc/opt3
OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 timeout 560 taskset -c 4-11 nice -n 19 ../run.sh $A/opt3_geom.py jobs $A/base_jobs.txt $A/geom_base.npz 8 2>&1 | tail -n 8 | cut -c1-400
ls -la $A/geom_base.npz
python3 - <<'EOF'
import numpy as np, os
z = np.load(os.path.expanduser("~/mobo_toy_v2/results/db_pool/pool65k_s51100.npz"))
print([k for k in z.files][:30])
u = z["u13"]; f = z["feasible"]; print(u.shape, f.sum())
x = z["x13"]; names = [str(s) for s in z["var_names"]]; print(names)
im = names.index("m"); print("m range", x[:, im].min(), x[:, im].max(), "feasible m>=1", int((f & (x[:, im] >= 1.0)).sum()))
for n, k in (("cr4096", "db_cr4096_s52101"), ("loc_al3m", "db_loc_al3m_s53401"), ("loc_al4m", "db_loc_al4m_s53501")):
    z2 = np.load(os.path.expanduser(f"~/mobo_toy_v2/results/db_pool/{k}.npz"))
    print(n, z2["u13"].shape, int(z2["feasible"].sum()), "m>=1", int((z2["feasible"] & (z2["x13"][:, im] >= 1.0)).sum()), "t_s median", round(float(np.nanmedian(z2["t_s"])), 2))
EOF
