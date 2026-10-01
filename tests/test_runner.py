import asyncio
import copy

import pytest
from sqlmodel import Session, select

from app import jobstore
from app.agent import runner
from app.agent.planner import PlannerError
from app.agent.qc import QCError
from app.agent.runner import GenerationService
from app.events import EventHub
from app.models import CostEntry, JobStatus, SceneStatus
from app.providers.base import ProviderError
from tests.fakes import FakePlanner, ScriptedProvider, planner_result
from tests.helpers import seed_job

QC_PROBLEM = "sai tỉ lệ khung hình (clip 1280×720, cần 9:16)"


@pytest.fixture(autouse=True)
def fast_and_stubbed(monkeypatch, settings):
    async def check(path, *, aspect, duration_sec, ffprobe_path):
        return [] if path.read_bytes() == b"ok" else [QC_PROBLEM]

    monkeypatch.setattr(runner, "check_clip", check)
    monkeypatch.setattr(runner, "_BACKOFF_BASE_SEC", 0)
    settings.config.veo.poll_interval_sec = 0.001
    settings.config.veo.price_usd_per_second = 0.1


def start(settings, engine, plan_dict, provider, *planner_outcomes, **job_attrs):
    hub = EventHub()
    planner = FakePlanner(*planner_outcomes)
    service = GenerationService(settings, engine, hub, lambda: provider, lambda: planner)
    job_id = seed_job(engine, settings.data_dir, plan_dict=plan_dict, status=JobStatus.generating, **job_attrs)
    return service, hub, planner, job_id


def state(engine, job_id):
    with Session(engine) as session:
        job = jobstore.get_job(session, job_id)
        scenes = jobstore.list_scenes(session, job_id)
        costs = session.exec(select(CostEntry).where(CostEntry.job_id == job_id)).all()
        session.expunge_all()
        return job, scenes, costs


def messages(settings, job_id):
    return [f"[{line['tag']}] {line['message']}" for line in jobstore.read_log(settings.data_dir, job_id)]


def rewritten(plan_dict, scene_no, prompt="A calm office desk, no on-screen text, no logos"):
    changed = copy.deepcopy(plan_dict)
    changed["scenes"][scene_no - 1]["veo_prompt_en"] = prompt
    return planner_result(changed, input_tokens=400, output_tokens=800)


# --- happy path ---------------------------------------------------------------------


async def test_every_scene_is_generated_checked_and_approved(settings, engine, plan_dict):
    provider = ScriptedProvider()
    service, hub, planner, job_id = start(settings, engine, plan_dict, provider)
    subscription = hub.subscribe(job_id)

    await service.run(job_id)

    job, scenes, costs = state(engine, job_id)
    events = [event async for event in subscription]
    assert job.status == JobStatus.assembling
    assert [(s.status, s.attempts, s.error) for s in scenes] == [(SceneStatus.approved, 1, None)] * 5
    for scene in scenes:
        assert scene.clip_path == f"clips/scene_{scene.scene_no:02d}.mp4"
        assert jobstore.clip_path(settings.data_dir, job_id, scene.scene_no).read_bytes() == b"ok"
    assert sorted(n for n, _ in provider.submitted) == [1, 2, 3, 4, 5]
    assert [(c.kind, c.unit, c.units, c.usd) for c in costs] == [("veo", "seconds", 6, 0.6)] * 5
    assert planner.calls == []
    assert events[-1] == {"type": "end"} and {"type": "update"} in events
    log = messages(settings, job_id)
    assert "[veo] cảnh 1 → hoàn tất, đạt kiểm tra" in log
    assert not list(jobstore.job_dir(settings.data_dir, job_id).glob("clips/*.part*"))


async def test_the_prompt_sent_is_the_scene_prompt_plus_the_style_guide(settings, engine, plan_dict):
    provider = ScriptedProvider()
    service, _, _, job_id = start(settings, engine, plan_dict, provider)

    await service.run(job_id)

    prompt = dict(provider.submitted)[1]
    assert prompt.startswith(plan_dict["scenes"][0]["veo_prompt_en"])
    assert plan_dict["style_guide"] in prompt


