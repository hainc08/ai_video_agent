"""Generates the clips of an approved job: provider calls, QC, one regeneration, hard cost cap."""
from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Engine
from sqlmodel import Session

from app import jobstore
from app.agent.planner import PlannerBase, PlannerError
from app.agent.qc import QCError, check_clip
from app.config import Settings
from app.events import EventHub
from app.models import JobStatus, SceneStatus
from app.providers.base import ClipRequest, ContentFilteredError, ProviderError, VideoProvider
from app.schemas import Plan

log = logging.getLogger("app.runner")

ProviderFactory = Callable[[], VideoProvider]
PlannerFactory = Callable[[], PlannerBase]

_SUBMIT_TRIES = 5  # waits about 2, 4, 8, 16 s: long enough to outlast a short rate limit
_DOWNLOAD_TRIES = 3
_BACKOFF_BASE_SEC = 2.0
_BACKOFF_MAX_SEC = 60.0


def _usd(amount: float) -> str:
    return f"{amount:.2f}".replace(".", ",")


async def _backoff(attempt: int) -> None:
    delay = min(_BACKOFF_MAX_SEC, _BACKOFF_BASE_SEC * 2 ** (attempt - 1))
    await asyncio.sleep(delay * (1 + random.random() / 4))  # jitter, so parallel scenes do not retry in step


class _AttemptFailed(Exception):
    """This attempt produced no usable clip; a rewritten prompt may fix it."""


class _TimedOut(_AttemptFailed):
    """We stopped waiting; the operation may still finish (and be billed) on the provider's side."""


class _JobStopped(Exception):
    """The job stopped while this scene was waiting for a slot: nothing was submitted."""


@dataclass
class _JobRun:
    """What the scene pipelines of one job share while it runs."""

    job_id: str
    provider: VideoProvider
    aspect: str
    cap_usd: float
    money: asyncio.Lock = field(default_factory=asyncio.Lock)
    plan: asyncio.Lock = field(default_factory=asyncio.Lock)
    reserved_usd: float = 0.0  # cost of clips submitted but not yet recorded as CostEntry
    stop_reason: str | None = None

    def stop(self, reason: str) -> None:
        # The first reason wins: it is what the user is shown.
        if self.stop_reason is None:
            self.stop_reason = reason


