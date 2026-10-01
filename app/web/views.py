"""Jinja setup and the view models shared by HTML pages and the JSON API."""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timezone
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from app import jobstore
from app.agent.estimator import Estimate, PriceNotConfiguredError, estimate
from app.config import Settings
from app.models import Job, JobStatus, Scene, SceneStatus
from app.options import ASPECTS, DURATIONS, STYLES, VOICES, voice_label
from app.providers import supported_aspects
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


def aspect_problem(settings: Settings, job: Job) -> str | None:
    """Why this job's aspect ratio cannot be generated with the selected provider, if it cannot."""
    supported = supported_aspects(settings)
    if job.aspect in supported:
        return None
    names = " và ".join(aspect for aspect in ASPECTS if aspect in supported)
    return (
        f"Veo chỉ hỗ trợ tỉ lệ {names}, không có {job.aspect}. "
        "Hãy quay lại sửa ý tưởng và chọn một trong các tỉ lệ đó."
    )


def clip_url(job_id: str, scene: Scene) -> str | None:
    if scene.status != SceneStatus.approved:
        return None
    return f"/api/jobs/{job_id}/clips/{scene.scene_no}"


def video_url(settings: Settings, job: Job) -> str | None:
    if job.status != JobStatus.done or not jobstore.final_path(settings.data_dir, job.id).exists():
        return None
    return f"/api/jobs/{job.id}/video"


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
            {
                "scene_no": scene.scene_no,
                "status": scene.status.value,
                "attempts": scene.attempts,
                "error": scene.error,
                "clip_url": clip_url(job.id, scene),
            }
            for scene in jobstore.list_scenes(session, job.id)
        ],
        "log": jobstore.read_log(settings.data_dir, job.id, limit=50),
        "cost_usd": jobstore.job_cost_usd(session, job.id),
        "video_url": video_url(settings, job),
        "estimate": estimated.model_dump() if estimated is not None else None,
    }


def scene_rows(plan: Plan) -> list[dict[str, Any]]:
    rows = []
    start = 0
    for scene in plan.scenes:
        end = start + scene.duration_sec
        rows.append({"scene": scene, "time": f"{fmt_clock(start)}–{fmt_clock(end)}"})
        start = end
    return rows


def review_context(settings: Settings, job: Job, plan: Plan, spent: float = 0.0) -> dict[str, Any]:
    estimated, estimate_error = plan_estimate(settings, job, plan)
    # Same rule as POST /approve and the runner: what the job already spent counts.
    over_cap = estimated is not None and round(estimated.cost_usd + spent, 6) > job.cost_cap_usd
    aspect_error = aspect_problem(settings, job)
    return {
        "job": job,
        "plan": plan,
        "rows": scene_rows(plan),
        "voice": voice_label(job.voice),
        "cap": f"{job.cost_cap_usd:g}",
        "estimate": estimated,
        "estimate_error": estimate_error,
        # The server enforces the same rule in POST /approve; this only disables the button.
        "locked": estimated is None or over_cap or aspect_error is not None,
        "over_cap": over_cap,
        "spent": spent,
        "aspect_error": aspect_error,
        "fake_video": settings.secrets.video_provider == "fake",
    }


_TILES: dict[SceneStatus, tuple[str, str]] = {
    # status -> (badge label, tile kind for styling)
    SceneStatus.planned: ("Hàng đợi", "wait"),
    SceneStatus.generating: ("Đang sinh", "run"),
    SceneStatus.generated: ("Đang kiểm tra", "run"),
    SceneStatus.qc_failed: ("Sinh lại", "run"),
    SceneStatus.regenerating: ("Sinh lại", "run"),
    SceneStatus.approved: ("Đạt", "done"),
    SceneStatus.failed: ("Lỗi", "fail"),
}


def _tile(job: Job, scene: Scene, duration_sec: int, max_regenerations: int) -> dict[str, Any]:
    label, kind = _TILES[scene.status]
    if scene.status == SceneStatus.approved:
        note = f"{duration_sec} giây"
    elif scene.status == SceneStatus.generating:
        note = "Veo đang xử lý"
    elif scene.status == SceneStatus.generated:
        note = "Đang kiểm tra clip"
    elif scene.status in (SceneStatus.regenerating, SceneStatus.qc_failed):
        # `attempts` moves to 2 only when the new attempt starts; until then the error is still set.
        number = max(1, scene.attempts if scene.error else scene.attempts - 1)
        note = f"Lần {number}/{max_regenerations}" + (f" · {scene.error}" if scene.error else "")
    elif scene.status == SceneStatus.failed:
        note = scene.error or "Không rõ lý do"
    else:
        note = "Chờ lượt"
    return {"n": scene.scene_no, "label": label, "kind": kind, "note": note, "clip_url": clip_url(job.id, scene)}


