#!/bin/bash
# FEA settings check round 2 (2026-10-28): base decks for the foam-yield ranking test, production code path, outside the queue
cd ~/mobo_toy_v2/code
export OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1
while read name job; do
  echo "== $(date -u +%FT%TZ) $name $job"
  nice -n 19 taskset -c 8-11 ../run.sh ../deck/fea_check_r2/gen_decks.py ../deck/fea_check_r2 $job $name 2>&1 | tail -2
done <<LIST
B_base sb13_a78_b0f465da
Bp_base sb13_a53_23a3f031
D_base sb14_a26_96c5ab9b
a62_base sb13_a62_1e4338ee
q010_base sb14_a55_05d890db
q020_base sb14_a10_6d867062
q050_base db_sf_p117_c42901c3
q100_base db_sf_p54_904a24f3
q200_base db_sf_p138_3fb83422
q500_base db_sf_p116_6a321d94
LIST
echo "== $(date -u +%FT%TZ) done"
