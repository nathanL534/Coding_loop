# Phases

Each phase has explicit exit criteria and tests. Do not advance until criteria met.

## Phase 1 — It can hear me and answer

**Goal**: You can DM the Telegram bot; it replies with a real Claude response routed through the bridge.

- [x] Bridge `/v1/complete` endpoint on Unix socket
- [x] Bridge spawns `claude -p` subprocess, streams JSON back
- [x] Budget enforcement (daily cap) in bridge
- [x] Append-only audit log
- [x] Rate limiter
- [x] Kill-switch file check on every request
- [x] Telegram bot on bridge (inbound: dispatch to container via queue; outbound: `/v1/notify` endpoint)
- [x] Agent container skeleton; `bridge_client` sends completion requests over socket
- [x] Dockerfile + docker-compose; container hardening (read-only FS, non-root, caps dropped)
- [x] Unit tests: budget, rate limit, policy, audit
- [x] Integration tests: bridge endpoints (mocked claude subprocess), end-to-end via test client

**Exit**: tests green; manual smoke test: "hello" → response in Telegram.

## Phase 2 — It remembers me

- [ ] Memory store (SQLite + FTS5) with L0–L4 layers
- [ ] Bootstrap script for L2 (profile intake)
- [ ] Trust-level tagging on every memory entry
- [ ] Memory retrieval: router (L1) → targeted lookup
- [ ] Research skill (web fetch + synthesize)
- [ ] Prompt-injection defense: untrusted-source content never enters system prompt
- [ ] Tests: memory CRUD, trust-level enforcement, retrieval correctness

**Exit**: ask agent about yourself across a restart, get correct answer. Tests green.

## Phase 3 — It shows up on its own

- [ ] Heartbeat entrypoint (cron-triggered in container)
- [ ] `state.json` resume pointer; crash-safe
- [ ] Differentiated cadence (1h awake / 4h night / event-driven)
- [ ] Morning brief (8am) + evening wrap (10pm) skills
- [ ] Dry-run mode (logs planned actions, doesn't execute)
- [ ] Per-wake budget cap (bridge-enforced)
- [ ] Tests: heartbeat execution paths, state persistence, dry-run mode

**Exit**: 3 days of dry-run without anomalies; tests green.

## Phase 4 — It handles inbox

- [ ] Google OAuth flow (host-side, scoped read-only first)
- [ ] Gmail MCP or direct API integration (read + draft-only, no send)
- [ ] Google Calendar integration (read)
- [ ] Draft-for-approval workflow via Telegram
- [ ] Tests: mocked Google API, draft-approval state machine

**Exit**: agent can summarize inbox + draft reply to your approval. Tests green.

## Phase 5 — It learns

- [ ] Evolver install + config (`--review` mode)
- [ ] Correction-tracking: log diffs when user edits agent output
- [ ] Weekly self-edit proposal workflow (Telegram approval)
- [ ] Protected-files manifest + hash check in bridge
- [ ] Tests: proposed-diff dry-run, protected-file refusal

**Exit**: first self-edit proposed, approved, merged, observed behavior change. Tests green.

## Phase 6 — It does web things

- [ ] Dedicated browser profile (separate accounts, prepaid card)
- [ ] Browser driver (Playwright) in isolated sub-container
- [ ] Per-action approval for POSTs/form submits
- [ ] Screenshot attached to every approval request
- [ ] Tests: mocked Playwright, approval state machine

**Exit**: one real end-to-end transaction under approval. Tests green.

## Phase 7 — Mostly autonomous

- [ ] Loosen allowlists based on trust history
- [ ] Evolver `--loop` for non-safety paths
- [ ] Weekly metrics digest
- [ ] Quarterly memory audit

No hard exit criteria — ongoing tuning.
