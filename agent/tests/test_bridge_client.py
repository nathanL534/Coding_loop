"""Tests for BridgeClient against a real FastAPI bridge app over ASGI."""
from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest
import yaml

# Make the bridge source importable too.
BRIDGE_SRC = Path(__file__).resolve().parents[2] / "claude-bridge" / "src"
if str(BRIDGE_SRC) not in sys.path:
    sys.path.insert(0, str(BRIDGE_SRC))

from agent.bridge_client import BridgeClient, BridgeUnavailable  # noqa: E402
from bridge import config as cfg  # noqa: E402
from bridge.claude_client import ClaudeResult  # noqa: E402
from bridge.main import build_app  # noqa: E402


def _write_safety(dir_: Path) -> None:
    (dir_ / "budget.yaml").write_text(
        yaml.safe_dump(
            {
                "daily_usd_cap": 1.0,
                "per_wake_usd_cap": 0.5,
                "per_request_usd_cap": 0.15,
                "per_request_timeout_seconds": 30,
                "rate_limits": {"requests_per_hour": 100, "requests_per_minute_burst": 10},
                "models": {
                    "default": "claude-sonnet-4-6",
                    "allowed": ["claude-sonnet-4-6"],
                    "denied_for_autonomous": [],
                },
            }
        )
    )
    (dir_ / "allowlist.yaml").write_text(yaml.safe_dump({}))
    (dir_ / "protected-files.txt").write_text("")


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    safety = tmp_path / "safety"
    safety.mkdir()
    _write_safety(safety)
    config_toml = tmp_path / "config.toml"
    config_toml.write_text(
        f"""
[bridge]
socket_path = "{tmp_path}/bridge.sock"
state_dir = "{tmp_path}/state"
safety_dir = "{safety}"

[claude]
cli_path = "claude"
timeout_seconds = 30

[telegram]
bot_token = "PASTE_BOT_TOKEN_HERE"
allowed_user_id = 0
"""
    )
    config = cfg.load(config_toml)

    # Stub the claude subprocess.
    async def fake_complete(self, *, prompt, model, system=None, max_turns=None, allowed_tool_names=None):
        return ClaudeResult(
            content=f"echo: {prompt}", model=model, cost_usd=0.01, duration_ms=10, raw={}
        )

    from bridge.claude_client import ClaudeClient

    monkeypatch.setattr(ClaudeClient, "complete", fake_complete)
    return build_app(config)


class _ASGIBridge(BridgeClient):
    """BridgeClient variant backed by ASGITransport rather than a Unix socket."""

    def __init__(self, app) -> None:
        self._client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://bridge", timeout=30.0
        )


async def test_complete_happy(app) -> None:
    c = _ASGIBridge(app)
    res = await c.complete(prompt="hi", cost_estimate_usd=0.01)
    assert res.content == "echo: hi"
    assert res.cost_usd == pytest.approx(0.01)
    await c.close()


async def test_health(app) -> None:
    c = _ASGIBridge(app)
    h = await c.health()
    assert h["ok"] is True
    await c.close()


async def test_unreachable_bridge() -> None:
    # Point to a path that doesn't exist.
    c = BridgeClient(socket_path="/tmp/does-not-exist.sock", timeout=1.0)
    with pytest.raises(BridgeUnavailable):
        await c.health()
    await c.close()
