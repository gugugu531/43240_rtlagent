#!/usr/bin/env bash
# serve/run_api.sh -- keep the submission API (serve_api.py) up.
#
#   ./serve/run_api.sh start     # start in the background, detached from this terminal
#   ./serve/run_api.sh stop      # stop the watchdog and the API
#   ./serve/run_api.sh status
#   ./serve/run_api.sh ui on|off|status
#   ./serve/run_api.sh mode submission|local
#
# Why it exists: Radeon Cloud's rc-tunnel probes 127.0.0.1:7860 every 10 s and
# revokes the tunnel after about a minute of failed probes. The public URL is
# then gone for good, and a restarted service does not get it back. So the API
# must never be down for long: this script restarts it within a couple of
# seconds whenever it exits, and runs under setsid so closing the terminal or
# notebook that started it does not take it down.
#
# Start serve/start.sh (the inference service) first, then this, then
# rc-tunnel expose. FPGACHINA_TOKEN and MODEL_NAME must be set in the
# environment, e.g. by `source /workspace/env.sh`.
# A local demo can use RTLAGENT_UI_TASKS and RTLAGENT_UI_OPERATOR_TOKEN.
#
# Do not use `set -u` here, see docs/API_CONTRACT.md section 10.

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -n "${AGENT_TMP:-}" && "$AGENT_TMP" != /* ]]; then
    export AGENT_TMP="$PWD/$AGENT_TMP"
fi
case "${1:-}" in
ui|mode)
    exec python3 "$HERE/ui_control.py" "$@"
    ;;
esac
PORT="${API_PORT:-7860}"
if ! [[ "$PORT" =~ ^0*([1-9][0-9]{0,4})$ ]] || (( BASH_REMATCH[1] > 65535 )); then
    echo "run_api.sh: invalid API_PORT" >&2
    exit 2
fi
PORT="${BASH_REMATCH[1]}"
STATE="${AGENT_TMP:-/var/tmp}/run_api"
if [ "$PORT" != "7860" ]; then
    STATE="$STATE-$PORT"
fi
PIDFILE="$STATE/run_api.pid"
CHILD_PIDFILE="$STATE/serve_api.pid"
LOG="$STATE/serve_api.log"
mkdir -p "$STATE"

running() { [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }
child_running() { [ -f "$CHILD_PIDFILE" ] && kill -0 "$(cat "$CHILD_PIDFILE")" 2>/dev/null; }

case "${1:-}" in
start)
    if running; then
        if child_running; then
            echo "run_api.sh: already running (pid $(cat "$PIDFILE")), log $LOG"
            exit 0
        fi
        echo "run_api.sh: watchdog running but API is recovering; see $LOG" >&2
        exit 1
    fi
    if [ -z "$FPGACHINA_TOKEN" ] && { [ -z "$RTLAGENT_UI_TASKS" ] || [ -z "$RTLAGENT_UI_OPERATOR_TOKEN" ]; }; then
        echo "run_api.sh: FPGACHINA_TOKEN is not set" >&2
        exit 1
    fi
    for dependency in setsid uvicorn; do
        command -v "$dependency" >/dev/null 2>&1 || {
            echo "run_api.sh: required executable not found: $dependency" >&2
            exit 1
        }
    done
    rm -f "$CHILD_PIDFILE"
    setsid "$0" _loop </dev/null >>"$LOG" 2>&1 &
    supervisor=$!
    for _ in 1 2 3 4 5; do
        sleep 1
        if running && child_running; then
            started_child="$(cat "$CHILD_PIDFILE")"
            sleep 1
            if running && child_running && [ "$(cat "$CHILD_PIDFILE")" = "$started_child" ]; then
                echo "run_api.sh: started (pid $(cat "$PIDFILE")), log $LOG"
                exit 0
            fi
        fi
    done
    kill "$supervisor" 2>/dev/null
    wait "$supervisor" 2>/dev/null
    echo "run_api.sh: API did not stay running; see $LOG" >&2
    exit 1
    ;;
_loop)
    echo $$ > "$PIDFILE"
    trap 'kill "$child" 2>/dev/null; wait "$child" 2>/dev/null; rm -f "$PIDFILE" "$CHILD_PIDFILE"; exit 0' TERM INT
    cd "$HERE/.."
    while :; do
        echo "$(date '+%F %T') run_api.sh: starting serve_api on 127.0.0.1:$PORT"
        uvicorn serve.serve_api:app --host 127.0.0.1 --port "$PORT" --workers 1 &
        child=$!
        echo "$child" > "$CHILD_PIDFILE"
        wait "$child"
        rc=$?
        rm -f "$CHILD_PIDFILE"
        echo "$(date '+%F %T') run_api.sh: serve_api exited (rc=$rc), restarting in 2 s"
        sleep 2
    done
    ;;
stop)
    if running; then
        kill "$(cat "$PIDFILE")"
        for _ in 1 2 3 4 5 6 7 8 9 10; do running || break; sleep 1; done
        echo "run_api.sh: stopped"
    else
        echo "run_api.sh: not running"
    fi
    ;;
status)
    if running && child_running; then echo "run_api.sh: running (pid $(cat "$PIDFILE")), log $LOG"
    else echo "run_api.sh: not running"; exit 1; fi
    ;;
*)
    echo "usage: $0 start|stop|status | ui on|off|status | mode submission|local" >&2
    exit 2
    ;;
esac
