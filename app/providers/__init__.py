"""Video providers. `build_video_provider` picks one from VIDEO_PROVIDER in .env."""
from __future__ import annotations

from app.config import Settings
from app.providers.base import ProviderError, VideoProvider
from app.providers.fake_video import FakeVideoProvider

_REQUEST_TIMEOUT_MS = 120_000


def build_video_provider(settings: Settings) -> VideoProvider:
    if settings.secrets.video_provider == "fake":
        return FakeVideoProvider(settings.config.assembler.ffmpeg_path)

    # Imported here so the app starts without touching the Google SDK when the fake provider is used.
    from google import genai
    from google.genai import types

    from app.providers.veo_gemini import VeoProvider

    api_key = settings.secrets.gemini_key()
    if not api_key:
        raise ProviderError("Thiếu GEMINI_API_KEY trong file .env nên không gọi được Veo.")
    if settings.config.veo.price_usd_per_second is None:
        raise ProviderError("Chưa điền veo.price_usd_per_second trong config.yaml nên không chạy Veo thật.")
    client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=_REQUEST_TIMEOUT_MS))
    return VeoProvider(client, settings.config.veo)
