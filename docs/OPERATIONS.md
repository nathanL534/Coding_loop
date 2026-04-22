# Operations

## Install (Mac mini, once)

```bash
# 1. Prereqs
brew install --cask orbstack
brew install uv
# Install Claude Code per Anthropic docs, complete OAuth flow

# 2. Clone this repo (Mac mini)
git clone <your-private-remote> ~/Coding_loop
cd ~/Coding_loop

# 3. Run setup
./scripts/setup-macos.sh

# 4. Configure
cp claude-bridge/config.example.toml claude-bridge/config.toml
# Edit: telegram.bot_token, telegram.allowed_user_id
# Edit: openai.api_key  (optional -- enables Whisper + TTS voice notes)
# Edit: safety/goals.md with your profile

# 5. Start
cp claude-bridge/launchd/com.nathan.claude-bridge.plist ~/Library/LaunchAgents/
# Edit the plist first to match your actual paths
launchctl load ~/Library/LaunchAgents/com.nathan.claude-bridge.plist
docker compose up -d

# 6. Schedule heartbeats
crontab -e
# Add the lines from scripts/heartbeat.sh header
```

## Everyday commands

| What | Command |
|------|---------|
| Status | `docker ps`, `launchctl list \| grep claude-bridge` |
| Bridge logs | `tail -f ~/Library/Logs/claude-bridge.out.log` |
| Audit log | `tail -f ~/.claude-bridge/audit.log` |
| Budget | `curl --unix-socket /tmp/claude-bridge.sock http://bridge/v1/budget` |
| Container logs | `docker logs -f coding-loop-agent` |
| One heartbeat | `./scripts/heartbeat.sh` |
| Dry-run heartbeat | `AGENT_DRY_RUN=1 ./scripts/heartbeat.sh` |
| **Kill everything** | `./scripts/kill.sh` |
| Clear kill | `rm ~/.claude-bridge/pause` |
| Update manifest after intentional safety edit | `cd claude-bridge && uv run python -m bridge.manifest generate $(pwd)/..` |

## Deployment checklist

Before flipping the hourly cron to real (non-dry) mode:

- [ ] Config files filled (telegram token, user id, goals)
- [ ] `safety/manifest.sha256` committed after your edits
- [ ] `docker compose ps` shows the container healthy
- [ ] `/v1/health` returns `ok=true`
- [ ] A manual `./scripts/heartbeat.sh` succeeds
- [ ] A Telegram message round-trips end-to-end
- [ ] 3 days of `AGENT_DRY_RUN=1` heartbeats with no anomalies

## Daily routine

- Morning: check the brief you received at 08:00
- Anytime: text the bot with tasks
- Evening: check the wrap at 22:00
- Weekly: `tail ~/.claude-bridge/audit.log | wc -l`; prune memory if disk growing

## Voice notes

- **Enable**: set `openai.api_key` in `config.toml`. Leave empty to disable.
- **Inbound**: send a voice note in Telegram; bridge auto-transcribes (Whisper) and routes to the agent. You'll see the transcribed text as the agent's context.
- **Outbound**: if the agent receives a voice note, it replies as a voice note (OpenAI TTS `nova` by default). Typed messages get typed replies.
- **Cost**: Whisper $0.006/min + TTS `tts-1-hd` $30/1M chars. Realistic: ~$1–3/month at moderate use, charged against the same `daily_usd_cap`.
- **Voice override**: edit `openai.tts_voice` in `config.toml` (`nova | shimmer | onyx | echo | fable | alloy`) or switch to `tts-1` for cheaper output.

## Known failure modes

- **Bridge OAuth expired.** Symptom: every `/v1/complete` returns 502. Fix: open Claude Code on host, re-auth, `launchctl kickstart -k gui/$(id -u)/com.nathan.claude-bridge`.
- **Container can't reach socket.** Symptom: container `BridgeUnavailable`. Fix: ensure the host socket exists (`ls /tmp/claude-bridge.sock`) and compose re-mounts it. Restart container.
- **FileVault reboot locks.** Symptom: agent silent for hours after macOS update reboot. Fix: `fdesetup authrestart` for planned restarts, or disable FileVault.
- **Manifest mismatch.** Symptom: bridge returns 403 with "manifest mismatch." Fix: audit the diff, if legitimate regenerate the manifest.

## Upgrade procedure

1. `git pull` on Mac mini
2. `cd claude-bridge && uv pip install -e ".[dev]"` (if deps changed)
3. `launchctl kickstart -k gui/$(id -u)/com.nathan.claude-bridge`
4. `docker compose build && docker compose up -d`
5. `./scripts/test-all.sh`
6. Check audit log for any abnormal patterns from the last wake
