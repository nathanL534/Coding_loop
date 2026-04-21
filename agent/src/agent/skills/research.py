"""Research skill: fetch+synthesize. GET-only. Domain allowlist enforced.

All fetched content enters memory as trust=untrusted, so it can never be
concatenated into the system prompt via the retriever.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

import httpx


class DomainNotAllowed(Exception):
    pass


@dataclass
class FetchResult:
    url: str
    status: int
    text: str
    content_type: str


def is_allowed(url: str, allowed_domains: frozenset[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    for d in allowed_domains:
        d = d.lower().strip()
        if host == d or host.endswith("." + d):
            return True
    return False


async def fetch(
    url: str,
    *,
    allowed_domains: frozenset[str],
    timeout: float = 15.0,
    max_bytes: int = 500_000,
) -> FetchResult:
    if not is_allowed(url, allowed_domains):
        raise DomainNotAllowed(f"domain not in research_domains allowlist: {url}")

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as c:
        r = await c.get(url, headers={"User-Agent": "coding-loop-agent/0.1"})
    content = r.content[:max_bytes]
    try:
        text = content.decode(r.encoding or "utf-8", errors="replace")
    except LookupError:
        text = content.decode("utf-8", errors="replace")
    return FetchResult(
        url=str(r.url),
        status=r.status_code,
        text=text,
        content_type=r.headers.get("content-type", ""),
    )
