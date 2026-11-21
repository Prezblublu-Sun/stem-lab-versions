#!/bin/bash
until grep -q "^{" ~/mobo_toy_v2/deck/db_feat/tpl_area_v0.2.json 2>/dev/null && ! pgrep -f tpl_area_features.py > /dev/null; do sleep 30; done
cd ~/mobo_toy_v2/code
export OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 MKL_NUM_THREADS=4 PYTHONDONTWRITEBYTECODE=1
nice -n 19 taskset -c 4-11 ../run.sh v2/stage_al.py select al1 --export ~/ml3406/data/v0.2 --tpl-area ../deck/db_feat/tpl_area_v0.2.json --dry
echo "rc $?"
