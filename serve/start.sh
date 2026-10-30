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
# Do not use `set -u` here; see serve/README.md for the offline-script constraints.

set -eo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${SERVE_LOG_DIR:-${AGENT_TMP:-/var/tmp}/serve-logs}"
LLM_PORT="${PORT:-8000}"
MODEL_NAME="${MODEL_NAME:-qwen38-27b-q4-k-m}"
START_TIMEOUT_S="${START_TIMEOUT_S:-900}"   # loading weights can take minutes

mkdir -p "$LOG_DIR"

# wait_ready <name> <url> <pid>: poll until <url> answers, the process dies, or
# the timeout runs out.
wait_ready() {
    local name="$1" url="$2" pid="$3" waited=0
    while ! curl --noproxy '*' --connect-timeout 2 --max-time 3 -sf -o /dev/null "$url"; do
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

# --- /tmp/eda cleanup -------------------------------------------------------
#
# The image entrypoint (eda-entrypoint) runs this same loop, but Radeon Cloud
# replaces the container command with JupyterLab, so on the platform it may
# never have started. Start it here as well; flock keeps re-runs of this
# script from stacking copies, and running alongside the entrypoint's copy is
# harmless. Only directories whose whole subtree has been idle for two hours
# are removed; see serve/README.md for the process-group cleanup contract.

EDA_TMP="${EDA_TMP:-/var/tmp/eda}"
mkdir -p "$EDA_TMP"
setsid flock -n "$EDA_TMP/.cleanup.lock" bash -c '
    while :; do
        for d in "$1"/*/; do
            [ -d "$d" ] || continue
            [ -n "$(find "$d" -mmin -120 -print -quit 2>/dev/null)" ] && continue
            rm -rf "$d"
        done
        sleep 600
    done' cleanup "$EDA_TMP" >/dev/null 2>&1 </dev/null &

# --- inference service ------------------------------------------------------

LLM_URL="http://127.0.0.1:$LLM_PORT/health"
if curl --noproxy '*' --connect-timeout 2 --max-time 3 -sf -o /dev/null "$LLM_URL"; then
    echo "start.sh: llama.cpp already up on $LLM_PORT" >&2
else
    setsid "$HERE/llamacpp.sh" >"$LOG_DIR/llamacpp.log" 2>&1 </dev/null &
    wait_ready llamacpp "$LLM_URL" "$!"
fi

# A healthy process on this port may serve a different model. Do not silently
# reuse it as the declared inference service (API contract sections 2 and 8).
curl --noproxy '*' --connect-timeout 2 --max-time 3 -sf "http://127.0.0.1:$LLM_PORT/v1/models" |
    python3 -c 'import json,sys; data=json.load(sys.stdin); sys.exit(0 if any(item.get("id") == sys.argv[1] for item in data.get("data", [])) else "start.sh: model alias does not match MODEL_NAME")' "$MODEL_NAME"

# The default guided workflow routes every stage to the primary model.
# Research-only small services must be started explicitly via start_verireason.sh;
# a leftover VERI_GGUF variable must not load another model on the default path.

# --- your own resident processes -------------------------------------------
#
# If run.sh hands tasks to a resident engine instead of solving them itself,
# start that engine here, the same way: check whether it is already up,
# otherwise `setsid ... &` and wait_ready on its health URL.
