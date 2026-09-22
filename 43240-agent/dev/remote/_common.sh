# Shared helpers for dev/remote/*.sh. Source it, do not execute it.
#
# Loads remote.env and defines paths, the ssh wrapper and the tunnel probe.

REMOTE_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_ROOT="$(cd "$REMOTE_HERE/../.." && pwd)"     # 43240-agent/
REPO_ROOT="$(dirname "$AGENT_ROOT")"
DEV_ROOT="$AGENT_ROOT/dev"
SELFTEST_DIR="${SELFTEST_DIR:-$REPO_ROOT/selftest}"

if [ ! -f "$REMOTE_HERE/remote.env" ]; then
    echo "✗ 缺少 $REMOTE_HERE/remote.env，先 cp remote.env.example remote.env 再填写" >&2
    exit 1
fi
. "$REMOTE_HERE/remote.env"

: "${REMOTE_SSH_PORT:=22}"
: "${REMOTE_VLLM_PORT:=8000}"
: "${LOCAL_VLLM_PORT:=18000}"
: "${LOCAL_API_PORT:=7860}"

# ControlMaster socket: keeps one ssh connection for the tunnel, lets
# status/down address it without hunting for PIDs.
TUNNEL_SOCK="${XDG_RUNTIME_DIR:-/tmp}/fpgachina-tunnel-$(id -u).sock"
LOCAL_BASE_URL="http://127.0.0.1:${LOCAL_VLLM_PORT}/v1"

rssh() {   # rssh <remote command...>
    # shellcheck disable=SC2086
    ssh -p "$REMOTE_SSH_PORT" $REMOTE_SSH_OPTS "$REMOTE_HOST" "$@"
}

# Print the model id vLLM is serving through the tunnel, or fail.
served_model() {
    python3 - "$LOCAL_BASE_URL" <<'EOF'
import json, sys, urllib.request
try:
    with urllib.request.urlopen(sys.argv[1] + "/models", timeout=10) as r:
        data = json.loads(r.read()).get("data", [])
    print(data[0]["id"])
except Exception as exc:
    sys.exit(f"{type(exc).__name__}: {exc}")
EOF
}

# Point agent/llm.py and baseline.py at the tunnel. Both must hit the same
# service, otherwise the gain metric compares two different models.
export_llm_env() {
    local model
    model=$(served_model) || {
        echo "✗ 通过隧道访问 $LOCAL_BASE_URL/models 失败，请检查：./tunnel.sh status、./remote_vllm.sh status" >&2
        return 1
    }
    export LLM_BACKEND=openai
    export LLM_BASE_URL="$LOCAL_BASE_URL"
    export LLM_API_KEY=dummy
    export LLM_MODEL="$model"
    export MODEL_NAME="$model"
    echo "✓ 推理服务       $LLM_BASE_URL  ($model)"
}
