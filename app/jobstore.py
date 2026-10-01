"""Job persistence: rows in SQLite, plan versions under data/jobs/<job_id>/."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func
from sqlmodel import Session, desc, select

from app.agent.estimator import PriceNotConfiguredError, llm_cost_usd
from app.config import ClaudeConfig, GeminiConfig
from app.models import CostEntry, Job, JobStatus, Scene
from app.schemas import Plan

INTERRUPTED_MESSAGE = "Việc lập plan bị gián đoạn vì máy chủ khởi động lại. Hãy thử lại."


def _save(session: Session, job: Job) -> None:
    job.updated_at = datetime.now(timezone.utc)
    session.add(job)
    session.commit()


def job_dir(data_dir: Path, job_id: str) -> Path:
    return data_dir / "jobs" / job_id


def create_job(
    session: Session,
    *,
    idea: str,
    duration_sec: int,
    aspect: str,
    voice: str,
    style: str,
    cost_cap_usd: float,
) -> Job:
    job = Job(
        idea=idea,
        duration_sec=duration_sec,
        aspect=aspect,
        voice=voice,
        style=style,
        cost_cap_usd=cost_cap_usd,
        status=JobStatus.planning,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def get_job(session: Session, job_id: str) -> Job | None:
    return session.get(Job, job_id)


def list_recent_jobs(session: Session, limit: int = 10) -> list[Job]:
    return list(session.exec(select(Job).order_by(desc(Job.created_at)).limit(limit)).all())


def list_scenes(session: Session, job_id: str) -> list[Scene]:
    return list(session.exec(select(Scene).where(Scene.job_id == job_id).order_by(Scene.scene_no)).all())


def load_plan(job: Job) -> Plan | None:
    if not job.plan_json:
        return None
    return Plan.model_validate(json.loads(job.plan_json))


def save_plan(session: Session, data_dir: Path, job: Job, plan: Plan) -> None:
    data = plan.to_dict()
    version = job.plan_version + 1

    # Files first: the database is the source of truth and is only updated once they exist.
    folder = job_dir(data_dir, job.id)
    folder.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2)
    (folder / f"plan.v{version}.json").write_text(text, encoding="utf-8")
    (folder / "plan.json").write_text(text, encoding="utf-8")

    for row in list_scenes(session, job.id):
        session.delete(row)
    for scene in plan.scenes:
        session.add(Scene(job_id=job.id, scene_no=scene.id))
    job.plan_json = json.dumps(data, ensure_ascii=False)
    job.plan_version = version
    job.status = JobStatus.awaiting_approval
    job.error = None
    job.failed_step = None
    _save(session, job)


def mark_planning(session: Session, job: Job) -> None:
    job.status = JobStatus.planning
    job.error = None
    _save(session, job)


def mark_planning_failed(session: Session, job: Job, message: str) -> None:
    if job.plan_json:
        # A revise or rewrite failed: the plan the user already had is still good.
        job.status = JobStatus.awaiting_approval
    else:
        job.status = JobStatus.failed
        job.failed_step = "planning"
    job.error = message
    _save(session, job)


def mark_approved(session: Session, job: Job) -> None:
    job.status = JobStatus.generating
    _save(session, job)


def record_llm_usage(
    session: Session,
    job_id: str,
    *,
    kind: str,
    action: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    config: ClaudeConfig | GeminiConfig,
) -> None:
    detail = f"{action} ({model})"
    try:
        usd_in = llm_cost_usd(input_tokens, 0, config)
        usd_out = llm_cost_usd(0, output_tokens, config)
    except PriceNotConfiguredError:
        usd_in = usd_out = 0.0
        detail += " - price not configured"
    for unit, units, usd in (("tokens_in", input_tokens, usd_in), ("tokens_out", output_tokens, usd_out)):
        if units:
            session.add(CostEntry(job_id=job_id, kind=kind, detail=detail, units=units, unit=unit, usd=usd))
    session.commit()


def job_cost_usd(session: Session, job_id: str) -> float:
    total = session.exec(select(func.sum(CostEntry.usd)).where(CostEntry.job_id == job_id)).one()
    return round(float(total or 0.0), 6)


def recover_interrupted(session: Session) -> int:
    jobs = session.exec(select(Job).where(Job.status == JobStatus.planning)).all()
    for job in jobs:
        mark_planning_failed(session, job, INTERRUPTED_MESSAGE)
    return len(jobs)
