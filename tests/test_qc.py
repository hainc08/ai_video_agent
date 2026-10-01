import shutil

import pytest

from app.agent.qc import ClipInfo, QCError, check_clip, probe_clip
from app.providers.base import ClipRequest
from app.providers.fake_video import FakeVideoProvider

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg is not installed on this machine",
)


async def make_clip(path, aspect="9:16", duration=4):
    provider = FakeVideoProvider("ffmpeg")
    operation = await provider.submit(ClipRequest(scene_no=1, prompt="x", aspect=aspect, duration_sec=duration))
    await provider.download(operation, path)
    return path


async def test_probe_reads_size_and_duration(tmp_path):
    clip = await make_clip(tmp_path / "a.mp4", "9:16", 4)

    info = await probe_clip(clip, "ffprobe")

    assert isinstance(info, ClipInfo)
    assert (info.width, info.height) == (720, 1280)
    assert abs(info.duration_sec - 4) <= 0.2


async def test_a_correct_clip_has_no_problems(tmp_path):
    clip = await make_clip(tmp_path / "a.mp4", "9:16", 6)

    assert await check_clip(clip, aspect="9:16", duration_sec=6, ffprobe_path="ffprobe") == []


async def test_wrong_aspect_ratio_is_reported(tmp_path):
    clip = await make_clip(tmp_path / "a.mp4", "16:9", 4)

    problems = await check_clip(clip, aspect="9:16", duration_sec=4, ffprobe_path="ffprobe")

    assert problems == ["sai tỉ lệ khung hình (clip 1280×720, cần 9:16)"]


async def test_wrong_duration_is_reported(tmp_path):
    clip = await make_clip(tmp_path / "a.mp4", "9:16", 4)

    problems = await check_clip(clip, aspect="9:16", duration_sec=8, ffprobe_path="ffprobe")

    assert problems == ["sai thời lượng (clip dài 4.0 giây, cần 8 giây)"]


async def test_both_problems_are_reported_together(tmp_path):
    clip = await make_clip(tmp_path / "a.mp4", "1:1", 4)

    problems = await check_clip(clip, aspect="16:9", duration_sec=8, ffprobe_path="ffprobe")

    assert len(problems) == 2


async def test_missing_empty_and_non_video_files_are_problems_not_crashes(tmp_path):
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    text = tmp_path / "text.mp4"
    text.write_text("this is not a video", encoding="utf-8")

    missing = await check_clip(tmp_path / "missing.mp4", aspect="9:16", duration_sec=4, ffprobe_path="ffprobe")
    zero = await check_clip(empty, aspect="9:16", duration_sec=4, ffprobe_path="ffprobe")
    garbage = await check_clip(text, aspect="9:16", duration_sec=4, ffprobe_path="ffprobe")

    assert missing == ["không tìm thấy file clip"]
    assert zero == ["file clip rỗng"]
    assert garbage == ["file clip không đọc được như một video"]


async def test_ffprobe_that_cannot_run_is_an_error_not_a_clip_problem(tmp_path):
    clip = await make_clip(tmp_path / "a.mp4")

    with pytest.raises(QCError, match="ffprobe"):
        await check_clip(clip, aspect="9:16", duration_sec=4, ffprobe_path="no-such-ffprobe-xyz")
