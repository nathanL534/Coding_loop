"""Client that reaches the host bridge over a Unix socket."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import httpx


@dataclass(frozen=True)
class CompleteResult:
    request_id: str
    content: str
    model: str
    cost_usd: float
    duration_ms: int


class BridgeUnavailable(Exception):
    pass


class BridgeClient:
    """All Claude calls from the container go through this."""

    def __init__(self, socket_path: str | Path | None = None, timeout: float = 180.0) -> None:
        sock = str(socket_path or os.environ.get("BRIDGE_SOCKET", "/run/claude-bridge.sock"))
        self._socket = sock
        transport = httpx.AsyncHTTPTransport(uds=sock)
        self._client = httpx.AsyncClient(
            transport=transport, base_url="http://bridge", timeout=timeout
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def health(self) -> dict:
        try:
            r = await self._client.get("/v1/health")
        except httpx.HTTPError as e:
            raise BridgeUnavailable(f"bridge unreachable: {e}") from e
        r.raise_for_status()
        return r.json()

    async def budget(self) -> dict:
        r = await self._client.get("/v1/budget")
        r.raise_for_status()
        return r.json()

    async def complete(
        self,
        *,
        prompt: str,
        system: str | None = None,
        model: str | None = None,
        tools: list[dict] | None = None,
        max_turns: int | None = None,
        task_id: str | None = None,
        inbox_token: str | None = None,
        cost_estimate_usd: float = 0.05,
    ) -> CompleteResult:
        """Autonomy is decided by the bridge. Pass the inbox_token from a
        prior /v1/inbox delivery to mark this call as user-initiated."""
        body: dict = {
            "prompt": prompt,
            "cost_estimate_usd": cost_estimate_usd,
        }
        if system is not None:
            body["system"] = system
        if model is not None:
            body["model"] = model
        if tools is not None:
            body["tools"] = tools
        if max_turns is not None:
            body["max_turns"] = max_turns
        if task_id is not None:
            body["task_id"] = task_id
        if inbox_token is not None:
            body["inbox_token"] = inbox_token

        try:
            r = await self._client.post("/v1/complete", json=body)
        except httpx.HTTPError as e:
            raise BridgeUnavailable(f"bridge unreachable: {e}") from e
        r.raise_for_status()
        data = r.json()
        return CompleteResult(
            request_id=data["request_id"],
            content=data["content"],
            model=data["model"],
            cost_usd=data["cost_usd"],
            duration_ms=data["duration_ms"],
        )

    async def notify(self, text: str) -> None:
        r = await self._client.post("/v1/notify", json={"text": text})
        r.raise_for_status()

    async def approve(
        self, *, action: str, reason: str, cost_estimate_usd: float = 0.0, timeout_seconds: int = 3600
    ) -> bool:
        r = await self._client.post(
            "/v1/approve-required",
            json={
                "action": action,
                "reason": reason,
                "cost_estimate_usd": cost_estimate_usd,
                "timeout_seconds": timeout_seconds,
            },
            timeout=timeout_seconds + 30,
        )
        if r.status_code == 408:
            return False
        r.raise_for_status()
        return bool(r.json()["approved"])

    async def inbox(self, timeout: float = 25.0) -> dict | None:
        r = await self._client.get("/v1/inbox", params={"timeout": timeout}, timeout=timeout + 10)
        r.raise_for_status()
        return r.json().get("msg")
