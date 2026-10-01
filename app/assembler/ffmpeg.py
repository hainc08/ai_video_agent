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


# --- the final video --------------------------------------------------------------------------

MAX_OUTPUT_BYTES = 100 * 1024 * 1024  # FR-11
_OUTPUT_FPS = 30
_LOGO_WIDTH_RATIO = 0.14
_LOGO_MARGIN_RATIO = 0.04
_MUSIC_VOLUME = 0.35


def _inside(folder: Path, path: Path) -> str:
    """`path` as FFmpeg should see it when run from `folder`: relative when possible.

    Filter options cannot hold a Windows drive colon without awkward escaping, so anything a
    filter references (subtitles, fonts) is passed relative to the working directory.
    """
    try:
        return Path(os.path.relpath(path, folder)).as_posix()
    except ValueError:  # another drive: no relative path exists
        return path.as_posix()


async def assemble(
    job_folder: Path,
    *,
    clips: list[Path],
    voices: list[Path],
    subtitles: Path,
    output: Path,
    size: tuple[int, int],
    music: Path | None,
    logo: Path | None,
    fonts_dir: Path | None,
    cfg: AssemblerConfig,
) -> None:
    """Join the scene clips with their voice tracks into `output` (H.264/AAC MP4 of `size`).

    Each clip's own audio is dropped. Subtitles are burned in; a logo and looped, ducked
    background music are added when given.
    """
    for path in [*clips, *voices, subtitles]:
        if not path.exists():
            raise AssemblyError(f"Thiếu file {path.name} nên không ghép được video.")
    width, height = size
    count = len(clips)
    total = 0.0
    for voice in voices:
        total += await probe_duration(voice, cfg.ffprobe_path)

    inputs: list[str] = []
    for path in [*clips, *voices]:
        inputs += ["-i", _inside(job_folder, path)]
    graph = [
        # Clips can differ in size and frame rate (Veo 720p/24 fps, other aspects): make them uniform.
        f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},"
        f"setsar=1,fps={_OUTPUT_FPS},format=yuv420p[v{i}]"
        for i in range(count)
    ]
    graph.append("".join(f"[v{i}]" for i in range(count)) + f"concat=n={count}:v=1:a=0[joined]")

    subtitle_filter = f"subtitles='{_inside(job_folder, subtitles)}'"
    fonts = _inside(job_folder, fonts_dir) if fonts_dir is not None and fonts_dir.is_dir() else None
    if fonts is not None and ":" not in fonts:
        subtitle_filter += f":fontsdir='{fonts}'"
    graph.append(f"[joined]{subtitle_filter}[titled]")
    video_out = "titled"

    next_input = 2 * count
    if logo is not None and logo.exists():
        inputs += ["-i", str(logo)]
        margin = round(min(width, height) * _LOGO_MARGIN_RATIO)
        graph.append(f"[{next_input}:v]scale={round(width * _LOGO_WIDTH_RATIO)}:-1[logo]")
        graph.append(f"[titled][logo]overlay=W-w-{margin}:{margin}[branded]")
        video_out = "branded"
        next_input += 1

    graph.append("".join(f"[{count + i}:a]" for i in range(count)) + f"concat=n={count}:v=0:a=1[voice]")
    audio_out = "voice"
    if music is not None and music.exists():
        inputs += ["-stream_loop", "-1", "-i", str(music)]  # looped: music may be shorter than the video
        graph.append("[voice]asplit=2[say][key]")
        graph.append(
            f"[{next_input}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={_MUSIC_VOLUME}[bed]"
        )
        # Ducking: the music drops while the voice speaks.
        graph.append("[bed][key]sidechaincompress=threshold=0.03:ratio=10:attack=20:release=350[ducked]")
        graph.append("[say][ducked]amix=inputs=2:duration=first:normalize=0[mixed]")
        audio_out = "mixed"

    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(output.stem + ".part.mp4")
    try:
        await run_ffmpeg(
            cfg.ffmpeg_path,
            [
                *inputs,
                "-filter_complex", ";".join(graph),
                "-map", f"[{video_out}]", "-map", f"[{audio_out}]",
                "-c:v", "libx264", "-preset", cfg.x264_preset, "-crf", "20", "-pix_fmt", "yuv420p",
                "-r", str(_OUTPUT_FPS),
                "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
                "-movflags", "+faststart",
                "-t", f"{total:.3f}",
                _inside(job_folder, partial),
            ],
            cwd=job_folder,
        )
        if partial.stat().st_size > MAX_OUTPUT_BYTES:
            megabytes = partial.stat().st_size / 1024 / 1024
            raise AssemblyError(f"Video ghép xong nặng {megabytes:.0f} MB, vượt giới hạn 100 MB.")
        os.replace(partial, output)  # the final name only ever holds a complete video
    finally:
        partial.unlink(missing_ok=True)
