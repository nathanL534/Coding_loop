"""Hourly-ish wake loop. Single-shot: exits after one pass.

Triggered by a launchd-scheduled `docker exec` on the Mac mini, or equivalent.

Cadence (enforced by the caller, not us):
- 1h during awake hours (07:00-24:00 local)
- 4h during quiet hours (00:00-07:00 local)  — lighter work only
- Event-driven: morning brief at 08:00, evening wrap at 22:00

This module only handles "what to do in one wake." Scheduling lives in cron/launchd.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .bridge_client import BridgeClient, BridgeUnavailable
from .state import AgentState, load, save
from .tasks import TaskQueue, TaskStatus

log = logging.getLogger("heartbeat")


@dataclass
class HeartbeatResult:
    wake_kind: str
    tasks_processed: int
    messages_handled: int
    briefings_sent: int
    aborted: str | None = None   # reason for early exit


def classify_wake(now: datetime) -> str:
    h = now.hour
    if h == 8:
        return "morning-brief"
    if h == 22:
        return "evening-wrap"
    if 0 <= h < 7:
        return "quiet"
    return "awake"


async def run_once(
    *,
    bridge: BridgeClient,
    tasks: TaskQueue,
    state_path: Path,
    dry_run: bool,
    now: datetime | None = None,
) -> HeartbeatResult:
    now = now or datetime.now()
    kind = classify_wake(now)
    log.info("heartbeat start: kind=%s dry_run=%s", kind, dry_run)

    # Per-wake budget reset is a bridge concern; we poke /v1/budget to check.
    try:
        h = await bridge.health()
    except BridgeUnavailable as e:
        return HeartbeatResult(wake_kind=kind, tasks_processed=0, messages_handled=0, briefings_sent=0, aborted=f"bridge: {e}")
    if h.get("kill_switch"):
        return HeartbeatResult(wake_kind=kind, tasks_processed=0, messages_handled=0, briefings_sent=0, aborted="kill_switch")

    messages_handled = 0
    # Drain user messages that arrived since last wake (short poll).
    while True:
        msg = await bridge.inbox(timeout=0.5)
        if not msg:
            break
        messages_handled += 1
        log.info("inbound: %r", msg["text"][:60])
        if dry_run:
            continue
        try:
            res = await bridge.complete(
                prompt=msg["text"],
                task_id=f"chat-{int(msg['ts'])}",
                inbox_token=msg.get("inbox_token"),
                cost_estimate_usd=0.05,
            )
            await bridge.notify(res.content)
        except Exception as e:
            log.exception("failed to handle inbound: %s", e)

    tasks_processed = 0
    # Quiet hours: memory consolidation only (not implemented yet) — skip tasks.
    if kind != "quiet":
        # Process one task per wake to cap spend.
        t = tasks.pop_next()
        if t is not None:
            tasks_processed = 1
            log.info("processing task: %s", t.title)
            if dry_run:
                tasks.update_status(t.id, TaskStatus.QUEUED, notes="[dry-run] not executed")
            else:
                try:
                    res = await bridge.complete(
                        prompt=t.title,
                        task_id=t.id,
                        cost_estimate_usd=0.10,
                    )
                    tasks.update_status(t.id, TaskStatus.DONE, notes=res.content[:500])
                    await bridge.notify(f"[task done] {t.title}\n\n{res.content[:500]}")
                except Exception as e:
                    tasks.update_status(t.id, TaskStatus.FAILED, notes=str(e)[:500])
                    log.exception("task failed: %s", e)

    briefings_sent = 0
    if kind == "morning-brief":
        briefings_sent += await _send_brief(bridge, tasks, dry_run, which="morning")
    elif kind == "evening-wrap":
        briefings_sent += await _send_brief(bridge, tasks, dry_run, which="evening")

    # Persist state
    s = load(state_path)
    s.last_update_ts = time.time()
    s.status = "idle"
    save(state_path, s)

    log.info(
        "heartbeat done: tasks=%d msgs=%d briefings=%d",
        tasks_processed, messages_handled, briefings_sent,
    )
    return HeartbeatResult(
        wake_kind=kind,
        tasks_processed=tasks_processed,
        messages_handled=messages_handled,
        briefings_sent=briefings_sent,
    )


async def _send_brief(
    bridge: BridgeClient, tasks: TaskQueue, dry_run: bool, *, which: str
) -> int:
    queued = tasks.list(status=TaskStatus.QUEUED)
    done = tasks.list(status=TaskStatus.DONE)
    if which == "morning":
        summary = _morning_summary(queued, done)
    else:
        summary = _evening_summary(queued, done)

    if dry_run:
        log.info("[dry-run] would send %s brief: %s", which, summary[:120])
        return 1
    await bridge.notify(summary)
    return 1


def _morning_summary(queued, done) -> str:
    lines = [f"Morning. {len(queued)} queued, {len(done)} done yesterday."]
    if queued:
        lines.append("Top 3 queued:")
        for t in sorted(queued, key=lambda x: (x.priority, x.created_ts))[:3]:
            lines.append(f"- {t.title}")
    return "\n".join(lines)


def _evening_summary(queued, done) -> str:
    lines = [f"Evening wrap: {len(done)} done, {len(queued)} still queued."]
    return "\n".join(lines)
