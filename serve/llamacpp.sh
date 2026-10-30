#!/usr/bin/env bash
# Start the local, offline HIP + MTP3 inference service.
# Keep defaults aligned with model/MODEL.md and manifest.json.

set -eo pipefail

MODEL="${MODEL:-/models/Qwen3.8-27B-Q4_K_M.gguf}"
MTP_MODEL="${MTP_MODEL:-/models/mtp-Qwen3.8-27B-Q4_0.gguf}"
MODEL_NAME="${MODEL_NAME:-qwen38-27b-q4-k-m}"
LLAMA_SERVER="${LLAMA_SERVER:-llama-server}"
PORT="${PORT:-8010}"
MAX_LEN="${MAX_LEN:-65536}"
PARALLEL="${PARALLEL:-1}"
N_GPU_LAYERS="${N_GPU_LAYERS:-all}"
THREADS="${THREADS:-16}"
THREADS_BATCH="${THREADS_BATCH:-16}"
FLASH_ATTN="${FLASH_ATTN:-on}"
REASONING_BUDGET="${REASONING_BUDGET:--1}"

if [ ! -f "$MODEL" ] || [ ! -r "$MODEL" ]; then
    echo "llamacpp.sh: readable local GGUF not found: $MODEL" >&2
    exit 1
fi
if [ ! -f "$MTP_MODEL" ] || [ ! -r "$MTP_MODEL" ]; then
    echo "llamacpp.sh: readable local MTP GGUF not found: $MTP_MODEL" >&2
    exit 1
fi
if ! command -v "$LLAMA_SERVER" >/dev/null 2>&1 || [ ! -x "$(command -v "$LLAMA_SERVER")" ]; then
    echo "llamacpp.sh: llama-server not found; set LLAMA_SERVER to an executable or add it to PATH: $LLAMA_SERVER" >&2
    exit 1
fi

exec "$LLAMA_SERVER" \
    -m "$MODEL" \
    --alias "$MODEL_NAME" \
    --host 127.0.0.1 \
    --port "$PORT" \
    --ctx-size "$MAX_LEN" \
    --parallel "$PARALLEL" \
    --n-gpu-layers "$N_GPU_LAYERS" \
    --threads "$THREADS" \
    --threads-batch "$THREADS_BATCH" \
    --cpu-strict 1 \
    --cache-type-k f16 \
    --cache-type-v f16 \
    --flash-attn "$FLASH_ATTN" \
    --no-webui \
    --metrics \
    --reasoning-budget "$REASONING_BUDGET" \
    --spec-type draft-mtp \
    --model-draft "$MTP_MODEL" \
    --spec-draft-ngl all \
    --spec-draft-n-max 3
