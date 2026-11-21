#!/usr/bin/env bash
# b28 0 FE prep on Linux: stem geometry with the new neck axis (F, bone removed, bed quantities). Reads the queue and the pools; writes only under adhoc/opt4.
cd ~/mobo_toy_v2/code || exit 1
A=~/mobo_toy_v2/adhoc/opt4
P=~/mobo_toy_v2/results/db_pool
echo "start $(date -u +%FT%TZ)" > $A/run.log
run() { OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 taskset -c 2-11 nice -n 19 ../run.sh $A/opt3_geom.py "$@" 2>&1 | tail -n 1 | cut -c1-500 >> $A/run.log; }
run jobs $A/base_jobs_v11.txt $A/geom_base_v11.npz 10
echo "base $(date -u +%FT%TZ)" >> $A/run.log
cp ~/mobo_toy_v2/adhoc/opt3/idx_pool65k.npy $A/idx_pool65k.npy
run pool $P/pool65k_s51100.npz $A/idx_pool65k.npy $A/geom_pool65k_v11.npz 10
echo "pool $(date -u +%FT%TZ)" >> $A/run.log
run fixe $A/new_u13.npy $A/new_e.npy $A/geom_new_v11.npz 10
echo "done $(date -u +%FT%TZ)" >> $A/run.log
touch $A/PREP_DONE
