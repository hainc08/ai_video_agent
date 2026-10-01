import copy
import shutil

import pytest
from sqlmodel import Session, select

from app import jobstore
from app.agent.finisher import Finisher
from app.agent.runner import GenerationService
from app.events import EventHub
from app.models import CostEntry, JobStatus
from app.providers.base import ProviderError
from app.providers.fake_video import FakeVideoProvider
from app.providers.tts_fake import FakeTTSProvider
from tests.fakes import FakePlanner
from tests.helpers import make_assembling_job, seed_job

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg is not installed on this machine",
)


class ScriptedTTS(FakeTTSProvider):
    """Real (silent) audio, but with scripted failures and a record of what was asked."""

    def __init__(self, failures=None):
        super().__init__("ffmpeg")
        self.failures = list(failures or [])
        self.calls = []  # (text, voice)

    async def synthesize(self, text, voice, path):
        self.calls.append((text, voice))
        if self.failures:
            raise self.failures.pop(0)
        await super().synthesize(text, voice, path)


@pytest.fixture
def short_plan(plan_dict):
    """Two 4-second scenes: enough to exercise every step while keeping the encodes short."""
    plan = copy.deepcopy(plan_dict)
    plan["scenes"] = plan["scenes"][:2]
    for scene in plan["scenes"]:
        scene["duration_sec"] = 4
    return plan


@pytest.fixture(autouse=True)
def fast(settings, monkeypatch):
    settings.config.assembler.output_width = 270
    settings.config.assembler.output_height = 480
    settings.config.assembler.x264_preset = "ultrafast"
    monkeypatch.setattr("app.agent.finisher._BACKOFF_BASE_SEC", 0)


def make_finisher(settings, engine, tts):
    log = []
    finisher = Finisher(settings, engine, lambda: tts, lambda job_id, tag, message: log.append(f"[{tag}] {message}"))
    return finisher, log


def job_of(engine, job_id):
    with Session(engine) as session:
        job = jobstore.get_job(session, job_id)
        session.expunge(job)
        return job


async def test_finisher_adds_voice_subtitles_and_assembles_the_final_video(settings, engine, short_plan):
    tts = ScriptedTTS()
    finisher, log = make_finisher(settings, engine, tts)
    job_id = await make_assembling_job(settings, engine, short_plan, voice="vi-male-north")

    await finisher.run(job_id)

    folder = jobstore.job_dir(settings.data_dir, job_id)
    job = job_of(engine, job_id)
    assert (job.status, job.error) == (JobStatus.done, None)
    assert jobstore.final_path(settings.data_dir, job_id).stat().st_size > 1000
    assert (folder / "audio" / "scene_01.wav").exists() and (folder / "audio" / "scene_02.wav").exists()
    assert short_plan["scenes"][0]["subtitle_vi"] in (folder / "subtitles.ass").read_text(encoding="utf-8")
    assert sorted(tts.calls) == sorted((scene["voiceover_vi"], "vi-male-north") for scene in short_plan["scenes"])
    assert not list(folder.glob("audio/*.raw.*"))
    assert any("cảnh 1" in line and "giọng đọc" in line for line in log)
    assert any("final.mp4" in line for line in log)


async def test_existing_voice_files_are_reused(settings, engine, short_plan):
    first = ScriptedTTS()
    finisher, _ = make_finisher(settings, engine, first)
    job_id = await make_assembling_job(settings, engine, short_plan)
    await finisher.run(job_id)
    jobstore.final_path(settings.data_dir, job_id).unlink()
    jobstore.audio_path(settings.data_dir, job_id, 2).unlink()
    with Session(engine) as session:
        job = jobstore.get_job(session, job_id)
        job.status = JobStatus.assembling
        session.add(job)
        session.commit()

    second = ScriptedTTS()
    again, _ = make_finisher(settings, engine, second)
    await again.run(job_id)

    assert job_of(engine, job_id).status == JobStatus.done
    assert [text for text, _ in second.calls] == [short_plan["scenes"][1]["voiceover_vi"]]


async def test_a_transient_tts_error_is_retried(settings, engine, short_plan):
    tts = ScriptedTTS([ProviderError("Dịch vụ giọng đọc Edge không phản hồi (TimeoutError).", retryable=True)])
    finisher, _ = make_finisher(settings, engine, tts)
    job_id = await make_assembling_job(settings, engine, short_plan)

    await finisher.run(job_id)

    assert job_of(engine, job_id).status == JobStatus.done
    assert len(tts.calls) == 3


