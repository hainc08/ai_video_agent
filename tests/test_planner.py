import copy
from types import SimpleNamespace as NS

import anthropic
import pytest

from app.agent.planner import (
    PlanOptions,
    Planner,
    PlannerError,
    PlannerRefusedError,
    build_planner,
    build_tool,
    strict_tool_schema,
)
from app.config import ClaudeConfig, load_settings
from app.schemas import load_plan_json_schema

OPTIONS = PlanOptions(duration_sec=30, aspect="9:16", voice="vi-female-north", style="clean corporate office")
IDEA = "5 việc sếp không biết bạn đang làm bằng AI"


def tool_use(plan, block_id="toolu_1"):
    return NS(type="tool_use", id=block_id, name="submit_plan", input=plan)


def text(value):
    return NS(type="text", text=value)


def reply(*blocks, stop_reason="tool_use", input_tokens=100, output_tokens=200):
    return NS(
        content=list(blocks),
        stop_reason=stop_reason,
        usage=NS(input_tokens=input_tokens, output_tokens=output_tokens),
        model="claude-sonnet-5-5",
    )


class FakeClient:
    """Stands in for AsyncAnthropic: returns queued replies and records every request."""

    def __init__(self, *replies):
        self._replies = list(replies)
        self.calls = []  # (endpoint, kwargs) with a snapshot of `messages`
        self.messages = NS(create=self._endpoint("messages"))
        self.beta = NS(messages=NS(create=self._endpoint("beta.messages")))

    def _endpoint(self, name):
        async def create(**kwargs):
            self.calls.append((name, {**kwargs, "messages": list(kwargs["messages"])}))
            outcome = self._replies.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        return create


def make_planner(client, **config_overrides):
    config = ClaudeConfig(**({"model": "claude-sonnet-5-5", "refusal_fallback": False} | config_overrides))
    return Planner(client, config, "SYSTEM PROMPT")


def short_voiceovers(plan_dict):
    bad = copy.deepcopy(plan_dict)
    for scene in bad["scenes"]:
        scene["voiceover_vi"] = "Xin chào các bạn."
    return bad


# --- tool schema -----------------------------------------------------------------

UNSUPPORTED = {"$schema", "title", "default", "minLength", "maxLength", "minimum", "maximum", "minItems", "maxItems"}


def _keywords(schema):
    """All JSON Schema keywords used anywhere in the schema (property names excluded)."""
    found = set()
    for key, value in schema.items():
        found.add(key)
        if key == "properties":
            for sub in value.values():
                found |= _keywords(sub)
        elif isinstance(value, dict):
            found |= _keywords(value)
    return found


def test_strict_schema_drops_unsupported_keywords_and_keeps_the_rest():
    original = load_plan_json_schema()
    strict = strict_tool_schema(original)

    assert _keywords(strict).isdisjoint(UNSUPPORTED)
    assert strict["additionalProperties"] is False
    assert strict["required"] == original["required"]
    assert set(strict["properties"]) == set(original["properties"])
    scene = strict["properties"]["scenes"]["items"]
    assert scene["additionalProperties"] is False
    assert scene["properties"]["duration_sec"] == {"type": "integer", "enum": [4, 6, 8]}
    assert scene["properties"]["veo_prompt_en"] == {"type": "string"}
    assert "minLength" in original["properties"]["idea"]  # the file on disk is not modified


def test_strict_schema_keeps_properties_that_are_named_like_keywords():
    schema = {"type": "object", "title": "T", "properties": {"title": {"type": "string", "minLength": 1}}}

    assert strict_tool_schema(schema) == {"type": "object", "properties": {"title": {"type": "string"}}}


def test_tool_definition_is_strict():
    tool = build_tool()

    assert tool["name"] == "submit_plan"
    assert tool["strict"] is True
    assert tool["input_schema"]["type"] == "object"


# --- create_plan -----------------------------------------------------------------


async def test_create_plan_returns_the_validated_plan(plan_dict):
    client = FakeClient(reply(tool_use(plan_dict)))

    result = await make_planner(client).create_plan(IDEA, OPTIONS)

    assert result.plan.to_dict() == plan_dict
    assert (result.calls, result.input_tokens, result.output_tokens) == (1, 100, 200)
    assert result.model == "claude-sonnet-5-5"


async def test_request_follows_the_claude_api_constraints(plan_dict):
    client = FakeClient(reply(tool_use(plan_dict)))

    await make_planner(client).create_plan(IDEA, OPTIONS)

    endpoint, request = client.calls[0]
    assert endpoint == "messages"
    assert request["model"] == "claude-sonnet-5-5"
    assert request["max_tokens"] == 16000
    assert request["system"] == "SYSTEM PROMPT"
    assert request["output_config"] == {"effort": "medium"}
    assert request["tool_choice"] == {"type": "auto", "disable_parallel_tool_use": True}
    assert [tool["name"] for tool in request["tools"]] == ["submit_plan"]
    assert request["tools"][0]["strict"] is True
    assert not {"thinking", "temperature", "top_p", "top_k", "fallbacks", "betas"} & set(request)
    prompt = request["messages"][0]["content"]
    assert request["messages"][0]["role"] == "user"
    assert IDEA in prompt and "30 giây" in prompt and "9:16" in prompt
    assert "clean corporate office" in prompt and "submit_plan" in prompt


