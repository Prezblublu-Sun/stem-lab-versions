#!/usr/bin/env bash
# b28 0 FE prep on Linux: geometry of the ring candidates (unit distance 0.25 to 0.75 from A), new neck axis. Writes only under adhoc/opt4.
cd ~/mobo_toy_v2/code || exit 1
A=~/mobo_toy_v2/adhoc/opt4
echo "ring start $(date -u +%FT%TZ)" >> $A/run.log
OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 taskset -c 2-11 nice -n 19 ../run.sh $A/opt3_geom.py fixe $A/ring_u13.npy $A/ring_e.npy $A/geom_ring_v11.npz 10 2>&1 | tail -n 1 | cut -c1-500 >> $A/run.log
echo "ring done $(date -u +%FT%TZ)" >> $A/run.log
touch $A/RING_DONE
