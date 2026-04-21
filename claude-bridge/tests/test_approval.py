"""Unit tests for ApprovalQueue."""
from __future__ import annotations

import asyncio

import pytest

from bridge.approval import ApprovalQueue, ApprovalTimeout


async def test_yes_approves() -> None:
    q = ApprovalQueue()

    async def resolver() -> None:
        await asyncio.sleep(0.01)
        pending = await q.list()
        await q.resolve(pending[0]["id"], "yes")

    task = asyncio.create_task(resolver())
    ok = await q.request(action="x", reason="y", cost_estimate_usd=0.0, timeout_seconds=5)
    assert ok is True
    await task


async def test_no_rejects() -> None:
    q = ApprovalQueue()

    async def resolver() -> None:
        await asyncio.sleep(0.01)
        pending = await q.list()
        await q.resolve(pending[0]["id"], "no")

    task = asyncio.create_task(resolver())
    ok = await q.request(action="x", reason="y", cost_estimate_usd=0.0, timeout_seconds=5)
    assert ok is False
    await task


async def test_timeout() -> None:
    q = ApprovalQueue()
    with pytest.raises(ApprovalTimeout):
        await q.request(action="x", reason="y", cost_estimate_usd=0.0, timeout_seconds=1)


async def test_unknown_id_returns_false() -> None:
    q = ApprovalQueue()
    ok = await q.resolve("nonexistent", "yes")
    assert ok is False


async def test_list_shows_pending() -> None:
    q = ApprovalQueue()

    async def sleeper() -> None:
        try:
            await q.request(action="a", reason="r", cost_estimate_usd=0.0, timeout_seconds=5)
        except ApprovalTimeout:
            pass

    task = asyncio.create_task(sleeper())
    await asyncio.sleep(0.01)
    pending = await q.list()
    assert len(pending) == 1
    assert pending[0]["action"] == "a"
    await q.resolve(pending[0]["id"], "no")
    await task


async def test_notifier_receives_request() -> None:
    notifications = []

    async def notify(req) -> None:
        notifications.append({"id": req.id, "action": req.action})

    q = ApprovalQueue(notifier=notify)

    async def resolver() -> None:
        await asyncio.sleep(0.01)
        pending = await q.list()
        await q.resolve(pending[0]["id"], "yes")

    task = asyncio.create_task(resolver())
    ok = await q.request(action="spend", reason="buy thing", cost_estimate_usd=5.0, timeout_seconds=5)
    assert ok is True
    await task
    assert len(notifications) == 1
    assert notifications[0]["action"] == "spend"


async def test_resolve_race_with_timeout_no_crash() -> None:
    """If wait_for cancels the future and a resolve arrives simultaneously,
    the queue should not crash with InvalidStateError."""
    q = ApprovalQueue()

    async def request_and_timeout() -> None:
        try:
            await q.request(action="a", reason="r", cost_estimate_usd=0.0, timeout_seconds=1)
        except ApprovalTimeout:
            pass

    # Start request, wait past timeout, then try to resolve after the pop already happened
    await request_and_timeout()
    # After timeout, nothing pending; resolving a stale id is a no-op.
    assert await q.resolve("missing-id", "yes") is False
