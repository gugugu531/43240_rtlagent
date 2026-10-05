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
# The contract is: never fail loudly. "Could not solve it" and "the service is
# broken" must stay distinguishable at the protocol level, so a failed run still
# produces an empty solution.v and exits 0.

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

mkdir -p "$OUT"

cd "$HERE"
# Create protocol files before starting the supervised process.
[ -f "$OUT/solution.v" ] || : > "$OUT/solution.v"
[ -f "$OUT/trace.jsonl" ] || : > "$OUT/trace.jsonl"

stop_agent() {
    kill -TERM "$agent_pid" 2>/dev/null || true
    wait "$agent_pid" || true
    exit 0
}

rc=0
python3 -m agent.main --input "$IN" --output "$OUT" &
agent_pid=$!
trap stop_agent TERM INT
wait "$agent_pid" || rc=$?
trap - TERM INT

if [ $rc -ne 0 ]; then
    echo "run.sh: agent exited with $rc, emitted empty solution" >&2
fi
exit 0
