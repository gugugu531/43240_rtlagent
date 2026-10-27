#!/usr/bin/env bash
# run.sh <input_dir> <output_dir>
#
#   <input_dir>/prompt.txt      task statement
#   <input_dir>/interface.txt   not provided by the evaluation task set -- the
#                               module interface is in prompt.txt
#
#   <output_dir>/solution.v   generated Verilog/SystemVerilog (empty file if we failed)
#   <output_dir>/trace.jsonl    one JSON object per tool / model call
#
# Exit code follows docs/API_CONTRACT.md section 8: 0 when solution.v contains
# an answer, non-zero when the task was given up. "Could not solve it" still
# leaves an empty solution.v so the service can distinguish it from a crash.

set -eo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IN="${1:?usage: run.sh <input_dir> <output_dir>}"
OUT="${2:?usage: run.sh <input_dir> <output_dir>}"

# The script changes to its own directory before importing agent. Preserve the
# caller's meaning for relative task/output paths before doing that.
case "$IN" in
    /*) ;;
    *) IN="$PWD/$IN" ;;
esac
case "$OUT" in
    /*) ;;
    *) OUT="$PWD/$OUT" ;;
esac

# This development branch defaults to adaptive_verify. An explicit
# AGENT_CONFIG still wins, and the sealed main branch keeps single_generate
# until this refactor is merged.
if [ -z "${AGENT_CONFIG:-}" ]; then
    # The default belongs to this checkout, not to the caller's directory.
    AGENT_CONFIG="$HERE/config/adaptive_verify.yaml"
else
    # A user-supplied relative path keeps the caller's meaning.
    case "$AGENT_CONFIG" in /*) ;; *) AGENT_CONFIG="$PWD/$AGENT_CONFIG" ;; esac
fi
export AGENT_CONFIG
export AGENT_CALLER_CWD="$PWD"
mkdir -p "$OUT"

cd "$HERE"
# Create protocol files before starting the Burr application.
[ -f "$OUT/solution.v" ] || : > "$OUT/solution.v"
[ -f "$OUT/trace.jsonl" ] || : > "$OUT/trace.jsonl"

answer_ready() {
    # A whitespace-only file is not an answer; the contract counts content.
    [ -s "$OUT/solution.v" ] || return 1
    [ -n "$(tr -d '[:space:]' < "$OUT/solution.v")" ]
}

stop_agent() {
    kill -TERM "$agent_pid" 2>/dev/null || true
    wait "$agent_pid" || true
    if answer_ready; then exit 0; else exit 1; fi
}

rc=0
python3 -m agent.main --input "$IN" --output "$OUT" "${@:3}" &
agent_pid=$!
trap stop_agent TERM INT
wait "$agent_pid" || rc=$?
trap - TERM INT

if [ $rc -ne 0 ]; then
    echo "run.sh: agent exited with $rc, preserved the last saved solution" >&2
fi
if answer_ready; then
    exit 0
fi
echo "run.sh: no answer produced" >&2
exit 1
