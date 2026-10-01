import asyncio
import copy
import os
import shutil
import time
from datetime import datetime, timezone

import httpx
import pytest
from sqlmodel import Session

from app import jobstore
from app.db import init_db, make_engine
from app.main import create_app
from app.models import CostEntry, JobStatus, SceneStatus
from app.providers.fake_video import FakeVideoProvider
from app.providers.tts_fake import FakeTTSProvider
from tests.fakes import FakePlanner
from tests.helpers import make_assembling_job, seed_job

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg is not installed on this machine",
)


@pytest.fixture
def short_plan(plan_dict):
    plan = copy.deepcopy(plan_dict)
    plan["scenes"] = plan["scenes"][:2]
    for scene in plan["scenes"]:
        scene["duration_sec"] = 4
    return plan


@pytest.fixture(autouse=True)
def fast(settings):
    settings.config.assembler.output_width = 270
    settings.config.assembler.output_height = 480
    settings.config.assembler.x264_preset = "ultrafast"


def wait_until_finished(client, job_id, timeout=120.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/jobs/{job_id}").json()
        if body["status"] not in ("generating", "assembling"):
            return body
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} did not finish within {timeout}s")


def done_job(client, settings, plan, **attrs):
    """A finished job with a (tiny, fake) final.mp4 on disk."""
    job_id = seed_job(client.app.state.engine, settings.data_dir, plan_dict=plan, status=JobStatus.done, **attrs)
    final = jobstore.final_path(settings.data_dir, job_id)
    final.parent.mkdir(parents=True, exist_ok=True)
    final.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 200)
    return job_id


# --- from approval to a finished video ---------------------------------------------------


@needs_ffmpeg
def test_approving_runs_all_the_way_to_a_finished_video(start_app, settings, short_plan):
    client, _ = start_app(provider=FakeVideoProvider("ffmpeg"), auto_assemble=True)
    job_id = seed_job(client.app.state.engine, settings.data_dir, plan_dict=short_plan)

    assert client.post(f"/api/jobs/{job_id}/approve").status_code == 200
    body = wait_until_finished(client, job_id)
    video = client.get(f"/api/jobs/{job_id}/video")

    assert (body["status"], body["error"]) == ("done", None)
    assert body["video_url"] == f"/api/jobs/{job_id}/video"
    assert video.status_code == 200
    assert video.headers["content-type"] == "video/mp4"
    assert len(video.content) > 1000
    assert any("final.mp4 xong" in line["message"] for line in body["log"])


@needs_ffmpeg
def test_a_job_left_assembling_by_a_restart_is_finished_at_startup(start_app, settings, short_plan):
    engine = make_engine(settings.data_dir)
    init_db(engine)
    job_id = asyncio.run(make_assembling_job(settings, engine, short_plan))
    engine.dispose()

    client, _ = start_app(auto_assemble=True)
    body = wait_until_finished(client, job_id)

    assert body["status"] == "done"


@needs_ffmpeg
async def test_events_follow_the_assembly_until_the_video_is_done(settings, short_plan):
    tts = FakeTTSProvider("ffmpeg")
    app = create_app(
        settings, planner_factory=lambda: FakePlanner(), provider_factory=lambda: FakeVideoProvider("ffmpeg"),
        tts_factory=lambda: tts,
    )
    async with app.router.lifespan_context(app):
        job_id = await make_assembling_job(settings, app.state.engine, short_plan)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            listening = asyncio.create_task(client.get(f"/api/jobs/{job_id}/events"))
            for _ in range(200):
                await asyncio.sleep(0.01)
                if app.state.hub.subscriber_count(job_id):
                    break
            app.state.generation.spawn(app.state.generation.run(job_id))
            response = await asyncio.wait_for(listening, timeout=120)
            detail = (await client.get(f"/api/jobs/{job_id}")).json()

    assert response.text.count("event: update") >= 3
    assert response.text.rstrip().splitlines()[-2:] == ["event: end", "data: {}"]
    assert detail["status"] == "done"


# --- video route ------------------------------------------------------------------------


