"""HTML pages."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from app import jobstore
from app.web.forms import default_form_values
from app.web.views import get_session, render_index

router = APIRouter()


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
