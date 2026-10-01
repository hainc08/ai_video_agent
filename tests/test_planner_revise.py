import copy

import pytest

from app.schemas import Plan
from tests.test_planner import FakeClient, make_planner, reply, tool_use


def _words(count):
    return " ".join(["từ"] * count)


# --- revise ----------------------------------------------------------------------


async def test_revise_sends_the_current_plan_and_feedback_and_returns_the_new_plan(plan_dict):
    revised = copy.deepcopy(plan_dict)
    revised["brief"]["cta"] = "Lưu video để xem lại"
    client = FakeClient(reply(tool_use(revised)))
    plan = Plan.model_validate(plan_dict)

    result = await make_planner(client).revise(plan, "Đổi CTA thành lưu video")

    assert result.plan.brief.cta == "Lưu video để xem lại"
    prompt = client.calls[0][1]["messages"][0]["content"]
    assert "Đổi CTA thành lưu video" in prompt
    assert '"cta": "Theo dõi kênh để xem thêm mẹo AI"' in prompt  # current plan, readable Vietnamese
    assert "submit_plan" in prompt


async def test_revise_validates_against_the_plans_own_target(plan_dict):
    changed_target = copy.deepcopy(plan_dict)
    changed_target["target"]["duration_sec"] = 15
    client = FakeClient(reply(tool_use(changed_target)), reply(tool_use(plan_dict)))

    result = await make_planner(client).revise(Plan.model_validate(plan_dict), "Ngắn gọn hơn")

    assert result.calls == 2
    tool_result = client.calls[1][1]["messages"][2]["content"][0]
    assert "target.duration_sec must be 30" in tool_result["content"]


@pytest.mark.parametrize("feedback", ["", "   \n"])
async def test_revise_requires_feedback(plan_dict, feedback):
    client = FakeClient()

    with pytest.raises(ValueError):
        await make_planner(client).revise(Plan.model_validate(plan_dict), feedback)

    assert client.calls == []


# --- rewrite_scene ---------------------------------------------------------------


async def test_rewrite_scene_replaces_only_that_scene(plan_dict):
    original = Plan.model_validate(plan_dict)
    from_claude = copy.deepcopy(plan_dict)
    from_claude["scenes"][1]["voiceover_vi"] = _words(16)
    from_claude["scenes"][1]["veo_prompt_en"] = "Vertical shot of an inbox, no on-screen text, no logos"
    from_claude["scenes"][0]["voiceover_vi"] = _words(15)  # not asked for
    from_claude["brief"]["cta"] = "Changed without being asked"  # not asked for
    client = FakeClient(reply(tool_use(from_claude)))

    result = await make_planner(client).rewrite_scene(original, 2, "Cảnh này cần sinh động hơn")

    assert result.plan.scenes[1].voiceover_vi == _words(16)
    assert result.plan.scenes[1].veo_prompt_en.startswith("Vertical shot of an inbox")
    assert result.plan.scenes[0] == original.scenes[0]
    assert result.plan.scenes[2:] == original.scenes[2:]
    assert result.plan.brief == original.brief
    prompt = client.calls[0][1]["messages"][0]["content"]
    assert "cảnh 2" in prompt and "Cảnh này cần sinh động hơn" in prompt


async def test_rewrite_scene_works_without_feedback(plan_dict):
    client = FakeClient(reply(tool_use(plan_dict)))

    result = await make_planner(client).rewrite_scene(Plan.model_validate(plan_dict), 2)

    assert result.calls == 1
    assert "cảnh 2" in client.calls[0][1]["messages"][0]["content"]


async def test_rewrite_scene_revalidates_the_merged_plan(plan_dict):
    too_long = copy.deepcopy(plan_dict)
    too_long["scenes"][1]["voiceover_vi"] = _words(25)
    client = FakeClient(reply(tool_use(too_long)), reply(tool_use(plan_dict)))

    result = await make_planner(client).rewrite_scene(Plan.model_validate(plan_dict), 2, "Dài hơn")

    assert result.calls == 2
    tool_result = client.calls[1][1]["messages"][2]["content"][0]
    assert "scene 2: voiceover_vi has 25 words" in tool_result["content"]


async def test_rewrite_scene_reports_a_reply_that_dropped_the_scene(plan_dict):
    without_scene_5 = copy.deepcopy(plan_dict)
    without_scene_5["scenes"].pop()
    client = FakeClient(reply(tool_use(without_scene_5)), reply(tool_use(plan_dict)))

    result = await make_planner(client).rewrite_scene(Plan.model_validate(plan_dict), 5, "Kết mạnh hơn")

    assert result.calls == 2
    tool_result = client.calls[1][1]["messages"][2]["content"][0]
    assert "scene 5 is missing" in tool_result["content"]


async def test_rewrite_scene_rejects_an_unknown_scene_before_any_api_call(plan_dict):
    client = FakeClient()

    with pytest.raises(ValueError, match="scene 9"):
        await make_planner(client).rewrite_scene(Plan.model_validate(plan_dict), 9, "x")

    assert client.calls == []


async def test_rewrite_scene_is_not_blocked_by_an_issue_that_was_already_in_another_scene(plan_dict):
    plan_dict["scenes"][0]["subtitle_vi"] = _words(13)  # e.g. left by a hand edit
    original = Plan.model_validate(plan_dict)
    from_claude = copy.deepcopy(plan_dict)
    from_claude["scenes"][1]["voiceover_vi"] = _words(16)
    client = FakeClient(reply(tool_use(from_claude)))

    result = await make_planner(client).rewrite_scene(original, 2, "sinh động hơn")

    assert result.calls == 1
    assert result.plan.scenes[1].voiceover_vi == _words(16)
    assert result.plan.scenes[0] == original.scenes[0]
