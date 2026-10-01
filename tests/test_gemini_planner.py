import copy
import json
from types import SimpleNamespace as NS

import pytest
from google.genai import errors, types

from app.agent.gemini_planner import GeminiPlanner
from app.agent.planner import PlannerError, PlannerRefusedError, PlanOptions
from app.config import GeminiConfig
from app.schemas import Plan

OPTIONS = PlanOptions(duration_sec=30, aspect="9:16", voice="vi-female-north", style="clean corporate office")
IDEA = "5 việc sếp không biết bạn đang làm bằng AI"


def reply(payload, finish="STOP", block=None):
    """A google-genai response as the planner reads it. `payload` is a dict (sent as JSON) or raw text."""
    text = payload if isinstance(payload, str) or payload is None else json.dumps(payload, ensure_ascii=False)
    content = types.Content(role="model", parts=[types.Part(text=text or "")])
    candidates = [] if block else [NS(content=content, finish_reason=getattr(types.FinishReason, finish))]
    return NS(
        text=text,
        candidates=candidates,
        prompt_feedback=NS(block_reason=block) if block else None,
        usage_metadata=NS(prompt_token_count=100, candidates_token_count=200, thoughts_token_count=50),
        model_version="gemini-3.8-flash",
    )


class FakeAPIError(errors.APIError):
    def __init__(self, code):
        Exception.__init__(self, "quota exceeded for key AIza-secret-should-not-leak")
        self.code = code


