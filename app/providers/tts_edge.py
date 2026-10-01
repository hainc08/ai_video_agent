"""Vietnamese voice-over through Microsoft Edge's read-aloud service (the `edge-tts` package).

Free and keyless, but unofficial: no SLA, and it can rate-limit or change without notice,
so every failure is reported as retryable and the caller decides how long to insist.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import aiohttp
import edge_tts
from edge_tts.exceptions import EdgeTTSException

from app.providers.base import ProviderError

_FEMALE = "vi-VN-HoaiMyNeural"
_MALE = "vi-VN-NamMinhNeural"
# Edge has exactly one female and one male Vietnamese voice. Keys of voices the form no
# longer offers still resolve, so older jobs keep working.
_VOICES = {
    "vi-female-north": _FEMALE,
    "vi-female-south": _FEMALE,
    "vi-male-north": _MALE,
}
_NETWORK_ERRORS = (EdgeTTSException, aiohttp.ClientError, asyncio.TimeoutError, OSError)


class EdgeTTSProvider:
    name = "edge"
    price_usd_per_1k_chars = 0.0

    def __init__(self, communicate: Any = edge_tts.Communicate) -> None:
        self._communicate = communicate

    async def synthesize(self, text: str, voice: str, path: Path) -> None:
        text = text.strip()
        if not any(ch.isalnum() for ch in text):
            raise ProviderError("Lời thoại trống nên không có gì để đọc.")
        path.parent.mkdir(parents=True, exist_ok=True)
        received = 0
        try:
            with path.open("wb") as handle:
                async for chunk in self._communicate(text, _VOICES.get(voice, _FEMALE)).stream():
                    if chunk["type"] == "audio":
                        handle.write(chunk["data"])
                        received += len(chunk["data"])
        except _NETWORK_ERRORS as exc:
            path.unlink(missing_ok=True)
            raise ProviderError(
                f"Dịch vụ giọng đọc Edge không phản hồi ({type(exc).__name__}).", retryable=True
            ) from exc
        if received == 0:
            path.unlink(missing_ok=True)
            raise ProviderError("Dịch vụ giọng đọc Edge không trả về âm thanh.", retryable=True)
