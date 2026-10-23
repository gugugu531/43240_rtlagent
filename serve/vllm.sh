#!/usr/bin/env bash
# Start the local inference service.
#
# This is the configuration that must be in effect at evaluation time: local
# open weights, single card, offline. The agent connects to this local service
# through agent/llm/client.py.
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
# vLLM pre-allocates gpu-memory-utilization x total VRAM up front (weights +
# KV cache + activations), regardless of model size. 0.90 of a 48 GB W7900 is
# about 43 GB -- over the 32 GB per-card limit. So the default is derived from
# a VRAM budget instead of a fixed fraction; set GPU_UTIL to override, and
# verify the steady-state figure with `rocm-smi --showmemuse`.
VRAM_BUDGET_GB="${VRAM_BUDGET_GB:-30}"   # stay under 32 GB with some headroom

# Single card. Tensor / pipeline parallelism across cards is not usable on
# gfx1201 (no XGMI, collective comms will not start reliably), and the memory
# budget is per-card anyway. Four cards means four independent instances.
export HIP_VISIBLE_DEVICES="${HIP_VISIBLE_DEVICES:-0}"

if [ -z "${GPU_UTIL:-}" ]; then
    GPU_UTIL="$(python3 - "$VRAM_BUDGET_GB" <<'PY' 2>/dev/null || true
import sys, torch
total = torch.cuda.get_device_properties(0).total_memory / 2**30
print(f"{min(0.95, float(sys.argv[1]) / total):.2f}")
PY
)"
    if [ -z "$GPU_UTIL" ]; then
        echo "vllm.sh: cannot read VRAM size; set GPU_UTIL explicitly" >&2
        exit 1
    fi
fi
echo "vllm.sh: gpu-memory-utilization=$GPU_UTIL (budget ${VRAM_BUDGET_GB} GB)" >&2

TOOL_FLAGS=()
if [ "${ENABLE_TOOL_CALLING:-0}" = 1 ]; then
    TOOL_FLAGS=(--enable-auto-tool-choice --tool-call-parser "${TOOL_CALL_PARSER:-hermes}")
fi

exec python3 -m vllm.entrypoints.openai.api_server \
    --model "$MODEL" \
    --served-model-name "$(basename "$MODEL")" \
    --host 127.0.0.1 \
    --port "$PORT" \
    --max-model-len "$MAX_LEN" \
    --gpu-memory-utilization "$GPU_UTIL" \
    "${TOOL_FLAGS[@]}" \
    --no-enable-log-requests     # vLLM >= 0.27; the old --disable-log-requests is gone
