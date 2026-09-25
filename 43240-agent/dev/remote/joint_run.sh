#!/usr/bin/env bash
# joint_run.sh — 跑一个模型的联合跑分（agent + baseline 同一次运行），并把指标采全。
#
#     ./joint_run.sh <远端权重目录> <标签> [quick|full] [vLLM 额外参数]
#
# 例：
#     ./joint_run.sh /workspace/models/Qwen3-4B-BF16 joint-A6-full full
#     ./joint_run.sh /workspace/models/Qwen3-4B-AWQ4 joint-Q1a-full full "'--dtype float16'"
#
# 做五件事，每一步都会打印结果：
#   1. 换模型重启远端 vLLM，等它就绪（轮询 /v1/models，失败会打日志）
#   2. 读 KV 池大小与权重占用（vLLM 启动日志）
#   3. 并发 1 的速度探测（metrics.py probe）
#   4. 起显存采样，跑 `run_eval.py --modes agent,baseline`（分子分母同一次运行）
#   5. 停采样、取回并汇总显存
#
# 为什么要用脚本：手工跑时容易漏掉 tunnel、漏掉 --metrics-url、或者把
# `--dtype float16` 忘掉（AWQ 会直接起不来，见 ../failures/serving-stack.md）。
#
# 前提：实例已启动（./cloud.py up）、中转已建立（./tunnel.sh up）。

set -eo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_ROOT="$(cd "$HERE/../.." && pwd)"
DEV_ROOT="$AGENT_ROOT/dev"

MODEL="${1:-}"
TAG="${2:-}"
TASKSET="${3:-quick}"
EXTRA="${4:-}"

# 参数检查放在 source _common.sh 之前：没有实例时 _common.sh 会直接退出，
# 那样连用法都打不出来。
if [ -z "$MODEL" ] || [ -z "$TAG" ]; then
    sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
fi

case "$TASKSET" in
    quick|full) ;;
    *) echo "✗ 第三个参数只能是 quick 或 full，收到：$TASKSET" >&2; exit 2 ;;
esac

# shellcheck source=_common.sh
. "$HERE/_common.sh"

RUN_EVAL="$AGENT_ROOT/dev/eval/run_eval.py"
METRICS="$AGENT_ROOT/dev/eval/metrics.py"

wait_ready() {
    local i
    for i in $(seq 1 40); do
        if curl -s -m 8 "$LOCAL_BASE_URL/models" | grep -q '"id"'; then
            echo "✓ 服务就绪（等了 $((i * 15))s）"
            return 0
        fi
        if rssh "grep -q 'EngineCore failed to start' ~/fpgachina2026-remote/vllm.log" 2>/dev/null; then
            echo "✗ vLLM 启动失败，日志里的错误：" >&2
            rssh "grep -n 'ValueError\|Error\|error' ~/fpgachina2026-remote/vllm.log | grep -v WARNING | tail -6" >&2
            return 1
        fi
        sleep 15
    done
    echo "✗ 等 10 分钟仍未就绪，检查 ./remote_vllm.sh logs" >&2
    return 1
}

echo "=== 0. 权重指纹（sha256 + 上游 commit）==="
# 先记指纹再看分数：第一批实验就是因为没记、实例销毁后无法追溯。
FINGERPRINT="$DEV_ROOT/runs/${TAG}.weights.md"
if ./weights.sh "$MODEL" "$FINGERPRINT" >/dev/null 2>&1; then
    echo "✓ 已记录 $FINGERPRINT（跑完请把内容并进 dev/notes/ 的指纹文档）"
else
    echo "⚠ 权重指纹没取到（远端目录不存在？）——继续跑分，但事后要补记" >&2
fi

echo "=== 1. 启动 vLLM：$MODEL ==="
./remote_vllm.sh stop >/dev/null 2>&1 || true
# shellcheck disable=SC2086
REMOTE_MODEL="$MODEL" REMOTE_EXTRA_ENV="$EXTRA" ./remote_vllm.sh start 2>&1 | tail -2
wait_ready || exit 1

echo "=== 2. KV 池与权重占用 ==="
rssh "grep -n 'Model loading took\|Available KV cache\|GPU KV cache size\|Maximum concurrency' \
      ~/fpgachina2026-remote/vllm.log | tail -4"

echo "=== 3. 并发 1 速度探测 ==="
export_llm_env
python3 "$METRICS" probe "$LLM_BASE_URL" --model "$LLM_MODEL" --max-tokens 512 --repeat 2 \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print("  tps_decode_median", d["tps_decode_median"], " ttft_median", d["ttft_median"])'

echo "=== 4. 联合跑分（agent + baseline，$TASKSET）==="
./vram_watch.sh start 3
TS_ARGS=()
[ "$TASKSET" = quick ] && TS_ARGS=(--taskset quick)
python3 "$RUN_EVAL" --tag "$TAG" --modes agent,baseline "${TS_ARGS[@]}" \
    --jobs 4 --judge-jobs 4 --metrics-url "$LLM_BASE_URL" 2>&1 | tail -30

echo "=== 5. 显存汇总 ==="
./vram_watch.sh stop 2>&1 | tail -1
RUN_DIR=$(ls -td "$DEV_ROOT/runs"/*-"$TAG" | head -1)
./vram_watch.sh report "$RUN_DIR/vram.log" 2>&1 | grep -E 'peak_gib|steady_gib' || true
echo "✓ 完成：dev/runs/$(basename "$RUN_DIR")"
