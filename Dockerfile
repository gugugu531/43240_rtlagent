# Build on the official base image. It carries ROCm, Vivado and a
# working inference stack for the target architecture; rebuilding that yourself
# is a large amount of work for no score.
#
# Both preliminary and final rounds use gfx1100 (Radeon PRO W7900).
# This official image is available only inside the platform. Organisers
# rebuild it in fallback mode; keep installation steps aligned with the instance.
ARG BASE_IMAGE=fpgachina-rtlhls@sha256:a7cf627e11708e8a6dcd9de689ff934f7b450b79369ebc7bb0217e8b54d81e56
FROM ${BASE_IMAGE}

# --- everything must be baked in: the sandbox has no network ----------------

WORKDIR /opt/agent

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY config/ config/
COPY agent/  agent/
COPY skill/  skill/
COPY knowledge/ knowledge/
COPY serve/  serve/
COPY model/  model/
COPY run.sh run_baseline.sh baseline.py manifest.json REPORT.md LICENSE ./
RUN chmod +x run.sh run_baseline.sh serve/llamacpp.sh serve/start.sh serve/start_verireason.sh serve/run_api.sh

# Use the official image's bundled HIP server and matching runtime libraries.
# A different build must be prepared during image construction, never at runtime.
RUN test -x /opt/llamacpp/llama-server && test -d /opt/llamacpp/rocblas/library
# Bind-mount both the text GGUF and its Q4_0 MTP head under /models;
# weights and development files are deliberately not copied into this image.

ENV LLM_BACKEND=openai \
    LLM_BASE_URL=http://127.0.0.1:8000/v1 \
    LLM_MODEL=qwen38-27b-q4-k-m \
    MODEL_NAME=qwen38-27b-q4-k-m \
    MODEL=/models/Qwen3.8-27B-Q4_K_M.gguf \
    MTP_MODEL=/models/mtp-Qwen3.8-27B-Q4_0.gguf \
    LLAMA_SERVER=/opt/llamacpp/llama-server \
    ROCBLAS_TENSILE_LIBPATH=/opt/llamacpp/rocblas/library \
    PORT=8000 \
    LLM_API_KEY=dummy \
    AGENT_TMP=/var/tmp \
    EDA_TMP=/var/tmp/eda \
    SELFTEST_TMP=/var/tmp \
    RTL_PART=xczu3eg-sbva484-1-e

# Do NOT set PATH for the toolchain here. The base image already exports it,
# along with XILINX_VIVADO / XILINX_VITIS. The tools actually live under
# /tools/Xilinx/2026.1/, and the layout is version-first in 2026.1 but
# tool-first in 2024.2 and earlier -- which is why CONTRACT.md section 1
# says to read the variables instead of hardcoding a path.

# Container metadata only. On Radeon Cloud both services bind 127.0.0.1 and
# just 7860 is published, via rc-tunnel. See docs/API_CONTRACT.md section 7.
EXPOSE 7860 8000

# Start resident services once with serve/start.sh before calling run.sh or
# run_baseline.sh. HTTP submission additionally runs serve/serve_api.py.
CMD ["/bin/bash"]
