"""FastAPI application: HTML pages and (from Phase 2) the job API."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.assembler.ffmpeg import FFmpegNotFoundError, check_binaries
from app.config import Settings, load_settings
from app.db import init_db, make_engine

APP_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=APP_DIR / "templates")
log = logging.getLogger("app")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.engine = make_engine(settings.data_dir)
        init_db(app.state.engine)
        try:
            check_binaries(settings.config.assembler)
            app.state.ffmpeg_error = None
        except FFmpegNotFoundError as exc:
            # Planning and plan review work without FFmpeg, so warn instead of refusing to start.
            log.warning("%s", exc)
            app.state.ffmpeg_error = str(exc)
        yield
        app.state.engine.dispose()

    app = FastAPI(title="AI Video Agent", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return templates.TemplateResponse(
            request, "index.html", {"ffmpeg_error": request.app.state.ffmpeg_error}
        )

    return app


app = create_app()
