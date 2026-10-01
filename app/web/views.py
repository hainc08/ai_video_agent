"""Jinja setup and the view models shared by HTML pages and the JSON API."""
from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from app import jobstore
from app.agent.estimator import Estimate, PriceNotConfiguredError, estimate
from app.config import Settings
from app.models import Job, JobStatus
from app.options import ASPECTS, DURATIONS, STYLES, VOICES
from app.schemas import Plan
from app.web.forms import default_form_values

APP_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=APP_DIR / "templates")

STEPS = ((1, "Ý tưởng"), (2, "Duyệt plan"), (3, "Đang tạo"), (4, "Hoàn tất"))

STATUS_LABELS: dict[JobStatus, str] = {
    JobStatus.draft: "Nháp",
    JobStatus.planning: "Đang lập plan",
    JobStatus.awaiting_approval: "Chờ duyệt",
    JobStatus.generating: "Đang tạo",
    JobStatus.assembling: "Đang ghép",
    JobStatus.done: "Hoàn tất",
    JobStatus.failed: "Lỗi",
    JobStatus.cancelled: "Đã hủy",
}


def fmt_number(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def fmt_clock(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


templates.env.filters["num"] = fmt_number
templates.env.filters["clock"] = fmt_clock


async def get_session(request: Request) -> AsyncIterator[Session]:
    with Session(request.app.state.engine) as session:
        yield session


def current_step(job: Job | None) -> int:
    if job is None:
        return 1
    if job.status in (JobStatus.generating, JobStatus.assembling, JobStatus.cancelled):
        return 3
    if job.status == JobStatus.done:
        return 4
    if job.status == JobStatus.failed and job.failed_step != "planning":
        return 3
    return 2


def job_summary(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "idea": job.idea,
        "status": job.status.value,
        "status_label": STATUS_LABELS[job.status],
        "created_at": job.created_at.isoformat(),
    }


def render(
    request: Request, name: str, context: dict[str, Any], *, step: int, status_code: int = 200
) -> HTMLResponse:
    base = {"ffmpeg_error": request.app.state.ffmpeg_error, "steps": STEPS, "step": step}
    return templates.TemplateResponse(request, name, base | context, status_code=status_code)


def render_index(
    request: Request,
    session: Session,
    *,
    values: dict[str, Any] | None = None,
    errors: dict[str, str] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    config = request.app.state.settings.config
    context = {
        "values": values or default_form_values(config),
        "errors": errors or {},
        "durations": DURATIONS,
        "aspects": ASPECTS,
        "voices": VOICES,
        "styles": STYLES,
        "recent": [job_summary(job) for job in jobstore.list_recent_jobs(session)],
    }
    return render(request, "index.html", context, step=1, status_code=status_code)


def plan_estimate(settings: Settings, job: Job, plan: Plan) -> tuple[Estimate | None, str | None]:
    try:
        result = estimate(
            plan,
            settings.config,
            video_provider=settings.secrets.video_provider,
            cap_usd=job.cost_cap_usd,
        )
    except PriceNotConfiguredError as exc:
        return None, str(exc)
    return result, None


def job_detail(session: Session, settings: Settings, job: Job) -> dict[str, Any]:
    plan = jobstore.load_plan(job)
    estimated = plan_estimate(settings, job, plan)[0] if plan is not None else None
    return job_summary(job) | {
        "duration_sec": job.duration_sec,
        "aspect": job.aspect,
        "voice": job.voice,
        "style": job.style,
        "cost_cap_usd": job.cost_cap_usd,
        "plan_version": job.plan_version,
        "failed_step": job.failed_step,
        "error": job.error,
        "plan": plan.to_dict() if plan is not None else None,
        "scenes": [
            {"scene_no": scene.scene_no, "status": scene.status.value, "attempts": scene.attempts}
            for scene in jobstore.list_scenes(session, job.id)
        ],
        "cost_usd": jobstore.job_cost_usd(session, job.id),
        "estimate": estimated.model_dump() if estimated is not None else None,
    }
