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

# A zombie still answers kill -0. On cloud instances PID 1 is JupyterLab, which
# never reaps orphans, so a crashed vLLM stays a zombie: check the state too.
pid_alive='[ -f vllm.pid ] && kill -0 "$(cat vllm.pid)" 2>/dev/null && ! ps -o stat= -p "$(cat vllm.pid)" | grep -q Z'

case "${1:-status}" in
    start)
        rssh "mkdir -p $REMOTE_DIR && cat > $REMOTE_DIR/vllm.sh && chmod +x $REMOTE_DIR/vllm.sh" \
            < "$AGENT_ROOT/serve/vllm.sh"
        echo "✓ 已同步 serve/vllm.sh -> $REMOTE_HOST:$REMOTE_DIR/"
        # 云端镜像里的 vLLM 可能不再接受提交脚本里的某些启动参数，那样服务根本起不来。
        # 2026-09-25 实测：vLLM 0.27.0 移除了 --disable-log-requests，报
        # "unrecognized arguments"。这里只在**远端副本**上把它剥掉，提交文件保持不变，
        # 因为改 serve/vllm.sh 属于提交层面的决定。见 dev/remote/README.md。
        if [ -n "${REMOTE_STRIP_ARGS:-}" ]; then
            for arg in $REMOTE_STRIP_ARGS; do
                rssh "cd $REMOTE_DIR && sed -i 's# $arg##g' vllm.sh"
            done
            echo "✓ 已在远端副本上剥离参数：$REMOTE_STRIP_ARGS（仓库里的 serve/vllm.sh 未改动）"
        fi
        rssh "cd $REMOTE_DIR && if $pid_alive; then echo '✓ vLLM 已在运行（进程号 '\$(cat vllm.pid)'）'; exit 0; fi
              # Redirect the whole group: with REMOTE_ACTIVATE the backgrounded
              # job is 'activate && vllm', and a redirect on vllm alone leaves
              # the job holding ssh's stdout -- ssh then never returns.
              # exec: the job's pid (\$! below) must be vLLM itself, not a shell
              # around it, or stop kills the shell and leaves vLLM running.
              { ${REMOTE_ACTIVATE:+$REMOTE_ACTIVATE &&} \
                exec env MODEL='$REMOTE_MODEL' PORT='$REMOTE_VLLM_PORT' MAX_LEN='${REMOTE_MAX_LEN:-32768}' \
                    GPU_UTIL='${REMOTE_GPU_UTIL:-0.90}' $REMOTE_EXTRA_ENV \
                    setsid nohup ./vllm.sh; } > vllm.log 2>&1 < /dev/null &
              echo \$! > vllm.pid
              echo \"✓ vLLM 已启动（进程号 \$(cat vllm.pid)），日志 $REMOTE_DIR/vllm.log\""
        echo "  加载模型需要一些时间，可以运行 ./remote_vllm.sh wait 等待"
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
        rssh "cd $REMOTE_DIR 2>/dev/null || { echo '✗ 远端目录不存在，请先运行 ./remote_vllm.sh start'; exit 1; }
              if $pid_alive; then echo \"✓ vLLM 正在运行（进程号 \$(cat vllm.pid)）\"; else echo '✗ vLLM 未运行'; fi
              echo '--- vllm.log 最后几行 ---'; tail -n 15 vllm.log 2>/dev/null"
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
              else echo 'vLLM 原本就没有运行'; fi; rm -f vllm.pid
              # Fallback: anything still serving this port (e.g. started by an
              # older version of this script, whose pid file named a shell).
              if pkill -f '[v]llm.entrypoints.openai.api_server.*--port $REMOTE_VLLM_PORT'; then
                  sleep 5; pkill -9 -f '[v]llm.entrypoints.openai.api_server.*--port $REMOTE_VLLM_PORT'
                  echo '✓ 已清理残留的 vLLM 进程'
              fi; true"
        ;;
    *)
        sed -n '2,9p' "$0"; exit 2 ;;
esac
