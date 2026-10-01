from app.schemas import Plan
from app.web.views import fmt_clock, fmt_number, scene_rows
from tests.helpers import seed_job

APPROVE_OPEN = 'hx-disabled-elt="this">Duyệt &amp; tạo video</button>'
APPROVE_LOCKED = 'hx-disabled-elt="this" disabled>Duyệt &amp; tạo video</button>'


def review_page(start_app, settings, plan_dict, **attrs):
    client, _ = start_app()
    job_id = seed_job(client.app.state.engine, settings.data_dir, plan_dict=plan_dict, **attrs)
    response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    return job_id, response.text, client


def test_formatting_helpers():
    assert (fmt_clock(0), fmt_clock(6), fmt_clock(64)) == ("0:00", "0:06", "1:04")
    assert (fmt_number(12), fmt_number(5.5, 1), fmt_number(0)) == ("12,00", "5,5", "0,00")


def test_scene_timeline_adds_up_scene_durations(plan_dict):
    plan_dict["scenes"][0]["duration_sec"] = 4
    plan_dict["scenes"][1]["duration_sec"] = 8

    rows = scene_rows(Plan.model_validate(plan_dict))

    assert [row["time"] for row in rows] == ["0:00–0:04", "0:04–0:12", "0:12–0:18", "0:18–0:24", "0:24–0:30"]
    assert [row["scene"].id for row in rows] == [1, 2, 3, 4, 5]


def test_review_shows_the_idea_brief_and_every_scene(start_app, settings, plan_dict):
    job_id, text, _ = review_page(start_app, settings, plan_dict)

    assert "PLAN DO AI ĐỀ XUẤT" in text
    assert "<h1>5 việc sếp không biết bạn đang làm bằng AI</h1>" in text
    assert "30 giây · 9:16 · 5 cảnh · Giọng: Nữ (Hoài My)" in text
    for value in plan_dict["brief"].values():
        assert value in text
    for scene in plan_dict["scenes"]:
        assert f"Cảnh {scene['id']}" in text
        assert scene["voiceover_vi"] in text
        assert scene["visual"] in text
        assert scene["veo_prompt_en"] in text
    assert "0:00–0:06" in text and "0:24–0:30" in text
    assert '<li class="step current"><span class="step-dot">2</span>Duyệt plan</li>' in text
    assert "hx-trigger" not in text  # no polling once the plan is ready


def test_review_wires_the_actions_to_the_api(start_app, settings, plan_dict):
    job_id, text, _ = review_page(start_app, settings, plan_dict)

    assert f'hx-post="/api/jobs/{job_id}/revise"' in text
    assert f'hx-patch="/api/jobs/{job_id}/scenes/2"' in text
    assert f'hx-post="/api/jobs/{job_id}/scenes/2/rewrite"' in text
    assert f'hx-post="/api/jobs/{job_id}/approve"' in text
    assert 'data-toggle="edit-2"' in text and 'id="edit-2"' in text
    assert f'href="/?job={job_id}"' in text
    assert f'href="/api/jobs/{job_id}/plan.json"' in text


def test_estimate_with_the_fake_provider_is_free_and_approvable(start_app, settings, plan_dict):
    _, text, _ = review_page(start_app, settings, plan_dict)

    assert "<strong>30 giây</strong>" in text
    assert "<strong>5 (+ tối đa 5 lần sinh lại)</strong>" in text
    assert "<strong>~5,5 phút</strong>" in text
    assert "<strong>0,00 USD</strong>" in text
    assert "Trần của bạn: 5 USD" in text
    assert "VIDEO_PROVIDER=fake" in text
    assert APPROVE_OPEN in text


def test_estimate_over_the_cap_locks_the_approve_button(start_app, settings, plan_dict):
    settings.secrets.video_provider = "veo"
    settings.config.veo.price_usd_per_second = 0.4

    _, text, _ = review_page(start_app, settings, plan_dict)

    assert "<strong>12,00 USD</strong>" in text
    assert "Tối đa 24,00 USD" in text
    assert "vượt trần" in text
    assert APPROVE_LOCKED in text
    assert "VIDEO_PROVIDER=fake" not in text


def test_estimate_within_a_higher_job_cap_is_approvable(start_app, settings, plan_dict):
    settings.secrets.video_provider = "veo"
    settings.config.veo.price_usd_per_second = 0.4

    _, text, _ = review_page(start_app, settings, plan_dict, cost_cap_usd=15.0)

    assert "Trần của bạn: 15 USD" in text
    assert APPROVE_OPEN in text


def test_missing_veo_price_explains_and_locks(start_app, settings, plan_dict):
    settings.secrets.video_provider = "veo"

    _, text, _ = review_page(start_app, settings, plan_dict)

    assert "veo.price_usd_per_second" in text
    assert APPROVE_LOCKED in text


def test_error_from_a_failed_rewrite_is_shown_above_the_plan(start_app, settings, plan_dict):
    _, text, _ = review_page(start_app, settings, plan_dict, error="Claude từ chối viết lại.")

    assert "Claude từ chối viết lại." in text
    assert "<h1>5 việc sếp" in text


def test_text_from_the_plan_is_escaped(start_app, settings, plan_dict):
    plan_dict["scenes"][0]["visual"] = '<script>alert("x")</script>'
    plan_dict["brief"]["cta"] = "Theo dõi <b>ngay</b>"

    _, text, _ = review_page(start_app, settings, plan_dict, idea="<img src=x onerror=alert(1)>")

    assert "<script>alert" not in text and "<img src=x" not in text and "<b>ngay</b>" not in text
    assert "&lt;script&gt;" in text and "&lt;b&gt;ngay&lt;/b&gt;" in text


def test_plan_json_download(start_app, settings, plan_dict):
    job_id, _, client = review_page(start_app, settings, plan_dict)

    response = client.get(f"/api/jobs/{job_id}/plan.json")

    assert response.status_code == 200
    assert response.json() == plan_dict
    assert response.headers["content-disposition"] == f'attachment; filename="plan-{job_id}.json"'


def test_plan_json_for_a_job_without_a_plan_is_a_404(start_app, settings):
    client, _ = start_app()
    job_id = seed_job(client.app.state.engine, settings.data_dir)

    response = client.get(f"/api/jobs/{job_id}/plan.json")

    assert (response.status_code, response.json()) == (404, {"detail": "Job này chưa có plan."})
