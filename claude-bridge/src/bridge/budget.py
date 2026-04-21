"""Bridge-enforced budget tracking. Persists to JSON; thread/async-safe via lock."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path


class BudgetExceeded(Exception):
    """Raised when a request would exceed a configured cap."""


@dataclass
class BudgetSnapshot:
    day: str
    spent_today_usd: float
    spent_this_wake_usd: float
    daily_cap_usd: float
    per_wake_cap_usd: float
    per_request_cap_usd: float

    def remaining_today(self) -> float:
        return max(0.0, self.daily_cap_usd - self.spent_today_usd)


class BudgetTracker:
    """Persists daily and per-wake spend. Safe to share across async tasks."""

    def __init__(
        self,
        state_path: Path,
        daily_cap_usd: float,
        per_wake_cap_usd: float,
        per_request_cap_usd: float,
    ) -> None:
        self._path = state_path
        self._daily_cap = daily_cap_usd
        self._per_wake_cap = per_wake_cap_usd
        self._per_request_cap = per_request_cap_usd
        self._lock = asyncio.Lock()
        self._load()

    def _today(self) -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def _load(self) -> None:
        if self._path.exists():
            data = json.loads(self._path.read_text())
        else:
            data = {}
        today = self._today()
        if data.get("day") != today:
            data = {"day": today, "spent_today_usd": 0.0, "spent_this_wake_usd": 0.0}
            self._write(data)
        self._state = data

    def _write(self, data: dict) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        tmp.replace(self._path)

    async def reset_wake(self) -> None:
        async with self._lock:
            self._roll_day_if_needed()
            self._state["spent_this_wake_usd"] = 0.0
            self._write(self._state)

    def _roll_day_if_needed(self) -> None:
        today = self._today()
        if self._state.get("day") != today:
            self._state = {"day": today, "spent_today_usd": 0.0, "spent_this_wake_usd": 0.0}

    async def check_can_spend(self, estimate_usd: float) -> None:
        """Raise BudgetExceeded if this estimate would blow any cap."""
        if estimate_usd < 0:
            raise ValueError("estimate_usd must be non-negative")
        if estimate_usd > self._per_request_cap:
            raise BudgetExceeded(
                f"per-request cap: estimate ${estimate_usd:.4f} > cap ${self._per_request_cap:.4f}"
            )
        async with self._lock:
            self._roll_day_if_needed()
            if self._state["spent_today_usd"] + estimate_usd > self._daily_cap:
                raise BudgetExceeded(
                    f"daily cap: spent ${self._state['spent_today_usd']:.4f} + "
                    f"${estimate_usd:.4f} > ${self._daily_cap:.4f}"
                )
            if self._state["spent_this_wake_usd"] + estimate_usd > self._per_wake_cap:
                raise BudgetExceeded(
                    f"per-wake cap: wake spend ${self._state['spent_this_wake_usd']:.4f} + "
                    f"${estimate_usd:.4f} > ${self._per_wake_cap:.4f}"
                )

    async def record(self, actual_usd: float) -> None:
        """Record actual spend after a successful request."""
        if actual_usd < 0:
            raise ValueError("actual_usd must be non-negative")
        async with self._lock:
            self._roll_day_if_needed()
            self._state["spent_today_usd"] += actual_usd
            self._state["spent_this_wake_usd"] += actual_usd
            self._write(self._state)

    async def snapshot(self) -> BudgetSnapshot:
        async with self._lock:
            self._roll_day_if_needed()
            return BudgetSnapshot(
                day=self._state["day"],
                spent_today_usd=self._state["spent_today_usd"],
                spent_this_wake_usd=self._state["spent_this_wake_usd"],
                daily_cap_usd=self._daily_cap,
                per_wake_cap_usd=self._per_wake_cap,
                per_request_cap_usd=self._per_request_cap,
            )
