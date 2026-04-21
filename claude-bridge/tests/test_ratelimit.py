"""Unit tests for RateLimiter."""
from __future__ import annotations

import pytest

from bridge.ratelimit import RateLimiter, RateLimitExceeded


async def test_under_limit_ok() -> None:
    rl = RateLimiter(per_hour=5, burst_per_minute=3)
    await rl.check(now=0.0)
    await rl.check(now=0.1)


async def test_burst_limit_triggers() -> None:
    rl = RateLimiter(per_hour=100, burst_per_minute=2)
    await rl.check(now=0.0)
    await rl.check(now=0.1)
    with pytest.raises(RateLimitExceeded, match="burst"):
        await rl.check(now=0.2)


async def test_burst_recovers_after_60s() -> None:
    rl = RateLimiter(per_hour=100, burst_per_minute=2)
    await rl.check(now=0.0)
    await rl.check(now=0.1)
    await rl.check(now=61.0)  # minute window slid


async def test_hourly_limit_triggers() -> None:
    rl = RateLimiter(per_hour=3, burst_per_minute=100)
    for i in range(3):
        await rl.check(now=float(i * 100))
    with pytest.raises(RateLimitExceeded, match="hourly"):
        await rl.check(now=400.0)


async def test_hourly_recovers_after_3600s() -> None:
    rl = RateLimiter(per_hour=3, burst_per_minute=100)
    for i in range(3):
        await rl.check(now=float(i * 10))
    await rl.check(now=3700.0)


def test_invalid_limits_raise() -> None:
    with pytest.raises(ValueError):
        RateLimiter(per_hour=0, burst_per_minute=1)
    with pytest.raises(ValueError):
        RateLimiter(per_hour=1, burst_per_minute=-1)
