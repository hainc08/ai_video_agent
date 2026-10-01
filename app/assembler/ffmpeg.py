"""FFmpeg helpers: the startup check, and the audio/video steps that build the final video."""
from __future__ import annotations

import asyncio
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.config import AssemblerConfig

_CHECK_TIMEOUT_SEC = 10


class FFmpegNotFoundError(Exception):
    """ffmpeg or ffprobe cannot be executed."""


def _version(binary: str, name: str) -> str:
    hint = (
        f"Không chạy được {name} tại '{binary}'. Hãy cài FFmpeg và thêm vào PATH, "
        f"hoặc sửa assembler.{name}_path trong config.yaml."
    )
    try:
        proc = subprocess.run(
            [binary, "-version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_CHECK_TIMEOUT_SEC,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FFmpegNotFoundError(hint) from exc
    if proc.returncode != 0 or not proc.stdout:
        raise FFmpegNotFoundError(hint)
    return proc.stdout.splitlines()[0].strip()


def check_binaries(cfg: AssemblerConfig) -> dict[str, str]:
    return {
        "ffmpeg": _version(cfg.ffmpeg_path, "ffmpeg"),
        "ffprobe": _version(cfg.ffprobe_path, "ffprobe"),
    }


# --- running FFmpeg for the assembly steps (Phase 4) ----------------------------------------

_RUN_TIMEOUT_SEC = 900
MAX_VOICE_SPEED = 1.5  # beyond this a voice sounds wrong, so the rest is cut instead


class AssemblyError(Exception):
    """A voice, subtitle or assembly step failed; the message is shown to the user."""


@dataclass(frozen=True)
class FitResult:
    speed: float  # tempo applied to the voice (1.0 = unchanged)
    cut: bool  # True when even the fastest allowed tempo did not fit and the end was cut off


async def _run(binary: str, args: list[str], *, cwd: Path | None, timeout: float, key: str) -> str:
    """Run an FFmpeg tool in a thread (asyncio's subprocess API needs the Proactor loop on Windows)."""
    try:
        result = await asyncio.to_thread(
            subprocess.run, [binary, *args], cwd=cwd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AssemblyError(
            f"Không chạy được FFmpeg tại '{binary}' ({type(exc).__name__}). "
            f"Hãy kiểm tra assembler.{key} trong config.yaml."
        ) from exc
    if result.returncode != 0:
        raise AssemblyError(f"FFmpeg báo lỗi: {result.stderr.strip()[-600:]}")
    return result.stdout


async def run_ffmpeg(
    ffmpeg_path: str, args: list[str], *, cwd: Path | None = None, timeout: float = _RUN_TIMEOUT_SEC
) -> None:
    await _run(ffmpeg_path, ["-hide_banner", "-loglevel", "error", "-y", *args], cwd=cwd, timeout=timeout,
               key="ffmpeg_path")


async def probe_duration(path: Path, ffprobe_path: str) -> float:
    try:
        out = await _run(
            ffprobe_path,
            ["-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
            cwd=None, timeout=60, key="ffprobe_path",
        )
        return float(out.strip())
    except ValueError:
        raise AssemblyError(f"Không đọc được thời lượng của file '{path.name}'.") from None


def output_size(aspect: str, cfg: AssemblerConfig) -> tuple[int, int]:
    """Frame size of the final video: the configured 9:16 size, turned or squared for other aspects."""
    short, long = sorted((cfg.output_width, cfg.output_height))
    sizes = {"9:16": (short, long), "16:9": (long, short), "1:1": (short, short)}
    try:
        return sizes[aspect]
    except KeyError:
        raise AssemblyError(f"Tỉ lệ khung hình không được hỗ trợ khi ghép video: {aspect}") from None


async def fit_audio(source: Path, target: Path, *, target_sec: float, cfg: AssemblerConfig) -> FitResult:
    """Write `source` as a 48 kHz stereo WAV lasting exactly `target_sec`.

    Shorter speech is padded with silence; longer speech is sped up, at most MAX_VOICE_SPEED,
    and whatever still does not fit is cut. Every scene's voice is then as long as its clip,
    so the voices stay aligned with the pictures when they are joined.
    """
    duration = await probe_duration(source, cfg.ffprobe_path)
    speed = max(1.0, duration / target_sec)
    cut = speed > MAX_VOICE_SPEED
    speed = min(speed, MAX_VOICE_SPEED)
    filters = ([f"atempo={speed:.4f}"] if speed > 1.001 else []) + ["apad"]
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.stem + ".part.wav")
    try:
        await run_ffmpeg(
            cfg.ffmpeg_path,
            ["-i", str(source), "-af", ",".join(filters), "-t", f"{target_sec:.3f}",
             "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(partial)],
        )
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    return FitResult(speed=round(speed, 4), cut=cut)
