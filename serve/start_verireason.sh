#!/usr/bin/env bash
# start_verireason.sh -- optional 8011 llama.cpp service for guided_verify.
#
# This is not part of the official default startup. Call it explicitly, or
# export VERI_GGUF before serve/start.sh, when guided_verify is being tested.
# It requires a llama-server binary and a converted GGUF file.
#
#   VERI_GGUF=/models/verireason-1.5b-f16.gguf ./serve/start.sh
#
# The script is idempotent: it returns 0 when 8011 already answers.

set -eo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${SERVE_LOG_DIR:-${AGENT_TMP:-/tmp}/serve-logs}"
MODEL="${VERI_GGUF:-/models/verireason-1.5b-f16.gguf}"
PORT="${VERI_PORT:-8011}"
ALIAS="${VERI_ALIAS:-verireason-1.5b}"
CTX="${VERI_CTX:-8192}"
THREADS="${VERI_THREADS:-8}"
SERVER="${VERI_SERVER:-/opt/llamacpp/llama-server}"
WAIT_S="${VERI_WAIT_S:-180}"
mkdir -p "$LOG_DIR"

if curl -sf -o /dev/null "http://127.0.0.1:$PORT/v1/models"; then
    echo "start_verireason.sh: small model already up on $PORT" >&2
    exit 0
fi
if [ ! -x "$SERVER" ]; then
    echo "start_verireason.sh: llama-server not executable: $SERVER" >&2
    exit 1
fi
if [ ! -f "$MODEL" ]; then
    echo "start_verireason.sh: GGUF missing: $MODEL" >&2
    exit 1
fi

# Resident process must not share the per-task process group.
setsid "$SERVER" \
    --model "$MODEL" \
    --alias "$ALIAS" \
    --host 127.0.0.1 --port "$PORT" \
    --ctx-size "$CTX" --parallel 1 \
    --n-gpu-layers all --threads "$THREADS" \
    --flash-attn on --no-webui --metrics \
    >>"$LOG_DIR/verireason.log" 2>&1 </dev/null &

waited=0
while ! curl -sf -o /dev/null "http://127.0.0.1:$PORT/v1/models"; do
    if [ "$waited" -ge "$WAIT_S" ]; then
        echo "start_verireason.sh: not ready after ${WAIT_S}s, see $LOG_DIR/verireason.log" >&2
        exit 1
    fi
    sleep 2
    waited=$((waited + 2))
done
echo "start_verireason.sh: ready on $PORT" >&2
