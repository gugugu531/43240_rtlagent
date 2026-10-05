#!/usr/bin/env bash
# One relayed connection for tunnel.sh relay mode: socat runs this per accepted
# connection with the connection on stdin/stdout, and it pipes that through a
# plain ssh session to 127.0.0.1:$REMOTE_VLLM_PORT on the remote (bash
# /dev/tcp), because the remote sshd refuses port forwarding.

. "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
# shellcheck disable=SC2086
exec ssh -p "$REMOTE_SSH_PORT" $REMOTE_SSH_OPTS -o BatchMode=yes -o ControlPath=none \
    "$REMOTE_HOST" \
    "bash -c 'exec 3<>/dev/tcp/127.0.0.1/$REMOTE_VLLM_PORT; cat <&3 & cat >&3; wait'"
