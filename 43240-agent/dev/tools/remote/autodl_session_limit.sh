#!/usr/bin/env bash
# Optional whole-session cap. Per-request / per-task budgets are independent.
set -eo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
duration="${AUTODL_SESSION_LIMIT_S:-0}"
[[ "$duration" =~ ^[0-9]+$ ]] || { echo 'AUTODL_SESSION_LIMIT_S 必须为非负整数' >&2; exit 2; }
systemctl --user stop fpgachina-autodl-cutoff.timer fpgachina-autodl-warning.timer 2>/dev/null || true
bash "$REMOTE_HERE/autodl_watchdog.sh" disarm
if [ "$duration" -gt 0 ]; then
    bash "$REMOTE_HERE/autodl_watchdog.sh" "$duration"
else
    echo '整轮实验无固定时长截止；保留单题预算和退出清理'
fi
