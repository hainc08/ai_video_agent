"""Runs planner calls for a job in the background and persists the outcome."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

from sqlalchemy import Engine
from sqlmodel import Session

from app import jobstore
from app.agent.planner import PlanOptions, Planner, PlannerError, PlannerResult
from app.config import Settings
from app.models import Job, JobStatus
from app.options import style_prompt
from app.schemas import Plan

log = logging.getLogger("app.planning")

PlannerFactory = Callable[[], Planner]
_PlannerCall = Callable[[Planner, Job, Plan | None], Awaitable[PlannerResult]]


class PlanningService:
    def __init__(self, settings: Settings, engine: Engine, planner_factory: PlannerFactory) -> None:
        self._settings = settings
        self._engine = engine
        self._planner_factory = planner_factory
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

    async def create(self, job_id: str) -> None:
        async def call(planner: Planner, job: Job, plan: Plan | None) -> PlannerResult:
            options = PlanOptions(
                duration_sec=job.duration_sec,
                aspect=job.aspect,
                voice=job.voice,
                style=style_prompt(job.style, self._settings.config),
            )
            return await planner.create_plan(job.idea, options)

        await self._run(job_id, "create_plan", call)

    async def revise(self, job_id: str, feedback: str) -> None:
        async def call(planner: Planner, job: Job, plan: Plan | None) -> PlannerResult:
            return await planner.revise(plan, feedback)

        await self._run(job_id, "revise", call)

    async def rewrite_scene(self, job_id: str, scene_id: int, feedback: str = "") -> None:
        async def call(planner: Planner, job: Job, plan: Plan | None) -> PlannerResult:
            return await planner.rewrite_scene(plan, scene_id, feedback)

        await self._run(job_id, "rewrite_scene", call)

    async def _run(self, job_id: str, action: str, call: _PlannerCall) -> None:
        claude = self._settings.config.claude
        version: int | None = None

        # Whatever goes wrong, the job must leave "planning": the page polls until it does.
        try:
            with Session(self._engine) as session:
                job = jobstore.get_job(session, job_id)
                if job is None:
                    return
                version = job.plan_version
                plan = jobstore.load_plan(job)
            planner = self._planner_factory()
            result = await call(planner, job, plan)
            with Session(self._engine) as session:
                jobstore.record_claude_usage(
                    session, job_id, action=action, model=result.model,
                    input_tokens=result.input_tokens, output_tokens=result.output_tokens, config=claude,
                )
                waiting = self._still_waiting(session, job_id, version)
                if waiting is not None:
                    jobstore.save_plan(session, self._settings.data_dir, waiting, result.plan)
        except PlannerError as exc:
            self._fail(job_id, action, version, str(exc), exc.input_tokens, exc.output_tokens)
        except Exception:
            log.exception("Unexpected error while planning job %s", job_id)
            self._fail(
                job_id, action, version,
                "Lỗi không mong muốn khi lập plan. Xem log của máy chủ để biết chi tiết.",
            )

    def _still_waiting(self, session: Session, job_id: str, version: int | None) -> Job | None:
        """The job, if it is still waiting for the plan this task was started for.

        While Claude was working the job may have been approved, cancelled, edited or deleted;
        writing a late result over that would undo what the user did.
        """
        job = jobstore.get_job(session, job_id)
        if job is None or job.status != JobStatus.planning:
            log.warning("Dropping a planning result for job %s: it is no longer planning", job_id)
            return None
        if version is not None and job.plan_version != version:
            log.warning("Dropping a planning result for job %s: its plan changed meanwhile", job_id)
            return None
        return job

    def _fail(
        self,
        job_id: str,
        action: str,
        version: int | None,
        message: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        claude = self._settings.config.claude
        try:
            with Session(self._engine) as session:
                jobstore.record_claude_usage(
                    session, job_id, action=action, model=claude.model,
                    input_tokens=input_tokens, output_tokens=output_tokens, config=claude,
                )
                waiting = self._still_waiting(session, job_id, version)
                if waiting is not None:
                    jobstore.mark_planning_failed(session, waiting, message)
        except Exception:
            # Last resort: startup recovery (recover_interrupted) will resolve the job.
            log.exception("Could not record the planning failure for job %s", job_id)
