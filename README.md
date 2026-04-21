# Coding Loop

Personal autonomous AI agent — a "staff member" that knows your life and offloads work.

Architecture: hardened Docker container talks to a host-side `claude-bridge` that mediates all calls to Claude via your Claude Code OAuth session (macOS Keychain).

See `docs/ARCHITECTURE.md` for the full design and `docs/PHASES.md` for the rollout plan.

## Quick start (macOS, once)

```bash
# 1. Install Claude Code, log in (OAuth -> Keychain)
# 2. Install Orbstack (https://orbstack.dev)
# 3. Set up the bridge
cd claude-bridge
uv sync
cp config.example.toml config.toml  # edit with your Telegram token, user ID, budget
launchctl load launchd/com.nathan.claude-bridge.plist

# 4. Build + run the agent container
docker compose up -d
```

## Testing

```bash
# Bridge unit + integration tests (mocked)
cd claude-bridge && uv run pytest

# Agent unit + integration tests (mocked)
cd agent && uv run pytest

# Full repo test
./scripts/test-all.sh
```

## Safety

This agent is self-editing and runs autonomously. See `docs/SECURITY.md` for the threat model and invariants. Kill switch: `touch ~/.claude-bridge/pause`.
