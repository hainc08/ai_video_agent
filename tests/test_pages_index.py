from datetime import datetime, timezone

from sqlmodel import Session

from app import jobstore
from app.db import init_db, make_engine
from app.models import JobStatus
from tests.helpers import seed_job


def test_form_posts_to_the_api_with_the_defaults_selected(start_app):
    client, _ = start_app()

    text = client.get("/").text

    assert '<form method="post" action="/api/jobs"' in text
    assert '<textarea id="idea" name="idea"' in text
    assert 'id="duration-30" value="30" checked>' in text
    assert 'id="duration-15" value="15">' in text
    assert 'id="aspect-1" value="9:16" checked>' in text
    assert '<option value="vi-female-north" selected>Nữ · miền Bắc</option>' in text
    assert '<option value="office" selected>Văn phòng · chuyên nghiệp</option>' in text
    assert 'name="cost_cap_usd" value="5"' in text
    assert "Lập kế hoạch" in text


def test_header_marks_step_one_as_current(start_app):
    client, _ = start_app()

    text = client.get("/").text

    assert '<li class="step current"><span class="step-dot">1</span>Ý tưởng</li>' in text
    assert '<li class="step"><span class="step-dot">2</span>Duyệt plan</li>' in text
    assert '<li class="step"><span class="step-dot">4</span>Hoàn tất</li>' in text


def test_recent_videos_show_an_empty_state(start_app):
    client, _ = start_app()

    assert "Chưa có video nào" in client.get("/").text


def test_recent_videos_list_jobs_with_status_and_escaped_text(start_app, settings, plan_dict):
    client, _ = start_app()
    engine = client.app.state.engine
    old = seed_job(engine, settings.data_dir, idea="Mẹo <script>alert(1)</script>",
                   status=JobStatus.failed, created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    new = seed_job(engine, settings.data_dir, plan_dict=plan_dict, idea="Ý tưởng mới",
                   created_at=datetime(2026, 1, 2, tzinfo=timezone.utc))

    text = client.get("/").text

    assert "Chưa có video nào" not in text
    assert f'href="/jobs/{new}"' in text and f'href="/jobs/{old}"' in text
    assert text.index("Ý tưởng mới") < text.index("Mẹo")
    assert "Chờ duyệt" in text and "Lỗi" in text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text
    assert "<script>alert(1)</script>" not in text


def test_form_can_be_prefilled_from_an_existing_job(start_app, settings):
    client, _ = start_app()
    job_id = seed_job(client.app.state.engine, settings.data_dir, idea="ý tưởng cũ", duration_sec=60,
                      aspect="1:1", voice="vi-male-north", style="cinematic", cost_cap_usd=2.5)

    text = client.get(f"/?job={job_id}").text

    assert ">ý tưởng cũ</textarea>" in text
    assert 'id="duration-60" value="60" checked>' in text
    assert 'id="aspect-2" value="1:1" checked>' in text
    assert '<option value="vi-male-north" selected>' in text
    assert '<option value="cinematic" selected>' in text
    assert 'name="cost_cap_usd" value="2.5"' in text


def test_prefill_with_an_unknown_job_shows_the_default_form(start_app):
    client, _ = start_app()

    response = client.get("/?job=missing")

    assert response.status_code == 200
    assert 'id="duration-30" value="30" checked>' in response.text


def test_static_scripts_are_served(start_app):
    client, _ = start_app()

    assert "htmx" in client.get("/static/htmx.min.js").text
    assert "htmx:responseError" in client.get("/static/app.js").text


def test_jobs_left_planning_by_a_restart_are_recovered_on_startup(start_app, settings):
    engine = make_engine(settings.data_dir)
    init_db(engine)
    job_id = seed_job(engine, settings.data_dir)
    engine.dispose()

    client, _ = start_app()

    with Session(client.app.state.engine) as session:
        job = jobstore.get_job(session, job_id)
        assert (job.status, job.error) == (JobStatus.failed, jobstore.INTERRUPTED_MESSAGE)
