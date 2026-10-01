import json
import shutil
from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.config import PROJECT_ROOT, load_settings
from app.db import init_db, make_engine
from app.main import create_app
from tests.fakes import FakePlanner, HeldProvider

_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "VIDEO_PROVIDER",
    "TTS_PROVIDER",
    "FPT_TTS_API_KEY",
    "LLM_PROVIDER",
)


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch):
    """Tests must not see the developer's real keys or provider switches."""
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def project_root(tmp_path):
    shutil.copy(PROJECT_ROOT / "config.example.yaml", tmp_path / "config.example.yaml")
    return tmp_path


@pytest.fixture
def settings(project_root):
    return load_settings(project_root)


@pytest.fixture
def plan_dict():
    path = PROJECT_ROOT / "tests" / "fixtures" / "plan_30s.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def engine(tmp_path):
    engine = make_engine(tmp_path / "data")
    init_db(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture
def start_app(settings):
    """start_app(*planner_outcomes, provider=None) -> (client, planner).

    Every started app is closed after the test. Without `provider`, approved jobs stay
    `generating` (HeldProvider) so tests see a stable state and no FFmpeg is needed.
    """
    with ExitStack() as stack:

        def start(*outcomes, provider=None):
            planner = FakePlanner(*outcomes)
            video = provider or HeldProvider()
            app = create_app(settings, planner_factory=lambda: planner, provider_factory=lambda: video)
            return stack.enter_context(TestClient(app)), planner

        yield start
