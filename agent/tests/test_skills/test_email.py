"""Tests for email stub skills. Real Google integration deferred to Phase 4 runtime wiring."""
from datetime import datetime, timedelta

import pytest

from agent.skills.email import (
    CalendarEvent,
    EmailSummary,
    StubCalendarClient,
    StubEmailClient,
)


def _msg(id_: str, unread: bool = True) -> EmailSummary:
    return EmailSummary(
        id=id_,
        subject=f"subj-{id_}",
        sender="prof@university.edu",
        snippet="hello",
        received_at=datetime(2025, 1, 1, 10, 0),
        unread=unread,
    )


async def test_list_inbox_filters_unread() -> None:
    c = StubEmailClient([_msg("1", True), _msg("2", False), _msg("3", True)])
    msgs = await c.list_inbox(unread_only=True)
    assert [m.id for m in msgs] == ["1", "3"]


async def test_list_inbox_all() -> None:
    c = StubEmailClient([_msg("1", True), _msg("2", False)])
    msgs = await c.list_inbox(unread_only=False)
    assert len(msgs) == 2


async def test_list_inbox_limit() -> None:
    c = StubEmailClient([_msg(str(i)) for i in range(50)])
    msgs = await c.list_inbox(limit=5)
    assert len(msgs) == 5


async def test_get_body_known_id() -> None:
    c = StubEmailClient([_msg("42")])
    body = await c.get_body("42")
    assert "subj-42" in body


async def test_get_body_unknown_id_raises() -> None:
    c = StubEmailClient([])
    with pytest.raises(KeyError):
        await c.get_body("missing")


async def test_calendar_events_in_range() -> None:
    today = datetime(2025, 1, 1, 0, 0)
    evts = [
        CalendarEvent(id="a", title="class", start=today + timedelta(hours=9), end=today + timedelta(hours=10)),
        CalendarEvent(id="b", title="standup", start=today + timedelta(hours=14), end=today + timedelta(hours=15)),
        CalendarEvent(id="c", title="tomorrow", start=today + timedelta(days=1), end=today + timedelta(days=1, hours=1)),
    ]
    c = StubCalendarClient(evts)
    hits = await c.events_between(today, today + timedelta(hours=23))
    assert [e.id for e in hits] == ["a", "b"]
