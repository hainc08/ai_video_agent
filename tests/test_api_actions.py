import copy

import pytest

from app.agent.planner import PlannerError
from app.models import JobStatus
from app.schemas import Plan
from tests.fakes import planner_result
from tests.helpers import seed_job, wait_until_planned

ACTIONS = [
    ("POST", "/api/jobs/{id}/revise", {"feedback": "hook mạnh hơn"}),
    ("PATCH", "/api/jobs/{id}/scenes/2", {"visual": "bàn làm việc"}),
    ("POST", "/api/jobs/{id}/scenes/2/rewrite", {}),
    ("POST", "/api/jobs/{id}/approve", {}),
]
ACTION_IDS = ["revise", "edit", "rewrite", "approve"]


def words(count):
    return " ".join(["từ"] * count)


def reviewable(start_app, settings, plan_dict, *outcomes, **attrs):
    client, planner = start_app(*outcomes)
    job_id = seed_job(client.app.state.engine, settings.data_dir, plan_dict=plan_dict, **attrs)
    return client, planner, job_id


def detail(client, job_id):
    return client.get(f"/api/jobs/{job_id}").json()


# --- every action: wrong state, unknown job ---------------------------------------


@pytest.mark.parametrize("method, url, data", ACTIONS, ids=ACTION_IDS)
def test_actions_are_refused_while_the_job_is_not_awaiting_approval(start_app, settings, plan_dict, method, url, data):
    client, planner, job_id = reviewable(start_app, settings, plan_dict, status=JobStatus.planning)

    response = client.request(method, url.format(id=job_id), data=data)

    assert response.status_code == 409
    assert "không ở bước duyệt plan" in response.json()["detail"]
    assert detail(client, job_id)["status"] == "planning"
    assert planner.calls == []


@pytest.mark.parametrize("method, url, data", ACTIONS, ids=ACTION_IDS)
def test_actions_on_an_unknown_job_are_404(start_app, method, url, data):
    client, _ = start_app()

    response = client.request(method, url.format(id="missing"), data=data)

    assert (response.status_code, response.json()) == (404, {"detail": "Không tìm thấy job."})


@pytest.mark.parametrize("method, path", [("PATCH", "scenes/99"), ("POST", "scenes/99/rewrite")])
def test_unknown_scene_is_a_404(start_app, settings, plan_dict, method, path):
    client, planner, job_id = reviewable(start_app, settings, plan_dict)

    response = client.request(method, f"/api/jobs/{job_id}/{path}", data={"visual": "x"})

    assert (response.status_code, response.json()) == (404, {"detail": "Không tìm thấy cảnh 99."})
    assert planner.calls == []
    assert detail(client, job_id)["status"] == "awaiting_approval"


# --- revise ---------------------------------------------------------------------


def test_revise_sends_the_feedback_to_claude_and_stores_the_new_version(start_app, settings, plan_dict):
    revised = copy.deepcopy(plan_dict)
    revised["brief"]["cta"] = "Lưu video để xem lại"
    client, planner, job_id = reviewable(start_app, settings, plan_dict, planner_result(revised))

    response = client.post(f"/api/jobs/{job_id}/revise", data={"feedback": "  Đổi CTA  "})
    body = wait_until_planned(client, job_id)

    assert response.status_code == 200
    assert response.headers["hx-refresh"] == "true"
    assert response.json()["status"] == "planning"
    assert (body["status"], body["plan_version"]) == ("awaiting_approval", 2)
    assert body["plan"]["brief"]["cta"] == "Lưu video để xem lại"
    assert planner.calls == [("revise", Plan.model_validate(plan_dict), "Đổi CTA")]


@pytest.mark.parametrize("feedback, message", [("", "Hãy nhập góp ý"), ("   ", "Hãy nhập góp ý"), ("x" * 2001, "quá dài")])
def test_revise_needs_usable_feedback(start_app, settings, plan_dict, feedback, message):
    client, planner, job_id = reviewable(start_app, settings, plan_dict)

    response = client.post(f"/api/jobs/{job_id}/revise", data={"feedback": feedback})

    assert response.status_code == 422
    assert message in response.json()["detail"]
    assert planner.calls == []
    assert detail(client, job_id)["status"] == "awaiting_approval"


def test_a_failed_revise_keeps_the_plan_and_shows_the_error(start_app, settings, plan_dict):
    client, _, job_id = reviewable(start_app, settings, plan_dict, PlannerError("Claude từ chối viết lại."))

    client.post(f"/api/jobs/{job_id}/revise", data={"feedback": "Đổi CTA"})
    body = wait_until_planned(client, job_id)
    page = client.get(f"/jobs/{job_id}").text

    assert (body["status"], body["plan_version"], body["error"]) == ("awaiting_approval", 1, "Claude từ chối viết lại.")
    assert body["plan"] == plan_dict
    assert "Claude từ chối viết lại." in page and "PLAN DO CLAUDE ĐỀ XUẤT" in page


# --- manual scene edit ----------------------------------------------------------


def test_editing_a_scene_saves_a_new_plan_version(start_app, settings, plan_dict):
    client, planner, job_id = reviewable(start_app, settings, plan_dict)

    response = client.patch(
        f"/api/jobs/{job_id}/scenes/2",
        data={"voiceover_vi": f"  {words(16)}  ", "subtitle_vi": "Phụ đề mới", "camera": "Máy tĩnh"},
    )

    body = response.json()
    scene = body["plan"]["scenes"][1]
    assert response.status_code == 200
    assert response.headers["hx-refresh"] == "true"
    assert (body["status"], body["plan_version"]) == ("awaiting_approval", 2)
    assert (scene["voiceover_vi"], scene["subtitle_vi"], scene["camera"]) == (words(16), "Phụ đề mới", "Máy tĩnh")
    assert scene["visual"] == plan_dict["scenes"][1]["visual"]
    assert body["plan"]["scenes"][0] == plan_dict["scenes"][0]
    assert "Phụ đề mới" in (settings.data_dir / "jobs" / job_id / "plan.json").read_text(encoding="utf-8")
    assert planner.calls == []


