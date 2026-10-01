"""Veo 3.1 through the official Gemini API (google-genai)."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from google.genai import errors as genai_errors
from google.genai import types

from app.config import VeoConfig
from app.providers.base import ClipRequest, ContentFilteredError, PollResult, ProviderError

# Veo on the Gemini API renders only these two; 1080p and 4k are offered only for 8-second clips.
_SUPPORTED_ASPECTS = frozenset({"9:16", "16:9"})
_BASE_RESOLUTION = "720p"
_FULL_LENGTH_SEC = 8


def _provider_error(exc: genai_errors.APIError, action: str) -> ProviderError:
    # Class name and status code only: the exception text can quote the request.
    code = getattr(exc, "code", None)
    retryable = code == 429 or (isinstance(code, int) and code >= 500)
    return ProviderError(f"Veo báo lỗi khi {action} ({type(exc).__name__}, mã {code}).", retryable=retryable)


class VeoProvider:
    name = "veo"
    supported_aspects = _SUPPORTED_ASPECTS

    def __init__(self, client: Any, config: VeoConfig) -> None:
        self._client = client
        self._config = config
        self.price_usd_per_second = config.price_usd_per_second or 0.0
        self._operations: dict[str, Any] = {}

    async def submit(self, request: ClipRequest) -> str:
        if request.aspect not in _SUPPORTED_ASPECTS:
            raise ProviderError(f"Veo chỉ hỗ trợ tỉ lệ 9:16 và 16:9, không hỗ trợ {request.aspect}.")
        resolution = self._config.resolution if request.duration_sec == _FULL_LENGTH_SEC else _BASE_RESOLUTION
        try:
            operation = await self._client.aio.models.generate_videos(
                model=self._config.model,
                prompt=request.prompt,
                config=types.GenerateVideosConfig(
                    aspect_ratio=request.aspect,
                    duration_seconds=request.duration_sec,
                    resolution=resolution,
                    number_of_videos=1,
                ),
            )
        except genai_errors.APIError as exc:
            raise _provider_error(exc, "gửi yêu cầu sinh clip") from exc
        self._operations[operation.name] = operation
        return operation.name

    async def poll(self, operation_id: str) -> PollResult:
        current = self._operations.get(operation_id) or types.GenerateVideosOperation(name=operation_id)
        try:
            operation = await self._client.aio.operations.get(current)
        except genai_errors.APIError as exc:
            raise _provider_error(exc, "hỏi trạng thái clip") from exc
        self._operations[operation_id] = operation

        if not operation.done:
            return PollResult("running")
        if operation.error:
            message = operation.error.get("message") if isinstance(operation.error, dict) else str(operation.error)
            return PollResult("failed", f"Veo không sinh được clip: {message}")
        response = operation.response
        if response is None or not response.generated_videos:
            if response is not None and response.rai_media_filtered_count:
                reasons = "; ".join(response.rai_media_filtered_reasons or []) or "không nêu lý do"
                raise ContentFilteredError(f"Prompt bị bộ lọc an toàn của Veo chặn: {reasons}")
            return PollResult("failed", "Veo không trả về video nào.")
        return PollResult("done")

    async def download(self, operation_id: str, path: Path) -> None:
        operation = self._operations.get(operation_id)
        if operation is None or not operation.done or not getattr(operation.response, "generated_videos", None):
            raise ProviderError(f"Clip của tác vụ '{operation_id}' chưa sẵn sàng để tải.")
        video = operation.response.generated_videos[0].video
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            await self._client.aio.files.download(file=video)
        except genai_errors.APIError as exc:
            raise _provider_error(exc, "tải clip") from exc
        await asyncio.to_thread(video.save, str(path))
