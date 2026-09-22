#!/usr/bin/env bash
# Link B2, server side: start serve/serve_api.py locally, backed by the remote
# vLLM through the tunnel. Runs in the foreground; use a second terminal for
# ./submit_client.py.
#
#   ./serve_local.sh
#
# Local rather than remote because Vivado is local: the agent's lint()/synth()
# only work where Vivado is, and evaluation day has Vivado in the base image.
# Needs fastapi + uvicorn locally: pip install -r ../../requirements.txt

set -eo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

"$REMOTE_HERE/tunnel.sh" status >/dev/null 2>&1 || "$REMOTE_HERE/tunnel.sh" up
export_llm_env
export FPGACHINA_TOKEN="${FPGACHINA_TOKEN:?remote.env 里须设置 FPGACHINA_TOKEN}"

python3 -c 'import fastapi, uvicorn' 2>/dev/null || {
    echo "✗ 缺少 fastapi / uvicorn：pip install -r $AGENT_ROOT/requirements.txt" >&2
    exit 1
}

echo "✓ 投题接口       http://127.0.0.1:${LOCAL_API_PORT}  (Ctrl-C 停止)"
cd "$AGENT_ROOT"
exec python3 -m uvicorn serve.serve_api:app --host 127.0.0.1 --port "$LOCAL_API_PORT"
