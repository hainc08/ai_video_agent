from types import SimpleNamespace as NS

import pytest
from google.genai import errors

from app.config import VeoConfig, load_settings
from app.providers import build_video_provider
from app.providers.base import ClipRequest, ContentFilteredError, ProviderError
from app.providers.fake_video import FakeVideoProvider
from app.providers.veo_gemini import VeoProvider

CONFIG = VeoConfig(model="veo-3.1-fast-generate-preview", resolution="720p", price_usd_per_second=0.1)
REQUEST = ClipRequest(scene_no=2, prompt="An office, no on-screen text, no logos", aspect="9:16", duration_sec=6)


class FakeAPIError(errors.APIError):
    def __init__(self, code):
        Exception.__init__(self, "bad request for key AIza-secret-should-not-leak")
        self.code = code


class FakeVideo:
    def __init__(self, data=b"mp4-bytes"):
        self.data = data
        self.downloaded = False

    def save(self, path):
        assert self.downloaded, "files.download must be called before save"
        with open(path, "wb") as handle:
            handle.write(self.data)


def operation(name="operations/op-1", *, done=False, error=None, videos=None, filtered=0, reasons=None):
    response = None
    if done and error is None:
        response = NS(
            generated_videos=[NS(video=video) for video in (videos or [])],
            rai_media_filtered_count=filtered,
            rai_media_filtered_reasons=reasons,
        )
    return NS(name=name, done=done, error=error, response=response)


class FakeVeoClient:
    """Stands in for google.genai.Client: scripted operations, every call recorded."""

    def __init__(self, *, start=None, polls=()):
        self._start = start if start is not None else operation()
        self._polls = list(polls)
        self.generate_calls = []
        self.poll_calls = []
        self.aio = NS(
            models=NS(generate_videos=self._generate),
            operations=NS(get=self._get),
            files=NS(download=self._download),
        )

    async def _generate(self, **kwargs):
        self.generate_calls.append(kwargs)
        if isinstance(self._start, Exception):
            raise self._start
        return self._start

    async def _get(self, current):
        self.poll_calls.append(current.name)
        outcome = self._polls.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def _download(self, *, file):
        file.downloaded = True


def test_provider_reports_its_price_and_supported_aspects():
    provider = VeoProvider(FakeVeoClient(), CONFIG)

    assert provider.name == "veo"
    assert provider.price_usd_per_second == 0.1
    assert provider.supported_aspects == {"9:16", "16:9"}


async def test_submit_sends_model_prompt_aspect_and_duration():
    client = FakeVeoClient()

    operation_id = await VeoProvider(client, CONFIG).submit(REQUEST)

    (call,) = client.generate_calls
    assert operation_id == "operations/op-1"
    assert call["model"] == "veo-3.1-fast-generate-preview"
    assert call["prompt"] == REQUEST.prompt
    assert call["config"].aspect_ratio == "9:16"
    assert call["config"].duration_seconds == 6
    assert call["config"].resolution == "720p"
    assert call["config"].number_of_videos == 1


@pytest.mark.parametrize("duration, expected", [(4, "720p"), (6, "720p"), (8, "1080p")])
async def test_high_resolution_is_only_requested_for_eight_second_clips(duration, expected):
    client = FakeVeoClient()
    config = VeoConfig(model="veo-3.1-generate-preview", resolution="1080p", price_usd_per_second=0.4)

    await VeoProvider(client, config).submit(ClipRequest(scene_no=1, prompt="x", aspect="16:9", duration_sec=duration))

    assert client.generate_calls[0]["config"].resolution == expected


async def test_square_video_is_refused_before_calling_the_api():
    client = FakeVeoClient()

    with pytest.raises(ProviderError, match="1:1") as excinfo:
        await VeoProvider(client, CONFIG).submit(ClipRequest(scene_no=1, prompt="x", aspect="1:1", duration_sec=4))

    assert excinfo.value.retryable is False
    assert client.generate_calls == []


@pytest.mark.parametrize("code, retryable", [(429, True), (500, True), (503, True), (400, False), (403, False)])
async def test_submit_errors_say_whether_a_retry_can_help(code, retryable):
    client = FakeVeoClient(start=FakeAPIError(code))

    with pytest.raises(ProviderError) as excinfo:
        await VeoProvider(client, CONFIG).submit(REQUEST)

    assert excinfo.value.retryable is retryable
    assert str(code) in str(excinfo.value)
    assert "AIza-secret" not in str(excinfo.value)


