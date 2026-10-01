"""Free stand-in for Veo: FFmpeg draws a solid-colour clip with the scene number on it."""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from uuid import uuid4

from app.providers.base import ClipRequest, PollResult, ProviderError, frame_size

_COLOURS = ("0x1D4ED8", "0xC2410C", "0x15803D", "0x7C3AED", "0x0E7490", "0xB45309")
# drawtext needs a font file; the clip is still valid without the number when none is found.
_FONT_CANDIDATES = (
    Path("C:/Windows/Fonts/arial.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
)
_TIMEOUT_SEC = 120


def _number_filter(scene_no: int) -> list[str]:
    font = next((path for path in _FONT_CANDIDATES if path.exists()), None)
    if font is None:
        return []
    # Inside a filter graph ':' separates options, so the drive colon must be escaped.
    fontfile = font.as_posix().replace(":", "\\:")
    return [
        "-vf",
        f"drawtext=fontfile='{fontfile}':text='{scene_no}':fontsize=h/4:fontcolor=white"
        ":x=(w-text_w)/2:y=(h-text_h)/2",
    ]


class FakeVideoProvider:
    name = "fake"
    price_usd_per_second = 0.0
    supported_aspects = frozenset({"9:16", "16:9", "1:1"})

    def __init__(self, ffmpeg_path: str) -> None:
        self._ffmpeg = ffmpeg_path
        self._requests: dict[str, ClipRequest] = {}

    async def submit(self, request: ClipRequest) -> str:
        frame_size(request.aspect)  # reject an unknown aspect before "generating"
        operation_id = f"fake-{uuid4().hex[:12]}"
        self._requests[operation_id] = request
        return operation_id

    async def poll(self, operation_id: str) -> PollResult:
        self._request(operation_id)
        return PollResult("done")

    async def download(self, operation_id: str, path: Path) -> None:
        request = self._request(operation_id)
        width, height = frame_size(request.aspect)
        colour = _COLOURS[(request.scene_no - 1) % len(_COLOURS)]
        path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            self._ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"color=c={colour}:s={width}x{height}:r=24:d={request.duration_sec}",
            # Veo clips always carry audio, so the stand-in does too (silence).
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
            *_number_filter(request.scene_no),
            "-t", str(request.duration_sec),
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest",
            str(path),
        ]
        # In a thread, not asyncio's subprocess API: that needs the Proactor loop on Windows,
        # which uvicorn does not always use.
        try:
            result = await asyncio.to_thread(
                subprocess.run, command, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=_TIMEOUT_SEC, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ProviderError(
                f"Không chạy được FFmpeg tại '{self._ffmpeg}' để tạo clip giả ({type(exc).__name__})."
            ) from exc
        if result.returncode != 0:
            path.unlink(missing_ok=True)
            raise ProviderError(f"FFmpeg không tạo được clip giả: {result.stderr.strip()[-300:]}")

    def _request(self, operation_id: str) -> ClipRequest:
        try:
            return self._requests[operation_id]
        except KeyError:
            raise ProviderError(f"Không tìm thấy tác vụ sinh clip '{operation_id}'.") from None