def progress_context(session: Session, settings: Settings, job: Job, plan: Plan) -> dict[str, Any]:
    """Everything screen 3 shows, read from the database and the job's log file."""
    scenes = jobstore.list_scenes(session, job.id)
    durations = {scene.id: scene.duration_sec for scene in plan.scenes}
    total = len(scenes)
    approved = sum(1 for scene in scenes if scene.status == SceneStatus.approved)
    generating = job.status == JobStatus.generating
    # While the job is being finished, progress shows in the files the finisher has written.
    voiced = sum(1 for scene in scenes if jobstore.audio_path(settings.data_dir, job.id, scene.scene_no).exists())
    voices_done = not generating and total > 0 and voiced == total

    def step(number: int, title: str, note: str, state: str) -> dict[str, str]:
        mark = {"done": "✓", "run": "•"}.get(state, str(number))
        return {"title": title, "note": note, "state": state, "mark": mark}

    spent = jobstore.job_cost_usd(session, job.id)
    width, height = job.aspect.split(":")
    return {
        "job": job,
        "running": job.status in (JobStatus.generating, JobStatus.assembling),
        "psteps": [
            step(1, "Lập plan", "Hoàn tất", "done"),
            step(2, "Duyệt plan", "Bạn đã duyệt", "done"),
            step(3, "Sinh clip bằng Veo", f"{approved}/{total} cảnh xong", "run" if generating else "done"),
            step(4, "Kiểm tra clip", "Chạy sau mỗi clip" if generating else f"{approved}/{total} clip đạt",
                 "wait" if generating else "done"),
            step(5, "Giọng đọc + phụ đề",
                 "Đang chờ" if generating else f"{voiced}/{total} cảnh có giọng đọc",
                 "wait" if generating else ("done" if voices_done else "run")),
            step(6, "Ghép MP4", "Đang ghép video…" if voices_done else "Đang chờ", "run" if voices_done else "wait"),
        ],
        "tiles": [
            _tile(job, scene, durations.get(scene.scene_no, 0), settings.config.limits.max_regenerations_per_scene)
            for scene in scenes
        ],
        "tile_ratio": f"{width} / {height}",
        "max_concurrent": settings.config.veo.max_concurrent,
        "spent": spent,
        "cap": f"{job.cost_cap_usd:g}",
        "cost_percent": round(min(100.0, spent / job.cost_cap_usd * 100)) if job.cost_cap_usd > 0 else 100,
        "log": jobstore.read_log(settings.data_dir, job.id),
    }


def failed_context(session: Session, job: Job) -> dict[str, Any]:
    scenes = jobstore.list_scenes(session, job.id)
    return {
        "job": job,
        "failed_scenes": [scene for scene in scenes if scene.status == SceneStatus.failed],
        "clips_done": sum(1 for scene in scenes if scene.status == SceneStatus.approved),
        "clips_total": len(scenes),
    }


def _elapsed(seconds: float) -> str:
    seconds = max(0, round(seconds))
    minutes, rest = divmod(seconds, 60)
    return f"{minutes} phút {rest} giây" if minutes else f"{rest} giây"


def done_context(session: Session, settings: Settings, job: Job, plan: Plan) -> dict[str, Any]:
    """Screen 4: the finished video and the real figures of the run."""
    scenes = jobstore.list_scenes(session, job.id)
    final = jobstore.final_path(settings.data_dir, job.id)
    # No "finished at" column exists (and none is added: there are no migrations), so the
    # video file's own timestamp says when the job ended.
    created = job.created_at if job.created_at.tzinfo else job.created_at.replace(tzinfo=timezone.utc)
    elapsed = _elapsed(final.stat().st_mtime - created.timestamp()) if final.exists() else "không rõ"
    width, height = job.aspect.split(":")
    return {
        "job": job,
        "video_url": video_url(settings, job),
        "ratio": f"{width} / {height}",
        "voice": voice_label(job.voice),
        "total_sec": sum(scene.duration_sec for scene in plan.scenes),
        "scene_count": len(plan.scenes),
        "caption": plan.caption_vi,
        "elapsed": elapsed,
        "cost": jobstore.job_cost_usd(session, job.id),
        "regenerated": sum(1 for scene in scenes if scene.attempts > 1),
    }
