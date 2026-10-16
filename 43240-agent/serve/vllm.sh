#!/usr/bin/env bash
# Start the local inference service.
#
# This is the configuration that must be in effect at evaluation time: local
# open weights, single card, offline. The commercial-API path in agent/llm.py is
# for development only -- the sandbox has no network.
#
#   ./serve/vllm.sh
#   export LLM_BACKEND=openai LLM_BASE_URL=http://localhost:8000/v1 LLM_MODEL=$MODEL
#
# Every value below is a placeholder. Choosing them -- and being able to explain
# why -- is part of what the track scores. Whatever you settle on must match
# model/MODEL.md and section 3 of REPORT.md exactly, including the context
# configuration, because run_baseline.sh has to run against the same service.

set -eo pipefail

MODEL="${MODEL:-/models/Qwen3-8B}"     # local path, not a Hub id: the sandbox is offline
PORT="${PORT:-8000}"
MAX_LEN="${MAX_LEN:-32768}"            # declare this in MODEL.md, it is not a free parameter
VRAM_BUDGET_GB="${VRAM_BUDGET_GB:-30}"
# Extra vLLM flags, e.g. "--reasoning-parser qwen3". They change what the
# baseline sees as well (same service), so whatever is used must be declared
# in model/MODEL.md.
VLLM_EXTRA_ARGS="${VLLM_EXTRA_ARGS:-}"

# Single card. Tensor / pipeline parallelism across cards is not usable on
# gfx1201 (no XGMI, collective comms will not start reliably), and the memory
# budget is per-card anyway. Four cards means four independent instances.
export HIP_VISIBLE_DEVICES="${HIP_VISIBLE_DEVICES:-0}"

# Derive the fraction from the budget: 90% of a 48 GB GPU exceeds 32 GB.
if [ -z "${GPU_UTIL:-}" ]; then
    GPU_UTIL="$(python3 - "$VRAM_BUDGET_GB" <<'PYGPU'
import math, sys, torch
total = torch.cuda.get_device_properties(0).total_memory / 2**30
budget = float(sys.argv[1])
if not math.isfinite(budget) or not 0 < budget <= 32:
    raise ValueError("VRAM_BUDGET_GB must be in (0, 32]")
# Round down so the allocation never exceeds the requested budget.
print(f"{math.floor(min(0.95, budget / total) * 10000) / 10000:.4f}")
PYGPU
)" || { echo "vllm.sh: cannot derive VRAM budget; check GPU or set GPU_UTIL" >&2; exit 1; }
fi
# vLLM changed this flag in recent versions; use the installed CLI's help.
VLLM_HELP="$(python3 -m vllm.entrypoints.openai.api_server --help)"
if [[ "$VLLM_HELP" == *"--no-enable-log-requests"* ]]; then
    LOG_FLAG=--no-enable-log-requests
else
    LOG_FLAG=--disable-log-requests
fi

exec python3 -m vllm.entrypoints.openai.api_server \
    --model "$MODEL" \
    --served-model-name "${MODEL_NAME:-$(basename "$MODEL")}" \
    --host 127.0.0.1 \
    --port "$PORT" \
    --max-model-len "$MAX_LEN" \
    --gpu-memory-utilization "$GPU_UTIL" \
    "$LOG_FLAG" \
    $VLLM_EXTRA_ARGS
