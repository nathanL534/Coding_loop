"""Unit tests for research skill."""
from __future__ import annotations

import pytest

from agent.skills.research import DomainNotAllowed, fetch, is_allowed


ALLOWED = frozenset({"wikipedia.org", "arxiv.org"})


def test_is_allowed_exact() -> None:
    assert is_allowed("https://wikipedia.org/x", ALLOWED)


def test_is_allowed_subdomain() -> None:
    assert is_allowed("https://en.wikipedia.org/wiki/Test", ALLOWED)


def test_is_allowed_case_insensitive() -> None:
    assert is_allowed("https://EN.WIKIPEDIA.ORG/", ALLOWED)


def test_is_allowed_disallowed_domain() -> None:
    assert not is_allowed("https://evil.example.com/x", ALLOWED)


def test_is_allowed_no_host() -> None:
    assert not is_allowed("not-a-url", ALLOWED)


def test_is_allowed_rejects_lookalike() -> None:
    # "evilwikipedia.org" must not match "wikipedia.org"
    assert not is_allowed("https://evilwikipedia.org/x", ALLOWED)


async def test_fetch_rejects_bad_domain() -> None:
    with pytest.raises(DomainNotAllowed):
        await fetch("https://example.com/", allowed_domains=ALLOWED)


async def test_fetch_rejects_redirect_to_disallowed_domain(monkeypatch) -> None:
    """A redirect from an allowlisted domain to a disallowed one must be blocked."""
    import httpx

    from agent.skills import research as research_mod

    call_log = []

    class _FakeResponse:
        def __init__(self, status_code, headers=None, content=b"", url="https://wikipedia.org/x"):
            self.status_code = status_code
            self.headers = headers or {}
            self.content = content
            self.encoding = "utf-8"
            self.url = httpx.URL(url)

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            call_log.append(url)
            # First call: redirect to evil.com
            return _FakeResponse(
                status_code=302,
                headers={"location": "https://evil.example/stolen"},
                url=url,
            )

    monkeypatch.setattr(research_mod.httpx, "AsyncClient", _FakeClient)
    with pytest.raises(research_mod.DomainNotAllowed):
        await research_mod.fetch("https://wikipedia.org/a", allowed_domains=ALLOWED)