def test_editing_a_scene_duration_within_tolerance_is_allowed(start_app, settings, plan_dict):
    client, _, job_id = reviewable(start_app, settings, plan_dict)

    response = client.patch(f"/api/jobs/{job_id}/scenes/1", data={"duration_sec": "8"})

    assert response.status_code == 200
    assert response.json()["plan"]["scenes"][0]["duration_sec"] == 8


@pytest.mark.parametrize(
    "data, message",
    [
        ({"voiceover_vi": words(25)}, "Cảnh 2: lời thoại có 25 từ, tối đa 19 từ cho cảnh 6 giây"),
        ({"voiceover_vi": "   "}, "Cảnh 2: lời thoại không được để trống"),
        ({"subtitle_vi": words(13)}, "Cảnh 2: phụ đề có 13 từ, tối đa 12 từ"),
        ({"veo_prompt_en": "x" * 1001}, "Prompt Veo dài quá 1.000 ký tự."),
        ({"veo_prompt_en": "An office with a big sign"}, "Cảnh 2: prompt Veo phải kết thúc bằng"),
        ({"duration_sec": "5"}, "Thời lượng cảnh phải là 4, 6 hoặc 8 giây."),
        ({"duration_sec": "abc"}, "Thời lượng cảnh phải là 4, 6 hoặc 8 giây."),
    ],
    ids=["too-many-words", "empty-voiceover", "long-subtitle", "long-prompt", "prompt-allows-text", "duration-5", "duration-text"],
)
def test_an_edit_that_breaks_the_plan_is_rejected_and_nothing_is_saved(start_app, settings, plan_dict, data, message):
    client, _, job_id = reviewable(start_app, settings, plan_dict)

    response = client.patch(f"/api/jobs/{job_id}/scenes/2", data=data)

    assert response.status_code == 422
    assert message in response.json()["detail"]
    body = detail(client, job_id)
    assert (body["plan_version"], body["plan"]) == (1, plan_dict)


# --- rewrite one scene ----------------------------------------------------------


def test_rewrite_scene_asks_claude_for_that_scene(start_app, settings, plan_dict):
    rewritten = copy.deepcopy(plan_dict)
    rewritten["scenes"][2]["visual"] = "Màn hình biểu đồ"
    client, planner, job_id = reviewable(start_app, settings, plan_dict, planner_result(rewritten))

    response = client.post(f"/api/jobs/{job_id}/scenes/3/rewrite", data={"feedback": " sinh động hơn "})
    body = wait_until_planned(client, job_id)

    assert response.status_code == 200
    assert response.headers["hx-refresh"] == "true"
    assert (body["status"], body["plan_version"]) == ("awaiting_approval", 2)
    assert body["plan"]["scenes"][2]["visual"] == "Màn hình biểu đồ"
    assert planner.calls == [("rewrite_scene", Plan.model_validate(plan_dict), 3, "sinh động hơn")]


def test_rewrite_scene_works_without_feedback(start_app, settings, plan_dict):
    client, planner, job_id = reviewable(start_app, settings, plan_dict, planner_result(plan_dict))

    client.post(f"/api/jobs/{job_id}/scenes/3/rewrite")
    wait_until_planned(client, job_id)

    assert planner.calls == [("rewrite_scene", Plan.model_validate(plan_dict), 3, "")]


# --- approve --------------------------------------------------------------------


def test_approve_moves_the_job_to_generating(start_app, settings, plan_dict):
    client, _, job_id = reviewable(start_app, settings, plan_dict)

    response = client.post(f"/api/jobs/{job_id}/approve")
    page = client.get(f"/jobs/{job_id}").text

    assert response.status_code == 200
    assert response.headers["hx-refresh"] == "true"
    assert response.json()["status"] == "generating"
    assert "Plan đã được duyệt." in page
    assert '<li class="step current"><span class="step-dot">3</span>Đang tạo</li>' in page


def test_approving_twice_is_refused(start_app, settings, plan_dict):
    client, _, job_id = reviewable(start_app, settings, plan_dict)
    client.post(f"/api/jobs/{job_id}/approve")

    assert client.post(f"/api/jobs/{job_id}/approve").status_code == 409


def test_approve_is_refused_on_the_server_when_over_the_cap(start_app, settings, plan_dict):
    settings.secrets.video_provider = "veo"
    settings.config.veo.price_usd_per_second = 0.4
    client, _, job_id = reviewable(start_app, settings, plan_dict)

    response = client.post(f"/api/jobs/{job_id}/approve")

    assert response.status_code == 409
    assert response.json()["detail"] == "Chi phí dự kiến 12,00 USD vượt trần 5 USD của video này."
    assert detail(client, job_id)["status"] == "awaiting_approval"


def test_approve_is_refused_when_the_veo_price_is_not_configured(start_app, settings, plan_dict):
    settings.secrets.video_provider = "veo"
    client, _, job_id = reviewable(start_app, settings, plan_dict)

    response = client.post(f"/api/jobs/{job_id}/approve")

    assert response.status_code == 409
    assert "veo.price_usd_per_second" in response.json()["detail"]
    assert detail(client, job_id)["status"] == "awaiting_approval"
