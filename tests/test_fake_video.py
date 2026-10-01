import json
import shutil
import subprocess

import pytest

from app.providers.base import ClipRequest, ProviderError, frame_size
from app.providers.fake_video import FakeVideoProvider

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg is not installed on this machine",
)


def streams(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    data = json.loads(out)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    audio = [s for s in data["streams"] if s["codec_type"] == "audio"]
    return video, audio, float(data["format"]["duration"])


@pytest.mark.parametrize(
    "aspect, size", [("9:16", (720, 1280)), ("16:9", (1280, 720)), ("1:1", (720, 720))]
)
def test_frame_size(aspect, size):
    assert frame_size(aspect) == size


def test_frame_size_of_an_unknown_aspect_is_an_error():
    with pytest.raises(ProviderError):
        frame_size("4:3")


def test_fake_provider_is_free_and_supports_every_aspect_on_the_form():
    provider = FakeVideoProvider("ffmpeg")

    assert provider.name == "fake"
    assert provider.price_usd_per_second == 0
    assert provider.supported_aspects == {"9:16", "16:9", "1:1"}


@needs_ffmpeg
@pytest.mark.parametrize("aspect, duration", [("9:16", 4), ("16:9", 6), ("1:1", 8)])
async def test_clip_has_the_requested_size_length_and_an_audio_track(tmp_path, aspect, duration):
    provider = FakeVideoProvider("ffmpeg")
    target = tmp_path / "clips" / "scene_03.mp4"  # the folder does not exist yet

    operation = await provider.submit(ClipRequest(scene_no=3, prompt="an office", aspect=aspect, duration_sec=duration))
    state = await provider.poll(operation)
    await provider.download(operation, target)

    video, audio, length = streams(target)
    assert state.state == "done"
    assert (video["width"], video["height"]) == frame_size(aspect)
    assert video["codec_name"] == "h264"
    assert abs(length - duration) <= 0.2
    assert len(audio) == 1


async def test_unknown_operation_is_a_provider_error(tmp_path):
    provider = FakeVideoProvider("ffmpeg")

    with pytest.raises(ProviderError):
        await provider.poll("nope")
    with pytest.raises(ProviderError):
        await provider.download("nope", tmp_path / "x.mp4")


async def test_missing_ffmpeg_is_a_clear_error_and_leaves_no_file(tmp_path):
    provider = FakeVideoProvider("no-such-ffmpeg-binary-xyz")
    operation = await provider.submit(ClipRequest(scene_no=1, prompt="x", aspect="9:16", duration_sec=4))

    with pytest.raises(ProviderError, match="FFmpeg") as excinfo:
        await provider.download(operation, tmp_path / "x.mp4")

    assert excinfo.value.retryable is False
    assert not (tmp_path / "x.mp4").exists()
