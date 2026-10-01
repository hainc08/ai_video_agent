import asyncio
import copy

from sqlmodel import Session, select

from app import jobstore
from app.agent.planner import PlannerError, PlanOptions
from app.agent.planning import PlanningService
from app.models import CostEntry, JobStatus
from app.schemas import Plan
from tests.fakes import FakePlanner, planner_result
from tests.helpers import seed_job


def make_service(settings, engine, *outcomes):
    planner = FakePlanner(*outcomes)
    return PlanningService(settings, engine, lambda: planner), planner


def load(engine, job_id):
    with Session(engine) as session:
        job = jobstore.get_job(session, job_id)
        costs = session.exec(select(CostEntry).where(CostEntry.job_id == job_id)).all()
        return job, jobstore.load_plan(job), costs


async def test_create_stores_the_plan_and_the_claude_cost(settings, engine, plan_dict):
    service, planner = make_service(settings, engine, planner_result(plan_dict))
    job_id = seed_job(engine, settings.data_dir, duration_sec=60, aspect="1:1", style="cinematic")

    await service.create(job_id)

    job, plan, costs = load(engine, job_id)
    assert job.status == JobStatus.awaiting_approval
    assert plan.to_dict() == plan_dict
    assert (settings.data_dir / "jobs" / job_id / "plan.json").exists()
    assert sorted(cost.usd for cost in costs) == [0.002, 0.02]
    assert planner.calls == [
        (
            "create_plan",
            "5 việc sếp không biết bạn đang làm bằng AI",
            PlanOptions(
                duration_sec=60,
                aspect="1:1",
                voice="vi-female-north",
                style="cinematic look, shallow depth of field, warm contrast lighting, slow camera moves",
            ),
        )
    ]


async def test_planner_error_fails_the_job_and_still_records_what_was_spent(settings, engine):
    error = PlannerError("Claude không tạo được plan hợp lệ sau 3 lần thử", input_tokens=300, output_tokens=600)
    service, _ = make_service(settings, engine, error)
    job_id = seed_job(engine, settings.data_dir)

    await service.create(job_id)

    job, plan, costs = load(engine, job_id)
    assert (job.status, job.failed_step) == (JobStatus.failed, "planning")
    assert job.error == "Claude không tạo được plan hợp lệ sau 3 lần thử"
    assert plan is None
    assert sorted(cost.units for cost in costs) == [300, 600]


async def test_missing_api_key_fails_the_job_with_the_factory_message(settings, engine):
    def factory():
        raise PlannerError("Thiếu ANTHROPIC_API_KEY trong file .env.")

    service = PlanningService(settings, engine, factory)
    job_id = seed_job(engine, settings.data_dir)

    await service.create(job_id)

    job, _, costs = load(engine, job_id)
    assert job.status == JobStatus.failed
    assert job.error == "Thiếu ANTHROPIC_API_KEY trong file .env."
    assert costs == []


async def test_unexpected_error_fails_the_job_instead_of_leaving_it_planning(settings, engine):
    service, _ = make_service(settings, engine, RuntimeError("boom"))
    job_id = seed_job(engine, settings.data_dir)

    await service.create(job_id)

    job, _, _ = load(engine, job_id)
    assert job.status == JobStatus.failed
    assert "Lỗi không mong muốn" in job.error
    assert "boom" not in job.error


async def test_revise_saves_a_new_plan_version(settings, engine, plan_dict):
    revised = copy.deepcopy(plan_dict)
    revised["brief"]["cta"] = "Lưu video để xem lại"
    service, planner = make_service(settings, engine, planner_result(revised))
    job_id = seed_job(engine, settings.data_dir, plan_dict=plan_dict, status=JobStatus.planning)

    await service.revise(job_id, "Đổi CTA")

    job, plan, _ = load(engine, job_id)
    assert (job.status, job.plan_version) == (JobStatus.awaiting_approval, 2)
    assert plan.brief.cta == "Lưu video để xem lại"
    assert (settings.data_dir / "jobs" / job_id / "plan.v2.json").exists()
    assert planner.calls == [("revise", Plan.model_validate(plan_dict), "Đổi CTA")]


async def test_failed_revise_keeps_the_previous_plan(settings, engine, plan_dict):
    service, _ = make_service(settings, engine, PlannerError("Claude từ chối", input_tokens=50))
    job_id = seed_job(engine, settings.data_dir, plan_dict=plan_dict, status=JobStatus.planning)

    await service.revise(job_id, "Đổi CTA")

    job, plan, _ = load(engine, job_id)
    assert (job.status, job.plan_version, job.error) == (JobStatus.awaiting_approval, 1, "Claude từ chối")
    assert plan.to_dict() == plan_dict


async def test_rewrite_scene_passes_the_scene_and_feedback(settings, engine, plan_dict):
    service, planner = make_service(settings, engine, planner_result(plan_dict))
    job_id = seed_job(engine, settings.data_dir, plan_dict=plan_dict, status=JobStatus.planning)

    await service.rewrite_scene(job_id, 3, "sinh động hơn")

    job, _, _ = load(engine, job_id)
    assert (job.status, job.plan_version) == (JobStatus.awaiting_approval, 2)
    assert planner.calls == [("rewrite_scene", Plan.model_validate(plan_dict), 3, "sinh động hơn")]


async def test_unknown_job_is_ignored(settings, engine):
    service, planner = make_service(settings, engine)

    await service.create("missing")

    assert planner.calls == []


async def test_spawn_runs_the_work_in_the_background(settings, engine, plan_dict):
    service, _ = make_service(settings, engine, planner_result(plan_dict))
    job_id = seed_job(engine, settings.data_dir)

    service.spawn(service.create(job_id))
    assert load(engine, job_id)[0].status == JobStatus.planning  # not started yet
    for _ in range(100):
        await asyncio.sleep(0.01)
        if load(engine, job_id)[0].status != JobStatus.planning:
            break

    assert load(engine, job_id)[0].status == JobStatus.awaiting_approval


async def test_shutdown_cancels_work_that_is_still_running(settings, engine):
    class StuckPlanner:
        async def create_plan(self, idea, options):
            await asyncio.Event().wait()

    service = PlanningService(settings, engine, StuckPlanner)
    job_id = seed_job(engine, settings.data_dir)
    service.spawn(service.create(job_id))
    await asyncio.sleep(0.01)

    await asyncio.wait_for(service.shutdown(), timeout=2)

    # Still "planning": the next startup's recover_interrupted() resolves it.
    assert load(engine, job_id)[0].status == JobStatus.planning