async def test_poll_is_running_until_the_operation_is_done():
    video = FakeVideo()
    client = FakeVeoClient(polls=[operation(), operation(done=True, videos=[video])])
    provider = VeoProvider(client, CONFIG)
    operation_id = await provider.submit(REQUEST)

    first = await provider.poll(operation_id)
    second = await provider.poll(operation_id)

    assert (first.state, second.state) == ("running", "done")
    assert client.poll_calls == ["operations/op-1", "operations/op-1"]


async def test_download_saves_the_video_and_creates_the_folder(tmp_path):
    client = FakeVeoClient(polls=[operation(done=True, videos=[FakeVideo(b"clip")])])
    provider = VeoProvider(client, CONFIG)
    operation_id = await provider.submit(REQUEST)
    await provider.poll(operation_id)
    target = tmp_path / "clips" / "scene_02.mp4"

    await provider.download(operation_id, target)

    assert target.read_bytes() == b"clip"


async def test_an_operation_that_ends_with_an_error_is_failed_with_its_message():
    client = FakeVeoClient(polls=[operation(done=True, error={"code": 13, "message": "Internal error while rendering"})])
    provider = VeoProvider(client, CONFIG)
    operation_id = await provider.submit(REQUEST)

    result = await provider.poll(operation_id)

    assert result.state == "failed"
    assert "Internal error while rendering" in result.message


async def test_a_safety_filtered_prompt_raises_content_filtered_with_the_reasons():
    client = FakeVeoClient(polls=[operation(done=True, filtered=1, reasons=["Violence is not allowed"])])
    provider = VeoProvider(client, CONFIG)
    operation_id = await provider.submit(REQUEST)

    with pytest.raises(ContentFilteredError, match="Violence is not allowed"):
        await provider.poll(operation_id)


async def test_a_finished_operation_without_any_video_is_failed():
    client = FakeVeoClient(polls=[operation(done=True)])
    provider = VeoProvider(client, CONFIG)
    operation_id = await provider.submit(REQUEST)

    result = await provider.poll(operation_id)

    assert result.state == "failed"
    assert "không trả về video" in result.message


async def test_poll_errors_are_provider_errors():
    client = FakeVeoClient(polls=[FakeAPIError(503)])
    provider = VeoProvider(client, CONFIG)
    operation_id = await provider.submit(REQUEST)

    with pytest.raises(ProviderError) as excinfo:
        await provider.poll(operation_id)

    assert excinfo.value.retryable is True


async def test_download_before_the_operation_finished_is_an_error(tmp_path):
    provider = VeoProvider(FakeVeoClient(), CONFIG)
    operation_id = await provider.submit(REQUEST)

    with pytest.raises(ProviderError):
        await provider.download(operation_id, tmp_path / "x.mp4")
    with pytest.raises(ProviderError):
        await provider.download("operations/unknown", tmp_path / "y.mp4")


# --- factory ----------------------------------------------------------------------


def test_fake_provider_is_the_default(settings):
    assert isinstance(build_video_provider(settings), FakeVideoProvider)


def test_veo_needs_a_key(project_root):
    (project_root / ".env").write_text("VIDEO_PROVIDER=veo\n", encoding="utf-8")

    with pytest.raises(ProviderError, match="GEMINI_API_KEY"):
        build_video_provider(load_settings(project_root))


def test_veo_needs_a_configured_price(project_root):
    (project_root / ".env").write_text("VIDEO_PROVIDER=veo\nGEMINI_API_KEY=test-key\n", encoding="utf-8")

    with pytest.raises(ProviderError, match="veo.price_usd_per_second"):
        build_video_provider(load_settings(project_root))


def test_veo_is_built_when_key_and_price_are_set(project_root):
    (project_root / ".env").write_text("VIDEO_PROVIDER=veo\nGEMINI_API_KEY=test-key\n", encoding="utf-8")
    settings = load_settings(project_root)
    settings.config.veo.price_usd_per_second = 0.1

    provider = build_video_provider(settings)

    assert isinstance(provider, VeoProvider)
    assert provider.price_usd_per_second == 0.1
