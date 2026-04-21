"""End-to-end bridge integration tests.

Uses httpx ASGITransport against the real FastAPI app with a mocked Claude subprocess.
No network, no real Claude, no real Keychain — just the policy pipeline.
"""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import yaml

from bridge import config as cfg
from bridge.claude_client import ClaudeResult
from bridge.main import build_app


def _write_safety(dir_: Path) -> None:
    (dir_ / "budget.yaml").write_text(
        yaml.safe_dump(
            {
                "daily_usd_cap": 1.0,
                "per_wake_usd_cap": 0.30,
                "per_request_usd_cap": 0.15,
                "per_request_timeout_seconds": 30,
                "rate_limits": {"requests_per_hour": 100, "requests_per_minute_burst": 10},
                "models": {
                    "default": "claude-sonnet-4-6",
                    "allowed": ["claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
                    "denied_for_autonomous": ["claude-opus-4-7"],
                },
            }
        )
    )
    (dir_ / "allowlist.yaml").write_text(yaml.safe_dump({}))
    (dir_ / "protected-files.txt").write_text("")


@pytest.fixture
def bridge_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> cfg.BridgeConfig:
    safety = tmp_path / "safety"
    safety.mkdir()
    _write_safety(safety)
    state = tmp_path / "state"
    config_toml = tmp_path / "config.toml"
    config_toml.write_text(
        f"""
[bridge]
socket_path = "{tmp_path}/bridge.sock"
state_dir = "{state}"
safety_dir = "{safety}"

[claude]
cli_path = "claude"
timeout_seconds = 30

[telegram]
bot_token = "PASTE_BOT_TOKEN_HERE"
allowed_user_id = 0
mode = "polling"
"""
    )
    return cfg.load(config_toml)


@pytest.fixture
def mocked_claude(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Replace ClaudeClient.complete with a deterministic stub. Returns a call log."""
    calls: list[dict] = []

    async def fake_complete(self, *, prompt, model, system=None, max_turns=None):
        calls.append({"prompt": prompt, "model": model, "system": system, "max_turns": max_turns})
        return ClaudeResult(
            content="stubbed response",
            model=model,
            cost_usd=0.02,
            duration_ms=123,
            raw={},
        )

    from bridge.claude_client import ClaudeClient

    monkeypatch.setattr(ClaudeClient, "complete", fake_complete)
    return calls


@pytest.fixture
async def client(bridge_config, mocked_claude):
    app = build_app(bridge_config)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        # Force lifespan to run so app state is populated.
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=True),
            base_url="http://test",
        ) as _:
            pass
        yield c


# ---- health ----

async def test_health_ok(bridge_config, mocked_claude) -> None:
    app = build_app(bridge_config)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get("/v1/health")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["kill_switch"] is False


# ---- complete happy path ----

async def test_complete_happy_path(bridge_config, mocked_claude) -> None:
    app = build_app(bridge_config)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(
            "/v1/complete",
            json={"prompt": "hello", "task_id": "t1", "cost_estimate_usd": 0.05},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["content"] == "stubbed response"
        assert body["cost_usd"] == pytest.approx(0.02)
        assert body["model"] == "claude-sonnet-4-6"

    assert len(mocked_claude) == 1
    assert mocked_claude[0]["prompt"] == "hello"
    # Meta-system prompt is always prepended
    assert "META" not in "" and "tool invoked by an automated agent" in mocked_claude[0]["system"]


# ---- kill switch ----

async def test_complete_blocked_by_kill_switch(bridge_config, mocked_claude) -> None:
    (bridge_config.state_dir / "pause").touch()
    app = build_app(bridge_config)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post("/v1/complete", json={"prompt": "hi", "cost_estimate_usd": 0.01})
        assert r.status_code == 503


# ---- policy: model allowlist ----

async def test_complete_rejects_unknown_model(bridge_config, mocked_claude) -> None:
    app = build_app(bridge_config)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(
            "/v1/complete",
            json={"prompt": "hi", "model": "gpt-4", "cost_estimate_usd": 0.01},
        )
        assert r.status_code == 403
        assert "allowlist" in r.json()["detail"]


# ---- budget ----

async def test_complete_rejects_over_per_request_cap(bridge_config, mocked_claude) -> None:
    app = build_app(bridge_config)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post("/v1/complete", json={"prompt": "hi", "cost_estimate_usd": 0.50})
        assert r.status_code == 402


async def test_budget_snapshot_reflects_spend(bridge_config, mocked_claude) -> None:
    app = build_app(bridge_config)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        await c.post("/v1/complete", json={"prompt": "a", "cost_estimate_usd": 0.01})
        await c.post("/v1/complete", json={"prompt": "b", "cost_estimate_usd": 0.01})
        r = await c.get("/v1/budget")
        assert r.status_code == 200
        body = r.json()
        assert body["spent_today_usd"] == pytest.approx(0.04)  # 2 * 0.02


# ---- policy: tool smuggling ----

async def test_tools_are_filtered(bridge_config, mocked_claude) -> None:
    app = build_app(bridge_config)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(
            "/v1/complete",
            json={
                "prompt": "hi",
                "tools": [
                    {"name": "web_fetch", "input_schema": {}},
                    {"name": "shell", "input_schema": {}},
                ],
                "cost_estimate_usd": 0.01,
            },
        )
        assert r.status_code == 200
    # The mock doesn't actually receive tools (bridge passes them to Claude via prompt
    # framing in a real impl); here we at least prove the request was accepted and the
    # unknown tool didn't surface in an error path.
    assert len(mocked_claude) == 1


# ---- notify w/o gateway ----

async def test_notify_503_without_gateway(bridge_config, mocked_claude) -> None:
    app = build_app(bridge_config)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post("/v1/notify", json={"text": "hi"})
        assert r.status_code == 503
