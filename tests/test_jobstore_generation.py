import copy

import pytest
from sqlmodel import select

from app import jobstore
from app.models import CostEntry, JobStatus, SceneStatus
from app.schemas import Plan
from tests.test_jobstore import FIELDS


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path / "data"


@pytest.fixture
def plan(plan_dict):
    return Plan.model_validate(plan_dict)


@pytest.fixture
def approved_job(session, data_dir, plan):
    job = jobstore.create_job(session, **FIELDS)
    jobstore.save_plan(session, data_dir, job, plan)
    jobstore.mark_approved(session, job)
    return job


def test_approving_clears_an_error_left_by_a_failed_rewrite(session, data_dir, plan):
    job = jobstore.create_job(session, **FIELDS)
    jobstore.save_plan(session, data_dir, job, plan)
    jobstore.mark_planning_failed(session, job, "Không viết lại được")

    jobstore.mark_approved(session, job)

    assert (job.status, job.error) == (JobStatus.generating, None)


def test_scene_rows_can_be_read_and_updated(session, approved_job):
    scene = jobstore.get_scene(session, approved_job.id, 2)
    assert (scene.scene_no, scene.status, scene.attempts) == (2, SceneStatus.planned, 0)

    jobstore.set_scene(session, approved_job.id, 2, status=SceneStatus.approved, attempts=1, clip_path="clips/scene_02.mp4")
    jobstore.set_scene(session, approved_job.id, 3, status=SceneStatus.failed, error="sai tỉ lệ khung hình")

    assert [
        (s.scene_no, s.status, s.attempts, s.clip_path, s.error) for s in jobstore.list_scenes(session, approved_job.id)
    ][1:3] == [
        (2, SceneStatus.approved, 1, "clips/scene_02.mp4", None),
        (3, SceneStatus.failed, 0, None, "sai tỉ lệ khung hình"),
    ]
    assert jobstore.get_scene(session, approved_job.id, 99) is None
    with pytest.raises(LookupError):
        jobstore.set_scene(session, approved_job.id, 99, status=SceneStatus.failed)


def test_updating_the_plan_during_generation_keeps_job_and_scene_state(session, data_dir, approved_job, plan_dict):
    jobstore.set_scene(session, approved_job.id, 1, status=SceneStatus.approved, attempts=1)
    changed = copy.deepcopy(plan_dict)
    changed["scenes"][1]["veo_prompt_en"] = "A safer prompt, no on-screen text, no logos"

    jobstore.update_plan(session, data_dir, approved_job, Plan.model_validate(changed))

    folder = jobstore.job_dir(data_dir, approved_job.id)
    assert approved_job.status == JobStatus.generating
    assert approved_job.plan_version == 2
    assert jobstore.load_plan(approved_job).scenes[1].veo_prompt_en.startswith("A safer prompt")
    assert "A safer prompt" in (folder / "plan.v2.json").read_text(encoding="utf-8")
    assert (folder / "plan.json").read_text(encoding="utf-8") == (folder / "plan.v2.json").read_text(encoding="utf-8")
    assert jobstore.get_scene(session, approved_job.id, 1).status == SceneStatus.approved


def test_video_cost_is_recorded_per_clip(session, approved_job):
    jobstore.record_video_cost(
        session, approved_job.id, provider="veo", model="veo-3.1-fast-generate-preview",
        seconds=6, price_usd_per_second=0.1, detail="cảnh 2, lần 1",
    )

    (row,) = session.exec(select(CostEntry).where(CostEntry.job_id == approved_job.id)).all()
    assert (row.kind, row.unit, row.units, row.usd) == ("veo", "seconds", 6, 0.6)
    assert "veo-3.1-fast-generate-preview" in row.detail and "cảnh 2, lần 1" in row.detail
    assert jobstore.job_cost_usd(session, approved_job.id) == 0.6


def test_clip_path_is_numbered_inside_the_job_folder(data_dir):
    assert jobstore.clip_path(data_dir, "abc123", 3) == data_dir / "jobs" / "abc123" / "clips" / "scene_03.mp4"
    assert jobstore.clip_path(data_dir, "abc123", 12).name == "scene_12.mp4"


def test_log_lines_round_trip_and_survive_a_corrupt_line(data_dir):
    assert jobstore.read_log(data_dir, "job-1") == []

    first = jobstore.append_log(data_dir, "job-1", "veo", "cảnh 1 → hoàn tất, đạt kiểm tra")
    with (jobstore.job_dir(data_dir, "job-1") / "log.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("{broken json\n")
    jobstore.append_log(data_dir, "job-1", "qc", "cảnh 2 → sai tỉ lệ khung hình")

    lines = jobstore.read_log(data_dir, "job-1")
    assert [(line["tag"], line["message"]) for line in lines] == [
        ("veo", "cảnh 1 → hoàn tất, đạt kiểm tra"),
        ("qc", "cảnh 2 → sai tỉ lệ khung hình"),
    ]
    assert first["ts"] and lines[0] == first
    assert "cảnh 1 → hoàn tất" in (jobstore.job_dir(data_dir, "job-1") / "log.jsonl").read_text(encoding="utf-8")


def test_log_reading_keeps_only_the_latest_lines(data_dir):
    for number in range(5):
        jobstore.append_log(data_dir, "job-1", "veo", f"dòng {number}")

    assert [line["message"] for line in jobstore.read_log(data_dir, "job-1", limit=2)] == ["dòng 3", "dòng 4"]


def test_generation_outcomes(session, approved_job):
    jobstore.mark_generated(session, approved_job)
    assert approved_job.status == JobStatus.assembling

    jobstore.mark_generation_failed(session, approved_job, "Cảnh 2 không đạt sau khi sinh lại")
    assert (approved_job.status, approved_job.failed_step, approved_job.error) == (
        JobStatus.failed, "generating", "Cảnh 2 không đạt sau khi sinh lại")


def test_jobs_interrupted_while_generating_are_failed_and_keep_their_scenes(session, data_dir, plan, approved_job):
    jobstore.set_scene(session, approved_job.id, 1, status=SceneStatus.approved, attempts=1, clip_path="x.mp4")
    waiting = jobstore.create_job(session, **FIELDS)
    jobstore.save_plan(session, data_dir, waiting, plan)

    assert jobstore.recover_interrupted(session) == 1

    assert (approved_job.status, approved_job.failed_step) == (JobStatus.failed, "generating")
    assert approved_job.error == jobstore.GENERATION_INTERRUPTED_MESSAGE
    assert jobstore.get_scene(session, approved_job.id, 1).status == SceneStatus.approved
    assert waiting.status == JobStatus.awaiting_approval
