import time

from sqlmodel import Session

from app import jobstore
from app.models import JobStatus, SceneStatus
from app.providers.base import ClipRequest
from app.providers.fake_video import FakeVideoProvider
from app.schemas import Plan

JOB_FIELDS = dict(
    idea="5 việc sếp không biết bạn đang làm bằng AI",
    duration_sec=30,
    aspect="9:16",
    voice="vi-female-north",
    style="office",
    cost_cap_usd=5.0,
)


def seed_job(engine, data_dir, *, plan_dict=None, **attrs):
    """Insert a job directly (no planner, no background task) and return its id."""
    fields = JOB_FIELDS | {key: attrs.pop(key) for key in list(attrs) if key in JOB_FIELDS}
    with Session(engine) as session:
        job = jobstore.create_job(session, **fields)
        if plan_dict is not None:
            jobstore.save_plan(session, data_dir, job, Plan.model_validate(plan_dict))
        for name, value in attrs.items():
            setattr(job, name, value)
        session.add(job)
        session.commit()
        return job.id


def wait_until_planned(client, job_id, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/jobs/{job_id}").json()
        if body["status"] != "planning":
            return body
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} is still planning after {timeout}s")


async def make_assembling_job(settings, engine, plan, **attrs):
    """A job whose clips exist (real FFmpeg clips) and are approved, waiting for voice and assembly."""
    job_id = seed_job(engine, settings.data_dir, plan_dict=plan, status=JobStatus.assembling, **attrs)
    provider = FakeVideoProvider("ffmpeg")
    with Session(engine) as session:
        for scene in plan["scenes"]:
            operation = await provider.submit(ClipRequest(scene["id"], "x", "9:16", scene["duration_sec"]))
            await provider.download(operation, jobstore.clip_path(settings.data_dir, job_id, scene["id"]))
            jobstore.set_scene(session, job_id, scene["id"], status=SceneStatus.approved, attempts=1)
    return job_id
