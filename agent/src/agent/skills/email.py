"""Email skill — Phase 4 scaffold.

Real Gmail/Calendar access requires Google OAuth performed on the host. This
module defines the interface and a deterministic stub so tests pass without
live credentials. Wiring to the real backend happens on the host side (bridge
proxies read-only Gmail/Calendar calls).

The container never sees Google tokens. Pattern mirrors the Claude bridge:
bridge exposes /v1/gmail/list, /v1/gmail/get, /v1/calendar/events — all
read-only in phase 4. Sends/drafts gate through /v1/approve-required.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class EmailSummary:
    id: str
    subject: str
    sender: str
    snippet: str
    received_at: datetime
    unread: bool


@dataclass
class CalendarEvent:
    id: str
    title: str
    start: datetime
    end: datetime
    location: str | None = None
    attendees: tuple[str, ...] = ()


class EmailClient(ABC):
    @abstractmethod
    async def list_inbox(self, *, unread_only: bool = True, limit: int = 20) -> list[EmailSummary]:
        ...

    @abstractmethod
    async def get_body(self, message_id: str) -> str:
        ...


class CalendarClient(ABC):
    @abstractmethod
    async def events_between(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        ...


class StubEmailClient(EmailClient):
    """Deterministic stub. Not used in prod; real impl goes through bridge."""

    def __init__(self, messages: list[EmailSummary] | None = None) -> None:
        self._msgs = messages or []

    async def list_inbox(self, *, unread_only: bool = True, limit: int = 20) -> list[EmailSummary]:
        msgs = [m for m in self._msgs if (m.unread if unread_only else True)]
        return msgs[:limit]

    async def get_body(self, message_id: str) -> str:
        for m in self._msgs:
            if m.id == message_id:
                return f"[stub body for {m.subject}]"
        raise KeyError(message_id)


class StubCalendarClient(CalendarClient):
    def __init__(self, events: list[CalendarEvent] | None = None) -> None:
        self._events = events or []

    async def events_between(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        return [e for e in self._events if start <= e.start <= end]
