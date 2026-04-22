"""OpenAI client for Whisper (speech-to-text) and TTS (text-to-speech).

Used only for Telegram voice notes. Key lives host-side in bridge config and
is NEVER exposed to the container. Both functions return cost_usd so the
bridge can charge against the shared daily budget.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

_API = "https://api.openai.com/v1"


class OpenAIError(Exception):
    pass


# --- Pricing as of Jan 2026. Update if OpenAI changes rates. -----------------
# Whisper bills by audio MINUTE (rounded up to the second per OpenAI docs).
_WHISPER_USD_PER_MINUTE = 0.006

# TTS bills by CHARACTER. tts-1 and tts-1-hd have different rates.
_TTS_USD_PER_1M_CHARS = {
    "tts-1": 15.0,
    "tts-1-hd": 30.0,
}


@dataclass
class TranscribeResult:
    text: str
    audio_seconds: float
    cost_usd: float


@dataclass
class TTSResult:
    audio_bytes: bytes
    content_type: str
    chars: int
    cost_usd: float


class OpenAIClient:
    def __init__(
        self,
        *,
        api_key: str,
        whisper_model: str = "whisper-1",
        tts_model: str = "tts-1-hd",
        tts_voice: str = "nova",
        timeout_seconds: float = 60.0,
    ) -> None:
        if not api_key:
            raise ValueError("openai api_key is required")
        self._key = api_key
        self._whisper_model = whisper_model
        self._tts_model = tts_model
        self._tts_voice = tts_voice
        self._timeout = timeout_seconds

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key}"}

    async def transcribe(
        self, audio_bytes: bytes, *, filename: str = "voice.ogg", audio_seconds: float | None = None
    ) -> TranscribeResult:
        """Send audio to Whisper. If caller knows duration, we bill accurately;
        otherwise we estimate from file size (OGG Opus ~ 6KB/sec at default bitrate)."""
        if not audio_bytes:
            raise ValueError("empty audio")

        seconds = float(audio_seconds) if audio_seconds else max(1.0, len(audio_bytes) / 6000.0)
        cost = (seconds / 60.0) * _WHISPER_USD_PER_MINUTE

        files = {
            "file": (filename, audio_bytes, "audio/ogg"),
            "model": (None, self._whisper_model),
            "response_format": (None, "json"),
        }
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.post(
                f"{_API}/audio/transcriptions",
                headers=self._headers(),
                files=files,
            )
        if r.status_code != 200:
            raise OpenAIError(f"whisper {r.status_code}: {r.text[:300]}")
        data = r.json()
        return TranscribeResult(
            text=str(data.get("text", "")),
            audio_seconds=seconds,
            cost_usd=cost,
        )

    async def tts(self, text: str, *, voice: str | None = None) -> TTSResult:
        """Send text to TTS. Requests OGG Opus so the result is ready to post as
        a Telegram voice note without re-encoding."""
        if not text:
            raise ValueError("empty text")
        chars = len(text)
        rate = _TTS_USD_PER_1M_CHARS.get(self._tts_model, _TTS_USD_PER_1M_CHARS["tts-1-hd"])
        cost = (chars / 1_000_000.0) * rate

        payload = {
            "model": self._tts_model,
            "input": text,
            "voice": voice or self._tts_voice,
            "response_format": "opus",
        }
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.post(
                f"{_API}/audio/speech",
                headers={**self._headers(), "Content-Type": "application/json"},
                json=payload,
            )
        if r.status_code != 200:
            raise OpenAIError(f"tts {r.status_code}: {r.text[:300]}")
        return TTSResult(
            audio_bytes=r.content,
            content_type=r.headers.get("content-type", "audio/ogg"),
            chars=chars,
            cost_usd=cost,
        )
