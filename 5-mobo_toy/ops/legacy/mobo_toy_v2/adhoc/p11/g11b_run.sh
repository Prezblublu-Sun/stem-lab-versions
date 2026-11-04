#!/bin/sh
# 来源阶段的 2 目标臂（转动 ↓ × 完全接触面积 ↑）= 并行两臂里的 2 目标臂。阶段号由环境变量给：SRC（默认 11）/ DST（默认 12，冻结热启动的目标阶段，
# 只用于闸门的键名与说明）。默认值 = 阶段 11 臂（计算计划_50h_2026-10-24.md §7 修订 1；审查 wf_6f8fbde1 第 1 条），行为与从前相同；
# 阶段 13 臂（δ 0.10、微动不作约束，用户 2026-10-24 12:20）用 g13b_run.sh（= SRC=13 DST=14 NEW=75 EXPECT_DELTA=0.1 再调本脚本）。
# 与目标阶段臂（g12_run.sh / g14_run.sh）同时跑，各 inflight 2、各 NEW 个自有提交。Linux 上从 ~/mobo_toy_v2/code 运行；
# CPU 4–11、nice 19、OMP / MKL 2。启动 / 停止 / 续跑见同目录 README_p11_ops.md：
#   cd ~/mobo_toy_v2 && nohup sh adhoc/p11/g11b_run.sh > logs/g11b.log 2>&1 < /dev/null & echo $! > logs/g11b.pid
# 步骤
#   1. 前置检查：logs/<NAME>.pid 指向另一个活着的实例 → 退出 4；任何阶段 SRC 的 bo / async 驱动还活着（例如段 A 的 init 驱动）→ 退出 4。
#   2. 闸门：python arms_gate.py init --src SRC --dst DST（同目录，只读；可手动跑看数字）：init（round 0）记录不 ok 的比例 > MAX_FAIL（0.15）
#      或 0 个可行（状态文件的 mm_limit 为 null 时这一条不适用，只报数字）或 EXPECT_DELTA 设了而 init 的 spec 的 delta 不符
#      或 EXPECT_MM 设了而状态文件的微动上限（"mm_limit" 键，没有 = 150）不符（--expect-mm-limit）
#      → 写 logs/<FLAG>（内容 = 数字）、退出 3；neckopt_p<SRC>.json 不存在 / 读不了 → 退出 5。
#      EXPECT_MM=none 时另查同步的代码：PHASES[SRC] 那一行要有 "mm_limit": None，没有 → 退出 2（审查 wxa60xosx 中 1：旧代码不定义 mm_limit）。
#      看过 init 批后可用 MAX_FAIL=1（不 ok 比例）/ ALLOW_INFEASIBLE=1（0 个可行）越过。
#   3. 预算：BUDGET<SRC> = init 记录数 + 收编数（不是阶段 SRC 驱动提交的 sb<SRC>_*，即冒烟作业）+ NEW（默认 95），由闸门脚本算出。
#      bo_async 的预算 = len(records) + len(pending)，init 记录与收编的冒烟作业都在阶段 SRC 的记录里，所以要加上（README §6 的账）。
#      续跑时同一个公式给出同一个数（init 与冒烟数不变）；BUDGET=… 可直接指定（与 BUDGET<SRC> 不同时日志里警告）。
#   4. async --phase SRC --budget BUDGET<SRC> --inflight 2 --pool 16384 --seed 0 --refresh 32 --refresh-rad 0.08 --warm none --workers 4
#      --warm none：只用自己状态文件里的记录 + 收编 sb<SRC>_*（不调 dataset），目标阶段的作业永远进不了来源阶段。
#   bo（段 A）与 async 共用 neckopt_p<SRC>.json 与候选池：--pool / --seed 必须与段 A 相同（16384 / 0）。
# 环境变量（默认即计划值）：SRC DST NEW BUDGET INFLIGHT POOL SEED WORKERS REFRESH REFRESH_RAD MAX_FAIL ALLOW_INFEASIBLE（=1：0 个可行不挡）
#   EXPECT_DELTA（设了 → 闸门 --expect-delta）EXPECT_MM（none 或 µm；设了 → 闸门 --expect-mm-limit，none 时另查 PHASES[SRC] 的
#   "mm_limit": None）EXPECT_GIT（设了就要求 code/VERSION 的 git= 以它开头）PY（闸门用的 python，默认
#   ~/mobo_toy_v2/.venv/bin/python，没有则 python3）GATE（闸门脚本，默认同目录 arms_gate.py）MOBO_BASE（测试用）。
#   名字随 SRC：NAME g11b / g13b（日志前缀、logs/<NAME>.pid、logs/<NAME>.child.pid）；标记文件 logs/arms_gate.FAIL（SRC 11）/ logs/arms_gate_p<SRC>.FAIL。
# 退出码：0 async 正常结束；2 前置检查失败；3 闸门不过；4 已有实例 / 阶段 SRC 驱动在跑；5 状态文件缺失或读不了；143 收到信号；其他 = async 的退出码。
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
BASE="${MOBO_BASE:-$HOME/mobo_toy_v2}"
CODE="$BASE/code"
RUN="$BASE/run.sh"
LOGS="$BASE/logs"
PY="${PY:-$BASE/.venv/bin/python}"
GATE="${GATE:-$HERE/arms_gate.py}"
SRC="${SRC:-11}"
DST="${DST:-12}"
NEW="${NEW:-95}"
INFLIGHT="${INFLIGHT:-2}"
POOL="${POOL:-16384}"
SEED="${SEED:-0}"
WORKERS="${WORKERS:-4}"
REFRESH="${REFRESH:-32}"
REFRESH_RAD="${REFRESH_RAD:-0.08}"
MAX_FAIL="${MAX_FAIL:-0.15}"
EXPECT_DELTA="${EXPECT_DELTA:-}"
EXPECT_MM="${EXPECT_MM:-}"
AI=""                                       # ALLOW_INFEASIBLE=1 -> arms_gate.py --allow-infeasible (zero feasible init designs do not block)
[ "${ALLOW_INFEASIBLE:-0}" = 1 ] && AI="--allow-infeasible"
case "$SRC" in ''|*[!0-9]*) echo "SRC=$SRC is not a phase number"; exit 2;; esac
case "$DST" in ''|*[!0-9]*) echo "DST=$DST is not a phase number"; exit 2;; esac
[ "$SRC" != "$DST" ] || { echo "SRC and DST are the same phase ($SRC)"; exit 2; }
if [ "$SRC" = 11 ]; then NAME=g11b; FLAGN=arms_gate.FAIL; else NAME="g${SRC}b"; FLAGN="arms_gate_p${SRC}.FAIL"; fi
PIDF="$LOGS/$NAME.pid"
CHILDF="$LOGS/$NAME.child.pid"
FLAG="$LOGS/$FLAGN"
DRIVER_PAT="stage_neckopt\\.py (bo|async) --phase $SRC( |\$)"
CHILD=""
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2

