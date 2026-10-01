"""Job persistence: rows in SQLite, plan versions under data/jobs/<job_id>/."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, desc, select

from app.agent.estimator import PriceNotConfiguredError, llm_cost_usd
from app.config import ClaudeConfig, GeminiConfig
from app.models import CostEntry, Job, JobStatus, Scene
from app.schemas import Plan

INTERRUPTED_MESSAGE = "Việc lập plan bị gián đoạn vì máy chủ khởi động lại. Hãy thử lại."
GENERATION_INTERRUPTED_MESSAGE = (
    "Việc sinh video bị gián đoạn vì máy chủ khởi động lại. Các clip đã xong vẫn được giữ."
)


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


def _store_plan_version(data_dir: Path, job: Job, plan: Plan) -> None:
    """Write the next plan version to disk and set it on the job (not committed here)."""
    data = plan.to_dict()
    version = job.plan_version + 1

    # Files first: the database is the source of truth and is only updated once they exist.
    folder = job_dir(data_dir, job.id)
    folder.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2)
    (folder / f"plan.v{version}.json").write_text(text, encoding="utf-8")
    (folder / "plan.json").write_text(text, encoding="utf-8")

    job.plan_json = json.dumps(data, ensure_ascii=False)
    job.plan_version = version


def save_plan(session: Session, data_dir: Path, job: Job, plan: Plan) -> None:
    """A new plan for review: fresh scene rows, job back to awaiting_approval."""
    _store_plan_version(data_dir, job, plan)
    for row in list_scenes(session, job.id):
        session.delete(row)
    for scene in plan.scenes:
        session.add(Scene(job_id=job.id, scene_no=scene.id))
    job.status = JobStatus.awaiting_approval
    job.error = None
    job.failed_step = None
    _save(session, job)


def update_plan(session: Session, data_dir: Path, job: Job, plan: Plan) -> None:
    """A new plan version while the job is running (a scene's prompt was rewritten).

    Unlike save_plan, the job's status and its scene rows — which track generation — are kept.
    """
    _store_plan_version(data_dir, job, plan)
    _save(session, job)


def get_scene(session: Session, job_id: str, scene_no: int) -> Scene | None:
    return session.exec(select(Scene).where(Scene.job_id == job_id, Scene.scene_no == scene_no)).first()


def set_scene(session: Session, job_id: str, scene_no: int, **changes: Any) -> Scene:
    scene = get_scene(session, job_id, scene_no)
    if scene is None:
        raise LookupError(f"job {job_id} has no scene {scene_no}")
    for name, value in changes.items():
        setattr(scene, name, value)
    session.add(scene)
    session.commit()
    return scene


def clip_path(data_dir: Path, job_id: str, scene_no: int) -> Path:
    return job_dir(data_dir, job_id) / "clips" / f"scene_{scene_no:02d}.mp4"


def audio_path(data_dir: Path, job_id: str, scene_no: int) -> Path:
    return job_dir(data_dir, job_id) / "audio" / f"scene_{scene_no:02d}.wav"


def subtitles_path(data_dir: Path, job_id: str) -> Path:
    return job_dir(data_dir, job_id) / "subtitles.ass"


def final_path(data_dir: Path, job_id: str) -> Path:
    return job_dir(data_dir, job_id) / "final.mp4"


def append_log(data_dir: Path, job_id: str, tag: str, message: str) -> dict[str, str]:
    """Append one line to the job's log.jsonl and return it."""
    entry = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "tag": tag, "message": message}
    folder = job_dir(data_dir, job_id)
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "log.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def read_log(data_dir: Path, job_id: str, limit: int = 200) -> list[dict[str, str]]:
    path = job_dir(data_dir, job_id) / "log.jsonl"
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue  # a line cut short by a crash must not hide the rest of the log
        if isinstance(entry, dict) and {"ts", "tag", "message"} <= entry.keys():
            entries.append(entry)
    return entries[-limit:]


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
    job.error = None  # e.g. the message left by a failed rewrite before the user approved
    _save(session, job)


def mark_generated(session: Session, job: Job) -> None:
    job.status = JobStatus.assembling
    _save(session, job)


def mark_done(session: Session, job: Job) -> None:
    job.status = JobStatus.done
    job.error = None
    job.failed_step = None
    _save(session, job)


def mark_assembly_failed(session: Session, job: Job, message: str) -> None:
    job.status = JobStatus.failed
    job.failed_step = "assembling"
    job.error = message
    _save(session, job)


def list_job_ids(session: Session, status: JobStatus) -> list[str]:
    return [job.id for job in session.exec(select(Job).where(Job.status == status)).all()]


def record_tts_cost(
    session: Session,
    job_id: str,
    *,
    provider: str,
    chars: int,
    price_usd_per_1k_chars: float,
    detail: str,
) -> None:
    session.add(
        CostEntry(
            job_id=job_id,
            kind="tts",
            detail=f"{detail} ({provider})",
            units=chars,
            unit="chars",
            usd=round(chars / 1000 * price_usd_per_1k_chars, 6),
        )
    )
    session.commit()


def mark_generation_failed(session: Session, job: Job, message: str) -> None:
    job.status = JobStatus.failed
    job.failed_step = "generating"
    job.error = message
    _save(session, job)


def record_video_cost(
    session: Session,
    job_id: str,
    *,
    provider: str,
    model: str,
    seconds: int,
    price_usd_per_second: float,
    detail: str,
) -> None:
    session.add(
        CostEntry(
            job_id=job_id,
            kind=provider,
            detail=f"{detail} ({model})",
            units=seconds,
            unit="seconds",
            usd=round(seconds * price_usd_per_second, 6),
        )
    )
    session.commit()


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
    """Resolve jobs whose background task died with the previous server process."""
    planning = session.exec(select(Job).where(Job.status == JobStatus.planning)).all()
    for job in planning:
        mark_planning_failed(session, job, INTERRUPTED_MESSAGE)
    # Not resumed automatically: restarting would spend money the user did not ask to spend again.
    generating = session.exec(select(Job).where(Job.status == JobStatus.generating)).all()
    for job in generating:
        mark_generation_failed(session, job, GENERATION_INTERRUPTED_MESSAGE)
    return len(planning) + len(generating)
