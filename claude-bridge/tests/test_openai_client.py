"""Unit tests for OpenAIClient (transcribe + TTS). All network mocked."""
from __future__ import annotations

import httpx
import pytest

from bridge.openai_client import OpenAIClient, OpenAIError


def _mock_transport(handler):
    return httpx.MockTransport(handler)


@pytest.fixture
def client(monkeypatch) -> OpenAIClient:
    return OpenAIClient(api_key="sk-test", whisper_model="whisper-1", tts_model="tts-1-hd", tts_voice="nova")


def test_rejects_empty_api_key() -> None:
    with pytest.raises(ValueError):
        OpenAIClient(api_key="")


async def test_transcribe_posts_audio_and_returns_text(client, monkeypatch) -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"text": "hello world"})

    class _MockAsyncClient(httpx.AsyncClient):
        def __init__(self, *a, **kw):
            kw["transport"] = _mock_transport(handler)
            super().__init__(*a, **kw)

    monkeypatch.setattr("bridge.openai_client.httpx.AsyncClient", _MockAsyncClient)

    res = await client.transcribe(b"x" * 12000, audio_seconds=2.0)
    assert res.text == "hello world"
    assert res.audio_seconds == 2.0
    # Whisper: 2s at $0.006/min
    assert res.cost_usd == pytest.approx(0.006 * 2 / 60)
    assert "transcriptions" in seen["url"]
    assert seen["auth"] == "Bearer sk-test"


async def test_transcribe_estimates_duration_if_not_given(client, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"text": "ok"})

    class _MockAsyncClient(httpx.AsyncClient):
        def __init__(self, *a, **kw):
            kw["transport"] = _mock_transport(handler)
            super().__init__(*a, **kw)

    monkeypatch.setattr("bridge.openai_client.httpx.AsyncClient", _MockAsyncClient)

    # 60000 bytes @ 6KB/sec ~= 10 sec estimated
    res = await client.transcribe(b"x" * 60000)
    assert res.audio_seconds == pytest.approx(10.0)


async def test_transcribe_raises_on_non_200(client, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="bad key")

    class _MockAsyncClient(httpx.AsyncClient):
        def __init__(self, *a, **kw):
            kw["transport"] = _mock_transport(handler)
            super().__init__(*a, **kw)

    monkeypatch.setattr("bridge.openai_client.httpx.AsyncClient", _MockAsyncClient)

    with pytest.raises(OpenAIError, match="401"):
        await client.transcribe(b"xxx")


async def test_transcribe_rejects_empty_audio(client) -> None:
    with pytest.raises(ValueError):
        await client.transcribe(b"")


async def test_tts_returns_ogg_and_billed_per_char(client, monkeypatch) -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, content=b"\x00\x01OGG_FAKE_BYTES", headers={"content-type": "audio/ogg"})

    class _MockAsyncClient(httpx.AsyncClient):
        def __init__(self, *a, **kw):
            kw["transport"] = _mock_transport(handler)
            super().__init__(*a, **kw)

    monkeypatch.setattr("bridge.openai_client.httpx.AsyncClient", _MockAsyncClient)

    text = "hello there general kenobi"
    res = await client.tts(text)
    assert res.audio_bytes.endswith(b"OGG_FAKE_BYTES")
    assert res.chars == len(text)
    # tts-1-hd: $30/1M chars
    assert res.cost_usd == pytest.approx(len(text) / 1_000_000 * 30)
    # Verify we requested OGG Opus so Telegram can send it as-is.
    assert captured["payload"]["response_format"] == "opus"
    assert captured["payload"]["voice"] == "nova"


async def test_tts_rejects_empty_text(client) -> None:
    with pytest.raises(ValueError):
        await client.tts("")


async def test_tts_voice_override(client, monkeypatch) -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, content=b"ogg", headers={"content-type": "audio/ogg"})

    class _MockAsyncClient(httpx.AsyncClient):
        def __init__(self, *a, **kw):
            kw["transport"] = _mock_transport(handler)
            super().__init__(*a, **kw)

    monkeypatch.setattr("bridge.openai_client.httpx.AsyncClient", _MockAsyncClient)

    await client.tts("hi", voice="shimmer")
    assert captured["payload"]["voice"] == "shimmer"
