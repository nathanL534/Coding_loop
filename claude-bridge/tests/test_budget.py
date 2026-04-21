"""Unit tests for BudgetTracker."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bridge.budget import BudgetExceeded, BudgetTracker


@pytest.fixture
def budget_path(tmp_path: Path) -> Path:
    return tmp_path / "budget.json"


@pytest.fixture
def tracker(budget_path: Path) -> BudgetTracker:
    return BudgetTracker(
        state_path=budget_path,
        daily_cap_usd=1.0,
        per_wake_cap_usd=0.30,
        per_request_cap_usd=0.15,
    )


async def test_initial_snapshot_is_zero(tracker: BudgetTracker) -> None:
    snap = await tracker.snapshot()
    assert snap.spent_today_usd == 0.0
    assert snap.spent_this_wake_usd == 0.0


async def test_can_spend_under_caps(tracker: BudgetTracker) -> None:
    await tracker.check_can_spend(0.05)  # no error


async def test_rejects_per_request_over_cap(tracker: BudgetTracker) -> None:
    with pytest.raises(BudgetExceeded, match="per-request"):
        await tracker.check_can_spend(0.20)


async def test_record_accumulates(tracker: BudgetTracker) -> None:
    await tracker.record(0.10)
    await tracker.record(0.05)
    snap = await tracker.snapshot()
    assert snap.spent_today_usd == pytest.approx(0.15)
    assert snap.spent_this_wake_usd == pytest.approx(0.15)


async def test_per_wake_cap_enforced(tracker: BudgetTracker) -> None:
    await tracker.record(0.10)
    await tracker.record(0.10)
    await tracker.record(0.10)
    with pytest.raises(BudgetExceeded, match="per-wake"):
        await tracker.check_can_spend(0.05)


async def test_reset_wake_clears_wake_not_day(tracker: BudgetTracker) -> None:
    await tracker.record(0.10)
    await tracker.reset_wake()
    snap = await tracker.snapshot()
    assert snap.spent_today_usd == pytest.approx(0.10)
    assert snap.spent_this_wake_usd == 0.0


async def test_daily_cap_enforced(budget_path: Path) -> None:
    t = BudgetTracker(state_path=budget_path, daily_cap_usd=0.20, per_wake_cap_usd=10.0, per_request_cap_usd=0.15)
    await t.record(0.15)
    with pytest.raises(BudgetExceeded, match="daily"):
        await t.check_can_spend(0.10)


async def test_persists_across_instances(budget_path: Path) -> None:
    t1 = BudgetTracker(state_path=budget_path, daily_cap_usd=1.0, per_wake_cap_usd=1.0, per_request_cap_usd=0.15)
    await t1.record(0.12)
    t2 = BudgetTracker(state_path=budget_path, daily_cap_usd=1.0, per_wake_cap_usd=1.0, per_request_cap_usd=0.15)
    snap = await t2.snapshot()
    assert snap.spent_today_usd == pytest.approx(0.12)


async def test_day_rollover_clears_spend(budget_path: Path) -> None:
    budget_path.write_text(
        json.dumps({"day": "1999-01-01", "spent_today_usd": 5.0, "spent_this_wake_usd": 5.0})
    )
    t = BudgetTracker(state_path=budget_path, daily_cap_usd=1.0, per_wake_cap_usd=1.0, per_request_cap_usd=0.15)
    snap = await t.snapshot()
    assert snap.spent_today_usd == 0.0


async def test_negative_spend_rejected(tracker: BudgetTracker) -> None:
    with pytest.raises(ValueError):
        await tracker.record(-0.01)
    with pytest.raises(ValueError):
        await tracker.check_can_spend(-0.01)


# ---- reserve / settle (closes the concurrency race) ----

async def test_reserve_debits_atomically(tracker: BudgetTracker) -> None:
    await tracker.reserve(0.08)
    snap = await tracker.snapshot()
    assert snap.spent_today_usd == pytest.approx(0.08)
    assert snap.spent_this_wake_usd == pytest.approx(0.08)


async def test_reserve_rejects_over_cap(budget_path: Path) -> None:
    t = BudgetTracker(state_path=budget_path, daily_cap_usd=0.20, per_wake_cap_usd=10.0, per_request_cap_usd=0.15)
    await t.reserve(0.15)
    with pytest.raises(BudgetExceeded):
        await t.reserve(0.10)


async def test_settle_trues_up_to_actual(tracker: BudgetTracker) -> None:
    await tracker.reserve(0.10)
    await tracker.settle(reserved=0.10, actual=0.03)
    snap = await tracker.snapshot()
    assert snap.spent_today_usd == pytest.approx(0.03)
    assert snap.spent_this_wake_usd == pytest.approx(0.03)


async def test_settle_refunds_on_failure(tracker: BudgetTracker) -> None:
    """When a reserved request fails, settle(actual=0) fully refunds."""
    await tracker.reserve(0.10)
    await tracker.settle(reserved=0.10, actual=0.0)
    snap = await tracker.snapshot()
    assert snap.spent_today_usd == pytest.approx(0.0)


async def test_settle_does_not_go_negative(tracker: BudgetTracker) -> None:
    """Double-settle (buggy caller) should not push balance below zero."""
    await tracker.reserve(0.05)
    await tracker.settle(reserved=0.05, actual=0.0)
    await tracker.settle(reserved=0.05, actual=0.0)
    snap = await tracker.snapshot()
    assert snap.spent_today_usd >= 0.0


async def test_reserve_concurrent_cannot_double_spend(budget_path: Path) -> None:
    """Two concurrent reserves must not both pass when sum > cap."""
    import asyncio
    t = BudgetTracker(
        state_path=budget_path, daily_cap_usd=0.10, per_wake_cap_usd=0.10, per_request_cap_usd=0.15
    )

    async def try_reserve() -> bool:
        try:
            await t.reserve(0.08)
            return True
        except BudgetExceeded:
            return False

    results = await asyncio.gather(try_reserve(), try_reserve(), try_reserve())
    # Only one should have succeeded (0.08 + 0.08 > 0.10)
    assert sum(results) == 1
