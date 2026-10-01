"""JSON API under /api. Bodies are form-encoded so plain forms and HTMX can both call it."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlmodel import Session

from app import jobstore
from app.models import Job
from app.web.forms import parse_job_form
from app.web.views import get_session, job_detail, job_summary, render_index

router = APIRouter(prefix="/api")


def job_or_404(session: Session, job_id: str) -> Job:
    job = jobstore.get_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy job.")
    return job


@router.post("/jobs")
async def create_job(request: Request, session: Session = Depends(get_session)):
    settings = request.app.state.settings
    values, cap, errors = parse_job_form(await request.form(), settings.config)
    if errors:
        return render_index(request, session, values=values, errors=errors, status_code=422)
    job = jobstore.create_job(
        session,
        idea=values["idea"],
        duration_sec=values["duration_sec"],
        aspect=values["aspect"],
        voice=values["voice"],
        style=values["style"],
        cost_cap_usd=cap,
    )
    planning = request.app.state.planning
    planning.spawn(planning.create(job.id))
    return RedirectResponse(f"/jobs/{job.id}", status_code=303)


@router.get("/jobs")
async def list_jobs(session: Session = Depends(get_session)):
    return [job_summary(job) for job in jobstore.list_recent_jobs(session, limit=50)]


@router.get("/jobs/{job_id}")
async def get_job(request: Request, job_id: str, session: Session = Depends(get_session)):
    return job_detail(session, request.app.state.settings, job_or_404(session, job_id))


@router.get("/jobs/{job_id}/plan.json")
async def download_plan(job_id: str, session: Session = Depends(get_session)):
    job = job_or_404(session, job_id)
    plan = jobstore.load_plan(job)
    if plan is None:
        raise HTTPException(status_code=404, detail="Job này chưa có plan.")
    return JSONResponse(
        plan.to_dict(),
        headers={"Content-Disposition": f'attachment; filename="plan-{job.id}.json"'},
    )
