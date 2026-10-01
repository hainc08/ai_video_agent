"""FFmpeg helpers. Phase 0 only checks that the binaries run; assembly comes in Phase 4."""
from __future__ import annotations

import subprocess

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
