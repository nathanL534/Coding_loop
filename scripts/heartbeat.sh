#!/usr/bin/env bash
# Cron-invoked wake. Runs a single heartbeat pass inside the agent container.
#
# Install via `crontab -e`:
#   # awake hours
#   0  7-23 * * * /Users/nathan/Coding_loop/scripts/heartbeat.sh
#   # quiet hours (every 4h)
#   0  0,4  * * * /Users/nathan/Coding_loop/scripts/heartbeat.sh
set -euo pipefail

# Require the container to be running.
if ! docker ps -q -f name=coding-loop-agent | grep -q .; then
    echo "agent container not running; exiting" >&2
    exit 0
fi

docker exec \
    -e AGENT_MODE=heartbeat \
    -e AGENT_DRY_RUN="${AGENT_DRY_RUN:-0}" \
    coding-loop-agent \
    python -m agent.main
