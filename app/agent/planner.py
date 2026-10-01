"""Claude planner: idea -> validated Plan, through the strict `submit_plan` tool."""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import anthropic
from anthropic import AsyncAnthropic
from pydantic import ValidationError

from app.agent.plan_rules import validate_plan
from app.config import PROJECT_ROOT, ClaudeConfig, Settings
from app.schemas import Plan, load_plan_json_schema

TOOL_NAME = "submit_plan"
MAX_FIX_ATTEMPTS = 2
SYSTEM_PROMPT_PATH = PROJECT_ROOT / "prompts" / "planner_system.md"
_FALLBACK_BETA = "server-side-fallback-2026-07-01"

# Strict tool use rejects these JSON Schema keywords. Pydantic (app.schemas) enforces
# the same constraints after the call, so nothing is lost by not sending them.
_UNSUPPORTED_KEYWORDS = frozenset(
    {"$schema", "title", "default", "minLength", "maxLength", "minimum", "maximum", "minItems", "maxItems"}
)


class PlannerError(Exception):
    """Planning failed. `input_tokens` / `output_tokens` are what was spent before failing."""

    def __init__(self, message: str, *, input_tokens: int = 0, output_tokens: int = 0) -> None:
        super().__init__(message)
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class PlannerRefusedError(PlannerError):
    """Claude declined the request (stop_reason == "refusal")."""


class PlanMergeError(Exception):
    """A structurally valid reply could not be merged into the plan being edited."""


@dataclass(frozen=True)
class PlanOptions:
    duration_sec: int
    aspect: str
    voice: str
    style: str


@dataclass(frozen=True)
class PlannerResult:
    plan: Plan
    model: str
    calls: int
    input_tokens: int
    output_tokens: int


