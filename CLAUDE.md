# CLAUDE.md

Guidelines for any Claude instance (interactive or via this agent) working in this repo.
Adapted from andrej-karpathy-skills.

## Core principles

**1. Think before coding.** State assumptions explicitly. If a request is ambiguous, enumerate interpretations and pick one (or ask). Don't silently guess.

**2. Simplicity first.** Solve what was asked, nothing more. No speculative features, no premature abstractions, no "while we're in here" refactors.

**3. Surgical changes.** Touch only code related to the request. Preserve existing style. If you see unrelated issues, note them — don't fix them unless asked.

**4. Goal-driven execution.** Translate vague goals into verifiable criteria. Prefer test-first: write the failing test, then make it pass.

## Repo-specific rules

- **Safety files are off-limits.** Anything under `safety/`, `claude-bridge/src/bridge/{budget,policy,audit,approval}.py`, or this file requires human approval to modify. Never edit these autonomously.
- **No network calls in tests.** Mock Anthropic, Telegram, and any other external service.
- **Never commit secrets.** `.env`, tokens, OAuth blobs — reject edits that would stage these.
- **Short comments only.** Explain *why* if non-obvious. Don't narrate *what*.
- **Don't invent features.** The phase docs (`docs/PHASES.md`) define scope per phase.