async def test_invalid_plan_is_sent_back_to_claude_and_the_fix_is_accepted(plan_dict):
    first = reply(tool_use(short_voiceovers(plan_dict), "toolu_bad"))
    client = FakeClient(first, reply(tool_use(plan_dict, "toolu_ok")))

    result = await make_planner(client).create_plan(IDEA, OPTIONS)

    assert result.plan.to_dict() == plan_dict
    assert (result.calls, result.input_tokens, result.output_tokens) == (2, 200, 400)
    messages = client.calls[1][1]["messages"]
    assert len(messages) == 3
    assert messages[1] == {"role": "assistant", "content": first.content}
    assert messages[2]["role"] == "user"
    (tool_result,) = messages[2]["content"]
    assert tool_result["type"] == "tool_result"
    assert tool_result["tool_use_id"] == "toolu_bad"
    assert tool_result["is_error"] is True
    assert "total voiceover is 20 words" in tool_result["content"]


async def test_structural_errors_are_reported_with_the_field_path(plan_dict):
    bad = copy.deepcopy(plan_dict)
    bad["scenes"][0]["duration_sec"] = 5
    client = FakeClient(reply(tool_use(bad)), reply(tool_use(plan_dict)))

    await make_planner(client).create_plan(IDEA, OPTIONS)

    tool_result = client.calls[1][1]["messages"][2]["content"][0]
    assert "scenes.0.duration_sec" in tool_result["content"]


async def test_gives_up_after_two_fix_attempts(plan_dict):
    bad = short_voiceovers(plan_dict)
    client = FakeClient(reply(tool_use(bad)), reply(tool_use(bad)), reply(tool_use(bad)))

    with pytest.raises(PlannerError, match="3 lần") as excinfo:
        await make_planner(client).create_plan(IDEA, OPTIONS)

    assert len(client.calls) == 3
    assert (excinfo.value.input_tokens, excinfo.value.output_tokens) == (300, 600)
    assert "total voiceover" in str(excinfo.value)


async def test_reply_without_a_tool_call_is_reprompted(plan_dict):
    chatty = reply(text("Đây là plan của tôi..."), stop_reason="end_turn")
    client = FakeClient(chatty, reply(tool_use(plan_dict)))

    result = await make_planner(client).create_plan(IDEA, OPTIONS)

    assert result.calls == 2
    messages = client.calls[1][1]["messages"]
    assert messages[1] == {"role": "assistant", "content": chatty.content}
    assert messages[2]["role"] == "user"
    assert "submit_plan" in messages[2]["content"]


async def test_refusal_raises_immediately(plan_dict):
    client = FakeClient(reply(stop_reason="refusal"), reply(tool_use(plan_dict)))

    with pytest.raises(PlannerRefusedError) as excinfo:
        await make_planner(client).create_plan(IDEA, OPTIONS)

    assert len(client.calls) == 1
    assert excinfo.value.input_tokens == 100


async def test_truncated_reply_is_never_accepted_as_a_plan(plan_dict):
    client = FakeClient(reply(tool_use(plan_dict), stop_reason="max_tokens"))

    with pytest.raises(PlannerError, match="max_tokens"):
        await make_planner(client).create_plan(IDEA, OPTIONS)

    assert len(client.calls) == 1


@pytest.mark.parametrize("stop_reason", ["model_context_window_exceeded", "pause_turn", "stop_sequence", None])
async def test_tool_input_is_only_accepted_when_the_reply_stopped_for_tool_use(plan_dict, stop_reason):
    client = FakeClient(reply(tool_use(plan_dict), stop_reason=stop_reason), reply(tool_use(plan_dict)))

    with pytest.raises(PlannerError) as excinfo:
        await make_planner(client).create_plan(IDEA, OPTIONS)

    assert len(client.calls) == 1
    assert excinfo.value.input_tokens == 100


class FakeAPIError(anthropic.APIError):
    def __init__(self):
        Exception.__init__(self, "connection refused sk-secret-should-not-leak")


async def test_api_error_becomes_a_planner_error_that_keeps_the_tokens_already_spent(plan_dict):
    chatty = reply(text("Đây là plan..."), stop_reason="end_turn")
    client = FakeClient(chatty, FakeAPIError())

    with pytest.raises(PlannerError) as excinfo:
        await make_planner(client).create_plan(IDEA, OPTIONS)

    assert (excinfo.value.input_tokens, excinfo.value.output_tokens) == (100, 200)
    assert "Không gọi được Claude API" in str(excinfo.value)
    assert "FakeAPIError" in str(excinfo.value)
    assert "sk-secret" not in str(excinfo.value)


async def test_refusal_fallback_uses_the_beta_endpoint(plan_dict):
    client = FakeClient(reply(tool_use(plan_dict)))

    await make_planner(client, refusal_fallback=True).create_plan(IDEA, OPTIONS)

    endpoint, request = client.calls[0]
    assert endpoint == "beta.messages"
    assert request["betas"] == ["server-side-fallback-2026-07-01"]
    assert request["fallbacks"] == "default"


@pytest.mark.parametrize("idea", ["", "   ", "ab"])
async def test_blank_idea_is_rejected_before_any_api_call(idea):
    client = FakeClient()

    with pytest.raises(ValueError):
        await make_planner(client).create_plan(idea, OPTIONS)

    assert client.calls == []


def test_build_planner_requires_an_api_key(settings):
    with pytest.raises(PlannerError, match="ANTHROPIC_API_KEY"):
        build_planner(settings)


def test_build_planner_loads_the_system_prompt_file(project_root):
    (project_root / ".env").write_text("ANTHROPIC_API_KEY=sk-test\n", encoding="utf-8")

    planner = build_planner(load_settings(project_root))

    assert "submit_plan" in planner.system_prompt
    assert "AI Văn Phòng" in planner.system_prompt