def strict_tool_schema(schema: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key in _UNSUPPORTED_KEYWORDS:
            continue
        if key == "properties":
            # Keys here are property names, not keywords: keep them all, clean their schemas.
            out[key] = {name: strict_tool_schema(sub) for name, sub in value.items()}
        elif isinstance(value, dict):
            out[key] = strict_tool_schema(value)
        else:
            out[key] = value
    return out


def build_tool() -> dict[str, Any]:
    return {
        "name": TOOL_NAME,
        "description": (
            "Submit the complete video production plan. Call exactly once per turn. "
            "Limits the schema cannot express: 2-12 scenes, scene ids 1..n in order, "
            "veo_prompt_en at most 1000 characters."
        ),
        "strict": True,
        "input_schema": strict_tool_schema(load_plan_json_schema()),
    }


def _plan_json(plan: Plan) -> str:
    return json.dumps(plan.to_dict(), ensure_ascii=False, indent=2)


def _keep_target_note(plan: Plan) -> str:
    return (
        f"Giữ nguyên thời lượng mục tiêu {plan.target.duration_sec} giây "
        f"và tỉ lệ {plan.target.aspect}."
    )


class Planner:
    def __init__(self, client: Any, config: ClaudeConfig, system_prompt: str) -> None:
        self._client = client
        self._config = config
        self.system_prompt = system_prompt
        self._tool = build_tool()

    async def create_plan(self, idea: str, options: PlanOptions) -> PlannerResult:
        idea = idea.strip()
        if len(idea) < 3:
            raise ValueError("idea must be at least 3 characters")
        prompt = (
            f"<idea>{idea}</idea>\n"
            f"Thời lượng mục tiêu: {options.duration_sec} giây\n"
            f"Tỉ lệ khung hình: {options.aspect}\n"
            f"Phong cách hình ảnh: {options.style}\n"
            f"Giọng đọc: {options.voice}\n\n"
            f"Lập plan cho ý tưởng trên rồi gọi tool {TOOL_NAME}."
        )
        return await self._run(prompt, duration_sec=options.duration_sec, aspect=options.aspect)

    async def revise(self, plan: Plan, feedback: str) -> PlannerResult:
        feedback = feedback.strip()
        if not feedback:
            raise ValueError("feedback must not be empty")
        prompt = (
            f"Đây là plan hiện tại:\n<plan>\n{_plan_json(plan)}\n</plan>\n\n"
            f"Góp ý của người dùng:\n<feedback>{feedback}</feedback>\n\n"
            "Sửa plan theo góp ý, giữ nguyên những phần không bị nhắc đến. "
            f"{_keep_target_note(plan)} Sau đó gọi tool {TOOL_NAME} với plan đầy đủ."
        )
        return await self._run(prompt, duration_sec=plan.target.duration_sec, aspect=plan.target.aspect)

    async def rewrite_scene(self, plan: Plan, scene_id: int, feedback: str = "") -> PlannerResult:
        if scene_id not in {scene.id for scene in plan.scenes}:
            raise ValueError(f"scene {scene_id} is not in the plan")
        feedback = feedback.strip() or "Viết lại cảnh này theo một hướng khác, hay hơn."
        prompt = (
            f"Đây là plan hiện tại:\n<plan>\n{_plan_json(plan)}\n</plan>\n\n"
            f"Chỉ viết lại cảnh {scene_id}, giữ nguyên thời lượng của cảnh đó và mọi phần khác của plan.\n"
            f"Yêu cầu:\n<feedback>{feedback}</feedback>\n\n"
            f"Sau đó gọi tool {TOOL_NAME} với plan đầy đủ."
        )

        # Issues the plan already had outside this rewrite (e.g. from a hand edit) are not
        # Claude's to fix here: everything except the rewritten scene is discarded anyway.
        known = set(validate_plan(plan, duration_sec=plan.target.duration_sec, aspect=plan.target.aspect))

        def keep_only_rewritten_scene(candidate: Plan) -> Plan:
            rewritten = next((scene for scene in candidate.scenes if scene.id == scene_id), None)
            if rewritten is None:
                raise PlanMergeError(f"scene {scene_id} is missing from the submitted plan")
            scenes = [rewritten if scene.id == scene_id else scene for scene in plan.scenes]
            return plan.model_copy(update={"scenes": scenes})

        return await self._run(
            prompt,
            duration_sec=plan.target.duration_sec,
            aspect=plan.target.aspect,
            finalize=keep_only_rewritten_scene,
            known_issues=known,
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
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        calls = input_tokens = output_tokens = 0
        errors: list[str] = []

        for _ in range(1 + MAX_FIX_ATTEMPTS):
            try:
                response = await self._call(messages)
            except anthropic.APIError as exc:
                # Keep what earlier calls cost, and name the error class only: an API
                # exception's text may quote the request.
                raise PlannerError(
                    f"Không gọi được Claude API ({type(exc).__name__}). "
                    "Hãy kiểm tra ANTHROPIC_API_KEY và kết nối mạng rồi thử lại.",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                ) from exc
            calls += 1
            input_tokens += response.usage.input_tokens
            output_tokens += response.usage.output_tokens
            spent = {"input_tokens": input_tokens, "output_tokens": output_tokens}

            if response.stop_reason == "refusal":
                raise PlannerRefusedError(
                    "Claude từ chối lập plan cho ý tưởng này. Hãy thử diễn đạt lại ý tưởng.", **spent
                )
            if response.stop_reason in ("max_tokens", "model_context_window_exceeded"):
                raise PlannerError(
                    "Plan bị cắt giữa chừng vì chạm claude.max_tokens. "
                    "Hãy tăng giá trị này trong config.yaml.",
                    **spent,
                )

            tool_uses = [block for block in response.content if block.type == "tool_use"]
            if tool_uses and response.stop_reason != "tool_use":
                # The turn did not end at the tool call, so its input may be incomplete.
                raise PlannerError(
                    f"Claude dừng bất thường khi đang gửi plan (stop_reason={response.stop_reason}). "
                    "Hãy thử lại.",
                    **spent,
                )
            # Pass the content back unchanged: it carries the model's thinking blocks.
            messages.append({"role": "assistant", "content": response.content})

            if not tool_uses:
                errors = [f"no {TOOL_NAME} tool call in the reply"]
                messages.append(
                    {
                        "role": "user",
                        "content": f"Bạn chưa gọi tool {TOOL_NAME}. Hãy gọi tool {TOOL_NAME} với plan đầy đủ.",
                    }
                )
                continue

            plan, errors = self._check(tool_uses[0].input, duration_sec, aspect, finalize, known_issues)
            if plan is not None:
                return PlannerResult(
                    plan=plan,
                    model=response.model,
                    calls=calls,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
            feedback = (
                "Plan chưa hợp lệ. Sửa các lỗi sau rồi gọi lại tool, giữ nguyên các phần không liên quan:\n"
                + "\n".join(f"- {error}" for error in errors)
            )
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": block.id, "is_error": True, "content": feedback}
                        for block in tool_uses
                    ],
                }
            )

        raise PlannerError(
            f"Claude không tạo được plan hợp lệ sau {calls} lần thử: " + "; ".join(errors),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def _check(
        self,
        raw: Any,
        duration_sec: int,
        aspect: str,
        finalize: Callable[[Plan], Plan] | None = None,
        known_issues: frozenset[str] | set[str] = frozenset(),
    ) -> tuple[Plan | None, list[str]]:
        try:
            plan = Plan.model_validate(raw)
            if finalize is not None:
                plan = finalize(plan)
        except ValidationError as exc:
            return None, [
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors()
            ]
        except PlanMergeError as exc:
            return None, [str(exc)]
        errors = [
            error
            for error in validate_plan(plan, duration_sec=duration_sec, aspect=aspect)
            if error not in known_issues
        ]
        return (None, errors) if errors else (plan, [])

    async def _call(self, messages: list[dict[str, Any]]) -> Any:
        request: dict[str, Any] = {
            "model": self._config.model,
            "max_tokens": self._config.max_tokens,
            "system": self.system_prompt,
            "tools": [self._tool],
            # Current Claude models reject forced tool choice; `auto` + strict schema + the
            # prompt instruction replaces it, and _run re-prompts when no call comes back.
            "tool_choice": {"type": "auto", "disable_parallel_tool_use": True},
            "output_config": {"effort": self._config.effort},
            "messages": messages,
        }
        if self._config.refusal_fallback:
            return await self._client.beta.messages.create(
                betas=[_FALLBACK_BETA], fallbacks="default", **request
            )
        return await self._client.messages.create(**request)


def build_planner(settings: Settings) -> Planner:
    api_key = settings.secrets.anthropic_key()
    if not api_key:
        raise PlannerError("Thiếu ANTHROPIC_API_KEY trong file .env.")
    return Planner(
        AsyncAnthropic(api_key=api_key),
        settings.config.claude,
        SYSTEM_PROMPT_PATH.read_text(encoding="utf-8"),
    )