async def test_no_more_than_max_concurrent_clips_are_in_flight(settings, engine, plan_dict):
    settings.config.veo.max_concurrent = 2
    provider = ScriptedProvider()
    service, _, _, job_id = start(settings, engine, plan_dict, provider)

    await service.run(job_id)

    assert provider.max_active == 2
    assert state(engine, job_id)[0].status == JobStatus.assembling


# --- regeneration -------------------------------------------------------------------


async def test_a_clip_that_fails_qc_is_regenerated_once_with_a_rewritten_prompt(settings, engine, plan_dict):
    provider = ScriptedProvider({2: ["bad", "ok"]})
    service, _, planner, job_id = start(settings, engine, plan_dict, provider, rewritten(plan_dict, 2))

    await service.run(job_id)

    job, scenes, costs = state(engine, job_id)
    scene_2_prompts = [prompt for number, prompt in provider.submitted if number == 2]
    assert job.status == JobStatus.assembling
    assert (scenes[1].status, scenes[1].attempts) == (SceneStatus.approved, 2)
    assert job.plan_version == 2  # the rewrite is stored as a new plan version
    assert scene_2_prompts[0].startswith(plan_dict["scenes"][1]["veo_prompt_en"])
    assert scene_2_prompts[1].startswith("A calm office desk")
    (call,) = planner.calls
    assert (call[0], call[2]) == ("rewrite_scene", 2)
    assert QC_PROBLEM in call[3]
    # both clips were paid for, and so was the rewrite
    assert sorted(c.usd for c in costs if c.kind == "veo") == [0.6] * 6
    assert {c.kind for c in costs} == {"veo", "gemini"}
    log = messages(settings, job_id)
    assert any("cảnh 2" in line and "sai tỉ lệ khung hình" in line for line in log)
    assert any("cảnh 2" in line and "sinh lại 1/1" in line for line in log)


async def test_a_second_bad_clip_fails_the_scene_and_the_job(settings, engine, plan_dict):
    provider = ScriptedProvider({3: ["bad", "bad"]})
    service, _, planner, job_id = start(settings, engine, plan_dict, provider, rewritten(plan_dict, 3))

    await service.run(job_id)

    job, scenes, _ = state(engine, job_id)
    assert (job.status, job.failed_step) == (JobStatus.failed, "generating")
    assert "Cảnh 3" in job.error and "sai tỉ lệ khung hình" in job.error
    assert (scenes[2].status, scenes[2].attempts) == (SceneStatus.failed, 2)
    assert QC_PROBLEM in scenes[2].error
    assert len(planner.calls) == 1  # one regeneration only
    assert len([n for n, _ in provider.submitted if n == 3]) == 2


async def test_a_filtered_prompt_is_rewritten_never_resent(settings, engine, plan_dict):
    provider = ScriptedProvider({1: ["filtered", "ok"]})
    service, _, planner, job_id = start(settings, engine, plan_dict, provider, rewritten(plan_dict, 1))

    await service.run(job_id)

    job, scenes, costs = state(engine, job_id)
    scene_1_prompts = [prompt for number, prompt in provider.submitted if number == 1]
    assert job.status == JobStatus.assembling
    assert scenes[0].status == SceneStatus.approved
    assert scene_1_prompts[0] != scene_1_prompts[1]
    assert "bộ lọc an toàn" in planner.calls[0][3]
    assert len([c for c in costs if c.kind == "veo"]) == 5  # the blocked attempt produced no clip to pay for