def test_video_is_served_inline_and_as_a_download(start_app, settings, plan_dict):
    client, _ = start_app()
    job_id = done_job(client, settings, plan_dict)

    inline = client.get(f"/api/jobs/{job_id}/video")
    download = client.get(f"/api/jobs/{job_id}/video?download=1")

    assert inline.status_code == 200 and inline.headers["content-type"] == "video/mp4"
    assert "attachment" not in inline.headers.get("content-disposition", "")
    assert f'filename="video-{job_id}.mp4"' in download.headers["content-disposition"]
    assert "attachment" in download.headers["content-disposition"]


def test_video_that_is_not_there_is_a_404(start_app, settings, plan_dict):
    client, _ = start_app()
    waiting = seed_job(client.app.state.engine, settings.data_dir, plan_dict=plan_dict)
    lost = done_job(client, settings, plan_dict)
    jobstore.final_path(settings.data_dir, lost).unlink()

    assert client.get(f"/api/jobs/{waiting}/video").status_code == 404
    assert client.get(f"/api/jobs/{lost}/video").status_code == 404
    assert client.get("/api/jobs/missing/video").status_code == 404
    assert client.get(f"/api/jobs/{lost}").json()["video_url"] is None


# --- caption ----------------------------------------------------------------------------


def test_the_suggested_caption_can_be_edited_and_saved(start_app, settings, plan_dict):
    client, _ = start_app()
    job_id = done_job(client, settings, plan_dict)

    response = client.post(f"/api/jobs/{job_id}/caption", data={"caption": "  Caption mới của tôi?  "})

    body = response.json()
    assert response.status_code == 200
    assert response.headers["hx-refresh"] == "true"
    assert body["plan"]["caption_vi"] == "Caption mới của tôi?"
    assert (body["status"], body["plan_version"]) == ("done", 2)
    assert body["plan"]["scenes"] == plan_dict["scenes"]


@pytest.mark.parametrize("caption, message", [("", "Hãy nhập caption"), ("   ", "Hãy nhập caption"), ("x" * 2201, "quá dài")])
def test_a_caption_must_be_usable(start_app, settings, plan_dict, caption, message):
    client, _ = start_app()
    job_id = done_job(client, settings, plan_dict)

    response = client.post(f"/api/jobs/{job_id}/caption", data={"caption": caption})

    assert response.status_code == 422
    assert message in response.json()["detail"]
    assert client.get(f"/api/jobs/{job_id}").json()["plan_version"] == 1


def test_caption_of_a_job_without_a_finished_video_cannot_be_changed(start_app, settings, plan_dict):
    client, _ = start_app()
    job_id = seed_job(client.app.state.engine, settings.data_dir, plan_dict=plan_dict)

    assert client.post(f"/api/jobs/{job_id}/caption", data={"caption": "x"}).status_code == 409
    assert client.post("/api/jobs/missing/caption", data={"caption": "x"}).status_code == 404


# --- screen 3 while the video is being finished -----------------------------------------------


def assembling(client, settings, plan):
    engine = client.app.state.engine
    job_id = seed_job(engine, settings.data_dir, plan_dict=plan, status=JobStatus.assembling)
    with Session(engine) as session:
        for scene in plan["scenes"]:
            jobstore.set_scene(session, job_id, scene["id"], status=SceneStatus.approved, attempts=1)
    return job_id


def voice_file(settings, job_id, scene_no):
    path = jobstore.audio_path(settings.data_dir, job_id, scene_no)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"wav")


def test_screen_three_shows_voice_progress_while_assembling(start_app, settings, short_plan):
    client, _ = start_app()
    job_id = assembling(client, settings, short_plan)
    voice_file(settings, job_id, 1)

    text = client.get(f"/jobs/{job_id}").text

    assert text.count('class="pstep done"') == 4
    assert text.count('class="pstep run"') == 1
    assert text.count('class="pstep wait"') == 1
    assert "1/2 cảnh có giọng đọc" in text
    assert f'data-events-url="/api/jobs/{job_id}/events"' in text  # still live: the job is running
    assert "Giai đoạn 4" not in text


