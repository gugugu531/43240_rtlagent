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
# RC_COOKIE / RC_API_KEY are only read by cloud.py. The cookie holds ';' and
# must not go through the shell: sourcing it runs its pieces as commands and
# prints them in the error messages.
. <(grep -vE '^[[:space:]]*RC_(COOKIE|API_KEY)=' "$REMOTE_HERE/remote.env")

# REMOTE_HOST=cloud: the SSH address belongs to the current Radeon Cloud
# instance and changes with every launch, so take it from cloud.state
# (written by ./cloud.py up). Host keys change too: keep them in a separate
# known_hosts that cloud.py clears with each new instance.
REMOTE_HOST_SETTING="$REMOTE_HOST"   # "cloud" survives the substitution below
if [ "$REMOTE_HOST" = cloud ]; then
    if [ ! -f "$REMOTE_HERE/cloud.state" ]; then
        echo "✗ REMOTE_HOST=cloud，但还没有实例：先运行 ./cloud.py up" >&2
        exit 1
    fi
    cloud_vars=$(python3 - "$REMOTE_HERE/cloud.state" <<'PYEOF'
import json, shlex, sys
s = json.load(open(sys.argv[1]))
if not s.get("ssh_host"):
    sys.exit("✗ cloud.state 中没有 SSH 地址：实例可能还没就绪，或模板没有打开 SSH（./cloud.py status）")
print(f"REMOTE_HOST={shlex.quote(str(s.get('ssh_user') or 'root') + '@' + s['ssh_host'])}")
print(f"REMOTE_SSH_PORT={shlex.quote(str(s['ssh_port']))}")
PYEOF
) || exit 1
    eval "$cloud_vars"
    REMOTE_SSH_OPTS="-o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$REMOTE_HERE/cloud_known_hosts $REMOTE_SSH_OPTS"
    # Proxy, mirrors and /opt/venv on PATH, written by cloud.py up.
    : "${REMOTE_ACTIVATE:=. /root/.platform_env}"
fi

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