async def test_a_failed_operation_and_a_timeout_also_lead_to_a_regeneration(settings, engine, plan_dict):
    settings.config.veo.job_timeout_sec = 0.5  # long enough that only the "timeout" scene runs out
    provider = ScriptedProvider({1: ["op_failed", "ok"], 2: ["timeout", "ok"]})
    service, _, planner, job_id = start(
        settings, engine, plan_dict, provider, rewritten(plan_dict, 1), rewritten(plan_dict, 2)
    )

    await service.run(job_id)

    job, scenes, _ = state(engine, job_id)
    reasons = " | ".join(call[3] for call in planner.calls)
    assert job.status == JobStatus.assembling
    assert [s.attempts for s in scenes[:2]] == [2, 2]
    assert "internal error" in reasons and "quá thời gian chờ" in reasons


async def test_a_rewrite_that_fails_fails_the_job_instead_of_hanging(settings, engine, plan_dict):
    provider = ScriptedProvider({2: ["bad"]})
    error = PlannerError("Gemini đang quá tải (mã 503).", input_tokens=10, output_tokens=20)
    service, _, _, job_id = start(settings, engine, plan_dict, provider, error)

    await asyncio.wait_for(service.run(job_id), timeout=5)

    job, scenes, costs = state(engine, job_id)
    assert job.status == JobStatus.failed
    assert "Cảnh 2" in job.error
    assert scenes[1].status == SceneStatus.failed
    assert sum(1 for c in costs if c.kind == "gemini") == 2  # the failed rewrite's tokens are still recorded


async def test_no_regeneration_when_the_limit_is_zero(settings, engine, plan_dict):
    settings.config.limits.max_regenerations_per_scene = 0
    provider = ScriptedProvider({1: ["bad"]})
    service, _, planner, job_id = start(settings, engine, plan_dict, provider)

    await service.run(job_id)

    job, scenes, _ = state(engine, job_id)
    assert job.status == JobStatus.failed
    assert (scenes[0].status, scenes[0].attempts) == (SceneStatus.failed, 1)
    assert planner.calls == []


# --- provider errors ----------------------------------------------------------------


async def test_a_retryable_submit_error_is_retried(settings, engine, plan_dict):
    overloaded = ProviderError("Veo báo lỗi khi gửi yêu cầu sinh clip (ServerError, mã 503).", retryable=True)
    provider = ScriptedProvider({1: [overloaded, overloaded, "ok"]})
    service, _, planner, job_id = start(settings, engine, plan_dict, provider)

    await service.run(job_id)

    job, scenes, _ = state(engine, job_id)
    assert job.status == JobStatus.assembling
    assert (scenes[0].status, scenes[0].attempts) == (SceneStatus.approved, 1)
    assert planner.calls == []


async def test_a_submit_error_that_keeps_failing_stops_the_job_without_rewriting(settings, engine, plan_dict):
    overloaded = ProviderError("Veo báo lỗi khi gửi yêu cầu sinh clip (ServerError, mã 503).", retryable=True)
    provider = ScriptedProvider({1: [overloaded] * 10})
    service, _, planner, job_id = start(settings, engine, plan_dict, provider)

    await service.run(job_id)

    job, scenes, _ = state(engine, job_id)
    assert job.status == JobStatus.failed
    assert "mã 503" in job.error
    assert scenes[0].status == SceneStatus.failed
    assert planner.calls == []  # rewriting the prompt cannot fix an API error


async def test_a_non_retryable_submit_error_is_not_retried(settings, engine, plan_dict):
    forbidden = ProviderError("Veo báo lỗi khi gửi yêu cầu sinh clip (ClientError, mã 403).", retryable=False)
    provider = ScriptedProvider({n: [forbidden] for n in range(1, 6)})
    service, _, planner, job_id = start(settings, engine, plan_dict, provider)

    await service.run(job_id)

    job, _, costs = state(engine, job_id)
    assert job.status == JobStatus.failed
    assert "mã 403" in job.error
    assert provider.submit_attempts <= 5  # one try per scene at most
    assert provider.submitted == [] and costs == [] and planner.calls == []


