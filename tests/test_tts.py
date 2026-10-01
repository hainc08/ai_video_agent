import json
import shutil
import subprocess

import aiohttp
import pytest

from app.config import load_settings
from app.options import VOICES, voice_label
from app.providers import build_tts_provider
from app.providers.base import ProviderError
from app.providers.tts_edge import EdgeTTSProvider
from app.providers.tts_fake import FakeTTSProvider

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg is not installed on this machine",
)


def audio_info(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    data = json.loads(out)
    return data["streams"], float(data["format"]["duration"])


class FakeCommunicate:
    """Stands in for edge_tts.Communicate: records what was asked, yields scripted chunks."""

    calls = []
    chunks = [{"type": "audio", "data": b"mp3-"}, {"type": "SentenceBoundary"}, {"type": "audio", "data": b"bytes"}]
    error = None

    def __init__(self, text, voice, **kwargs):
        type(self).calls.append((text, voice))

    async def stream(self):
        for chunk in type(self).chunks:
            yield chunk
        if type(self).error is not None:
            raise type(self).error


@pytest.fixture
def communicate():
    FakeCommunicate.calls = []
    FakeCommunicate.chunks = [
        {"type": "audio", "data": b"mp3-"}, {"type": "SentenceBoundary"}, {"type": "audio", "data": b"bytes"},
    ]
    FakeCommunicate.error = None
    return FakeCommunicate


# --- options ------------------------------------------------------------------------


def test_the_form_offers_the_two_voices_that_exist():
    assert VOICES == {"vi-female-north": "Nữ (Hoài My)", "vi-male-north": "Nam (Nam Minh)"}
    assert voice_label("vi-female-south") == "Nữ (Hoài My)"  # a job made before the south voice was retired
    assert voice_label("something-else") == "something-else"


# --- fake -----------------------------------------------------------------------------


@needs_ffmpeg
async def test_fake_tts_writes_silence_about_as_long_as_the_words_take(tmp_path):
    provider = FakeTTSProvider("ffmpeg")
    target = tmp_path / "audio" / "voice.wav"

    await provider.synthesize(" ".join(["từ"] * 11), "vi-female-north", target)

    streams, duration = audio_info(target)
    assert provider.name == "fake" and provider.price_usd_per_1k_chars == 0
    assert [s["codec_type"] for s in streams] == ["audio"]
    assert abs(duration - 4.0) <= 0.1  # 11 words at 2.75 words/second


@needs_ffmpeg
async def test_fake_tts_never_writes_an_empty_file(tmp_path):
    provider = FakeTTSProvider("ffmpeg")

    await provider.synthesize("À", "vi-female-north", tmp_path / "voice.wav")

    assert audio_info(tmp_path / "voice.wav")[1] >= 0.5


# --- edge -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "voice, edge_voice",
    [
        ("vi-female-north", "vi-VN-HoaiMyNeural"),
        ("vi-male-north", "vi-VN-NamMinhNeural"),
        ("vi-female-south", "vi-VN-HoaiMyNeural"),
        ("a-voice-nobody-knows", "vi-VN-HoaiMyNeural"),
    ],
)
async def test_edge_tts_maps_the_voice_and_writes_the_audio_chunks(tmp_path, communicate, voice, edge_voice):
    provider = EdgeTTSProvider(communicate)
    target = tmp_path / "audio" / "voice.mp3"

    await provider.synthesize("Xin chào các bạn.", voice, target)

    assert communicate.calls == [("Xin chào các bạn.", edge_voice)]
    assert target.read_bytes() == b"mp3-bytes"
    assert provider.name == "edge" and provider.price_usd_per_1k_chars == 0


async def test_edge_tts_without_any_audio_is_an_error_and_leaves_no_file(tmp_path, communicate):
    communicate.chunks = [{"type": "SentenceBoundary"}]

    with pytest.raises(ProviderError, match="không trả về âm thanh") as excinfo:
        await EdgeTTSProvider(communicate).synthesize("Xin chào.", "vi-female-north", tmp_path / "voice.mp3")

    assert excinfo.value.retryable is True
    assert not (tmp_path / "voice.mp3").exists()


@pytest.mark.parametrize("error", [aiohttp.ClientConnectionError("reset"), TimeoutError(), OSError("network down")])
async def test_edge_tts_network_trouble_is_retryable_and_removes_the_partial_file(tmp_path, communicate, error):
    communicate.error = error

    with pytest.raises(ProviderError) as excinfo:
        await EdgeTTSProvider(communicate).synthesize("Xin chào.", "vi-female-north", tmp_path / "voice.mp3")

    assert excinfo.value.retryable is True
    assert "Edge" in str(excinfo.value)
    assert not (tmp_path / "voice.mp3").exists()


@pytest.mark.parametrize("text", ["", "   ", "...", "—"])
async def test_edge_tts_refuses_text_with_nothing_to_say_without_calling_the_service(tmp_path, communicate, text):
    with pytest.raises(ProviderError) as excinfo:
        await EdgeTTSProvider(communicate).synthesize(text, "vi-female-north", tmp_path / "voice.mp3")

    assert excinfo.value.retryable is False
    assert communicate.calls == []


# --- factory --------------------------------------------------------------------------


def test_edge_is_the_default_tts(settings):
    assert settings.secrets.tts_provider == "edge"
    assert isinstance(build_tts_provider(settings), EdgeTTSProvider)


def test_fake_tts_can_be_selected(project_root):
    (project_root / ".env").write_text("TTS_PROVIDER=fake\n", encoding="utf-8")

    assert isinstance(build_tts_provider(load_settings(project_root)), FakeTTSProvider)
