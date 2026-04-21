"""Tests for browser action classification."""
import pytest

from agent.skills.browser import BrowserAction, BrowserDriver, BrowserOperation, classify


def test_read_dom_is_auto() -> None:
    assert classify(BrowserOperation(BrowserAction.READ_DOM, "https://x/")) == "auto"


def test_navigate_is_auto() -> None:
    assert classify(BrowserOperation(BrowserAction.NAVIGATE, "https://x/")) == "auto"


def test_click_requires_approval() -> None:
    assert classify(BrowserOperation(BrowserAction.CLICK, "https://x/", selector="#buy")) == "approval"


def test_submit_requires_approval() -> None:
    assert classify(BrowserOperation(BrowserAction.SUBMIT, "https://x/", selector="form")) == "approval"


def test_type_requires_approval() -> None:
    assert classify(BrowserOperation(BrowserAction.TYPE, "https://x/", selector="#q", value="foo")) == "approval"


async def test_driver_is_unimplemented() -> None:
    d = BrowserDriver()
    with pytest.raises(NotImplementedError):
        await d.read_dom("https://x/")