async def test_tts_that_keeps_failing_fails_the_job_at_the_assembling_step(settings, engine, short_plan):
    error = ProviderError("Dịch vụ giọng đọc Edge không phản hồi (TimeoutError).", retryable=True)
    tts = ScriptedTTS([error] * 20)
    finisher, _ = make_finisher(settings, engine, tts)
    job_id = await make_assembling_job(settings, engine, short_plan)

    await finisher.run(job_id)

    job = job_of(engine, job_id)
    assert (job.status, job.failed_step) == (JobStatus.failed, "assembling")
    assert "giọng đọc" in job.error and "Edge" in job.error
    assert not jobstore.final_path(settings.data_dir, job_id).exists()


async def test_a_missing_clip_fails_the_job_with_the_scene_number(settings, engine, short_plan):
    finisher, _ = make_finisher(settings, engine, ScriptedTTS())
    job_id = await make_assembling_job(settings, engine, short_plan)
    jobstore.clip_path(settings.data_dir, job_id, 2).unlink()

    await finisher.run(job_id)

    job = job_of(engine, job_id)
    assert (job.status, job.failed_step) == (JobStatus.failed, "assembling")
    assert "cảnh 2" in job.error


async def test_an_unexpected_error_fails_the_job_instead_of_leaving_it_assembling(settings, engine, short_plan):
    finisher, _ = make_finisher(settings, engine, ScriptedTTS([RuntimeError("boom")]))
    job_id = await make_assembling_job(settings, engine, short_plan)

    await finisher.run(job_id)

    job = job_of(engine, job_id)
    assert (job.status, job.failed_step) == (JobStatus.failed, "assembling")
    assert "Lỗi không mong muốn" in job.error and "boom" not in job.error


async def test_a_tts_factory_that_cannot_build_fails_the_job(settings, engine, short_plan):
    def factory():
        raise ProviderError("Không khởi tạo được dịch vụ giọng đọc.")

    finisher = Finisher(settings, engine, factory, lambda *args: None)
    job_id = await make_assembling_job(settings, engine, short_plan)

    await finisher.run(job_id)

    assert job_of(engine, job_id).status == JobStatus.failed


async def test_jobs_in_other_states_are_left_alone(settings, engine, short_plan):
    tts = ScriptedTTS()
    finisher, _ = make_finisher(settings, engine, tts)
    job_id = seed_job(engine, settings.data_dir, plan_dict=short_plan)  # awaiting_approval

    await finisher.run(job_id)
    await finisher.run("missing")

    assert job_of(engine, job_id).status == JobStatus.awaiting_approval
    assert tts.calls == []


async def test_a_priced_tts_is_recorded_as_cost(settings, engine, short_plan):
    tts = ScriptedTTS()
    tts.price_usd_per_1k_chars = 0.5
    finisher, _ = make_finisher(settings, engine, tts)
    job_id = await make_assembling_job(settings, engine, short_plan)

    await finisher.run(job_id)

    with Session(engine) as session:
        rows = session.exec(select(CostEntry).where(CostEntry.job_id == job_id)).all()
    chars = sum(len(scene["voiceover_vi"]) for scene in short_plan["scenes"])
    assert {row.kind for row in rows} == {"tts"}
    assert sum(row.units for row in rows) == chars
    assert round(sum(row.usd for row in rows), 6) == round(chars / 1000 * 0.5, 6)


async def test_generation_runs_on_into_voice_and_assembly(settings, engine, short_plan):
    hub = EventHub()
    tts = ScriptedTTS()
    service = GenerationService(
        settings, engine, hub, lambda: FakeVideoProvider("ffmpeg"), lambda: FakePlanner(), tts_factory=lambda: tts
    )
    job_id = seed_job(engine, settings.data_dir, plan_dict=short_plan, status=JobStatus.generating)
    subscription = hub.subscribe(job_id)

    await service.run(job_id)

    events = [event async for event in subscription]
    assert job_of(engine, job_id).status == JobStatus.done
    assert jobstore.final_path(settings.data_dir, job_id).exists()
    assert events[-1] == {"type": "end"}
    log = [f"[{line['tag']}] {line['message']}" for line in jobstore.read_log(settings.data_dir, job_id)]
    assert any(line.startswith("[tts]") for line in log) and any("final.mp4" in line for line in log)


async def test_a_job_already_waiting_for_assembly_is_resumed_by_run(settings, engine, short_plan):
    hub = EventHub()
    service = GenerationService(
        settings, engine, hub, lambda: FakeVideoProvider("ffmpeg"), lambda: FakePlanner(),
        tts_factory=lambda: ScriptedTTS(),
    )
    job_id = await make_assembling_job(settings, engine, short_plan)

    await service.run(job_id)

    assert job_of(engine, job_id).status == JobStatus.done
