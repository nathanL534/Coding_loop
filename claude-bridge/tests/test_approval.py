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
