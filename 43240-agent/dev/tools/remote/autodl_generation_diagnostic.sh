#!/usr/bin/env bash
# Authorized frozen generation sweep, optionally continuing cancelled samples.
set -eo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
session="$1"
diagnostic_tool="$AGENT_ROOT/dev/tools/generation_sweep.py"
if [ "${2:-}" = --resume ]; then
    diagnostic_tool="$AGENT_ROOT/dev/tools/generation_resume.py"
elif [ -n "${2:-}" ]; then
    echo '未知诊断启动选项' >&2; exit 2
fi
[ -f "$session/state.json" ] || { echo '需要已准备的实验会话目录' >&2; exit 2; }
# Tool path is supplied by the caller; do not alter model prompts or budgets.
[ -n "${DIAGNOSTIC_VIVADO_SETTINGS:-}" ] || { echo '缺少 Vivado settings64.sh 路径' >&2; exit 2; }
. "$DIAGNOSTIC_VIVADO_SETTINGS"
cleanup() {
    local rc=$?
    trap - EXIT
    set +e
    bash "$REMOTE_HERE/remote_vllm.sh" stop
    if rssh -o BatchMode=yes -o ConnectTimeout=10 "! pgrep -f '[v]llm.entrypoints.openai.api_server.*--port $REMOTE_VLLM_PORT'"; then
        bash "$REMOTE_HERE/autodl_watchdog.sh" disarm
    fi
    bash "$REMOTE_HERE/tunnel.sh" down
    systemctl --user stop fpgachina-autodl-cutoff.timer fpgachina-autodl-warning.timer
    systemctl --user stop fpgachina-autodl-inhibit.service
    date '+diagnostic session finished: %F %T %Z'
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT TERM
python3 "$diagnostic_tool" verify "$session"
# Read-only environment and weight fingerprint, before allocating GPU memory.
rssh "${REMOTE_ACTIVATE:+$REMOTE_ACTIVATE && }python3 - '$REMOTE_MODEL'" <<'PY' | python3 "$AGENT_ROOT/dev/tools/generation_sweep.py" environment "$session"
from pathlib import Path
import hashlib
import json
import platform
import subprocess
import sys
import torch
import vllm
p = Path(sys.argv[1])
names = sorted(p.glob('*.safetensors')) + [p/'config.json', p/'generation_config.json', p/'tokenizer_config.json', p/'tokenizer.json']
hashes = {}
for path in names:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(8*1024*1024), b''):
            h.update(block)
    hashes[path.name] = h.hexdigest()
print(json.dumps(dict(python=platform.python_version(), torch=torch.__version__, vllm=vllm.__version__,
    model_path=str(p), hashes=hashes,
    gpu=subprocess.check_output(['nvidia-smi','--query-gpu=name,driver_version,memory.total,memory.used','--format=csv,noheader'], text=True).strip())))
PY
# No whole-session cap unless explicitly requested; remove stale protections.
bash "$REMOTE_HERE/autodl_session_limit.sh"
rssh "cd $REMOTE_DIR && if [ -f vllm.log ]; then cp vllm.log vllm.previous-\$(date +%Y%m%d-%H%M%S).log; fi"
bash "$REMOTE_HERE/remote_vllm.sh" start
cd "$AGENT_ROOT"
python3 "$diagnostic_tool" run "$session"
