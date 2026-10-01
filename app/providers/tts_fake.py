"""Free stand-in for a TTS service: silence about as long as the text would take to read."""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from app.providers.base import ProviderError

_WORDS_PER_SEC = 2.75
_MIN_SEC = 0.5
_TIMEOUT_SEC = 60


class FakeTTSProvider:
    name = "fake"
    price_usd_per_1k_chars = 0.0

    def __init__(self, ffmpeg_path: str) -> None:
        self._ffmpeg = ffmpeg_path

    async def synthesize(self, text: str, voice: str, path: Path) -> None:
        seconds = max(_MIN_SEC, len(text.split()) / _WORDS_PER_SEC)
        path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            self._ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
            "-t", f"{seconds:.3f}", str(path),
        ]
        try:
            result = await asyncio.to_thread(
                subprocess.run, command, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=_TIMEOUT_SEC, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ProviderError(
                f"Không chạy được FFmpeg tại '{self._ffmpeg}' để tạo giọng đọc giả ({type(exc).__name__})."
            ) from exc
        if result.returncode != 0:
            path.unlink(missing_ok=True)
            raise ProviderError(f"FFmpeg không tạo được giọng đọc giả: {result.stderr.strip()[-300:]}")
