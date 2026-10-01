from datetime import datetime, timezone

import pytest

from app.agent.planner import PlannerError, PlanOptions
from app.models import JobStatus
from tests.fakes import planner_result
from tests.helpers import seed_job, wait_until_planned

IDEA = "5 việc sếp không biết bạn đang làm bằng AI"


def post_job(client, **data):
    return client.post("/api/jobs", data=data, follow_redirects=False)


def job_id_of(response):
    assert response.status_code == 303, response.text
    location = response.headers["location"]
    assert location.startswith("/jobs/")
    return location.removeprefix("/jobs/")


def test_posting_an_idea_creates_a_job_and_plans_it_in_the_background(start_app, plan_dict):
    client, planner = start_app(planner_result(plan_dict))

    response = post_job(client, idea=f"  {IDEA}  ", duration_sec="60", aspect="1:1",
                        voice="vi-male-north", style="minimal", cost_cap_usd="8")
    job_id = job_id_of(response)
    body = wait_until_planned(client, job_id)

    assert body["status"] == "awaiting_approval"
    assert body["idea"] == IDEA
    assert (body["duration_sec"], body["aspect"], body["voice"], body["style"], body["cost_cap_usd"]) == (
        60, "1:1", "vi-male-north", "minimal", 8.0)
    assert body["plan"] == plan_dict
    assert body["cost_usd"] == 0.00825
    assert planner.calls == [
        ("create_plan", IDEA, PlanOptions(
            duration_sec=60, aspect="1:1", voice="vi-male-north",
            style="minimal bright interior, white walls and light wood, soft diffused light")),
    ]


def test_missing_options_take_the_defaults(start_app, plan_dict):
    client, _ = start_app(planner_result(plan_dict))

    body = wait_until_planned(client, job_id_of(post_job(client, idea=IDEA, cost_cap_usd="")))

    assert (body["duration_sec"], body["aspect"], body["voice"], body["style"], body["cost_cap_usd"]) == (
        30, "9:16", "vi-female-north", "office", 5.0)


def test_cost_cap_accepts_a_decimal_comma(start_app, plan_dict):
    client, _ = start_app(planner_result(plan_dict))

    body = wait_until_planned(client, job_id_of(post_job(client, idea=IDEA, cost_cap_usd="2,5")))

    assert body["cost_cap_usd"] == 2.5


@pytest.mark.parametrize(
    "data, message",
    [
        ({"idea": ""}, "Hãy nhập ý tưởng"),
        ({"idea": "   "}, "Hãy nhập ý tưởng"),
        ({"idea": "ab"}, "Hãy nhập ý tưởng"),
        ({"idea": "x" * 1001}, "Ý tưởng quá dài"),
        ({"idea": IDEA, "cost_cap_usd": "0"}, "Trần chi phí phải là số lớn hơn 0"),
        ({"idea": IDEA, "cost_cap_usd": "-1"}, "Trần chi phí phải là số lớn hơn 0"),
        ({"idea": IDEA, "cost_cap_usd": "abc"}, "Trần chi phí phải là số lớn hơn 0"),
        ({"idea": IDEA, "cost_cap_usd": "nan"}, "Trần chi phí phải là số lớn hơn 0"),
        ({"idea": IDEA, "cost_cap_usd": "inf"}, "Trần chi phí phải là số lớn hơn 0"),
        ({"idea": IDEA, "duration_sec": "45"}, "Thời lượng không hợp lệ"),
        ({"idea": IDEA, "aspect": "4:3"}, "Tỉ lệ khung hình không hợp lệ"),
        ({"idea": IDEA, "voice": "robot"}, "Giọng đọc không hợp lệ"),
        ({"idea": IDEA, "style": "x"}, "Phong cách không hợp lệ"),
    ],
)
def test_invalid_input_re_renders_the_form_and_creates_nothing(start_app, data, message):
    client, planner = start_app()

    response = post_job(client, **data)

    assert response.status_code == 422
    assert message in response.text
    assert '<form method="post" action="/api/jobs"' in response.text
    assert client.get("/api/jobs").json() == []
    assert planner.calls == []


def test_the_form_keeps_what_the_user_typed_when_it_is_rejected(start_app):
    client, _ = start_app()

    response = post_job(client, idea=IDEA, duration_sec="60", cost_cap_usd="abc")

    assert f">{IDEA}</textarea>" in response.text
    assert 'id="duration-60" value="60" checked>' in response.text
    assert 'name="cost_cap_usd" value="abc"' in response.text


def test_a_failed_plan_shows_the_error_and_a_way_back(start_app):
    client, _ = start_app(PlannerError("Claude từ chối lập plan cho ý tưởng này."))

    job_id = job_id_of(post_job(client, idea=IDEA))
    body = wait_until_planned(client, job_id)
    page = client.get(f"/jobs/{job_id}")

    assert (body["status"], body["failed_step"]) == ("failed", "planning")
    assert page.status_code == 200
    assert "Claude từ chối lập plan cho ý tưởng này." in page.text
    assert f'href="/?job={job_id}"' in page.text
    assert "hx-trigger" not in page.text


def test_planning_page_polls_and_marks_step_two(start_app, settings):
    client, _ = start_app()
    job_id = seed_job(client.app.state.engine, settings.data_dir)

    text = client.get(f"/jobs/{job_id}").text

    assert "AI đang lập plan…" in text
    assert f'hx-get="/jobs/{job_id}"' in text
    assert 'hx-trigger="every 2s"' in text
    assert 'hx-select="#shell"' in text
    assert '<li class="step done"><span class="step-dot">✓</span>Ý tưởng</li>' in text
    assert '<li class="step current"><span class="step-dot">2</span>Duyệt plan</li>' in text


def test_planning_page_says_rewriting_when_a_plan_already_exists(start_app, settings, plan_dict):
    client, _ = start_app()
    job_id = seed_job(client.app.state.engine, settings.data_dir, plan_dict=plan_dict, status=JobStatus.planning)

    assert "AI đang viết lại plan…" in client.get(f"/jobs/{job_id}").text


def test_job_list_is_newest_first(start_app, settings):
    client, _ = start_app()
    engine = client.app.state.engine
    seed_job(engine, settings.data_dir, idea="cũ", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    seed_job(engine, settings.data_dir, idea="mới", created_at=datetime(2026, 1, 2, tzinfo=timezone.utc))

    jobs = client.get("/api/jobs").json()

    assert [(job["idea"], job["status"], job["status_label"]) for job in jobs] == [
        ("mới", "planning", "Đang lập plan"),
        ("cũ", "planning", "Đang lập plan"),
    ]


def test_job_detail_includes_plan_scenes_and_estimate(start_app, settings, plan_dict):
    client, _ = start_app()
    job_id = seed_job(client.app.state.engine, settings.data_dir, plan_dict=plan_dict)

    body = client.get(f"/api/jobs/{job_id}").json()

    assert body["status"] == "awaiting_approval"
    assert body["plan_version"] == 1
    assert body["plan"] == plan_dict
    assert [(s["scene_no"], s["status"], s["attempts"]) for s in body["scenes"]] == [
        (n, "planned", 0) for n in range(1, 6)
    ]
    assert body["estimate"]["total_video_sec"] == 30
    assert body["estimate"]["cost_usd"] == 0
    assert body["error"] is None


def test_unknown_job_is_a_404(start_app):
    client, _ = start_app()

    api = client.get("/api/jobs/missing")
    page = client.get("/jobs/missing")

    assert (api.status_code, api.json()) == (404, {"detail": "Không tìm thấy job."})
    assert page.status_code == 404
    assert "Không tìm thấy" in page.text
