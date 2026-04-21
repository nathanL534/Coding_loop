"""Append-only audit log. One JSON line per request."""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _hash_prompt(messages: list[dict]) -> str:
    """Hash the prompt for audit without storing the full content (PII-safe)."""
    h = hashlib.sha256()
    for m in messages:
        h.update(m.get("role", "").encode())
        content = m.get("content", "")
        if isinstance(content, list):
            content = json.dumps(content, sort_keys=True)
        h.update(str(content).encode())
    return h.hexdigest()[:16]


class AuditLog:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    async def write(
        self,
        *,
        event: str,
        task_id: str | None,
        request_id: str,
        model: str | None = None,
        messages: list[dict] | None = None,
        cost_usd: float | None = None,
        duration_ms: int | None = None,
        error: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        entry: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "request_id": request_id,
            "task_id": task_id,
        }
        if model is not None:
            entry["model"] = model
        if messages is not None:
            entry["prompt_hash"] = _hash_prompt(messages)
            entry["prompt_messages"] = len(messages)
        if cost_usd is not None:
            entry["cost_usd"] = round(cost_usd, 6)
        if duration_ms is not None:
            entry["duration_ms"] = duration_ms
        if error is not None:
            entry["error"] = error
        if extra:
            entry["extra"] = extra

        line = json.dumps(entry, separators=(",", ":")) + "\n"
        async with self._lock:
            with self._path.open("a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