async def test_a_provider_that_cannot_be_built_fails_the_job(settings, engine, plan_dict):
    def factory():
        raise ProviderError("Thiếu GEMINI_API_KEY trong file .env nên không gọi được Veo.")

    hub = EventHub()
    service = GenerationService(settings, engine, hub, factory, lambda: FakePlanner())
    job_id = seed_job(engine, settings.data_dir, plan_dict=plan_dict, status=JobStatus.generating)

    await service.run(job_id)

    job, _, _ = state(engine, job_id)
    assert (job.status, job.error) == (JobStatus.failed, "Thiếu GEMINI_API_KEY trong file .env nên không gọi được Veo.")


async def test_an_aspect_the_provider_cannot_render_fails_before_spending(settings, engine, plan_dict):
    provider = ScriptedProvider()
    square = copy.deepcopy(plan_dict)
    square["target"]["aspect"] = "1:1"
    service, _, _, job_id = start(settings, engine, square, provider, aspect="1:1")

    await service.run(job_id)

    job, _, _ = state(engine, job_id)
    assert job.status == JobStatus.failed
    assert "1:1" in job.error
    assert provider.submit_attempts == 0


async def test_a_qc_tool_failure_stops_the_job_with_its_message(settings, engine, plan_dict, monkeypatch):
    async def broken(path, **kwargs):
        raise QCError("Không chạy được ffprobe tại 'ffprobe' (FileNotFoundError).")

    monkeypatch.setattr(runner, "check_clip", broken)
    service, _, planner, job_id = start(settings, engine, plan_dict, ScriptedProvider())

    await service.run(job_id)

    job, _, _ = state(engine, job_id)
    assert job.status == JobStatus.failed
    assert "ffprobe" in job.error
    assert planner.calls == []


async def test_an_unexpected_error_fails_the_job_instead_of_leaving_it_generating(settings, engine, plan_dict):
    class Exploding(ScriptedProvider):
        async def submit(self, request):
            raise RuntimeError("boom")

    service, hub, _, job_id = start(settings, engine, plan_dict, Exploding())
    subscription = hub.subscribe(job_id)

    await service.run(job_id)

    job, _, _ = state(engine, job_id)
    assert job.status == JobStatus.failed
    assert "Lỗi không mong muốn" in job.error and "boom" not in job.error
    assert [event async for event in subscription][-1] == {"type": "end"}


# --- money --------------------------------------------------------------------------


async def test_a_job_that_cannot_fit_its_cap_fails_before_anything_is_submitted(settings, engine, plan_dict):
    provider = ScriptedProvider()  # 5 clips x 6 s x $0.10 = $3.00
    service, _, _, job_id = start(settings, engine, plan_dict, provider, cost_cap_usd=3.0)
    with Session(engine) as session:  # planning already cost a little, so $3.00 of clips no longer fits
        session.add(CostEntry(job_id=job_id, kind="gemini", units=1, unit="tokens_in", usd=0.02))
        session.commit()

    await service.run(job_id)

    job, scenes, costs = state(engine, job_id)
    assert job.status == JobStatus.failed
    assert "trần chi phí" in job.error and "3,02" in job.error
    assert provider.submit_attempts == 0
    assert [c.kind for c in costs] == ["gemini"]
    assert {s.status for s in scenes} == {SceneStatus.planned}


async def test_a_job_that_exactly_fits_its_cap_runs(settings, engine, plan_dict):
    provider = ScriptedProvider()
    service, _, _, job_id = start(settings, engine, plan_dict, provider, cost_cap_usd=3.0)

    await service.run(job_id)

    assert state(engine, job_id)[0].status == JobStatus.assembling


async def test_a_job_already_at_its_cap_submits_nothing(settings, engine, plan_dict):
    provider = ScriptedProvider()
    service, _, _, job_id = start(settings, engine, plan_dict, provider, cost_cap_usd=1.0)
    with Session(engine) as session:
        session.add(CostEntry(job_id=job_id, kind="gemini", units=1, unit="tokens_in", usd=0.9))
        session.commit()

    await service.run(job_id)

    job, _, _ = state(engine, job_id)
    assert job.status == JobStatus.failed
    assert "trần chi phí" in job.error
    assert provider.submit_attempts == 0


