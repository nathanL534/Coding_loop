"""Agent entrypoint. Dispatches based on $AGENT_MODE.

Modes:
- listen     : long-poll the bridge inbox, respond to user messages
- heartbeat  : single-shot wake; process pending work then exit
- smoke      : health check, single /v1/complete round-trip, exit
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

from . import state as state_mod
from .bridge_client import BridgeClient, BridgeUnavailable

log = logging.getLogger("agent")


async def smoke() -> int:
    bc = BridgeClient()
    try:
        h = await bc.health()
        log.info("health: %s", h)
        res = await bc.complete(prompt="ping", task_id="smoke", cost_estimate_usd=0.01)
        log.info("complete: %s (%s, $%.4f)", res.content[:60], res.model, res.cost_usd)
    except BridgeUnavailable as e:
        log.error("bridge unavailable: %s", e)
        return 2
    finally:
        await bc.close()
    return 0


async def listen() -> int:
    bc = BridgeClient()
    try:
        while True:
            msg = await bc.inbox(timeout=25.0)
            if msg is None:
                continue
            text = msg["text"]
            log.info("inbound: %r", text[:80])
            try:
                res = await bc.complete(
                    prompt=text,
                    task_id=f"chat-{msg['ts']:.0f}",
                    is_autonomous=False,
                    cost_estimate_usd=0.05,
                )
                await bc.notify(res.content)
            except BridgeUnavailable as e:
                log.error("bridge unavailable: %s", e)
                await asyncio.sleep(5)
    finally:
        await bc.close()


async def heartbeat() -> int:
    from pathlib import Path

    from .heartbeat import run_once
    from .tasks import TaskQueue

    bc = BridgeClient()
    try:
        state_path = Path(os.environ.get("AGENT_STATE", "/data/state.json"))
        queue_path = Path(os.environ.get("AGENT_TASKS", "/data/tasks.json"))
        dry_run = os.environ.get("AGENT_DRY_RUN", "0") == "1"
        tasks = TaskQueue(queue_path)
        res = await run_once(bridge=bc, tasks=tasks, state_path=state_path, dry_run=dry_run)
        log.info("result: %s", res)
        if res.aborted:
            return 1
    finally:
        await bc.close()
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    mode = os.environ.get("AGENT_MODE", "smoke")
    runners = {"smoke": smoke, "listen": listen, "heartbeat": heartbeat}
    runner = runners.get(mode)
    if runner is None:
        log.error("unknown AGENT_MODE=%s (expected: %s)", mode, list(runners))
        return 2
    return asyncio.run(runner())


if __name__ == "__main__":
    sys.exit(main())
