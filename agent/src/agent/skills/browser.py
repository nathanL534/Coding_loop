"""Browser skill — Phase 6 scaffold (disabled by default).

Hard constraints from the security review (documented in docs/SECURITY.md):

- MUST use a dedicated browser profile with separate accounts (NOT your primary
  logins). Shipping address locked. Payment = a single prepaid/virtual card with
  a low monthly limit.
- MUST treat every POST/form-submit/click as requiring per-action approval.
- MUST attach a screenshot to every approval request so the user sees context.
- Default mode: DOM-reader only (GET navigation + read, no interactions).
- MUST run in an isolated sub-container with no access to /safety, /data, or
  memory — it is its own untrusted zone.

This module defines the interface and an `Action` enum that the approval flow
keys on. The real Playwright/CDP driver lands in phase 6; until then only the
stubs + tests exist so the rest of the system can compile against the shape.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class BrowserAction(str, Enum):
    READ_DOM = "browser.read_dom"
    NAVIGATE = "browser.navigate"
    CLICK = "browser.click"
    TYPE = "browser.type"
    SUBMIT = "browser.submit"


APPROVAL_REQUIRED = frozenset(
    {BrowserAction.CLICK, BrowserAction.TYPE, BrowserAction.SUBMIT}
)


@dataclass
class BrowserOperation:
    action: BrowserAction
    url: str
    selector: str | None = None
    value: str | None = None


def classify(op: BrowserOperation) -> str:
    """Return 'auto' for read-only, 'approval' otherwise."""
    return "approval" if op.action in APPROVAL_REQUIRED else "auto"


class BrowserDriver:
    """Abstract. Real impl lives in sub-container under Playwright."""

    async def read_dom(self, url: str) -> str:
        raise NotImplementedError("Phase 6: Playwright driver not yet installed")

    async def screenshot(self, url: str) -> bytes:
        raise NotImplementedError("Phase 6: Playwright driver not yet installed")

    async def execute(self, op: BrowserOperation) -> dict:
        raise NotImplementedError("Phase 6: Playwright driver not yet installed")
