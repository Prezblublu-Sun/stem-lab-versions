#!/bin/bash
# L25 建模崩溃定位：不同柄长各自一个进程，12 GB 虚拟内存上限
cd ~/mobo_toy_v2/code
for L in 24 26 28 25; do
  ( ulimit -v 12000000; ~/mobo_toy_v2/run.sh ../adhoc/l25_build_probe.py $L 1.0 )
  echo "exit $? for L=$L"
done
