import shutil

import pytest

from app.config import PROJECT_ROOT, load_settings

_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "VIDEO_PROVIDER",
    "TTS_PROVIDER",
    "FPT_TTS_API_KEY",
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
