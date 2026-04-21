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