log() { printf '%s\n' "[$NAME $(date '+%Y-%m-%d %H:%M:%S')] $*"; }   # printf, not echo: dash's echo eats backslashes

finish() {                                  # finish <退出码> <说明>：写结束行、删自己的 pid 文件、退出
    rc=$1; shift
    log "END $(basename "$0") exit $rc: $*"
    [ "$(cat "$PIDF" 2>/dev/null)" = "$$" ] && rm -f "$PIDF"
    rm -f "$CHILDF"
    exit "$rc"
}

descendants() {                            # 子进程树（run.sh 若不 exec python，python 与池进程在下面一两层）
    for c in $(pgrep -P "$1" 2>/dev/null); do
        echo "$c"
        descendants "$c"
    done
}

on_signal() {
    log "signal received; stopping child ${CHILD:-none}"
    if [ -n "$CHILD" ]; then
        tree="$CHILD $(descendants "$CHILD" | tr '\n' ' ')"   # 先收齐整棵树再一起发 TERM：先杀父进程会让孙进程成孤儿
        log "  TERM -> $tree"
        kill -TERM $tree 2>/dev/null
    fi
    finish 143 "stopped by signal (submitted jobs keep solving; a restart resumes from neckopt_p$SRC.json)"
}
trap on_signal TERM INT

run_step() {                                # run_step <标签> <run.sh 的参数…>：后台起子进程并等它，返回它的退出码
    label=$1; shift
    log "START $label: taskset -c 4-11 nice -n 19 $RUN $*"
    t0=$(date +%s)
    taskset -c 4-11 nice -n 19 "$RUN" "$@" &
    CHILD=$!
    echo "$CHILD" > "$CHILDF"
    wait "$CHILD"
    rc=$?
    CHILD=""
    rm -f "$CHILDF"
    log "END $label: exit $rc after $(( $(date +%s) - t0 )) s"
    return "$rc"
}

# ---------------------------------------------------------------- 1. 前置检查
mkdir -p "$LOGS" || { echo "cannot create $LOGS"; exit 2; }
if [ -f "$PIDF" ]; then
    old=$(cat "$PIDF" 2>/dev/null)
    if [ -n "$old" ] && [ "$old" != "$$" ] && kill -0 "$old" 2>/dev/null; then
        log "another $NAME launcher is running (pid $old, $PIDF); not starting"
        exit 4
    fi
fi
echo "$$" > "$PIDF"
log "START $(basename "$0") pid $$ on $(hostname): SRC=$SRC DST=$DST NEW=$NEW BUDGET=${BUDGET:-auto} INFLIGHT=$INFLIGHT POOL=$POOL SEED=$SEED WORKERS=$WORKERS REFRESH=$REFRESH REFRESH_RAD=$REFRESH_RAD MAX_FAIL=$MAX_FAIL EXPECT_DELTA=${EXPECT_DELTA:-none} EXPECT_MM=${EXPECT_MM:-unchecked}"
for v in NEW INFLIGHT POOL SEED WORKERS REFRESH; do
    eval "val=\$$v"
    case "$val" in ''|*[!0-9]*) finish 2 "$v=$val is not a non-negative integer";; esac
done
if [ -n "${BUDGET:-}" ]; then
    case "$BUDGET" in *[!0-9]*) finish 2 "BUDGET=$BUDGET is not a non-negative integer";; esac