async def test_a_regeneration_is_refused_when_it_would_break_the_cap(settings, engine, plan_dict):
    provider = ScriptedProvider({1: ["bad", "ok"]})
    service, _, _, job_id = start(settings, engine, plan_dict, provider, rewritten(plan_dict, 1), cost_cap_usd=3.2)

    await service.run(job_id)

    job, _, costs = state(engine, job_id)
    assert job.status == JobStatus.failed
    assert "trần chi phí" in job.error
    # A regeneration would bring the total to $3.60: scene 1 is not submitted a second time, and
    # scenes still waiting for a slot are not started for a job that can no longer finish.
    assert [n for n, _ in provider.submitted].count(1) == 1
    assert len(provider.submitted) <= 5
    assert round(sum(c.usd for c in costs if c.kind == "veo"), 6) == round(0.6 * len(provider.submitted), 6)


# --- re-runs ------------------------------------------------------------------------


async def test_a_re_run_skips_scenes_that_are_already_approved(settings, engine, plan_dict):
    provider = ScriptedProvider()
    service, _, _, job_id = start(settings, engine, plan_dict, provider)
    with Session(engine) as session:
        for scene_no in (1, 2):
            clip = jobstore.clip_path(settings.data_dir, job_id, scene_no)
            clip.parent.mkdir(parents=True, exist_ok=True)
            clip.write_bytes(b"ok")
            jobstore.set_scene(session, job_id, scene_no, status=SceneStatus.approved, attempts=1,
                               clip_path=f"clips/scene_{scene_no:02d}.mp4")
        # approved in the database but its file is gone: must be generated again
        jobstore.set_scene(session, job_id, 3, status=SceneStatus.approved, attempts=1, clip_path="clips/scene_03.mp4")

    await service.run(job_id)

    job, scenes, _ = state(engine, job_id)
    assert job.status == JobStatus.assembling
    assert sorted(n for n, _ in provider.submitted) == [3, 4, 5]
    assert all(s.status == SceneStatus.approved for s in scenes)


async def test_a_job_that_is_not_generating_is_left_alone(settings, engine, plan_dict):
    provider = ScriptedProvider()
    hub = EventHub()
    service = GenerationService(settings, engine, hub, lambda: provider, lambda: FakePlanner())
    job_id = seed_job(engine, settings.data_dir, plan_dict=plan_dict)  # awaiting_approval

    await service.run(job_id)
    await service.run("missing")

    assert state(engine, job_id)[0].status == JobStatus.awaiting_approval
    assert provider.submit_attempts == 0


async def test_spawned_work_runs_in_the_background_and_shutdown_cancels_it(settings, engine, plan_dict):
    settings.config.veo.job_timeout_sec = 60
    provider = ScriptedProvider({n: ["timeout"] for n in range(1, 6)})
    service, _, _, job_id = start(settings, engine, plan_dict, provider)

    service.spawn(service.run(job_id))
    await asyncio.sleep(0.05)
    await asyncio.wait_for(service.shutdown(), timeout=2)

    # Still "generating": the next startup's recover_interrupted() resolves it.
    assert state(engine, job_id)[0].status == JobStatus.generating


# --- findings from the phase 3 review ---------------------------------------------------


async def test_a_provider_crash_fails_that_scene_with_a_reason_instead_of_leaving_it_generating(
    settings, engine, plan_dict
):
    provider = ScriptedProvider({1: ["poll_crash"]})
    service, _, _, job_id = start(settings, engine, plan_dict, provider)

    await service.run(job_id)

    job, scenes, _ = state(engine, job_id)
    assert job.status == JobStatus.failed
    assert "Cảnh 1" in job.error and "boom" not in job.error
    assert scenes[0].status == SceneStatus.failed
    assert "RuntimeError" in scenes[0].error
    assert all(s.status in (SceneStatus.failed, SceneStatus.approved, SceneStatus.planned) for s in scenes)


