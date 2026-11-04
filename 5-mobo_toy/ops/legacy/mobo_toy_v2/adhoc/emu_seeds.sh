#!/bin/bash
# E2 模拟器上的多种子策略比较（0 次 FE）：种子 1–9，3 个并行
cd ~/mobo_toy_v2/code
seq 1 9 | xargs -P 3 -I{} sh -c "~/mobo_toy_v2/run.sh v2/emulator.py bench --emu E2 --seed {} --workers 2 > ~/mobo_toy_v2/logs/emu_E2_s{}.log 2>&1"
echo all done
