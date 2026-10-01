"""FastAPI application factory."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session

from app import jobstore
from app.agent.factory import build_planner
from app.agent.planning import PlannerFactory, PlanningService
from app.agent.runner import GenerationService, ProviderFactory
from app.assembler.ffmpeg import FFmpegNotFoundError, check_binaries
from app.config import Settings, load_settings
from app.db import init_db, make_engine
from app.events import EventHub
from app.providers import build_video_provider
from app.web import api, pages

APP_DIR = Path(__file__).resolve().parent
log = logging.getLogger("app")


_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class SameOriginOnly:
    """Refuse state-changing requests that a page on another site made the browser send.

    The server listens on localhost with no login, so any site open in the same browser
    could otherwise post forms to it and start jobs that cost money.
    """

    def __init__(self, app):
        self._app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] not in _SAFE_METHODS:
            headers = {name: value for name, value in scope["headers"]}
            origin = headers.get(b"origin", b"").decode("latin-1")
            host = headers.get(b"host", b"").decode("latin-1")
            if origin and urlsplit(origin).netloc != host:
                response = JSONResponse({"detail": "Yêu cầu từ trang khác bị từ chối."}, status_code=403)
                await response(scope, receive, send)
                return
        await self._app(scope, receive, send)


def create_app(
    settings: Settings | None = None,
    planner_factory: PlannerFactory | None = None,
    provider_factory: ProviderFactory | None = None,
) -> FastAPI:
    settings = settings or load_settings()
    # Built on first use, not at startup: the app must start without an API key.
    factory = planner_factory or (lambda: build_planner(settings))
    video_factory = provider_factory or (lambda: build_video_provider(settings))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.engine = make_engine(settings.data_dir)
        init_db(app.state.engine)
        with Session(app.state.engine) as session:
            recovered = jobstore.recover_interrupted(session)
        if recovered:
            log.warning("Recovered %d job(s) that were running when the server stopped", recovered)
        app.state.planning = PlanningService(settings, app.state.engine, factory)
        app.state.hub = EventHub()
        app.state.generation = GenerationService(
            settings, app.state.engine, app.state.hub, video_factory, factory
        )
        try:
            check_binaries(settings.config.assembler)
            app.state.ffmpeg_error = None
        except FFmpegNotFoundError as exc:
            # Planning and plan review work without FFmpeg, so warn instead of refusing to start.
            log.warning("%s", exc)
            app.state.ffmpeg_error = str(exc)
        yield
        await app.state.generation.shutdown()
        await app.state.planning.shutdown()
        app.state.engine.dispose()

    app = FastAPI(title="AI Video Agent", lifespan=lifespan)
    app.add_middleware(SameOriginOnly)
    app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
    app.include_router(pages.router)
    app.include_router(api.router)
    return app


app = create_app()
