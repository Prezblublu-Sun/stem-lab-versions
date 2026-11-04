#!/bin/bash
# Sequential Linux runs for the failure analysis (CPUs 4-11, nice 19, 3 workers + parent at any time).
# Writes only under ~/mobo_toy_v2/deck/ml_eff/failures/.
cd ~/mobo_toy_v2/code || exit 1
LOG=~/mobo_toy_v2/deck/ml_eff/failures/logs
RUN="env OMP_NUM_THREADS=2 taskset -c 4-11 nice -n 19"
NIS=neck10_a27_5ab887f9,neck10_a29_4e181bac,neck10_a41_366298fc,neck10_a47_4f618426,neck10_a53_775a3c90,neck10_a61_42877f34,neck9_a51_e73c2f5a
GRZ=neck10_a41_366298fc,hsweep_newsplit_long_h25_d2ddbafe,hsweep_newsplit_long_h27_ff798b79,neck2_r8_d3a04150,neck5_r7_344d6124
CTL=neck10_a34_fbf095a3,neck9_a69_ce80cc24,neck10_a7_60866408,neck9_a95_3753fea9,neck9_a18_07d6c4c2,neck9_a20_caefa8b2,ofat_b1_alpha_25.0_30f01904,neck5_r7_5df27b13,ofatw_b1_alpha_25.0_8acf25ed,collar_rule_LA_19ef9db6,neck1_r5_d2e3c83e,neck5_init_4f12c037,remesh_noise_FI_L+0.002_7c48f3b0,collar_rule_J1_6024f7e9,neck10_a18_83a0f847,neck10_a54_86992dd0
$RUN timeout 2400 ~/mobo_toy_v2/run.sh ../adhoc/ml_eff/fail_meshfix.py --jobs $NIS --variants neckr --workers 3 --tag neckr > $LOG/meshfix_neckr.log 2>&1
$RUN timeout 2400 ~/mobo_toy_v2/run.sh ../adhoc/ml_eff/fail_meshfix.py --jobs $GRZ --variants fuzzy10 --workers 3 --tag fuzzy10 > $LOG/meshfix_fuzzy10.log 2>&1
$RUN timeout 3600 ~/mobo_toy_v2/run.sh ../adhoc/ml_eff/fail_meshfix.py --jobs $CTL --variants base,fuzzy05 --workers 3 --tag controls > $LOG/meshfix_controls.log 2>&1
$RUN timeout 3600 ~/mobo_toy_v2/run.sh ../adhoc/ml_eff/fail_pool.py --phase 10 --workers 3 > $LOG/pool_p10.log 2>&1
$RUN timeout 5400 ~/mobo_toy_v2/run.sh ../adhoc/ml_eff/fail_occscan.py --set $(cat ~/mobo_toy_v2/adhoc/ml_eff/occ_jobs.txt) --tag collarless_sel --workers 3 > $LOG/occscan_sel.log 2>&1
echo CHAIN_DONE > $LOG/chain2.done
