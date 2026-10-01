import asyncio
import shutil
import time

import httpx
import pytest

from app.agent import runner
from app.main import create_app
from app.models import JobStatus, SceneStatus
from app.providers.fake_video import FakeVideoProvider
from tests.fakes import FakePlanner, ScriptedProvider
from tests.helpers import seed_job

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg is not installed on this machine",
)


def wait_until_generated(client, job_id, timeout=90.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/jobs/{job_id}").json()
        if body["status"] != "generating":
            return body
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} is still generating after {timeout}s")


@needs_ffmpeg
def test_approving_generates_every_clip_with_the_fake_provider(start_app, settings, plan_dict):
    client, _ = start_app(provider=FakeVideoProvider("ffmpeg"))
    job_id = seed_job(client.app.state.engine, settings.data_dir, plan_dict=plan_dict)

    response = client.post(f"/api/jobs/{job_id}/approve")
    body = wait_until_generated(client, job_id)
    clip = client.get(f"/api/jobs/{job_id}/clips/3")

    assert response.status_code == 200
    assert body["status"] == "assembling"
    assert [(s["scene_no"], s["status"], s["attempts"], s["error"]) for s in body["scenes"]] == [
        (n, "approved", 1, None) for n in range(1, 6)
    ]
    assert body["scenes"][2]["clip_url"] == f"/api/jobs/{job_id}/clips/3"
    assert body["cost_usd"] == 0
    assert any("cảnh 3 → hoàn tất, đạt kiểm tra" in line["message"] for line in body["log"])
    assert clip.status_code == 200
    assert clip.headers["content-type"] == "video/mp4"
    assert len(clip.content) > 1000


def test_job_detail_lists_scene_errors_and_no_clip_before_generation(start_app, settings, plan_dict):
    client, _ = start_app()
    job_id = seed_job(client.app.state.engine, settings.data_dir, plan_dict=plan_dict)

    body = client.get(f"/api/jobs/{job_id}").json()

    assert body["scenes"][0] == {"scene_no": 1, "status": "planned", "attempts": 0, "error": None, "clip_url": None}
    assert body["log"] == []


def test_a_clip_that_does_not_exist_yet_is_a_404(start_app, settings, plan_dict):
    client, _ = start_app()
    job_id = seed_job(client.app.state.engine, settings.data_dir, plan_dict=plan_dict)

    assert client.get(f"/api/jobs/{job_id}/clips/1").status_code == 404
    assert client.get(f"/api/jobs/{job_id}/clips/99").status_code == 404
    assert client.get("/api/jobs/missing/clips/1").status_code == 404


def test_a_square_job_cannot_be_approved_when_veo_is_selected(start_app, settings, plan_dict):
    settings.secrets.video_provider = "veo"
    settings.config.veo.price_usd_per_second = 0.05
    provider = ScriptedProvider()
    client, _ = start_app(provider=provider)
    job_id = seed_job(client.app.state.engine, settings.data_dir, plan_dict=plan_dict, aspect="1:1")

    response = client.post(f"/api/jobs/{job_id}/approve")
    page = client.get(f"/jobs/{job_id}").text

    assert response.status_code == 409
    assert "9:16 và 16:9" in response.json()["detail"]
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "awaiting_approval"
    assert provider.submit_attempts == 0
    assert "9:16 và 16:9" in page
    assert 'hx-disabled-elt="this" disabled>Duyệt &amp; tạo video</button>' in page


def test_a_square_job_is_fine_with_the_fake_provider(start_app, settings, plan_dict):
    client, _ = start_app()
    job_id = seed_job(client.app.state.engine, settings.data_dir, plan_dict=plan_dict, aspect="1:1")

    assert client.post(f"/api/jobs/{job_id}/approve").status_code == 200


# --- events -------------------------------------------------------------------------


def test_events_for_a_job_that_is_not_generating_end_at_once(start_app, settings, plan_dict):
    client, _ = start_app()
    job_id = seed_job(client.app.state.engine, settings.data_dir, plan_dict=plan_dict)

    response = client.get(f"/api/jobs/{job_id}/events")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text.index("event: update") < response.text.index("event: end")


def test_events_for_an_unknown_job_are_a_404(start_app):
    client, _ = start_app()

    assert client.get("/api/jobs/missing/events").status_code == 404


async def test_events_follow_a_running_job_until_it_ends(settings, plan_dict, monkeypatch):
    async def check(path, **kwargs):
        return []

    monkeypatch.setattr(runner, "check_clip", check)
    settings.config.veo.poll_interval_sec = 0.001
    provider = ScriptedProvider(price=0)
    app = create_app(
        settings, planner_factory=lambda: FakePlanner(), provider_factory=lambda: provider, auto_assemble=False
    )
    async with app.router.lifespan_context(app):
        job_id = seed_job(app.state.engine, settings.data_dir, plan_dict=plan_dict, status=JobStatus.generating)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            listening = asyncio.create_task(client.get(f"/api/jobs/{job_id}/events"))
            for _ in range(200):  # wait for the stream to subscribe before the job starts
                await asyncio.sleep(0.01)
                if app.state.hub.subscriber_count(job_id):
                    break
            app.state.generation.spawn(app.state.generation.run(job_id))
            response = await asyncio.wait_for(listening, timeout=20)
            detail = (await client.get(f"/api/jobs/{job_id}")).json()

    assert response.text.count("event: update") > 5
    assert response.text.rstrip().splitlines()[-2:] == ["event: end", "data: {}"]
    assert detail["status"] == "assembling"
    assert app.state.hub.subscriber_count(job_id) == 0


