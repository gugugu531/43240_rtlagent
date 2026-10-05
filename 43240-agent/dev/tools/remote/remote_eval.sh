#!/usr/bin/env bash
# 连接远端模型服务，再调用统一实验入口。
# 用法：remote_eval.sh --config dev/configs/remote-smoke.yaml [run.py 参数]
set -eo pipefail
if [ "${1:-}" = --help ] || [ "${1:-}" = -h ]; then
    sed -n '2,3p' "$0"
    exit 0
fi
. "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
"$REMOTE_HERE/tunnel.sh" status >/dev/null 2>&1 || "$REMOTE_HERE/tunnel.sh" up
export_llm_env
exec python3 "$DEV_ROOT/tools/run.py" "$@"
