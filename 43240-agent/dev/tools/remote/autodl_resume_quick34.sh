#!/usr/bin/env bash
# Continue only the five interrupted tasks; keep the original run immutable.
set -eo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
cd "$AGENT_ROOT"
python3 - <<'PY'
from pathlib import Path
import hashlib
import json
from agent.core.configuration import load_config, resolve_config
from dev.tools.experiment import parse_experiment, select_tasks, build_sample_plan
prior = Path('dev/runs/20261012-225403-autodl-qwen3-8b-a-fixed-quick34-460c1d2a')
manifest = json.loads((prior/'source/manifest.json').read_text())
# Only the development cutoff interpreter fix differs from the original source.
allowed = {'dev/tools/remote/autodl_watchdog.sh'}
for entry in manifest['files']:
    p = Path(entry['path'])
    if str(p) not in allowed:
        assert p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest() == entry['sha256'], str(p)
config = resolve_config(load_config(Path('dev/configs/quick34-remaining-20261013.yaml')), env={})
experiment = parse_experiment(config)
tasks = select_tasks(experiment.selection)
plan = build_sample_plan(tasks, experiment)
pending = set()
for p in prior.glob('samples/*/*/s0/solve.json'):
    if json.loads(p.read_text())['status'] == 'cancelled':
        pending.add((p.parent.parts[-3], p.parent.parts[-2]))
assert len(plan) == 10 and {(s.mode, s.task['task_id']) for s in plan} == pending
print('resume preflight: original source unchanged; exactly 10 interrupted samples', flush=True)
PY
cleanup() {
    local rc=$?
    trap - EXIT
    set +e
    bash "$REMOTE_HERE/remote_vllm.sh" stop
    if rssh "! pgrep -f '[v]llm.entrypoints.openai.api_server.*--port $REMOTE_VLLM_PORT'"; then
        bash "$REMOTE_HERE/autodl_watchdog.sh" disarm
    fi
    bash "$REMOTE_HERE/tunnel.sh" down
    systemctl --user stop fpgachina-autodl-cutoff.timer fpgachina-autodl-warning.timer
    systemctl --user stop fpgachina-autodl-inhibit.service
    date '+resume session finished: %F %T %Z'
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
python3 dev/tools/run.py --config dev/configs/quick34-remaining-20261013.yaml
