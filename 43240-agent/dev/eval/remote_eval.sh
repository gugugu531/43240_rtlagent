#!/usr/bin/env bash
# run_eval.py against the remote inference service.
#
#   ./remote_eval.sh [run_eval.py options...]
#   ./remote_eval.sh --tag veval-s1 --jobs 8
#
# Brings the SSH tunnel up if needed and points agent AND baseline at the
# remote model (dev/remote/_common.sh), then runs run_eval.py. Unlike
# remote_selftest.sh, selftest/env.sh is not read, so it cannot override them.

set -eo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/../remote/_common.sh"

"$REMOTE_HERE/tunnel.sh" status >/dev/null 2>&1 || "$REMOTE_HERE/tunnel.sh" up
export_llm_env
exec python3 "$DEV_ROOT/eval/run_eval.py" "$@"
