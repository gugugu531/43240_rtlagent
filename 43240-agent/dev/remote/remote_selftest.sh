#!/usr/bin/env bash
# Daily scoring: remote inference, local agent + local Vivado judging.
#
#   ./remote_selftest.sh [--tag NAME] [run_selftest.sh options...]
#
#   ./remote_selftest.sh --tag smoke
#   ./remote_selftest.sh --tag veval --tasks ../../../tasks --samples 5
#
# Brings the tunnel up if needed, points agent AND baseline at the remote vLLM,
# then runs selftest/run_selftest.sh against this agent. Artefacts go to
# dev/runs/<time>-<tag>/, a summary to dev/experiments/<time>-<tag>.md.

set -eo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

TAG=run
ARGS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --tag) TAG="$2"; shift 2 ;;
        --out|--agent) echo "✗ $1 由本脚本自动设置，不要手动传入" >&2; exit 2 ;;
        -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
        *) ARGS+=("$1"); shift ;;
    esac
done

"$REMOTE_HERE/tunnel.sh" status >/dev/null 2>&1 || "$REMOTE_HERE/tunnel.sh" up
export_llm_env

# run_selftest.sh sources selftest/env.sh AFTER our exports. If that file sets
# LLM_* (env.sh.example ships with LLM_BACKEND=mock uncommented), it silently
# replaces the remote model with mock or another endpoint. Refuse instead.
SELFTEST_ENV="$SELFTEST_DIR/env.sh"
if [ -f "$SELFTEST_ENV" ]; then
    after=$(bash -c ". '$SELFTEST_ENV' >/dev/null 2>&1; echo \"\$LLM_BACKEND|\$LLM_BASE_URL|\$LLM_MODEL\"")
    if [ "$after" != "$LLM_BACKEND|$LLM_BASE_URL|$LLM_MODEL" ]; then
        echo "✗ selftest/env.sh 会覆盖 LLM 配置（得到 $after）" >&2
        echo "  把 env.sh 里的 LLM_* 改成「没有设置时才使用默认值」的写法，例如：" >&2
        echo '      export LLM_BACKEND="${LLM_BACKEND:-openai}"' >&2
        echo '      export LLM_BASE_URL="${LLM_BASE_URL:-https://api.deepseek.com}"' >&2
        echo "  这样直接运行 run_selftest.sh 时仍使用 env.sh 的配置，通过本脚本运行时则使用远端模型" >&2
        exit 1
    fi
fi

RUN_ID="$(date +%Y%m%d-%H%M%S)-$TAG"
RUN_DIR="$DEV_ROOT/runs/$RUN_ID"
python3 "$REMOTE_HERE/record.py" meta "$RUN_DIR" remote_selftest "${ARGS[@]}"
echo "✓ 运行目录       dev/runs/$RUN_ID"

# Relative --tasks paths are resolved by run_selftest.sh from the caller's cwd.
"$SELFTEST_DIR/run_selftest.sh" --agent "$AGENT_ROOT" --out "$RUN_DIR" "${ARGS[@]}" \
    2>&1 | tee "$RUN_DIR/selftest.log"

python3 "$DEV_ROOT/eval/analyze.py" "$RUN_DIR" >/dev/null || true
python3 "$REMOTE_HERE/record.py" summary "$RUN_DIR"
