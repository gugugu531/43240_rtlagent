#!/usr/bin/env bash
# Run the authorized smoke + quick-34 session, then release GPU memory.
set -eo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
cleanup() {
    local rc=$?
    trap - EXIT
    set +e
    bash "$REMOTE_HERE/remote_vllm.sh" stop
    # Keep the remote cutoff armed if the stop could not reach the host.
    if rssh "! pgrep -f '[v]llm.entrypoints.openai.api_server.*--port $REMOTE_VLLM_PORT'"; then
        bash "$REMOTE_HERE/autodl_watchdog.sh" disarm
    fi
    bash "$REMOTE_HERE/tunnel.sh" down
    systemctl --user stop fpgachina-autodl-cutoff.timer fpgachina-autodl-warning.timer
    systemctl --user stop fpgachina-autodl-inhibit.service
    date '+session finished: %F %T %Z'
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT TERM
bash "$REMOTE_HERE/autodl_session_limit.sh"
rssh "cd $REMOTE_DIR && if [ -f vllm.log ]; then cp vllm.log vllm.previous-\$(date +%Y%m%d-%H%M%S).log; fi"
bash "$REMOTE_HERE/remote_vllm.sh" start
bash "$REMOTE_HERE/tunnel.sh" up
bash "$REMOTE_HERE/remote_vllm.sh" wait
export_llm_env
cd "$AGENT_ROOT"
smoke_output=$(python3 dev/tools/run.py --config dev/configs/remote-smoke.yaml \
    --workflow evidence_repair --solve-jobs 1 --metric-jobs 1 \
    --tag autodl-qwen3-8b-a-fixed-smoke)
printf '%s\n' "$smoke_output"
smoke_dir="${smoke_output%%$'\n'*}"
python3 - "$smoke_dir" <<'PY'
import json
from pathlib import Path
import sys
summary = json.loads((Path(sys.argv[1])/'summary.json').read_text())
assert summary['comparison']['full_comparison_valid'], 'smoke infrastructure failed'
assert all(mode['judge']['set_score'] == 1 for mode in summary['modes'].values()), 'smoke did not reach L3'
print('smoke passed: both modes L3; starting complete quick-34', flush=True)
PY
python3 dev/tools/run.py --config dev/configs/joint-quick.yaml \
    --workflow evidence_repair --modes agent baseline --samples 1 \
    --solve-jobs 1 --metric-jobs 1 --tag autodl-qwen3-8b-a-fixed-quick34