async def test_scenes_waiting_for_a_slot_are_not_submitted_once_the_job_has_stopped(settings, engine, plan_dict):
    settings.config.veo.max_concurrent = 1
    settings.config.limits.max_regenerations_per_scene = 0
    provider = ScriptedProvider({1: ["bad"]})
    service, _, _, job_id = start(settings, engine, plan_dict, provider)

    await service.run(job_id)

    job, scenes, costs = state(engine, job_id)
    assert job.status == JobStatus.failed
    assert [n for n, _ in provider.submitted] == [1]
    assert round(sum(c.usd for c in costs), 6) == 0.6
    assert [s.status for s in scenes] == [SceneStatus.failed] + [SceneStatus.planned] * 4


async def test_a_scene_waiting_for_a_slot_is_shown_as_queued_not_generating(settings, engine, plan_dict):
    settings.config.veo.max_concurrent = 1
    settings.config.veo.job_timeout_sec = 60
    provider = ScriptedProvider({1: ["timeout"]})
    service, _, _, job_id = start(settings, engine, plan_dict, provider)

    service.spawn(service.run(job_id))
    await asyncio.sleep(0.1)
    _, scenes, _ = state(engine, job_id)
    await service.shutdown()

    assert [s.status for s in scenes] == [SceneStatus.generating] + [SceneStatus.planned] * 4


async def test_a_download_that_fails_once_is_retried_instead_of_paying_for_a_new_clip(settings, engine, plan_dict):
    provider = ScriptedProvider()
    provider.download_script = {2: [ProviderError("Veo báo lỗi khi tải clip (ServerError, mã 503).", retryable=True)]}
    service, _, planner, job_id = start(settings, engine, plan_dict, provider)

    await service.run(job_id)

    job, scenes, costs = state(engine, job_id)
    assert job.status == JobStatus.assembling
    assert len(provider.submitted) == 5 and provider.downloads == 6
    assert len([c for c in costs if c.kind == "veo"]) == 5
    assert planner.calls == []


async def test_a_download_that_keeps_failing_stops_the_job_and_keeps_the_cost(settings, engine, plan_dict):
    provider = ScriptedProvider()
    error = ProviderError("Veo báo lỗi khi tải clip (ServerError, mã 503).", retryable=True)
    provider.download_script = {2: [error] * 20}
    service, _, planner, job_id = start(settings, engine, plan_dict, provider)

    await service.run(job_id)

    job, scenes, costs = state(engine, job_id)
    assert job.status == JobStatus.failed
    assert "Cảnh 2" in job.error and "mã 503" in job.error
    assert any("cảnh 2" in c.detail for c in costs)  # Veo rendered it, so it is paid for
    assert planner.calls == []
    log = " | ".join(messages(settings, job_id))
    assert "op-" in log  # the operation name is on record, so the clip can still be fetched by hand


async def test_an_operation_that_timed_out_is_logged_and_counted_as_possibly_charged(settings, engine, plan_dict):
    settings.config.veo.job_timeout_sec = 0.3
    provider = ScriptedProvider({1: ["timeout", "ok"]})
    service, _, _, job_id = start(settings, engine, plan_dict, provider, rewritten(plan_dict, 1))

    await service.run(job_id)

    job, _, costs = state(engine, job_id)
    veo = [c for c in costs if c.kind == "veo"]
    assert job.status == JobStatus.assembling
    assert len(veo) == 6  # five clips plus the abandoned operation
    assert sum(1 for c in veo if "có thể vẫn bị tính tiền" in c.detail) == 1
    assert any("op-" in line and "cảnh 1" in line for line in messages(settings, job_id))


async def test_submit_outlasts_a_longer_overload(settings, engine, plan_dict):
    overloaded = ProviderError("Veo báo lỗi khi gửi yêu cầu sinh clip (ServerError, mã 429).", retryable=True)
    provider = ScriptedProvider({1: [overloaded] * 4 + ["ok"]})
    service, _, _, job_id = start(settings, engine, plan_dict, provider)

    await service.run(job_id)

    assert state(engine, job_id)[0].status == JobStatus.assembling
