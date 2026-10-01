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
    """Keep other web sites from driving this server through the user's browser.

    The server listens on localhost with no login, so two things are refused:
    - any request for a host name the server is not configured to serve (a page that points
      its own domain at 127.0.0.1 — DNS rebinding — would otherwise look same-origin);
    - a state-changing request whose Origin is a different site (a cross-site form post).
    """

    def __init__(self, app, allowed_hosts):
        self._app = app
        self._allowed_hosts = allowed_hosts  # the live config list, so it can be extended

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = {name: value for name, value in scope["headers"]}
            host = headers.get(b"host", b"").decode("latin-1")
            hostname = urlsplit("//" + host).hostname if host else None
            if hostname not in {allowed.lower() for allowed in self._allowed_hosts}:
                await self._refuse(scope, receive, send, "Máy chủ không phục vụ tên miền này.")
                return
            origin = headers.get(b"origin", b"").decode("latin-1")
            if scope["method"] not in _SAFE_METHODS and origin and urlsplit(origin).netloc != host:
                await self._refuse(scope, receive, send, "Yêu cầu từ trang khác bị từ chối.")
                return
        await self._app(scope, receive, send)

    @staticmethod
    async def _refuse(scope, receive, send, detail):
        await JSONResponse({"detail": detail}, status_code=403)(scope, receive, send)


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
    app.add_middleware(SameOriginOnly, allowed_hosts=settings.config.server.allowed_hosts)
    app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
    app.include_router(pages.router)
    app.include_router(api.router)
    return app


app = create_app()
