#!/usr/bin/env bash
set -eo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
notify-send 'AutoDL 实验已到保护截止时间' '正在暂停实验并关闭 vLLM；请检查 AutoDL 网页计费状态。' || true
systemctl --user stop fpgachina-autodl-experiment.service || true
bash "$REMOTE_HERE/remote_vllm.sh" stop || true
bash "$REMOTE_HERE/tunnel.sh" down || true
systemctl --user stop fpgachina-autodl-inhibit.service || true
date '+local cutoff finished: %F %T %Z'
