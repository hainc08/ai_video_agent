"""FastAPI application factory."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session

from app import jobstore
from app.agent.planner import build_planner
from app.agent.planning import PlannerFactory, PlanningService
from app.assembler.ffmpeg import FFmpegNotFoundError, check_binaries
from app.config import Settings, load_settings
from app.db import init_db, make_engine
from app.web import pages

APP_DIR = Path(__file__).resolve().parent
log = logging.getLogger("app")


def create_app(settings: Settings | None = None, planner_factory: PlannerFactory | None = None) -> FastAPI:
    settings = settings or load_settings()
    # Built on first use, not at startup: the app must start without an API key.
    factory = planner_factory or (lambda: build_planner(settings))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.engine = make_engine(settings.data_dir)
        init_db(app.state.engine)
        with Session(app.state.engine) as session:
            recovered = jobstore.recover_interrupted(session)
        if recovered:
            log.warning("Recovered %d job(s) that were planning when the server stopped", recovered)
        app.state.planning = PlanningService(settings, app.state.engine, factory)
        try:
            check_binaries(settings.config.assembler)
            app.state.ffmpeg_error = None
        except FFmpegNotFoundError as exc:
            # Planning and plan review work without FFmpeg, so warn instead of refusing to start.
            log.warning("%s", exc)
            app.state.ffmpeg_error = str(exc)
        yield
        await app.state.planning.shutdown()
        app.state.engine.dispose()

    app = FastAPI(title="AI Video Agent", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
    app.include_router(pages.router)
    return app


app = create_app()