fi
[ "$INFLIGHT" -ge 1 ] || finish 2 "INFLIGHT must be >= 1"
ED=""
if [ -n "$EXPECT_DELTA" ]; then
    case "$EXPECT_DELTA" in *[!0-9.]*|.|*.*.*) finish 2 "EXPECT_DELTA=$EXPECT_DELTA is not a number";; esac
    ED="--expect-delta $EXPECT_DELTA"
fi
EM=""
if [ -n "$EXPECT_MM" ]; then
    case "$EXPECT_MM" in
        none|null) ;;
        .|*.*.*|*[!0-9.]*) finish 2 "EXPECT_MM=$EXPECT_MM is not 'none' or a number of um";;
    esac
    EM="--expect-mm-limit $EXPECT_MM"
fi
cd "$CODE" 2>/dev/null || finish 2 "no code directory $CODE"
[ -f "$CODE/v2/stage_neckopt.py" ] || finish 2 "no $CODE/v2/stage_neckopt.py"
[ -x "$RUN" ] || finish 2 "$RUN is not executable"
[ -f "$GATE" ] || finish 2 "no gate script $GATE"
command -v taskset >/dev/null 2>&1 || finish 2 "taskset not found"
[ -x "$PY" ] || PY=python3
command -v "$PY" >/dev/null 2>&1 || finish 2 "no python for the gate ($PY)"
if [ -f "$CODE/VERSION" ]; then
    log "code VERSION: $(tr '\n' ' ' < "$CODE/VERSION")"
else
    log "code VERSION: (missing)"
fi
if [ -n "${EXPECT_GIT:-}" ]; then
    grep -q "^git=$EXPECT_GIT" "$CODE/VERSION" 2>/dev/null || finish 2 "code/VERSION git= does not start with $EXPECT_GIT"
fi
if ! grep -Eq "^PHASES\\[$SRC\\][[:space:]]*=" "$CODE/v2/stage_neckopt.py"; then
    finish 2 "PHASES[$SRC] is not defined in the synced stage_neckopt.py (sync the code first)"
fi
if [ "$EXPECT_MM" = none ] || [ "$EXPECT_MM" = null ]; then
    grep -Eq "^PHASES\[$SRC\][^#]*\"mm_limit\": None" "$CODE/v2/stage_neckopt.py" \
        || finish 2 "EXPECT_MM=none but the PHASES[$SRC] line of the synced stage_neckopt.py has no \"mm_limit\": None (stale code? sync the reviewed commit)"
fi
if pgrep -f "$DRIVER_PAT" >/dev/null 2>&1; then
    ps -o pid,etime,args -p "$(pgrep -d, -f "$DRIVER_PAT")" 2>/dev/null | sed 's/^/    /'
    finish 4 "a phase-$SRC BO driver is still running (segment A's init driver, or another arm); not starting a second one"
fi

# ---------------------------------------------------------------- 2. 闸门（只读；数字写进日志，不过时写 logs/<FLAG>）
out=$("$PY" "$GATE" init --root "$BASE" --src "$SRC" --dst "$DST" --max-fail "$MAX_FAIL" --new "$NEW" --flag "$FLAG" $AI $ED $EM 2>&1)
grc=$?
printf '%s\n' "$out" | while IFS= read -r line; do log "  gate: $line"; done
case "$grc" in
    0) ;;
    3) finish 3 "init gate failed (see the numbers above and $FLAG); the phase-$SRC arm is not started (MAX_FAIL=1 overrides the failure-rate limit, ALLOW_INFEASIBLE=1 the zero-feasible rule)" ;;
    5) finish 5 "neckopt_p$SRC.json is missing or unreadable (segment A has not finished?); not started" ;;
    *) finish 2 "gate script exit $grc" ;;
esac
BS=$(printf '%s\n' "$out" | sed -n "s/^BUDGET$SRC=\\([0-9][0-9]*\\)\$/\\1/p" | tail -n 1)
[ -n "$BS" ] || finish 2 "gate did not print BUDGET$SRC"
if [ -n "${BUDGET:-}" ]; then
    [ "$BUDGET" = "$BS" ] || log "warning: BUDGET=$BUDGET given; the gate's BUDGET$SRC (init + adopted + NEW) is $BS — using $BUDGET"
    B=$BUDGET
else
    B=$BS
fi
if pgrep -f "$DRIVER_PAT" >/dev/null 2>&1; then
    finish 4 "a phase-$SRC BO driver appeared during the gate; not starting"
fi

# ---------------------------------------------------------------- 3. 2 目标异步 BO（只用自己的记录 + 收编 sb<SRC>_*）
run_step "phase-$SRC arm (async budget $B inflight $INFLIGHT, --warm none)" v2/stage_neckopt.py async --phase "$SRC" --budget "$B" \
    --inflight "$INFLIGHT" --pool "$POOL" --seed "$SEED" --refresh "$REFRESH" --refresh-rad "$REFRESH_RAD" --warm none --workers "$WORKERS"
rc=$?
finish "$rc" "phase-$SRC arm finished"
