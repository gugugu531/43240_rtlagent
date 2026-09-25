#!/usr/bin/env bash
# weights.sh — 采集一份权重的指纹（sha256 + 上游 commit），供后续确认「是不是同一份权重」。
#
#     ./weights.sh <远端权重目录> [输出文件] [HF 仓库名]
#
# 例：
#     ./weights.sh /workspace/models/Qwen3.6-35B-A3B-AWQ \
#                  ../runs/qwen3.6-35b.weights.md QuantTrio/Qwen3.6-35B-A3B-AWQ
#
# 为什么要有这个脚本：2026-09-25 第一批实验跑完就把实例销毁了，**没有留权重哈希**，
# 后来无法确认那几次跑分用的是不是同一份权重（见 ../notes/2026-09-25-model-fingerprints.md
# 的「缺口」一节）。哈希算起来要几分钟，很容易在赶时间时被跳过，所以做成一条命令，
# 并接进 joint_run.sh。
#
# 输出两样东西：
#   1) 远端的 `sha256sum *.safetensors`
#   2) HuggingFace 下载元数据里的上游 commit 号（比文件名更早暴露「仓库更新了」）
#
# 不写任何远端状态，纯读取，可以在跑分前后随时执行。

set -eo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_ROOT="$(cd "$HERE/../.." && pwd)"
DEV_ROOT="$AGENT_ROOT/dev"

MODEL_DIR="${1:-}"
OUT="${2:-}"
REPO="${3:-}"

if [ -z "$MODEL_DIR" ]; then
    sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
fi
: "${OUT:=$DEV_ROOT/runs/weights-$(basename "$MODEL_DIR")-$(date +%Y%m%d-%H%M%S).md}"

# shellcheck source=_common.sh
. "$HERE/_common.sh"

NAME="$(basename "$MODEL_DIR")"

echo "→ 计算 $NAME 的 sha256（权重越大越慢）…" >&2
HASHES="$(rssh "cd '$MODEL_DIR' 2>/dev/null || { echo 'NO_SUCH_DIR'; exit 0; }; sha256sum *.safetensors 2>/dev/null | sort -k2")"
if [ -z "$HASHES" ] || [ "$HASHES" = "NO_SUCH_DIR" ]; then
    echo "✗ 读不到 $MODEL_DIR 下的 *.safetensors" >&2
    exit 1
fi

COMMITS="$(rssh "ls '$MODEL_DIR'/.cache/huggingface/download/*.metadata 2>/dev/null | while read -r f; do head -1 \"\$f\"; done | sort -u")"
COUNT="$(printf '%s\n' "$HASHES" | grep -c 'safetensors' || true)"

{
    echo "### $NAME"
    echo
    echo "| 项 | 值 |"
    echo "| --- | --- |"
    [ -n "$REPO" ] && echo "| HF 仓库 | \`$REPO\` |"
    echo "| 远端路径 | \`$MODEL_DIR\` |"
    echo "| 上游 commit | ${COMMITS:-（元数据里没读到，可能不是 hf download 下的）} |"
    echo "| 权重文件数 | $COUNT |"
    echo
    echo '```'
    printf '%s\n' "$HASHES"
    echo '```'
    echo
    echo "复核：把上面代码块存成文件，在权重目录里跑 \`sha256sum -c <文件>\`。"
} > "$OUT"

echo "✓ 已写入 $OUT" >&2
cat "$OUT"
