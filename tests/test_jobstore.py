from datetime import datetime, timezone

import pytest
from sqlmodel import select

from app import jobstore
from app.config import ClaudeConfig
from app.models import CostEntry, JobStatus, Scene
from app.schemas import Plan

FIELDS = dict(
    idea="5 việc sếp không biết bạn đang làm bằng AI",
    duration_sec=30,
    aspect="9:16",
    voice="vi-female-north",
    style="office",
    cost_cap_usd=5.0,
)
PRICED = ClaudeConfig(model="m", price_usd_per_mtok_input=2.0, price_usd_per_mtok_output=10.0)


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path / "data"


@pytest.fixture
def plan(plan_dict):
    return Plan.model_validate(plan_dict)


def test_create_job_starts_in_planning(session):
    job = jobstore.create_job(session, **FIELDS)

    stored = jobstore.get_job(session, job.id)
    assert stored.status == JobStatus.planning
    assert stored.idea == FIELDS["idea"]
    assert stored.cost_cap_usd == 5.0
    assert jobstore.load_plan(stored) is None
    assert jobstore.get_job(session, "missing") is None


def test_save_plan_stores_the_plan_its_files_and_scene_rows(session, data_dir, plan, plan_dict):
    job = jobstore.create_job(session, **FIELDS)

    jobstore.save_plan(session, data_dir, job, plan)

    assert job.status == JobStatus.awaiting_approval
    assert job.plan_version == 1
    assert jobstore.load_plan(job).to_dict() == plan_dict
    folder = jobstore.job_dir(data_dir, job.id)
    text = (folder / "plan.json").read_text(encoding="utf-8")
    assert "Sếp không hề biết" in text  # readable Vietnamese, not \u escapes
    assert (folder / "plan.v1.json").read_text(encoding="utf-8") == text
    scenes = jobstore.list_scenes(session, job.id)
    assert [scene.scene_no for scene in scenes] == [1, 2, 3, 4, 5]


def test_saving_again_keeps_old_versions_and_replaces_scene_rows(session, data_dir, plan):
    job = jobstore.create_job(session, **FIELDS)
    jobstore.save_plan(session, data_dir, job, plan)
    job.error = "lỗi cũ"
    shorter = plan.model_copy(update={"scenes": plan.scenes[:4]})

    jobstore.save_plan(session, data_dir, job, shorter)

    folder = jobstore.job_dir(data_dir, job.id)
    assert job.plan_version == 2
    assert job.error is None
    assert (folder / "plan.v1.json").exists() and (folder / "plan.v2.json").exists()
    assert (folder / "plan.json").read_text(encoding="utf-8") == (folder / "plan.v2.json").read_text(encoding="utf-8")
    assert len(session.exec(select(Scene).where(Scene.job_id == job.id)).all()) == 4


def test_planning_failure_without_a_plan_fails_the_job(session):
    job = jobstore.create_job(session, **FIELDS)

    jobstore.mark_planning_failed(session, job, "Claude từ chối")

    assert (job.status, job.failed_step, job.error) == (JobStatus.failed, "planning", "Claude từ chối")


def test_planning_failure_with_a_plan_returns_to_review_and_keeps_it(session, data_dir, plan, plan_dict):
    job = jobstore.create_job(session, **FIELDS)
    jobstore.save_plan(session, data_dir, job, plan)
    jobstore.mark_planning(session, job)
    assert job.status == JobStatus.planning

    jobstore.mark_planning_failed(session, job, "Không viết lại được")

    assert job.status == JobStatus.awaiting_approval
    assert job.error == "Không viết lại được"
    assert job.failed_step is None
    assert job.plan_version == 1
    assert jobstore.load_plan(job).to_dict() == plan_dict


def test_mark_planning_clears_a_previous_error(session, data_dir, plan):
    job = jobstore.create_job(session, **FIELDS)
    jobstore.save_plan(session, data_dir, job, plan)
    jobstore.mark_planning_failed(session, job, "lỗi")

    jobstore.mark_planning(session, job)

    assert (job.status, job.error) == (JobStatus.planning, None)


def test_mark_approved_moves_the_job_to_generating(session, data_dir, plan):
    job = jobstore.create_job(session, **FIELDS)
    jobstore.save_plan(session, data_dir, job, plan)

    jobstore.mark_approved(session, job)

    assert jobstore.get_job(session, job.id).status == JobStatus.generating


def test_claude_usage_is_recorded_as_cost_entries(session):
    job = jobstore.create_job(session, **FIELDS)

    jobstore.record_claude_usage(
        session, job.id, action="create_plan", model="claude-sonnet-5-5",
        input_tokens=1000, output_tokens=2000, config=PRICED,
    )

    rows = session.exec(select(CostEntry).where(CostEntry.job_id == job.id).order_by(CostEntry.id)).all()
    assert [(row.kind, row.unit, row.units, row.usd) for row in rows] == [
        ("claude", "tokens_in", 1000, 0.002),
        ("claude", "tokens_out", 2000, 0.02),
    ]
    assert all("create_plan" in row.detail and "claude-sonnet-5-5" in row.detail for row in rows)
    assert jobstore.job_cost_usd(session, job.id) == 0.022
    assert jobstore.job_cost_usd(session, "missing") == 0


def test_usage_without_configured_prices_is_recorded_at_zero_cost(session):
    job = jobstore.create_job(session, **FIELDS)

    jobstore.record_claude_usage(
        session, job.id, action="revise", model="m",
        input_tokens=10, output_tokens=20, config=ClaudeConfig(model="m"),
    )

    rows = session.exec(select(CostEntry).where(CostEntry.job_id == job.id)).all()
    assert [row.usd for row in rows] == [0.0, 0.0]
    assert all("price not configured" in row.detail for row in rows)


def test_zero_tokens_record_nothing(session):
    job = jobstore.create_job(session, **FIELDS)

    jobstore.record_claude_usage(
        session, job.id, action="create_plan", model="m", input_tokens=0, output_tokens=0, config=PRICED,
    )

    assert session.exec(select(CostEntry)).all() == []


def test_recent_jobs_are_newest_first_and_limited(session):
    for day in (1, 3, 2):
        job = jobstore.create_job(session, **(FIELDS | {"idea": f"ý tưởng {day}"}))
        job.created_at = datetime(2026, 1, day, tzinfo=timezone.utc)
        session.add(job)
    session.commit()

    assert [job.idea for job in jobstore.list_recent_jobs(session)] == ["ý tưởng 3", "ý tưởng 2", "ý tưởng 1"]
    assert [job.idea for job in jobstore.list_recent_jobs(session, limit=2)] == ["ý tưởng 3", "ý tưởng 2"]


def test_jobs_interrupted_while_planning_are_recovered(session, data_dir, plan):
    fresh = jobstore.create_job(session, **FIELDS)
    revising = jobstore.create_job(session, **FIELDS)
    jobstore.save_plan(session, data_dir, revising, plan)
    jobstore.mark_planning(session, revising)
    untouched = jobstore.create_job(session, **FIELDS)
    jobstore.save_plan(session, data_dir, untouched, plan)

    assert jobstore.recover_interrupted(session) == 2

    assert (fresh.status, fresh.error) == (JobStatus.failed, jobstore.INTERRUPTED_MESSAGE)
    assert (revising.status, revising.error) == (JobStatus.awaiting_approval, jobstore.INTERRUPTED_MESSAGE)
    assert (untouched.status, untouched.error) == (JobStatus.awaiting_approval, None)
    assert jobstore.recover_interrupted(session) == 0