class FakeGemini:
    """Stands in for google.genai.Client: scripted replies, every request recorded."""

    def __init__(self, *replies):
        self._replies = list(replies)
        self.calls = []
        self.aio = NS(models=NS(generate_content=self._generate))

    async def _generate(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": list(contents), "config": config})
        outcome = self._replies.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make_planner(client):
    return GeminiPlanner(client, GeminiConfig(model="gemini-3.8-flash"), "SYSTEM PROMPT")


def short_voiceovers(plan_dict):
    bad = copy.deepcopy(plan_dict)
    for scene in bad["scenes"]:
        scene["voiceover_vi"] = "Xin chào các bạn."
    return bad


def _schema_keywords(schema):
    found = set()
    for key, value in schema.items():
        found.add(key)
        if key == "properties":
            for sub in value.values():
                found |= _schema_keywords(sub)
        elif isinstance(value, dict):
            found |= _schema_keywords(value)
    return found


async def test_create_plan_returns_the_validated_plan_and_counts_thinking_as_output(plan_dict):
    client = FakeGemini(reply(plan_dict))

    result = await make_planner(client).create_plan(IDEA, OPTIONS)

    assert result.plan.to_dict() == plan_dict
    assert (result.calls, result.input_tokens, result.output_tokens) == (1, 100, 250)
    assert result.model == "gemini-3.8-flash"


async def test_request_asks_for_json_constrained_by_the_plan_schema(plan_dict):
    client = FakeGemini(reply(plan_dict))

    await make_planner(client).create_plan(IDEA, OPTIONS)

    call = client.calls[0]
    config = call["config"]
    assert call["model"] == "gemini-3.8-flash"
    assert config.system_instruction == "SYSTEM PROMPT"
    assert config.response_mime_type == "application/json"
    assert config.max_output_tokens == 16000
    assert config.response_json_schema["required"] == ["idea", "target", "brief", "style_guide", "scenes", "caption_vi"]
    assert _schema_keywords(config.response_json_schema).isdisjoint({"$schema", "minLength", "maxLength", "default"})
    (message,) = call["contents"]
    prompt = message.parts[0].text
    assert message.role == "user"
    assert IDEA in prompt and "30 giây" in prompt and "9:16" in prompt and "clean corporate office" in prompt
    assert "JSON" in prompt and "submit_plan" not in prompt


async def test_invalid_plan_is_sent_back_and_the_fix_is_accepted(plan_dict):
    first = reply(short_voiceovers(plan_dict))
    client = FakeGemini(first, reply(plan_dict))

    result = await make_planner(client).create_plan(IDEA, OPTIONS)

    assert result.plan.to_dict() == plan_dict
    assert (result.calls, result.input_tokens, result.output_tokens) == (2, 200, 500)
    contents = client.calls[1]["contents"]
    assert [item.role for item in contents] == ["user", "model", "user"]
    assert contents[1] is first.candidates[0].content
    assert "total voiceover is 20 words" in contents[2].parts[0].text


@pytest.mark.parametrize("payload", ["not json at all", "", None, "[1, 2]"])
async def test_a_reply_that_is_not_a_json_object_is_sent_back(plan_dict, payload):
    client = FakeGemini(reply(payload), reply(plan_dict))

    result = await make_planner(client).create_plan(IDEA, OPTIONS)

    assert result.calls == 2
    assert "JSON" in client.calls[1]["contents"][-1].parts[0].text


async def test_gives_up_after_two_fix_attempts(plan_dict):
    bad = short_voiceovers(plan_dict)
    client = FakeGemini(reply(bad), reply(bad), reply(bad))

    with pytest.raises(PlannerError, match="3 lần") as excinfo:
        await make_planner(client).create_plan(IDEA, OPTIONS)

    assert len(client.calls) == 3
    assert (excinfo.value.input_tokens, excinfo.value.output_tokens) == (300, 750)


async def test_truncated_reply_is_never_accepted_as_a_plan(plan_dict):
    client = FakeGemini(reply(plan_dict, finish="MAX_TOKENS"), reply(plan_dict))

    with pytest.raises(PlannerError, match="max_output_tokens"):
        await make_planner(client).create_plan(IDEA, OPTIONS)

    assert len(client.calls) == 1


@pytest.mark.parametrize("finish", ["SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION"])
async def test_a_reply_stopped_by_a_content_filter_is_a_refusal(plan_dict, finish):
    client = FakeGemini(reply(plan_dict, finish=finish), reply(plan_dict))

    with pytest.raises(PlannerRefusedError) as excinfo:
        await make_planner(client).create_plan(IDEA, OPTIONS)

    assert len(client.calls) == 1
    assert excinfo.value.input_tokens == 100


async def test_a_blocked_prompt_is_a_refusal(plan_dict):
    client = FakeGemini(reply(None, block="SAFETY"))

    with pytest.raises(PlannerRefusedError):
        await make_planner(client).create_plan(IDEA, OPTIONS)


@pytest.mark.parametrize("finish", ["OTHER", "MALFORMED_FUNCTION_CALL", "FINISH_REASON_UNSPECIFIED"])
async def test_any_other_abnormal_stop_is_an_error_not_a_plan(plan_dict, finish):
    client = FakeGemini(reply(plan_dict, finish=finish), reply(plan_dict))

    with pytest.raises(PlannerError, match=finish):
        await make_planner(client).create_plan(IDEA, OPTIONS)

    assert len(client.calls) == 1


async def test_api_error_becomes_a_planner_error_that_keeps_the_tokens_already_spent(plan_dict):
    client = FakeGemini(reply(short_voiceovers(plan_dict)), FakeAPIError(401))

    with pytest.raises(PlannerError) as excinfo:
        await make_planner(client).create_plan(IDEA, OPTIONS)

    message = str(excinfo.value)
    assert (excinfo.value.input_tokens, excinfo.value.output_tokens) == (100, 250)
    assert "Không gọi được Gemini API" in message and "401" in message and "GEMINI_API_KEY" in message
    assert "AIza-secret" not in message


@pytest.mark.parametrize("code", [429, 503])
async def test_overload_and_quota_errors_tell_the_user_to_try_again_later(code):
    client = FakeGemini(FakeAPIError(code))

    with pytest.raises(PlannerError, match="thử lại sau") as excinfo:
        await make_planner(client).create_plan(IDEA, OPTIONS)

    assert str(code) in str(excinfo.value)


async def test_an_overloaded_model_falls_back_to_the_next_one_and_stays_there(plan_dict):
    client = FakeGemini(FakeAPIError(503), reply(short_voiceovers(plan_dict)), reply(plan_dict))
    config = GeminiConfig(model="gemini-3.8-flash", fallback_models=["gemini-3.7-flash", "gemini-3.6-flash"])

    result = await GeminiPlanner(client, config, "SYSTEM PROMPT").create_plan(IDEA, OPTIONS)

    assert [call["model"] for call in client.calls] == ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.7-flash"]
    assert result.plan.to_dict() == plan_dict
    assert result.calls == 2  # the overloaded attempt produced nothing and cost nothing


async def test_when_every_model_is_overloaded_the_user_is_told_to_try_later(plan_dict):
    client = FakeGemini(FakeAPIError(503), FakeAPIError(429))
    config = GeminiConfig(model="gemini-3.8-flash", fallback_models=["gemini-3.7-flash"])

    with pytest.raises(PlannerError, match="thử lại sau"):
        await GeminiPlanner(client, config, "SYSTEM PROMPT").create_plan(IDEA, OPTIONS)

    assert [call["model"] for call in client.calls] == ["gemini-3.8-flash", "gemini-3.7-flash"]


async def test_other_api_errors_do_not_try_another_model(plan_dict):
    client = FakeGemini(FakeAPIError(401), reply(plan_dict))
    config = GeminiConfig(model="gemini-3.8-flash", fallback_models=["gemini-3.7-flash"])

    with pytest.raises(PlannerError, match="GEMINI_API_KEY"):
        await GeminiPlanner(client, config, "SYSTEM PROMPT").create_plan(IDEA, OPTIONS)

    assert len(client.calls) == 1


async def test_blank_idea_is_rejected_before_any_api_call():
    client = FakeGemini()

    with pytest.raises(ValueError):
        await make_planner(client).create_plan("  ", OPTIONS)

    assert client.calls == []


async def test_revise_sends_the_current_plan_and_feedback(plan_dict):
    revised = copy.deepcopy(plan_dict)
    revised["brief"]["cta"] = "Lưu video để xem lại"
    client = FakeGemini(reply(revised))

    result = await make_planner(client).revise(Plan.model_validate(plan_dict), "Đổi CTA")

    prompt = client.calls[0]["contents"][0].parts[0].text
    assert result.plan.brief.cta == "Lưu video để xem lại"
    assert "Đổi CTA" in prompt and '"cta": "Theo dõi kênh để xem thêm mẹo AI"' in prompt
    assert "submit_plan" not in prompt


async def test_rewrite_scene_replaces_only_that_scene(plan_dict):
    original = Plan.model_validate(plan_dict)
    from_gemini = copy.deepcopy(plan_dict)
    from_gemini["scenes"][1]["visual"] = "Hộp thư đến trên màn hình"
    from_gemini["brief"]["cta"] = "Changed without being asked"
    client = FakeGemini(reply(from_gemini))

    result = await make_planner(client).rewrite_scene(original, 2, "sinh động hơn")

    assert result.plan.scenes[1].visual == "Hộp thư đến trên màn hình"
    assert result.plan.brief == original.brief
    assert "cảnh 2" in client.calls[0]["contents"][0].parts[0].text
