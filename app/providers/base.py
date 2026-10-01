"""The contracts video and TTS providers implement (REQUIREMENTS §5)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

_FRAME_SIZES = {"9:16": (720, 1280), "16:9": (1280, 720), "1:1": (720, 720)}


class ProviderError(Exception):
    """A provider call failed. `retryable` says whether trying the same request again can help."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class ContentFilteredError(ProviderError):
    """The provider's safety filter blocked the prompt: it must be rewritten, never resent as is."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=False)


@dataclass(frozen=True)
class ClipRequest:
    scene_no: int
    prompt: str
    aspect: str
    duration_sec: int


@dataclass(frozen=True)
class PollResult:
    state: Literal["running", "done", "failed"]
    message: str | None = None


class VideoProvider(Protocol):
    name: str
    price_usd_per_second: float
    supported_aspects: frozenset[str]

    async def submit(self, request: ClipRequest) -> str:
        """Start generating one clip; returns an operation id."""

    async def poll(self, operation_id: str) -> PollResult:
        """Where the operation stands. Raises ContentFilteredError when the prompt was blocked."""

    async def download(self, operation_id: str, path: Path) -> None:
        """Write the finished clip to `path` (creating its folder)."""


class TTSProvider(Protocol):
    name: str
    price_usd_per_1k_chars: float

    async def synthesize(self, text: str, voice: str, path: Path) -> None:
        """Write the spoken text to `path` (any format FFmpeg reads), creating its folder.

        `voice` is one of the app's voice keys (app.options.VOICES). Raises ProviderError.
        """


def frame_size(aspect: str) -> tuple[int, int]:
    try:
        return _FRAME_SIZES[aspect]
    except KeyError:
        raise ProviderError(f"Tỉ lệ khung hình không được hỗ trợ: {aspect}") from None
