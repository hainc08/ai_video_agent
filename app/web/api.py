"""JSON API under /api. Bodies are form-encoded so plain forms and HTMX can both call it."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import ValidationError
from sqlmodel import Session

from app import jobstore
from app.agent.plan_rules import find_issues
from app.models import Job, JobStatus
from app.schemas import Plan
from app.web.forms import parse_job_form
from app.web.views import fmt_number, get_session, job_detail, job_summary, plan_estimate, render_index

router = APIRouter(prefix="/api")

MAX_FEEDBACK_CHARS = 2000
_SCENE_TEXT_FIELDS = ("voiceover_vi", "subtitle_vi", "visual", "camera", "veo_prompt_en")
_SCENE_DURATIONS = {"4": 4, "6": 6, "8": 8}


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


def _reviewable_plan(job: Job) -> Plan:
    plan = jobstore.load_plan(job)
    if job.status != JobStatus.awaiting_approval or plan is None:
        raise HTTPException(
            status_code=409,
            detail="Job không ở bước duyệt plan nên không thực hiện được thao tác này.",
        )
    return plan


def _scene_or_404(plan: Plan, scene_no: int) -> None:
    if scene_no not in {scene.id for scene in plan.scenes}:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy cảnh {scene_no}.")


def _changed(request: Request, session: Session, job: Job) -> JSONResponse:
    # HX-Refresh makes the HTMX page reload itself and re-render from the database.
    body = job_detail(session, request.app.state.settings, job)
    return JSONResponse(body, headers={"HX-Refresh": "true"})


@router.post("/jobs/{job_id}/revise")
async def revise_plan(request: Request, job_id: str, session: Session = Depends(get_session)):
    # Read the body first: nothing may be awaited between checking the job's state and changing it,
    # or a second request could pass the same check in between.
    feedback = str((await request.form()).get("feedback") or "").strip()
    job = job_or_404(session, job_id)
    _reviewable_plan(job)
    if not feedback:
        raise HTTPException(status_code=422, detail="Hãy nhập góp ý cho Claude trước khi yêu cầu viết lại.")
    if len(feedback) > MAX_FEEDBACK_CHARS:
        raise HTTPException(status_code=422, detail="Góp ý quá dài (tối đa 2.000 ký tự).")
    jobstore.mark_planning(session, job)
    planning = request.app.state.planning
    planning.spawn(planning.revise(job.id, feedback))
    return _changed(request, session, job)


@router.patch("/jobs/{job_id}/scenes/{scene_no}")
async def edit_scene(request: Request, job_id: str, scene_no: int, session: Session = Depends(get_session)):
    # Read the body first: nothing may be awaited between checking the job's state and changing it,
    # or a second request could pass the same check in between.
    form = await request.form()
    job = job_or_404(session, job_id)
    plan = _reviewable_plan(job)
    _scene_or_404(plan, scene_no)

    data = plan.to_dict()
    scene = next(item for item in data["scenes"] if item["id"] == scene_no)
    for field in _SCENE_TEXT_FIELDS:
        if field in form:
            scene[field] = str(form[field]).strip()
    if "duration_sec" in form:
        duration = _SCENE_DURATIONS.get(str(form["duration_sec"]).strip())
        if duration is None:
            raise HTTPException(status_code=422, detail="Thời lượng cảnh phải là 4, 6 hoặc 8 giây.")
        scene["duration_sec"] = duration
    if len(scene["veo_prompt_en"]) > 1000:
        raise HTTPException(status_code=422, detail="Prompt Veo dài quá 1.000 ký tự.")

    try:
        edited = Plan.model_validate(data)
    except ValidationError:
        raise HTTPException(status_code=422, detail="Dữ liệu cảnh không hợp lệ.") from None
    # A hand-edited plan must meet the same rules as one from Claude: later phases rely on them.
    issues = find_issues(edited, duration_sec=job.duration_sec, aspect=job.aspect)
    if issues:
        raise HTTPException(status_code=422, detail="\n".join(issue.vi for issue in issues))

    jobstore.save_plan(session, request.app.state.settings.data_dir, job, edited)
    return _changed(request, session, job)


@router.post("/jobs/{job_id}/scenes/{scene_no}/rewrite")
async def rewrite_scene(request: Request, job_id: str, scene_no: int, session: Session = Depends(get_session)):
    # Read the body first: nothing may be awaited between checking the job's state and changing it,
    # or a second request could pass the same check in between.
    feedback = str((await request.form()).get("feedback") or "").strip()[:MAX_FEEDBACK_CHARS]
    job = job_or_404(session, job_id)
    plan = _reviewable_plan(job)
    _scene_or_404(plan, scene_no)
    jobstore.mark_planning(session, job)
    planning = request.app.state.planning
    planning.spawn(planning.rewrite_scene(job.id, scene_no, feedback))
    return _changed(request, session, job)


@router.post("/jobs/{job_id}/approve")
async def approve_plan(request: Request, job_id: str, session: Session = Depends(get_session)):
    job = job_or_404(session, job_id)
    plan = _reviewable_plan(job)
    # The disabled button is only a hint: the cap is enforced here.
    estimated, reason = plan_estimate(request.app.state.settings, job, plan)
    if estimated is None:
        raise HTTPException(status_code=409, detail=reason)
    if estimated.over_cap:
        raise HTTPException(
            status_code=409,
            detail=f"Chi phí dự kiến {fmt_number(estimated.cost_usd)} USD vượt trần "
            f"{job.cost_cap_usd:g} USD của video này.",
        )
    jobstore.mark_approved(session, job)
    return _changed(request, session, job)
