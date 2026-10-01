"""Gemini planner: the plan comes back as JSON constrained by the plan schema."""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.agent.planner import (
    MAX_FIX_ATTEMPTS,
    PlannerBase,
    PlannerError,
    PlannerRefusedError,
    PlannerResult,
    load_system_prompt,
    strict_tool_schema,
)
from app.config import GeminiConfig, Settings
from app.schemas import Plan, load_plan_json_schema

_GEMINI_OUTPUT_RULE = (
    "\n\nCách trả kết quả: trả về MỘT đối tượng JSON đúng schema được cung cấp. "
    "Không kèm chữ nào khác ngoài JSON."
)
_REQUEST_TIMEOUT_MS = 180_000
_RETRY_ATTEMPTS = 4  # the SDK retries overload (503) and rate-limit (429) replies with backoff
_OVERLOADED_CODES = (429, 503)

log = logging.getLogger("app.planner.gemini")

_FILTERED = frozenset(
    {
        types.FinishReason.SAFETY,
        types.FinishReason.PROHIBITED_CONTENT,
        types.FinishReason.BLOCKLIST,
        types.FinishReason.SPII,
        types.FinishReason.RECITATION,
    }
)
_REFUSED_MESSAGE = "Gemini từ chối lập plan cho ý tưởng này. Hãy thử diễn đạt lại ý tưởng."


def _user(text: str) -> types.Content:
    return types.Content(role="user", parts=[types.Part(text=text)])


class GeminiPlanner(PlannerBase):
    _submit = "trả về plan đầy đủ dưới dạng một đối tượng JSON"

    def __init__(self, client: Any, config: GeminiConfig, system_prompt: str) -> None:
        self._client = client
        self._config = config
        self.system_prompt = system_prompt
        self._models = [config.model, *config.fallback_models]
        self._request_config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            # Same trimmed schema as the Claude tool; Pydantic enforces what the trimming removed.
            response_json_schema=strict_tool_schema(load_plan_json_schema()),
            max_output_tokens=config.max_output_tokens,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    async def _run(
        self,
        prompt: str,
        *,
        duration_sec: int,
        aspect: str,
        finalize: Callable[[Plan], Plan] | None = None,
        known_issues: frozenset[str] | set[str] = frozenset(),
    ) -> PlannerResult:
        contents: list[types.Content] = [_user(prompt)]
        calls = input_tokens = output_tokens = 0
        errors: list[str] = []
        model_index = 0

        for _ in range(1 + MAX_FIX_ATTEMPTS):
            try:
                response, model_index = await self._generate(contents, model_index)
            except genai_errors.APIError as exc:
                raise PlannerError(
                    _api_error_message(exc), input_tokens=input_tokens, output_tokens=output_tokens
                ) from exc
            calls += 1
            usage = response.usage_metadata
            if usage is not None:
                input_tokens += usage.prompt_token_count or 0
                # Thinking tokens are billed at the output rate.
                output_tokens += (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
            spent = {"input_tokens": input_tokens, "output_tokens": output_tokens}

            if response.prompt_feedback is not None and response.prompt_feedback.block_reason:
                raise PlannerRefusedError(_REFUSED_MESSAGE, **spent)
            if not response.candidates:
                raise PlannerError("Gemini không trả về nội dung nào. Hãy thử lại.", **spent)
            candidate = response.candidates[0]
            finish = candidate.finish_reason
            if finish in _FILTERED:
                raise PlannerRefusedError(_REFUSED_MESSAGE, **spent)
            if finish == types.FinishReason.MAX_TOKENS:
                raise PlannerError(
                    "Plan bị cắt giữa chừng vì chạm gemini.max_output_tokens. "
                    "Hãy tăng giá trị này trong config.yaml.",
                    **spent,
                )
            if finish != types.FinishReason.STOP:
                # Only a reply that ended normally is read: anything else may be incomplete.
                name = getattr(finish, "name", finish)
                raise PlannerError(f"Gemini dừng bất thường khi đang gửi plan ({name}). Hãy thử lại.", **spent)

            try:
                raw = json.loads(response.text or "")
            except json.JSONDecodeError:
                raw = None
            if isinstance(raw, dict):
                plan, errors = self._check(raw, duration_sec, aspect, finalize, known_issues)
                if plan is not None:
                    return PlannerResult(
                        plan=plan,
                        model=response.model_version or self._models[model_index],
                        calls=calls,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                    )
            else:
                errors = ["the reply is not a JSON object"]

            if candidate.content is not None:
                contents.append(candidate.content)
            contents.append(
                _user(
                    "Plan chưa hợp lệ. Sửa các lỗi sau rồi trả lại plan đầy đủ dưới dạng một đối tượng JSON, "
                    "giữ nguyên các phần không liên quan:\n" + "\n".join(f"- {error}" for error in errors)
                )
            )

        raise PlannerError(
            f"Gemini không tạo được plan hợp lệ sau {calls} lần thử: " + "; ".join(errors),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


    async def _generate(self, contents: list[types.Content], start: int) -> tuple[Any, int]:
        """Call the model at `start`; if it is overloaded, move on to the next configured model.

        Returns the response and the index of the model that answered, so the rest of the
        run keeps using the model that works.
        """
        for index in range(start, len(self._models)):
            try:
                response = await self._client.aio.models.generate_content(
                    model=self._models[index], contents=contents, config=self._request_config
                )
                return response, index
            except genai_errors.APIError as exc:
                is_last = index == len(self._models) - 1
                if getattr(exc, "code", None) not in _OVERLOADED_CODES or is_last:
                    raise
                log.warning(
                    "Gemini model %s is overloaded (%s); trying %s",
                    self._models[index], exc.code, self._models[index + 1],
                )
        raise AssertionError("unreachable: the loop always returns or raises")


def _api_error_message(exc: genai_errors.APIError) -> str:
    # Class name and status code only: the exception text can quote the request.
    code = getattr(exc, "code", None)
    if code in _OVERLOADED_CODES:
        return (
            f"Gemini đang quá tải hoặc đã hết hạn mức (mã {code}). "
            "Hãy thử lại sau ít phút."
        )
    return (
        f"Không gọi được Gemini API ({type(exc).__name__}, mã {code}). "
        "Hãy kiểm tra GEMINI_API_KEY và kết nối mạng rồi thử lại."
    )


def build_gemini_planner(settings: Settings) -> GeminiPlanner:
    api_key = settings.secrets.gemini_key()
    if not api_key:
        raise PlannerError("Thiếu GEMINI_API_KEY trong file .env.")
    if settings.config.gemini is None:
        raise PlannerError("Thiếu mục 'gemini:' trong config.yaml.")
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=_REQUEST_TIMEOUT_MS,
            retry_options=types.HttpRetryOptions(attempts=_RETRY_ATTEMPTS),
        ),
    )
    return GeminiPlanner(client, settings.config.gemini, load_system_prompt() + _GEMINI_OUTPUT_RULE)
