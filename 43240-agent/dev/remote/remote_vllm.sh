#!/usr/bin/env bash
# Manage vLLM on the remote GPU server over ssh.
#
#   ./remote_vllm.sh start     sync serve/vllm.sh to the remote and start it
#   ./remote_vllm.sh wait      block until vLLM answers through the tunnel
#   ./remote_vllm.sh status    process alive? last log lines
#   ./remote_vllm.sh logs      follow the remote log (Ctrl-C to stop)
#   ./remote_vllm.sh stop
#
# Runs the very same serve/vllm.sh the submission ships, so the serving config
# measured here is the one declared in MODEL.md. It binds 127.0.0.1 on the
# remote; reach it with ./tunnel.sh up.

set -eo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

pid_alive='[ -f vllm.pid ] && kill -0 "$(cat vllm.pid)" 2>/dev/null'

case "${1:-status}" in
    start)
        rssh "mkdir -p $REMOTE_DIR && cat > $REMOTE_DIR/vllm.sh && chmod +x $REMOTE_DIR/vllm.sh" \
            < "$AGENT_ROOT/serve/vllm.sh"
        echo "✓ 已同步 serve/vllm.sh -> $REMOTE_HOST:$REMOTE_DIR/"
        rssh "cd $REMOTE_DIR && if $pid_alive; then echo '✓ vLLM 已在运行 (pid '\$(cat vllm.pid)')'; exit 0; fi
              ${REMOTE_ACTIVATE:+$REMOTE_ACTIVATE &&} \
              env MODEL='$REMOTE_MODEL' PORT='$REMOTE_VLLM_PORT' MAX_LEN='${REMOTE_MAX_LEN:-32768}' \
                  GPU_UTIL='${REMOTE_GPU_UTIL:-0.90}' $REMOTE_EXTRA_ENV \
                  setsid nohup ./vllm.sh > vllm.log 2>&1 < /dev/null &
              echo \$! > vllm.pid
              echo \"✓ vLLM 已启动 (pid \$(cat vllm.pid))，日志 $REMOTE_DIR/vllm.log\""
        echo "  加载权重需要时间：./remote_vllm.sh wait"
        ;;
    wait)
        deadline=$((SECONDS + ${WAIT_TIMEOUT:-900}))
        until served_model >/dev/null 2>&1; do
            if ! rssh "cd $REMOTE_DIR && $pid_alive"; then
                echo "✗ 远端 vLLM 进程已退出，最后的日志：" >&2
                rssh "tail -n 30 $REMOTE_DIR/vllm.log" >&2
                exit 1
            fi
            [ "$SECONDS" -ge "$deadline" ] && { echo "✗ 等待超时" >&2; exit 1; }
            sleep 5
        done
        echo "✓ vLLM 就绪      $(served_model)"
        ;;
    status)
        rssh "cd $REMOTE_DIR 2>/dev/null || { echo '✗ 远端目录不存在，尚未 start'; exit 1; }
              if $pid_alive; then echo \"✓ vLLM 进程存活 (pid \$(cat vllm.pid))\"; else echo '✗ vLLM 未运行'; fi
              echo '--- vllm.log (tail) ---'; tail -n 15 vllm.log 2>/dev/null"
        ;;
    logs)
        rssh "tail -n 50 -f $REMOTE_DIR/vllm.log"
        ;;
    stop)
        # setsid made the pid a process-group leader: kill the whole group so
        # vLLM's worker processes go too and release the GPU.
        rssh "cd $REMOTE_DIR && if $pid_alive; then
                  kill -- -\$(cat vllm.pid) 2>/dev/null || kill \$(cat vllm.pid)
                  for i in \$(seq 30); do $pid_alive || break; sleep 1; done
                  $pid_alive && kill -9 -- -\$(cat vllm.pid) 2>/dev/null
                  echo '✓ vLLM 已停止'
              else echo 'vLLM 本来就没在运行'; fi; rm -f vllm.pid"
        ;;
    *)
        sed -n '2,9p' "$0"; exit 2 ;;
esac
