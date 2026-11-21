#!/usr/bin/env bash
# After the pool geometry: template the 5200 local points at their own e and compute the same geometry. Read only; writes under adhoc/opt3.
cd ~/mobo_toy_v2/code || exit 1
A=~/mobo_toy_v2/adhoc/opt3
while pgrep -f opt3_run2.sh > /dev/null; do sleep 20; done
OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 taskset -c 4-11 nice -n 19 ../run.sh $A/opt3_geom.py fixe $A/loc_opt3_u13.npy $A/loc_opt3_e.npy $A/geom_loc_opt3.npz 8 2>&1 | tail -n 1 | cut -c1-500
echo finished3
