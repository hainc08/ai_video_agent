"""Clip quality check with ffprobe: is it a video, with the right shape and length (FR-09)."""
from __future__ import annotations

import asyncio
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

ASPECT_TOLERANCE = 0.02  # relative difference between the clip's ratio and the requested one
DURATION_TOLERANCE_SEC = 1.0
_TIMEOUT_SEC = 30


class QCError(Exception):
    """The check itself could not run (ffprobe missing or hung) — not a statement about the clip."""


class BadClipError(Exception):
    """The file is not a usable video; the message is the problem to report."""


@dataclass(frozen=True)
class ClipInfo:
    width: int
    height: int
    duration_sec: float


async def probe_clip(path: Path, ffprobe_path: str) -> ClipInfo:
    if not path.exists():
        raise BadClipError("không tìm thấy file clip")
    if path.stat().st_size == 0:
        raise BadClipError("file clip rỗng")
    command = [
        ffprobe_path, "-v", "error", "-print_format", "json",
        "-show_streams", "-show_format", str(path),
    ]
    try:
        # In a thread: asyncio's own subprocess API needs the Proactor loop on Windows.
        result = await asyncio.to_thread(
            subprocess.run, command, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=_TIMEOUT_SEC, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise QCError(
            f"Không chạy được ffprobe tại '{ffprobe_path}' ({type(exc).__name__}). "
            "Hãy kiểm tra assembler.ffprobe_path trong config.yaml."
        ) from exc
    try:
        data = json.loads(result.stdout or "{}")
        video = next(s for s in data.get("streams", []) if s.get("codec_type") == "video")
        duration = float(data["format"]["duration"])
        return ClipInfo(width=int(video["width"]), height=int(video["height"]), duration_sec=duration)
    except (StopIteration, KeyError, ValueError, TypeError):
        raise BadClipError("file clip không đọc được như một video") from None


async def check_clip(path: Path, *, aspect: str, duration_sec: int, ffprobe_path: str) -> list[str]:
    """Problems with the clip, in Vietnamese; an empty list means it passes."""
    try:
        info = await probe_clip(path, ffprobe_path)
    except BadClipError as exc:
        return [str(exc)]

    problems: list[str] = []
    wanted_w, wanted_h = (int(part) for part in aspect.split(":"))
    wanted_ratio = wanted_w / wanted_h
    if abs(info.width / info.height - wanted_ratio) / wanted_ratio > ASPECT_TOLERANCE:
        problems.append(f"sai tỉ lệ khung hình (clip {info.width}×{info.height}, cần {aspect})")
    if abs(info.duration_sec - duration_sec) > DURATION_TOLERANCE_SEC:
        problems.append(f"sai thời lượng (clip dài {info.duration_sec:.1f} giây, cần {duration_sec} giây)")
    return problems
