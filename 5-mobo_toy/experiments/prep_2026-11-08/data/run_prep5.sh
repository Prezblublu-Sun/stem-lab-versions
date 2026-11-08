#!/usr/bin/env bash
# 0 FE prep on Linux for R2 and OF-1: stem geometry with the new neck axis at the given entry offsets; then the 8-pose placement check of OF-1.
# Reads the queue and the pools; writes only under adhoc/opt5.
cd ~/mobo_toy_v2/code || exit 1
A=~/mobo_toy_v2/adhoc/opt5
G=~/mobo_toy_v2/adhoc/opt4/opt3_geom.py
echo "start $(date -u +%FT%TZ)" > $A/run.log
run() { OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 taskset -c 2-11 nice -n 19 ../run.sh "$@" 2>&1 | tail -n 3 | cut -c1-400 >> $A/run.log; }
run $G fixe $A/of1_u13.npy $A/of1_e.npy $A/geom_of1.npz 10
echo "of1 $(date -u +%FT%TZ)" >> $A/run.log
run $G fixe $A/r2_u13.npy $A/r2_e.npy $A/geom_r2.npz 10
echo "r2 $(date -u +%FT%TZ)" >> $A/run.log
run ~/mobo_toy_v2/adhoc/opt4/opt3_tol.py $A/of1_tol_list.csv $A/tol_of1.json 10
echo "done $(date -u +%FT%TZ)" >> $A/run.log
touch $A/PREP_DONE
