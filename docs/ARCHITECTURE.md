# Architecture

## Trust boundary

```
+------------------------------------------------------------+
|  macOS host (TRUSTED)                                      |
|                                                            |
|   Keychain (OAuth refresh token)                           |
|         ^                                                  |
|         |                                                  |
|   claude-bridge (launchd, Python/FastAPI, Unix socket)     |
|     - spawns `claude -p ...` subprocess per request        |
|     - enforces budget / rate limit / allowlists            |
|     - owns Telegram bot token                              |
|     - pushes approvals to user, accepts yes/no             |
|     - append-only audit log                                |
|                                                            |
+------------------------ socket ----------------------------+
                              |
+------------------------------------------------------------+
|  Orbstack Linux VM -> agent container (UNTRUSTED)          |
|                                                            |
|   hermes-core loop + memory + skills + evolver             |
|   mounts /run/claude-bridge.sock (RW)                      |
|   mounts /safety (RO) <-- hashed allowlists, kill-switch   |
|   mounts /goals.md (RO) <-- user-edited intents            |
|                                                            |
|   egress firewall: Anthropic API is NOT reachable directly |
|     (bridge is the only Claude path). Telegram/git only    |
|     through host-mediated endpoints.                       |
+------------------------------------------------------------+
```

## Why a bridge

Self-edit + autonomous = the container's code path to Claude is mutable. Putting Claude on the host side means evolver cannot rewrite the budget/tool-allowlist/kill-switch logic — it's baked into an immutable policy-enforcement point that evolver has no write access to.

See `docs/SECURITY.md` for the complete threat model.

## Memory layers (L0–L4)

- **L0** — immutable behavioral rules (e.g. CLAUDE.md, safety contracts). Never mutated by the agent.
- **L1** — memory routing index. Cheap lookup: "for X, look in L2.people or L3.skills."
- **L2** — long-term stable facts about Nathan (school, job, prefs).
- **L3** — reusable task skills / SOPs, crystallized after repeated success.
- **L4** — session archives for long-horizon recall; full-text + vector search.

The agent retrieves narrowly (L1 → targeted L2/L3/L4 lookup) to keep context compact.

## Phases

See `docs/PHASES.md`.