# --- same-origin check ----------------------------------------------------------------


def test_a_form_posted_from_another_site_is_refused(start_app):
    client, planner = start_app()

    response = client.post(
        "/api/jobs", data={"idea": "ý tưởng từ trang lạ"}, headers={"Origin": "https://evil.example"},
        follow_redirects=False,
    )

    assert response.status_code == 403
    assert client.get("/api/jobs").json() == []
    assert planner.calls == []


def test_same_origin_and_origin_less_posts_still_work(start_app, plan_dict):
    from tests.fakes import planner_result

    client, _ = start_app(planner_result(plan_dict), planner_result(plan_dict))

    same_origin = client.post(
        "/api/jobs", data={"idea": "ý tưởng thứ nhất"}, headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    no_origin = client.post("/api/jobs", data={"idea": "ý tưởng thứ hai"}, follow_redirects=False)

    assert (same_origin.status_code, no_origin.status_code) == (303, 303)


def test_reading_from_another_origin_is_not_blocked(start_app):
    client, _ = start_app()

    assert client.get("/api/jobs", headers={"Origin": "https://evil.example"}).status_code == 200


def test_scene_statuses_use_the_generation_states(start_app, settings, plan_dict):
    client, _ = start_app()
    engine = client.app.state.engine
    job_id = seed_job(engine, settings.data_dir, plan_dict=plan_dict, status=JobStatus.generating)
    from sqlmodel import Session

    from app import jobstore

    with Session(engine) as session:
        jobstore.set_scene(session, job_id, 2, status=SceneStatus.failed, attempts=2, error="sai tỉ lệ khung hình")

    scene = client.get(f"/api/jobs/{job_id}").json()["scenes"][1]

    assert scene == {"scene_no": 2, "status": "failed", "attempts": 2, "error": "sai tỉ lệ khung hình", "clip_url": None}


# --- findings from the phase 3 review ---------------------------------------------------


def test_approve_counts_what_the_job_already_spent_against_the_cap(start_app, settings, plan_dict):
    from sqlmodel import Session

    from app.models import CostEntry

    settings.secrets.video_provider = "veo"
    settings.config.veo.price_usd_per_second = 0.1  # 30 s of clips = $3.00
    provider = ScriptedProvider()
    client, _ = start_app(provider=provider)
    job_id = seed_job(client.app.state.engine, settings.data_dir, plan_dict=plan_dict, cost_cap_usd=3.0)
    with Session(client.app.state.engine) as session:
        session.add(CostEntry(job_id=job_id, kind="gemini", units=1, unit="tokens_in", usd=0.02))
        session.commit()

    response = client.post(f"/api/jobs/{job_id}/approve")
    page = client.get(f"/jobs/{job_id}").text

    assert response.status_code == 409
    assert "3,02 USD" in response.json()["detail"] and "trần 3 USD" in response.json()["detail"]
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "awaiting_approval"
    assert provider.submit_attempts == 0
    assert 'hx-disabled-elt="this" disabled>Duyệt &amp; tạo video</button>' in page
    assert "đã dùng 0,02 USD" in page


@pytest.mark.parametrize("method, path", [("GET", "/"), ("GET", "/api/jobs"), ("POST", "/api/jobs")])
def test_requests_for_a_host_the_server_does_not_serve_are_refused(start_app, method, path):
    client, _ = start_app()

    # A DNS-rebinding page reaches the server under its own host name, with a matching Origin.
    response = client.request(
        method, path, data={"idea": "ý tưởng từ trang lạ"} if method == "POST" else None,
        headers={"Host": "evil.example:8000", "Origin": "http://evil.example:8000"}, follow_redirects=False,
    )

    assert response.status_code == 403
    assert client.get("/api/jobs").json() == []


@pytest.mark.parametrize("host", ["localhost:8000", "127.0.0.1:8000", "127.0.0.1", "[::1]:8000", "LOCALHOST:8000"])
def test_local_host_names_are_served(start_app, host):
    client, _ = start_app()

    assert client.get("/api/jobs", headers={"Host": host}).status_code == 200


def test_an_extra_host_can_be_allowed_in_config(start_app, settings):
    settings.config.server.allowed_hosts.append("may-van-phong.local")
    client, _ = start_app()

    assert client.get("/api/jobs", headers={"Host": "may-van-phong.local:8000"}).status_code == 200
