#!/usr/bin/env bash
# SSH tunnel to the remote vLLM.
#
#   ./tunnel.sh up        127.0.0.1:$LOCAL_VLLM_PORT -> remote 127.0.0.1:$REMOTE_VLLM_PORT
#   ./tunnel.sh status    tunnel alive? vLLM answering through it?
#   ./tunnel.sh down
#
# Two modes (TUNNEL_MODE):
#   forward  ssh -L port forwarding. The default for ordinary servers.
#   relay    for servers whose sshd has AllowTcpForwarding no -- Radeon Cloud
#            instances do. socat listens locally and, per connection, opens a
#            plain ssh session that pipes to the remote port (relay_conn.sh).
#            About 0.7 s extra per request. The default when REMOTE_HOST=cloud;
#            needs socat locally and bash on the remote.

set -eo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

: "${TUNNEL_MODE:=$([ "${REMOTE_HOST_SETTING:-}" = cloud ] && echo relay || echo forward)}"
RELAY_PID="${XDG_RUNTIME_DIR:-/tmp}/fpgachina-relay-$(id -u).pid"
TRANSPORT_PORT="${LOCAL_RELAY_PORT:-$((LOCAL_VLLM_PORT + 1))}"
TRANSPORT_UNIT="fpgachina-transport-${LOCAL_VLLM_PORT}.service"
GATEWAY_UNIT="fpgachina-model-gateway-${LOCAL_VLLM_PORT}.service"

up_managed() {
    # Remove only the legacy tunnel, before the managed listeners claim its port.
    if relay_alive; then kill "$(cat "$RELAY_PID")"; fi
    rm -f "$RELAY_PID"
    ctl exit || true
    if ! systemctl --user is-active --quiet "$TRANSPORT_UNIT"; then
        systemd-run --user --collect --unit="$TRANSPORT_UNIT" \
            --property=Restart=always --property=RestartSec=3 \
            --property=StartLimitIntervalSec=0 \
            /usr/bin/bash "$REMOTE_HERE/tunnel.sh" run-transport
    fi
    if ! systemctl --user is-active --quiet "$GATEWAY_UNIT"; then
        gateway_args=()
        if [ -n "${MODEL_GATEWAY_PROFILE:-}" ]; then
            [ -n "${MODEL_GATEWAY_AUDIT_DIR:-}" ] || { echo '实验网关缺少审计目录' >&2; return 1; }
            gateway_args=(--profile "$MODEL_GATEWAY_PROFILE" --audit-dir "$MODEL_GATEWAY_AUDIT_DIR")
        fi
        systemd-run --user --collect --unit="$GATEWAY_UNIT" \
            --property=Restart=always --property=RestartSec=3 \
            --property=StartLimitIntervalSec=0 \
            /usr/bin/python3 "$REMOTE_HERE/model_gateway.py" \
            --port "$LOCAL_VLLM_PORT" --upstream-port "$TRANSPORT_PORT" "${gateway_args[@]}"
    fi
    echo "✓ 自动重连服务已启动；日志：journalctl --user -u $TRANSPORT_UNIT -u $GATEWAY_UNIT"
}

run_transport() {
    if [ "$TUNNEL_MODE" = relay ]; then
        command -v socat >/dev/null || { echo '需要 socat' >&2; exit 1; }
        exec socat "TCP-LISTEN:${TRANSPORT_PORT},bind=127.0.0.1,reuseaddr,fork" \
            "EXEC:$REMOTE_HERE/relay_conn.sh"
    else
        # Foreground SSH belongs to systemd, which reconnects after an exit.
        # shellcheck disable=SC2086
        exec ssh -p "$REMOTE_SSH_PORT" $REMOTE_SSH_OPTS -N \
            -o ControlPath=none -o BatchMode=yes -o ConnectTimeout=10 \
            -o ExitOnForwardFailure=yes -o ServerAliveInterval=10 -o ServerAliveCountMax=3 \
            -L "127.0.0.1:${TRANSPORT_PORT}:127.0.0.1:${REMOTE_VLLM_PORT}" "$REMOTE_HOST"
    fi
}

ctl() {   # ctl <check|exit>
    # shellcheck disable=SC2086
    ssh -p "$REMOTE_SSH_PORT" $REMOTE_SSH_OPTS -S "$TUNNEL_SOCK" -O "$1" "$REMOTE_HOST" 2>/dev/null
}

relay_alive() {
    [ -f "$RELAY_PID" ] && kill -0 "$(cat "$RELAY_PID")" 2>/dev/null
}

up_forward() {
    if ctl check; then
        echo "✓ 隧道已存在"
        return
    fi
    # shellcheck disable=SC2086
    ssh -p "$REMOTE_SSH_PORT" $REMOTE_SSH_OPTS \
        -f -N -M -S "$TUNNEL_SOCK" \
        -o ExitOnForwardFailure=yes \
        -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
        -L "127.0.0.1:${LOCAL_VLLM_PORT}:127.0.0.1:${REMOTE_VLLM_PORT}" \
        "$REMOTE_HOST"
    echo "✓ 隧道已建立     127.0.0.1:${LOCAL_VLLM_PORT} -> ${REMOTE_HOST}:127.0.0.1:${REMOTE_VLLM_PORT}"
}

up_relay() {
    if relay_alive; then
        echo "✓ 中转已存在"
        return
    fi
    command -v socat >/dev/null || { echo "✗ 中转模式需要本机安装 socat" >&2; exit 1; }
    setsid socat "TCP-LISTEN:${LOCAL_VLLM_PORT},bind=127.0.0.1,reuseaddr,fork" \
        "EXEC:$REMOTE_HERE/relay_conn.sh" > /dev/null 2>&1 < /dev/null &
    echo $! > "$RELAY_PID"
    sleep 0.5
    relay_alive || { echo "✗ socat 启动失败（端口 ${LOCAL_VLLM_PORT} 被占用？）" >&2; exit 1; }
    echo "✓ 中转已建立     127.0.0.1:${LOCAL_VLLM_PORT} -> ${REMOTE_HOST}:127.0.0.1:${REMOTE_VLLM_PORT}（每个连接一次 ssh 会话）"
}

case "${1:-status}" in
    up)
        up_managed
        ;;
    run-transport)
        run_transport
        ;;
    down)
        closed=0
        for unit in "$GATEWAY_UNIT" "$TRANSPORT_UNIT"; do
            if systemctl --user is-active --quiet "$unit"; then
                systemctl --user stop "$unit"; closed=1
            fi
        done
        if relay_alive; then kill "$(cat "$RELAY_PID")" && closed=1; fi
        rm -f "$RELAY_PID"
        ctl exit && closed=1 || true
        [ "$closed" = 1 ] && echo "✓ 隧道已关闭" || echo "隧道原本就没有建立"
        ;;
    status)
        if systemctl --user is-active --quiet "$GATEWAY_UNIT" && \
                systemctl --user is-active --quiet "$TRANSPORT_UNIT"; then
            echo "✓ 自动重连服务正常 127.0.0.1:${LOCAL_VLLM_PORT} -> relay:${TRANSPORT_PORT}"
        elif [ "$TUNNEL_MODE" = relay ]; then
            relay_alive || { echo "✗ 中转未建立     ./tunnel.sh up"; exit 1; }
            echo "✓ 中转正常       127.0.0.1:${LOCAL_VLLM_PORT} -> ${REMOTE_HOST}:${REMOTE_VLLM_PORT}"
        elif ctl check; then
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
        sed -n '2,14p' "$0"; exit 2 ;;
esac
