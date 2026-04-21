#!/usr/bin/env bash
# Run both test suites. Assumes uv is installed and venvs exist.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT/claude-bridge"
uv run pytest "$@"
cd "$REPO_ROOT/agent"
uv run pytest "$@"
echo "All tests passed."
