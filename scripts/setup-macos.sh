#!/usr/bin/env bash
# One-shot macOS setup helper. Idempotent; safe to re-run.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "1) checking required tools..."
need() { command -v "$1" >/dev/null 2>&1 || { echo "missing: $1"; exit 1; }; }
need uv
need docker
need claude

echo "2) setting up bridge venv..."
cd "$REPO_ROOT/claude-bridge"
uv venv >/dev/null 2>&1 || true
uv pip install -e ".[dev]" >/dev/null

echo "3) setting up agent venv (for local tests only)..."
cd "$REPO_ROOT/agent"
uv venv >/dev/null 2>&1 || true
uv pip install -e ".[dev]" >/dev/null

echo "4) creating state dir..."
mkdir -p "$HOME/.claude-bridge"
chmod 700 "$HOME/.claude-bridge"

echo "5) generating protected-files manifest..."
cd "$REPO_ROOT/claude-bridge"
uv run python -m bridge.manifest generate "$REPO_ROOT"

echo
echo "remaining manual steps:"
echo "  - copy claude-bridge/config.example.toml -> config.toml and fill in Telegram token + user id"
echo "  - edit safety/goals.md with your profile"
echo "  - copy claude-bridge/launchd/com.nathan.claude-bridge.plist -> ~/Library/LaunchAgents/"
echo "  - launchctl load ~/Library/LaunchAgents/com.nathan.claude-bridge.plist"
echo "  - docker compose up -d"