def test_screen_three_shows_the_assembly_step_once_all_voices_exist(start_app, settings, short_plan):
    client, _ = start_app()
    job_id = assembling(client, settings, short_plan)
    voice_file(settings, job_id, 1)
    voice_file(settings, job_id, 2)

    text = client.get(f"/jobs/{job_id}").text

    assert text.count('class="pstep done"') == 5
    assert text.count('class="pstep run"') == 1
    assert "2/2 cảnh có giọng đọc" in text
    assert "Đang ghép video…" in text


def test_a_failed_assembly_names_the_step(start_app, settings, plan_dict):
    client, _ = start_app()
    job_id = seed_job(
        client.app.state.engine, settings.data_dir, plan_dict=plan_dict, status=JobStatus.failed,
        failed_step="assembling", error="Không tạo được giọng đọc cho cảnh 2: Edge không phản hồi",
    )

    text = client.get(f"/jobs/{job_id}").text

    assert "Bước lỗi: Giọng đọc và ghép video" in text
    assert "Không tạo được giọng đọc cho cảnh 2" in text


# --- screen 4 -------------------------------------------------------------------------------


def test_screen_four_plays_the_video_and_offers_the_downloads(start_app, settings, plan_dict):
    client, _ = start_app()
    job_id = done_job(client, settings, plan_dict)

    text = client.get(f"/jobs/{job_id}").text

    assert '<li class="step current"><span class="step-dot">4</span>Hoàn tất</li>' in text
    assert f'<video class="player" src="/api/jobs/{job_id}/video" controls' in text
    assert f'href="/api/jobs/{job_id}/video?download=1"' in text and "Tải MP4" in text
    assert f'href="/api/jobs/{job_id}/plan.json"' in text and "Tải plan.json" in text
    assert f'hx-post="/api/jobs/{job_id}/caption"' in text
    assert plan_dict["caption_vi"] in text
    assert 'href="/"' in text and "Tạo video mới" in text
    assert "hx-trigger" not in text and "data-events-url" not in text


def test_screen_four_shows_real_time_cost_and_regenerated_scenes(start_app, settings, plan_dict):
    client, _ = start_app()
    engine = client.app.state.engine
    job_id = done_job(client, settings, plan_dict)
    with Session(engine) as session:
        job = jobstore.get_job(session, job_id)
        created = job.created_at.replace(tzinfo=timezone.utc).timestamp()
        jobstore.set_scene(session, job_id, 2, status=SceneStatus.approved, attempts=2)
        jobstore.set_scene(session, job_id, 4, status=SceneStatus.approved, attempts=2)
        session.add(CostEntry(job_id=job_id, kind="veo", units=30, unit="seconds", usd=1.5))
        session.add(CostEntry(job_id=job_id, kind="gemini", units=1, unit="tokens_in", usd=0.017))
        session.commit()
    final = jobstore.final_path(settings.data_dir, job_id)
    os.utime(final, (created + 125, created + 125))

    text = client.get(f"/jobs/{job_id}").text

    assert "2 phút 5 giây" in text
    assert "1,52 USD" in text
    assert '<div class="stat-value">2</div>' in text


def test_screen_four_escapes_the_caption_and_the_idea(start_app, settings, plan_dict):
    plan_dict["caption_vi"] = "</textarea><script>alert(1)</script>"
    client, _ = start_app()
    job_id = done_job(client, settings, plan_dict, idea="<b>ý tưởng</b>")

    text = client.get(f"/jobs/{job_id}").text

    assert "<script>alert(1)</script>" not in text and "<b>ý tưởng</b>" not in text
    assert "&lt;/textarea&gt;&lt;script&gt;" in text


def test_screen_four_without_its_video_file_says_so(start_app, settings, plan_dict):
    client, _ = start_app()
    job_id = done_job(client, settings, plan_dict)
    jobstore.final_path(settings.data_dir, job_id).unlink()

    response = client.get(f"/jobs/{job_id}")

    assert response.status_code == 200
    assert "Không tìm thấy file video" in response.text
    assert "<video" not in response.text
