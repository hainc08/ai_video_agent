import pytest
from sqlmodel import Session

from app import jobstore
from app.models import CostEntry, JobStatus, SceneStatus
from tests.helpers import seed_job


@pytest.fixture
def running_job(start_app, settings, plan_dict):
    """A job mid-generation: scene 1 done, 2 rendering, 3 being regenerated, 4 queued, 5 failed."""
    client, _ = start_app()
    engine = client.app.state.engine
    job_id = seed_job(engine, settings.data_dir, plan_dict=plan_dict, status=JobStatus.generating)
    clip = jobstore.clip_path(settings.data_dir, job_id, 1)
    clip.parent.mkdir(parents=True, exist_ok=True)
    clip.write_bytes(b"clip")
    with Session(engine) as session:
        jobstore.set_scene(session, job_id, 1, status=SceneStatus.approved, attempts=1, clip_path="clips/scene_01.mp4")
        jobstore.set_scene(session, job_id, 2, status=SceneStatus.generating, attempts=1)
        jobstore.set_scene(session, job_id, 3, status=SceneStatus.regenerating, attempts=1,
                           error="sai tỉ lệ khung hình (clip 1280×720, cần 9:16)")
        jobstore.set_scene(session, job_id, 5, status=SceneStatus.failed, attempts=2, error="Veo không trả về video nào.")
        session.add(CostEntry(job_id=job_id, kind="veo", units=6, unit="seconds", usd=0.6))
        session.commit()
    jobstore.append_log(settings.data_dir, job_id, "gate", "người dùng đã duyệt plan")
    jobstore.append_log(settings.data_dir, job_id, "veo", "cảnh 1 → hoàn tất, đạt kiểm tra")
    jobstore.append_log(settings.data_dir, job_id, "veo", "cảnh 3 → <script>alert(1)</script>")
    return client, job_id


def test_progress_page_shows_title_idea_and_header_step_three(running_job):
    client, job_id = running_job

    text = client.get(f"/jobs/{job_id}").text

    assert "<h1>Đang tạo video</h1>" in text
    assert "5 việc sếp không biết bạn đang làm bằng AI" in text
    assert '<li class="step current"><span class="step-dot">3</span>Đang tạo</li>' in text
    assert f'data-events-url="/api/jobs/{job_id}/events"' in text
    assert f'data-progress-url="/jobs/{job_id}/progress"' in text


def test_the_six_steps_show_what_is_done_running_and_waiting(running_job):
    client, job_id = running_job

    text = client.get(f"/jobs/{job_id}").text

    assert text.count('class="pstep done"') == 2
    assert text.count('class="pstep run"') == 1
    assert text.count('class="pstep wait"') == 3
    for title in ("Lập plan", "Duyệt plan", "Sinh clip bằng Veo", "Kiểm tra clip", "Giọng đọc + phụ đề", "Ghép MP4"):
        assert title in text
    assert "1/5 cảnh xong" in text


def test_each_scene_tile_shows_its_state(running_job):
    client, job_id = running_job

    text = client.get(f"/jobs/{job_id}").text

    assert text.count('class="tile ') == 5
    assert '<span class="tile-badge">Đạt</span>' in text
    assert '<span class="tile-badge">Đang sinh</span>' in text
    assert '<span class="tile-badge">Sinh lại</span>' in text
    assert '<span class="tile-badge">Hàng đợi</span>' in text
    assert '<span class="tile-badge">Lỗi</span>' in text
    assert "Lần 1/1 · sai tỉ lệ khung hình (clip 1280×720, cần 9:16)" in text
    assert "Veo không trả về video nào." in text
    assert "Chạy song song tối đa 3 clip" in text


def test_only_approved_scenes_get_a_video_player(running_job):
    client, job_id = running_job

    text = client.get(f"/jobs/{job_id}").text

    assert text.count("<video") == 1
    assert f'src="/api/jobs/{job_id}/clips/1"' in text
    assert 'id="clip-1" hx-preserve="true"' in text  # kept across live refreshes so it does not restart


def test_cost_bar_shows_spent_against_the_cap(running_job):
    client, job_id = running_job

    text = client.get(f"/jobs/{job_id}").text

    assert "0,60 / 5 USD" in text
    assert 'style="width: 12%"' in text


def test_log_lines_are_shown_and_escaped(running_job):
    client, job_id = running_job

    text = client.get(f"/jobs/{job_id}").text

    assert "[gate] người dùng đã duyệt plan" in text
    assert "[veo] cảnh 1 → hoàn tất, đạt kiểm tra" in text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text
    assert "<script>alert(1)</script>" not in text


def test_the_fragment_route_returns_only_the_progress_block(running_job):
    client, job_id = running_job

    response = client.get(f"/jobs/{job_id}/progress")

    assert response.status_code == 200
    assert response.text.lstrip().startswith('<div id="progress"')
    assert "<html" not in response.text and "site-header" not in response.text
    assert "1/5 cảnh xong" in response.text
    assert client.get("/jobs/missing/progress").status_code == 404


def test_cost_bar_never_exceeds_its_track(running_job, settings):
    client, job_id = running_job
    with Session(client.app.state.engine) as session:
        session.add(CostEntry(job_id=job_id, kind="veo", units=60, unit="seconds", usd=9.0))
        session.commit()

    assert 'style="width: 100%"' in client.get(f"/jobs/{job_id}/progress").text


def test_a_failed_generation_lists_the_scenes_that_failed(start_app, settings, plan_dict):
    client, _ = start_app()
    engine = client.app.state.engine
    job_id = seed_job(
        engine, settings.data_dir, plan_dict=plan_dict, status=JobStatus.failed, failed_step="generating",
        error="Cảnh 3 không sinh được clip: sai tỉ lệ khung hình",
    )
    with Session(engine) as session:
        jobstore.set_scene(session, job_id, 3, status=SceneStatus.failed, attempts=2, error="sai tỉ lệ khung hình")
        jobstore.set_scene(session, job_id, 1, status=SceneStatus.approved, attempts=1)

    text = client.get(f"/jobs/{job_id}").text

    assert "Bước lỗi: Sinh video" in text
    assert "Cảnh 3 không sinh được clip: sai tỉ lệ khung hình" in text
    assert "<li>Cảnh 3: sai tỉ lệ khung hình</li>" in text
    assert "1/5 cảnh đã có clip" in text
