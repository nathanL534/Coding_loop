#!/usr/bin/env bash
# Emergency kill: stop the agent container, activate bridge kill-switch.
set -euo pipefail

STATE_DIR="${STATE_DIR:-$HOME/.claude-bridge}"
mkdir -p "$STATE_DIR"
touch "$STATE_DIR/pause"
echo "kill-switch flag set at $STATE_DIR/pause"

if docker ps -q -f name=coding-loop-agent | grep -q .; then
    docker kill coding-loop-agent || true
    echo "container killed"
else
    echo "container not running"
fi
