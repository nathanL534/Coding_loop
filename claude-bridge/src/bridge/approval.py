"""Approval queue: high-cost/risky requests held until Telegram yes/no.

The bridge owns this — the container cannot bypass it.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal


class ApprovalTimeout(Exception):
    pass


@dataclass
class ApprovalRequest:
    id: str
    action: str
    reason: str
    cost_estimate_usd: float
    created_at: str
    future: asyncio.Future[bool] = field(repr=False)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "action": self.action,
            "reason": self.reason,
            "cost_estimate_usd": self.cost_estimate_usd,
            "created_at": self.created_at,
        }


class ApprovalQueue:
    """In-memory pending approvals. The Telegram gateway reads and resolves them."""

    def __init__(self) -> None:
        self._pending: dict[str, ApprovalRequest] = {}
        self._lock = asyncio.Lock()

    async def request(
        self, *, action: str, reason: str, cost_estimate_usd: float, timeout_seconds: int = 3600
    ) -> bool:
        req = ApprovalRequest(
            id=str(uuid.uuid4()),
            action=action,
            reason=reason,
            cost_estimate_usd=cost_estimate_usd,
            created_at=datetime.now(timezone.utc).isoformat(),
            future=asyncio.get_running_loop().create_future(),
        )
        async with self._lock:
            self._pending[req.id] = req
        try:
            return await asyncio.wait_for(req.future, timeout=timeout_seconds)
        except asyncio.TimeoutError:
            async with self._lock:
                self._pending.pop(req.id, None)
            raise ApprovalTimeout(f"approval {req.id} timed out after {timeout_seconds}s") from None

    async def resolve(self, request_id: str, decision: Literal["yes", "no"]) -> bool:
        async with self._lock:
            req = self._pending.pop(request_id, None)
        if req is None:
            return False
        req.future.set_result(decision == "yes")
        return True

    async def list(self) -> list[dict]:
        async with self._lock:
            return [r.as_dict() for r in self._pending.values()]
