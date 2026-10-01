import shutil
import subprocess

import pytest

from app.assembler import ffmpeg
from app.assembler.ffmpeg import FFmpegNotFoundError, check_binaries
from app.config import AssemblerConfig


def test_missing_binary_names_the_config_key_to_fix():
    cfg = AssemblerConfig(ffmpeg_path="no-such-ffmpeg-binary-xyz")

    with pytest.raises(FFmpegNotFoundError, match="assembler.ffmpeg_path"):
        check_binaries(cfg)


def test_runs_each_binary_with_an_argument_list_and_no_shell(monkeypatch):
    seen = []

    def fake_run(cmd, **kwargs):
        seen.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, stdout="ffmpeg version 7.1\nbuilt with gcc\n", stderr="")

    monkeypatch.setattr(ffmpeg.subprocess, "run", fake_run)
    cfg = AssemblerConfig(ffmpeg_path="C:/tools/ffmpeg.exe", ffprobe_path="C:/tools/ffprobe.exe")

    versions = check_binaries(cfg)

    assert versions == {"ffmpeg": "ffmpeg version 7.1", "ffprobe": "ffmpeg version 7.1"}
    assert [cmd for cmd, _ in seen] == [
        ["C:/tools/ffmpeg.exe", "-version"],
        ["C:/tools/ffprobe.exe", "-version"],
    ]
    assert all(kwargs.get("shell", False) is False for _, kwargs in seen)


def test_non_zero_exit_is_reported_as_not_runnable(monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")

    monkeypatch.setattr(ffmpeg.subprocess, "run", fake_run)

    with pytest.raises(FFmpegNotFoundError, match="assembler.ffmpeg_path"):
        check_binaries(AssemblerConfig())


def test_hung_binary_is_reported_as_not_runnable(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(ffmpeg.subprocess, "run", fake_run)

    with pytest.raises(FFmpegNotFoundError):
        check_binaries(AssemblerConfig())


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg is not installed on this machine",
)
def test_real_binaries_report_their_version():
    versions = check_binaries(AssemblerConfig())

    assert versions["ffmpeg"].startswith("ffmpeg version")
    assert versions["ffprobe"].startswith("ffprobe version")
