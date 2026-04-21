"""Sliding-window rate limiter. Enforced independently of budget."""
from __future__ import annotations

import asyncio
import time
from collections import deque


class RateLimitExceeded(Exception):
    pass


class RateLimiter:
    def __init__(self, per_hour: int, burst_per_minute: int) -> None:
        if per_hour <= 0 or burst_per_minute <= 0:
            raise ValueError("limits must be positive")
        self._per_hour = per_hour
        self._burst = burst_per_minute
        self._hour: deque[float] = deque()
        self._minute: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def check(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        async with self._lock:
            while self._hour and now - self._hour[0] > 3600:
                self._hour.popleft()
            while self._minute and now - self._minute[0] > 60:
                self._minute.popleft()
            if len(self._hour) >= self._per_hour:
                raise RateLimitExceeded(
                    f"hourly rate limit: {len(self._hour)} >= {self._per_hour}"
                )
            if len(self._minute) >= self._burst:
                raise RateLimitExceeded(
                    f"burst rate limit: {len(self._minute)} >= {self._burst} in last 60s"
                )
            self._hour.append(now)
            self._minute.append(now)