class GenerationService:
    def __init__(
        self,
        settings: Settings,
        engine: Engine,
        hub: EventHub,
        provider_factory: ProviderFactory,
        planner_factory: PlannerFactory,
    ) -> None:
        self._settings = settings
        self._engine = engine
        self._hub = hub
        self._provider_factory = provider_factory
        self._planner_factory = planner_factory
        # One limit for the whole process, across jobs (FR-08).
        self._slots = asyncio.Semaphore(settings.config.veo.max_concurrent)
        self._tasks: set[asyncio.Task[None]] = set()

    def spawn(self, work: Coroutine[Any, Any, None]) -> None:
        task = asyncio.get_running_loop().create_task(work)
        self._tasks.add(task)  # the event loop only keeps weak references to tasks
        task.add_done_callback(self._tasks.discard)

    async def shutdown(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def run(self, job_id: str) -> None:
        """Generate every missing clip of a job that is in `generating`. Never raises."""
        try:
            await self._run(job_id)
        except Exception:
            # Whatever goes wrong, the job must leave "generating": the page waits until it does.
            log.exception("Unexpected error while generating job %s", job_id)
            self._fail_job(job_id, "Lỗi không mong muốn khi sinh video. Xem log của máy chủ để biết chi tiết.")
        finally:
            self._hub.publish(job_id, {"type": "end"})
            self._hub.close(job_id)

    # --- one job ---------------------------------------------------------------------

    async def _run(self, job_id: str) -> None:
        with Session(self._engine) as session:
            job = jobstore.get_job(session, job_id)
            if job is None or job.status != JobStatus.generating:
                return
            plan = jobstore.load_plan(job)
            aspect, cap_usd = job.aspect, job.cost_cap_usd
            done = {
                row.scene_no
                for row in jobstore.list_scenes(session, job_id)
                if row.status == SceneStatus.approved
                and jobstore.clip_path(self._settings.data_dir, job_id, row.scene_no).exists()
            }
        if plan is None:
            self._fail_job(job_id, "Job không có plan để sinh video.")
            return

        try:
            provider = self._provider_factory()
        except ProviderError as exc:
            self._fail_job(job_id, str(exc))
            return
        if aspect not in provider.supported_aspects:
            supported = ", ".join(sorted(provider.supported_aspects))
            self._fail_job(job_id, f"Tỉ lệ {aspect} không được hỗ trợ khi sinh video (chỉ có {supported}).")
            return

        run = _JobRun(job_id=job_id, provider=provider, aspect=aspect, cap_usd=cap_usd)
        pending = [scene.id for scene in plan.scenes if scene.id not in done]

        # Refuse up front a job that cannot finish within its cap, rather than paying for some
        # clips and then stopping.
        needed = sum(scene.duration_sec for scene in plan.scenes if scene.id in pending) * provider.price_usd_per_second
        spent = self._spent(job_id)
        if pending and spent + needed > cap_usd + 1e-9:
            self._fail_job(
                job_id,
                f"Không sinh clip vì sẽ vượt trần chi phí {cap_usd:g} USD của video này: "
                f"{len(pending)} clip cần {_usd(needed)} USD, đã dùng {_usd(spent)} USD, "
                f"tổng {_usd(spent + needed)} USD.",
            )
            return
        self._log(job_id, "veo", f"bắt đầu sinh {len(pending)} cảnh (song song tối đa {self._settings.config.veo.max_concurrent})")

        results = await asyncio.gather(*(self._scene(run, scene_no) for scene_no in pending), return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                raise result

        with Session(self._engine) as session:
            job = jobstore.get_job(session, job_id)
            if job is None or job.status != JobStatus.generating:
                return  # changed by someone else while clips were rendering
            scenes = jobstore.list_scenes(session, job_id)
            if all(scene.status == SceneStatus.approved for scene in scenes):
                jobstore.mark_generated(session, job)
                self._log(job_id, "veo", f"đã xong {len(scenes)}/{len(scenes)} cảnh, tất cả đạt kiểm tra")
                return
            reason = run.stop_reason or "Có cảnh chưa sinh được clip."
            jobstore.mark_generation_failed(session, job, reason)
        self._log(job_id, "veo", f"dừng: {reason}")

    # --- one scene -------------------------------------------------------------------

    async def _scene(self, run: _JobRun, scene_no: int) -> None:
        max_attempts = 1 + self._settings.config.limits.max_regenerations_per_scene
        regenerations = max_attempts - 1

        for attempt in range(1, max_attempts + 1):
            if run.stop_reason is not None:
                return  # the job is stopping: start nothing new
            scene = self._current_plan(run.job_id).scenes[scene_no - 1]
            cost = scene.duration_sec * run.provider.price_usd_per_second
            if not await self._reserve(run, cost):
                return
            request = ClipRequest(
                scene_no=scene_no,
                prompt=f"{scene.veo_prompt_en}\n\nStyle: {self._current_plan(run.job_id).style_guide}",
                aspect=run.aspect,
                duration_sec=scene.duration_sec,
            )

            try:
                await self._attempt(run, request, cost, attempt)
            except _JobStopped:
                return
            except _AttemptFailed as exc:
                reason = str(exc)
            except ContentFilteredError as exc:
                reason = str(exc)
            except (ProviderError, QCError) as exc:
                # An API or tooling failure: a rewritten prompt cannot fix it, so stop here.
                self._scene_failed(run, scene_no, str(exc))
                return
            except Exception as exc:
                # Anything else (a bug, an error the provider did not translate): this scene fails
                # with a reason and the job stops, instead of one scene taking the whole run down.
                log.exception("Unexpected error while generating scene %s of job %s", scene_no, run.job_id)
                self._scene_failed(
                    run, scene_no, f"Lỗi không mong muốn khi gọi nhà cung cấp video ({type(exc).__name__})"
                )
                return
            else:
                self._set_scene(
                    run.job_id, scene_no, status=SceneStatus.approved, error=None,
                    clip_path=f"clips/scene_{scene_no:02d}.mp4",
                )
                self._log(run.job_id, "veo", f"cảnh {scene_no} → hoàn tất, đạt kiểm tra")
                return

            if attempt == max_attempts:
                self._scene_failed(run, scene_no, reason)
                return
            if not await self._can_afford(run, cost):
                self._scene_failed(run, scene_no, reason, stop_reason=self._cap_message(run))
                return
            self._set_scene(run.job_id, scene_no, status=SceneStatus.regenerating, error=reason)
            self._log(
                run.job_id, "veo",
                f"cảnh {scene_no} → {reason}, AI chỉnh prompt, sinh lại {attempt}/{regenerations}",
            )
            if not await self._rewrite(run, scene_no, reason):
                self._scene_failed(run, scene_no, f"{reason}; không viết lại được prompt")
                return

    async def _attempt(self, run: _JobRun, request: ClipRequest, cost: float, attempt: int) -> None:
        """Submit, wait, pay, download and check one clip. Raises when it is not usable."""
        target = jobstore.clip_path(self._settings.data_dir, run.job_id, request.scene_no)
        partial = target.with_name(target.stem + ".part.mp4")
        charged = False
        try:
            async with self._slots:
                if run.stop_reason is not None:
                    raise _JobStopped  # stopped while this scene waited for a slot: submit nothing
                # Only now is the scene "generating": while it waits for a slot it shows as queued.
                self._set_scene(
                    run.job_id, request.scene_no,
                    status=SceneStatus.generating if attempt == 1 else SceneStatus.regenerating,
                    attempts=attempt, error=None,
                )
                self._log(run.job_id, "veo", f"cảnh {request.scene_no} → đang sinh…")
                operation_id = await self._submit(run.provider, request)
                # On record, so a clip Veo finishes after we gave up on it can still be fetched by hand.
                self._log(run.job_id, "veo", f"cảnh {request.scene_no} → Veo đã nhận, mã tác vụ {operation_id}")
                try:
                    await self._wait(run.provider, operation_id)
                except _TimedOut:
                    # Veo may still finish and bill it: count it, so the cap errs on the safe side.
                    async with run.money:
                        self._record_clip_cost(
                            run, request, attempt, note="quá thời gian chờ, có thể vẫn bị tính tiền"
                        )
                        run.reserved_usd -= cost
                        charged = True
                    raise
                async with run.money:
                    self._record_clip_cost(run, request, attempt)
                    run.reserved_usd -= cost
                    charged = True
                await self._download(run.provider, operation_id, partial)
            self._set_scene(run.job_id, request.scene_no, status=SceneStatus.generated)
            problems = await check_clip(
                partial,
                aspect=request.aspect,
                duration_sec=request.duration_sec,
                ffprobe_path=self._settings.config.assembler.ffprobe_path,
            )
            if problems:
                raise _AttemptFailed("; ".join(problems))
            os.replace(partial, target)  # the final name only ever holds a clip that passed
        finally:
            partial.unlink(missing_ok=True)
            if not charged:
                async with run.money:
                    run.reserved_usd -= cost

    async def _submit(self, provider: VideoProvider, request: ClipRequest) -> str:
        for attempt in range(1, _SUBMIT_TRIES + 1):
            try:
                return await provider.submit(request)
            except ContentFilteredError:
                raise
            except ProviderError as exc:
                if not exc.retryable or attempt == _SUBMIT_TRIES:
                    raise
                await _backoff(attempt)
        raise AssertionError("unreachable: the loop always returns or raises")

    async def _download(self, provider: VideoProvider, operation_id: str, path: Any) -> None:
        # The clip is already paid for, and fetching it again is free: do not give up on one error.
        for attempt in range(1, _DOWNLOAD_TRIES + 1):
            try:
                await provider.download(operation_id, path)
                return
            except ProviderError as exc:
                if not exc.retryable or attempt == _DOWNLOAD_TRIES:
                    raise
                await _backoff(attempt)

    async def _wait(self, provider: VideoProvider, operation_id: str) -> None:
        veo = self._settings.config.veo
        deadline = time.monotonic() + veo.job_timeout_sec
        while True:
            try:
                result = await provider.poll(operation_id)
            except ContentFilteredError:
                raise
            except ProviderError as exc:
                if not exc.retryable:
                    raise
                result = None  # a transient error while asking: keep waiting until the deadline
            if result is not None:
                if result.state == "done":
                    return
                if result.state == "failed":
                    raise _AttemptFailed(result.message or "Veo không sinh được clip")
            if time.monotonic() >= deadline:
                raise _TimedOut(f"quá thời gian chờ ({veo.job_timeout_sec:g} giây) mà clip chưa xong")
            await asyncio.sleep(veo.poll_interval_sec)

    # --- money -----------------------------------------------------------------------

    async def _reserve(self, run: _JobRun, cost: float) -> bool:
        """Set `cost` aside for a clip about to be submitted, or stop the job at its cap."""
        async with run.money:
            if self._spent(run.job_id) + run.reserved_usd + cost > run.cap_usd + 1e-9:
                run.stop(self._cap_message(run))
                return False
            run.reserved_usd += cost
            return True

    async def _can_afford(self, run: _JobRun, cost: float) -> bool:
        async with run.money:
            if self._spent(run.job_id) + run.reserved_usd + cost > run.cap_usd + 1e-9:
                run.stop(self._cap_message(run))
                return False
            return True

    def _spent(self, job_id: str) -> float:
        with Session(self._engine) as session:
            return jobstore.job_cost_usd(session, job_id)

    def _cap_message(self, run: _JobRun) -> str:
        return (
            f"Chạm trần chi phí {run.cap_usd:g} USD của video này "
            f"(đã dùng {_usd(self._spent(run.job_id) + run.reserved_usd)} USD, kể cả clip đang sinh) "
            "nên dừng sinh clip."
        )

    def _record_clip_cost(self, run: _JobRun, request: ClipRequest, attempt: int, note: str = "") -> None:
        model = self._settings.config.veo.model if run.provider.name == "veo" else run.provider.name
        with Session(self._engine) as session:
            jobstore.record_video_cost(
                session, run.job_id, provider=run.provider.name, model=model,
                seconds=request.duration_sec, price_usd_per_second=run.provider.price_usd_per_second,
                detail=f"cảnh {request.scene_no}, lần {attempt}" + (f", {note}" if note else ""),
            )

    # --- prompt rewrite --------------------------------------------------------------

    async def _rewrite(self, run: _JobRun, scene_no: int, reason: str) -> bool:
        """Ask the LLM for a new prompt for one scene and store it as a new plan version."""
        feedback = (
            f"Clip của cảnh này không dùng được: {reason}. "
            "Viết lại veo_prompt_en theo hướng an toàn và cụ thể hơn, giữ nguyên ý nghĩa, "
            "lời thoại và thời lượng của cảnh."
        )
        llm = self._settings.llm
        kind = self._settings.secrets.llm_provider
        # One rewrite at a time per job: each starts from the plan the previous one saved.
        async with run.plan:
            plan = self._current_plan(run.job_id)
            try:
                planner = self._planner_factory()
                result = await planner.rewrite_scene(plan, scene_no, feedback)
            except PlannerError as exc:
                with Session(self._engine) as session:
                    jobstore.record_llm_usage(
                        session, run.job_id, kind=kind, action="rewrite_scene", model=llm.model,
                        input_tokens=exc.input_tokens, output_tokens=exc.output_tokens, config=llm,
                    )
                self._log(run.job_id, "planner", f"không viết lại được prompt cảnh {scene_no}: {exc}")
                return False
            with Session(self._engine) as session:
                jobstore.record_llm_usage(
                    session, run.job_id, kind=kind, action="rewrite_scene", model=result.model,
                    input_tokens=result.input_tokens, output_tokens=result.output_tokens, config=llm,
                )
                job = jobstore.get_job(session, run.job_id)
                jobstore.update_plan(session, self._settings.data_dir, job, result.plan)
        self._log(run.job_id, "planner", f"đã viết lại prompt cảnh {scene_no}")
        return True

    # --- small helpers ---------------------------------------------------------------

    def _current_plan(self, job_id: str) -> Plan:
        with Session(self._engine) as session:
            plan = jobstore.load_plan(jobstore.get_job(session, job_id))
        if plan is None:
            raise RuntimeError(f"job {job_id} lost its plan while generating")
        return plan

    def _set_scene(self, job_id: str, scene_no: int, **changes: Any) -> None:
        with Session(self._engine) as session:
            jobstore.set_scene(session, job_id, scene_no, **changes)
        self._hub.publish(job_id, {"type": "update"})

    def _scene_failed(self, run: _JobRun, scene_no: int, reason: str, *, stop_reason: str | None = None) -> None:
        self._set_scene(run.job_id, scene_no, status=SceneStatus.failed, error=reason)
        self._log(run.job_id, "veo", f"cảnh {scene_no} → lỗi: {reason}")
        run.stop(stop_reason or f"Cảnh {scene_no} không sinh được clip: {reason}")

    def _fail_job(self, job_id: str, message: str) -> None:
        try:
            with Session(self._engine) as session:
                job = jobstore.get_job(session, job_id)
                if job is not None and job.status == JobStatus.generating:
                    jobstore.mark_generation_failed(session, job, message)
            self._log(job_id, "veo", f"dừng: {message}")
        except Exception:
            # Last resort: startup recovery (recover_interrupted) will resolve the job.
            log.exception("Could not record the generation failure for job %s", job_id)

    def _log(self, job_id: str, tag: str, message: str) -> None:
        jobstore.append_log(self._settings.data_dir, job_id, tag, message)
        self._hub.publish(job_id, {"type": "update"})
