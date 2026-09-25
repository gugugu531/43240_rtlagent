#!/usr/bin/env bash
# vram_watch.sh — 在远端实例上按固定间隔采样显存，供模型筛选使用。
#
#     ./vram_watch.sh start [间隔秒]   在实例上后台起一个 rocm-smi 采样循环
#     ./vram_watch.sh fetch [输出文件] 把采样日志取回本机
#     ./vram_watch.sh report [输出文件] 取回并汇总峰值/稳态显存
#     ./vram_watch.sh stop             停掉采样循环
#
# 为什么要在远端采：模型跑在云实例上，本机的显卡与它无关，本机 rocm-smi
# 量不到任何有用的东西。采样日志默认写实例的 /workspace/vram.log。
#
# 与 dev/eval/run_eval.py 的配合：跑分前 start、跑分后 stop + report，
# 得到的就是那一次跑分的显存曲线。若同一次会话里要测多个模型，
# 每个模型单独 start/stop 一次，避免把上一个模型的读数混进来。

set -eo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_common.sh
. "$HERE/_common.sh"

VRAM_LOG="${VRAM_LOG:-/workspace/vram.log}"
VRAM_PID="${VRAM_PID:-/workspace/vram.pid}"

usage() {
    sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
}

cmd_start() {
    local interval="${1:-2}"
    rssh "INTERVAL=$interval LOG=$VRAM_LOG PIDF=$VRAM_PID bash -s" <<'EOF'
if [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; then
    echo "✗ 已有采样进程在跑（pid $(cat "$PIDF")）；先 ./vram_watch.sh stop" >&2
    exit 1
fi
: > "$LOG"
setsid nohup bash -c "while true; do rocm-smi --showmeminfo vram --csv 2>/dev/null; echo; sleep $INTERVAL; done" \
    > "$LOG" 2>&1 < /dev/null &
echo $! > "$PIDF"
sleep 1
echo "✓ 已在实例上开始采样：$LOG，间隔 ${INTERVAL}s，pid $(cat "$PIDF")"
EOF
}

cmd_stop() {
    rssh "LOG=$VRAM_LOG PIDF=$VRAM_PID bash -s" <<'EOF'
if [ -f "$PIDF" ]; then
    pid=$(cat "$PIDF")
    if kill "$pid" 2>/dev/null; then echo "✓ 已停止采样进程 $pid"; else echo "进程 $pid 已不在"; fi
    rm -f "$PIDF"
else
    echo "没有采样进程（$PIDF 不存在）"
fi
# 兜底：setsid 之后 pid 文件里可能是外层 shell 的号，把真正的循环也收掉。
pkill -f "rocm-smi --showmeminfo vram" 2>/dev/null || true
echo "采样日志 $LOG，$(grep -c '^card' "$LOG" 2>/dev/null || echo 0) 个采样点"
EOF
}

cmd_fetch() {
    local out="${1:-$DEV_ROOT/runs/vram-$(date +%Y%m%d-%H%M%S).log}"
    mkdir -p "$(dirname "$out")"
    rssh "cat $VRAM_LOG" > "$out"
    if [ ! -s "$out" ]; then
        echo "✗ 采样日志是空的：先 ./vram_watch.sh start，再跑分，最后 fetch" >&2
        exit 1
    fi
    echo "✓ 采样日志 $out（$(grep -c '^card' "$out" || true) 个采样点）"
}

cmd_report() {
    local out="${1:-$DEV_ROOT/runs/vram-$(date +%Y%m%d-%H%M%S).log}"
    cmd_fetch "$out" >&2
    python3 "$DEV_ROOT/eval/metrics.py" vram "$out"
}

case "${1:-}" in
    start)  shift; cmd_start "$@" ;;
    stop)   shift; cmd_stop "$@" ;;
    fetch)  shift; cmd_fetch "$@" ;;
    report) shift; cmd_report "$@" ;;
    *)      usage ;;
esac
