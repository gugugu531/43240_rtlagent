#!/usr/bin/env bash
# SSH tunnel to the remote vLLM.
#
#   ./tunnel.sh up        127.0.0.1:$LOCAL_VLLM_PORT -> remote 127.0.0.1:$REMOTE_VLLM_PORT
#   ./tunnel.sh status    tunnel alive? vLLM answering through it?
#   ./tunnel.sh down

set -eo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

ctl() {   # ctl <check|exit>
    # shellcheck disable=SC2086
    ssh -p "$REMOTE_SSH_PORT" $REMOTE_SSH_OPTS -S "$TUNNEL_SOCK" -O "$1" "$REMOTE_HOST" 2>/dev/null
}

case "${1:-status}" in
    up)
        if ctl check; then
            echo "✓ 隧道已存在"
        else
            # shellcheck disable=SC2086
            ssh -p "$REMOTE_SSH_PORT" $REMOTE_SSH_OPTS \
                -f -N -M -S "$TUNNEL_SOCK" \
                -o ExitOnForwardFailure=yes \
                -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
                -L "127.0.0.1:${LOCAL_VLLM_PORT}:127.0.0.1:${REMOTE_VLLM_PORT}" \
                "$REMOTE_HOST"
            echo "✓ 隧道已建立     127.0.0.1:${LOCAL_VLLM_PORT} -> ${REMOTE_HOST}:127.0.0.1:${REMOTE_VLLM_PORT}"
        fi
        ;;
    down)
        ctl exit && echo "✓ 隧道已关闭" || echo "隧道原本就没有建立"
        ;;
    status)
        if ctl check; then
            echo "✓ 隧道正常       127.0.0.1:${LOCAL_VLLM_PORT} -> ${REMOTE_HOST}:${REMOTE_VLLM_PORT}"
        else
            echo "✗ 隧道未建立     ./tunnel.sh up"
            exit 1
        fi
        if m=$(served_model 2>&1); then
            echo "✓ vLLM 响应正常  $m"
        else
            echo "✗ vLLM 没有响应  $m"
            echo "  远端服务可能还在加载权重，或未启动：./remote_vllm.sh status"
            exit 1
        fi
        ;;
    *)
        sed -n '2,6p' "$0"; exit 2 ;;
esac
