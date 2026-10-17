#!/usr/bin/env bash
# serve/start.sh -- bring up everything that has to stay resident, then return.
#
#   ./serve/start.sh            # returns 0 once every resident service is ready
#
# This is the one place resident processes are started, in both evaluation
# modes:
#
#   HTTP submission (primary)    the team runs this, then starts serve_api.py
#   container rebuild (fallback) the organisers run this once, then call
#                                run.sh / run_baseline.sh per task directly;
#                                serve_api.py is not started at all
#
# So anything run.sh depends on -- the inference service, and any resident
# engine of your own that run.sh talks to -- must be started here. A run.sh
# that only works after some manual step will not work in the fallback mode.
#
# The contract this script must keep:
#
#   * return 0 only when everything is ready to take a task, non-zero otherwise
#   * be idempotent: running it again while the services are up is a no-op
#   * detach every resident process into its own session (setsid). In the
#     fallback mode a timed-out run.sh is stopped by signalling its whole
#     process group; a resident process that shares that group would die with
#     the task. Started from here under setsid, it does not.
#
# Logs go to $SERVE_LOG_DIR (default $AGENT_TMP/serve-logs).
#
# Do not use `set -u` here, see docs/API_CONTRACT.md section 10.

set -eo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${SERVE_LOG_DIR:-${AGENT_TMP:-/tmp}/serve-logs}"
LLM_PORT="${PORT:-8000}"
START_TIMEOUT_S="${START_TIMEOUT_S:-900}"   # loading weights can take minutes

mkdir -p "$LOG_DIR"
# Serialize startup so simultaneous invocations cannot launch duplicate models.
exec 9>"$LOG_DIR/start.lock"
flock -x 9

# wait_ready <name> <url> <pid>: poll until <url> answers, the process dies, or
# the timeout runs out.
wait_ready() {
    local name="$1" url="$2" pid="$3" waited=0
    while ! curl --connect-timeout 1 --max-time 2 -sf -o /dev/null "$url"; do
        if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then
            echo "start.sh: $name exited during startup, see $LOG_DIR/$name.log" >&2
            tail -n 20 "$LOG_DIR/$name.log" >&2 || true
            return 1
        fi
        if [ "$waited" -ge "$START_TIMEOUT_S" ]; then
            echo "start.sh: $name not ready after ${START_TIMEOUT_S}s, see $LOG_DIR/$name.log" >&2
            return 1
        fi
        sleep 5
        waited=$((waited + 5))
    done
    echo "start.sh: $name ready ($url)" >&2
}

# --- inference service ------------------------------------------------------

LLM_URL="http://127.0.0.1:$LLM_PORT/v1/models"
if curl --connect-timeout 1 --max-time 2 -sf -o /dev/null "$LLM_URL"; then
    echo "start.sh: vllm already up on $LLM_PORT" >&2
else
    setsid "$HERE/vllm.sh" 9>&- >"$LOG_DIR/vllm.log" 2>&1 </dev/null &
    model_pid=$!
    if ! wait_ready vllm "$LLM_URL" "$model_pid"; then
        kill -TERM -- "-$model_pid" 2>/dev/null || true
        sleep 1
        kill -KILL -- "-$model_pid" 2>/dev/null || true
        wait "$model_pid" 2>/dev/null || true
        exit 1
    fi
fi

# --- /tmp/eda cleanup -------------------------------------------------------
#
# The image entrypoint (eda-entrypoint) runs this same loop, but Radeon Cloud
# replaces the container command with JupyterLab, so on the platform it may
# never have started. Start it here as well; flock keeps re-runs of this
# script from stacking copies, and running alongside the entrypoint's copy is
# harmless. Only directories whose whole subtree has been idle for two hours
# are removed, see docs/API_CONTRACT.md section 9.

EDA_TMP="${EDA_TMP:-/tmp/eda}"
mkdir -p "$EDA_TMP"
setsid flock -n "$EDA_TMP/.cleanup.lock" bash -c '
    while :; do
        for d in "$1"/*/; do
            [ -d "$d" ] || continue
            [ -n "$(find "$d" -mmin -120 -print -quit 2>/dev/null)" ] && continue
            rm -rf "$d"
        done
        sleep 600
    done' cleanup "$EDA_TMP" 9>&- >/dev/null 2>&1 </dev/null &
