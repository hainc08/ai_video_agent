"""HTML pages."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from app import jobstore
from app.models import JobStatus
from app.web.forms import default_form_values
from app.web.views import (
    STATUS_LABELS,
    current_step,
    failed_context,
    get_session,
    progress_context,
    render,
    render_index,
    review_context,
    templates,
)

router = APIRouter()

_PROGRESS_STATES = (JobStatus.generating, JobStatus.assembling)


@router.get("/", response_class=HTMLResponse)
async def index(request: Request, job: str | None = None, session: Session = Depends(get_session)):
    values = None
    source = jobstore.get_job(session, job) if job else None
    if source is not None:
        # "Quay lại sửa ý tưởng": start a new job from an earlier one's inputs.
        values = default_form_values(request.app.state.settings.config) | {
            "idea": source.idea,
            "duration_sec": source.duration_sec,
            "aspect": source.aspect,
            "voice": source.voice,
            "style": source.style,
            "cost_cap_usd": f"{source.cost_cap_usd:g}",
        }
    return render_index(request, session, values=values)


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_page(request: Request, job_id: str, session: Session = Depends(get_session)):
    job = jobstore.get_job(session, job_id)
    if job is None:
        return render(request, "not_found.html", {}, step=1, status_code=404)
    step = current_step(job)
    if job.status == JobStatus.planning:
        return render(request, "job_planning.html", {"job": job}, step=step)
    if job.status == JobStatus.failed:
        return render(request, "job_failed.html", failed_context(session, job), step=step)
    plan = jobstore.load_plan(job)
    if job.status == JobStatus.awaiting_approval and plan is not None:
        context = review_context(request.app.state.settings, job, plan)
        return render(request, "job_review.html", context, step=step)
    if job.status in _PROGRESS_STATES and plan is not None:
        context = progress_context(session, request.app.state.settings, job, plan)
        return render(request, "job_progress.html", context, step=step)
    return render(request, "job_status.html", {"job": job, "status_label": STATUS_LABELS[job.status]}, step=step)


@router.get("/jobs/{job_id}/progress", response_class=HTMLResponse)
async def job_progress_fragment(request: Request, job_id: str, session: Session = Depends(get_session)):
    """Only the #progress block of screen 3: the live page swaps it in whenever the job changes."""
    job = jobstore.get_job(session, job_id)
    plan = jobstore.load_plan(job) if job is not None else None
    if job is None or plan is None:
        return HTMLResponse("", status_code=404)
    context = progress_context(session, request.app.state.settings, job, plan)
    return templates.TemplateResponse(request, "_progress.html", context)
