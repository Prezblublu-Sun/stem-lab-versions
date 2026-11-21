#!/usr/bin/env bash
# b28 0 FE prep on Linux, step 3.5: the shortlisted ring designs on the e grid, new neck axis. Writes only under adhoc/opt4.
cd ~/mobo_toy_v2/code || exit 1
A=~/mobo_toy_v2/adhoc/opt4
echo "egrid start $(date -u +%FT%TZ)" >> $A/run.log
OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 taskset -c 2-11 nice -n 19 ../run.sh $A/opt3_geom.py fixe $A/egrid_u13.npy $A/egrid_e.npy $A/geom_egrid_v11.npz 10 2>&1 | tail -n 1 | cut -c1-500 >> $A/run.log
echo "egrid done $(date -u +%FT%TZ)" >> $A/run.log
tail -n 2 $A/run.log
