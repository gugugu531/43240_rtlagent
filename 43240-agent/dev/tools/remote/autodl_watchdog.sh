#!/usr/bin/env bash
# Arm an independent remote cutoff, including when the local network is lost.
set -eo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
duration="${1:-16800}"
if [ "$duration" = disarm ]; then
    # Non-interactive SSH may not include the image's Python on PATH.
    rssh "${REMOTE_ACTIVATE:+$REMOTE_ACTIVATE && }python3 -" <<'PY'
from pathlib import Path
import os
import signal
p = Path('/root/autodl-tmp/quick34-watchdog.pid')
if p.is_file():
    pid = int(p.read_text().strip())
    try:
        cmd = Path(f'/proc/{pid}/cmdline').read_bytes()
        if b'fpgachina-quick34-watchdog' in cmd:
            os.killpg(pid, signal.SIGTERM)
    except (FileNotFoundError, ProcessLookupError):
        pass
    p.unlink(missing_ok=True)
PY
    exit 0
fi
[[ "$duration" =~ ^[0-9]+$ ]] && [ "$duration" -gt 0 ] && [ "$duration" -le 16800 ] || exit 2
rssh "bash -s -- $duration $REMOTE_VLLM_PORT" <<'REMOTE'
set -eo pipefail
duration="$1"
port="$2"
mkdir -p /root/autodl-tmp/logs
setsid nohup bash -c '
    sleep "$1"
    date "+remote watchdog paused: %F %T %Z" > /root/autodl-tmp/deadline-paused.txt
    pkill -TERM -f "[v]llm.entrypoints.openai.api_server.*--port $2" || true
' fpgachina-quick34-watchdog "$duration" "$port" >/root/autodl-tmp/logs/quick34-watchdog.log 2>&1 < /dev/null &
echo $! > /root/autodl-tmp/quick34-watchdog.pid
date -d "+$duration seconds" '+remote cutoff: %F %T %Z'
REMOTE
