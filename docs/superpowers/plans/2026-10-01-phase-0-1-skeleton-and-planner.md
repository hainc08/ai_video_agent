# Phase 0–1: Project Skeleton + Claude Planner — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the runnable project skeleton (config, FFmpeg check, SQLite models, empty FastAPI page) and the Claude planner that turns an idea into a validated `Plan`, with revise / rewrite-scene and a cost-and-time estimator — all tested without any paid API call.

**Architecture:** A FastAPI app factory (`create_app(settings)`) wires config, SQLite and an FFmpeg check at startup. The planner is a class with an injected Anthropic client: it asks Claude to call a strict `submit_plan` tool, validates the result in two layers (Pydantic structure, then business rules), and feeds errors back to Claude up to 2 times. The estimator is a pure function over `Plan` + config.

**Tech Stack:** Python 3.11+ on Windows, FastAPI + Uvicorn, Jinja2, SQLModel/SQLite, Pydantic v2 + pydantic-settings, PyYAML, `anthropic` SDK (async), pytest + pytest-asyncio, jsonschema (tests only).

**Spec:** `CLAUDE.md`, `TASKS.md` (Giai đoạn 0 and 1), `docs/REQUIREMENTS.md`, `docs/ARCHITECTURE.md`, `docs/plan.schema.json`, `prompts/planner_system.md`. Executors read these alongside this plan.

**Scope:** This plan covers `TASKS.md` Giai đoạn 0 and Giai đoạn 1 only. Giai đoạn 2 (UI screens 1–2), 3 (Veo + runner), 4 (TTS + assembly) and 5 (hardening) each get their own plan. Not in this plan: job API routes, writing `CostEntry` rows (there are no jobs yet — the planner returns token counts so Phase 2 can record them), `app/providers/`.

**Working directory:** every command runs from the project root, the folder that contains `CLAUDE.md`:
`C:\Users\admin\workspace\00.APP\2026_CHANLEN\ai-video-agent\ai-video-agent`. Commands are PowerShell.

## Global Constraints

- Python 3.11+, Windows. Use `pathlib`; never hard-code `/` in paths. `subprocess` calls never use `shell=True`.
- Read every text file with an explicit encoding (`utf-8`, or `utf-8-sig` for files the user edits by hand: `config.yaml`, `.env`). Windows' default codepage corrupts Vietnamese.
- **Tests never call a paid API** (Claude, Veo, TTS). Claude is mocked with a fake client. Default `VIDEO_PROVIDER=fake`.
- API keys are read only from `.env`. Never log a key, never commit `.env` or `config.yaml`.
- Model names and prices live in `config.yaml` / `config.example.yaml`, never hard-coded in Python.
- Code, identifiers and comments in English. Strings shown to the user (error messages surfaced in the UI, templates) in Vietnamese.
- LLM: Claude via the Anthropic Python SDK with **tool use** against `docs/plan.schema.json`.
- Claude API facts that shape the planner (verified against the current SDK docs; do not "fix" these from memory):
  - `claude-sonnet-5-5` and `claude-opus-5-5` reject forced tool choice (`tool_choice` `{"type": "tool"}` / `{"type": "any"}` → HTTP 400). Use `{"type": "auto"}` + `strict: True` on the tool + a prompt instruction, and check that the tool was actually called.
  - Thinking is always on for these models. Do not send `thinking`, `temperature`, `top_p` or `top_k`. Depth is controlled by `output_config={"effort": ...}`. Thinking counts toward `max_tokens`, so `max_tokens` is 16000, not 4000.
  - Strict tool schemas reject `minLength`, `maxLength`, `minimum`, `maximum`, `minItems`, `maxItems`; those constraints are stripped from the schema sent to Claude and enforced by Pydantic instead.
  - Check `stop_reason` before reading content: `"refusal"` and `"max_tokens"` are not plans.
  - Append `response.content` to the history unchanged when continuing a conversation (it carries thinking blocks).
- UI tokens (used by the empty page in Task 4): background `#F4F2EC`, text `#17181C`, accent `#1D4ED8`, warning `#C2410C`, fonts Be Vietnam Pro and JetBrains Mono.
- Commit after every task.

## Review Focus

Input classes the spec implies but does not spell out, most likely first. Each has a test in the task named in brackets.

1. **Claude answers without calling `submit_plan`** (possible because the tool cannot be forced) — the planner re-prompts instead of crashing or returning nothing. [Task 7]
2. **Claude stops with `refusal` or `max_tokens`** — a clear Vietnamese error; a truncated tool input is never accepted as a plan, even when it happens to parse. [Task 7]
3. **Vietnamese text on Windows** — `config.yaml` saved by Notepad with a UTF-8 BOM and Vietnamese characters still loads; word counting ignores punctuation-only tokens and irregular whitespace. [Tasks 1, 6]
4. **Missing or half-filled configuration** — no `config.yaml`, no `.env`, empty key values, `veo.price_usd_per_second: null` with the real provider: the app starts on defaults, and the estimator refuses to report a cost of $0 for a paid run. [Tasks 1, 9]
5. **A plan that is right in total but wrong per scene** — one scene with far too many words for its clip, or duplicate / out-of-order scene ids — is rejected even though total duration and total word count pass. [Task 6]

---

## File Structure

| File | Responsibility |
| --- | --- |
| `pytest.ini` | pytest config (`asyncio_mode = auto`, import path) |
| `requirements.txt` | add `jsonschema` |
| `config.example.yaml` | add Claude effort / fallback / prices, time estimates; raise `max_tokens` |
| `app/config.py` | typed config from `config.yaml`, secrets from `.env`, `load_settings()` |
| `app/assembler/ffmpeg.py` | `check_binaries()` — are ffmpeg/ffprobe runnable (assembly itself is Phase 4) |
| `app/models.py` | SQLModel tables `Job`, `Scene`, `CostEntry` + status enums |
| `app/db.py` | `make_engine()`, `init_db()` |
| `app/main.py` | `create_app()`, startup lifespan, route `/` |
| `app/templates/base.html`, `index.html`, `app/static/app.css` | empty Vietnamese page with the design tokens |
| `app/schemas.py` | Pydantic `Plan`, `Target`, `Brief`, `Scene` mirroring `docs/plan.schema.json` |
| `app/agent/plan_rules.py` | business rules: durations, word counts, ids → list of error strings |
| `app/agent/planner.py` | `Planner.create_plan / revise / rewrite_scene`, strict tool schema, retry loop |
| `app/agent/estimator.py` | `estimate()` (USD + minutes), `claude_cost_usd()` |
| `scripts/try_planner.py` | manual smoke run against the real Claude API |
| `tests/…` | one test file per module, `tests/fixtures/plan_30s.json` |

---

### Task 1: Project scaffold and configuration

**Files:**
- Create: `pytest.ini`, `app/__init__.py`, `app/config.py`, `tests/__init__.py`, `tests/conftest.py`, `tests/test_config.py`
- Modify: `requirements.txt`, `config.example.yaml`

**Interfaces:**
- Consumes: nothing.
- Produces (from `app.config`):
  - `PROJECT_ROOT: Path` — the folder containing `CLAUDE.md`.
  - `class ConfigError(Exception)`.
  - `ClaudeConfig(model: str, max_tokens: int = 16000, effort: Literal["low","medium","high","xhigh","max"] = "medium", refusal_fallback: bool = True, price_usd_per_mtok_input: float | None = None, price_usd_per_mtok_output: float | None = None)`
  - `VeoConfig(model: str, resolution: str, generate_audio: bool, price_usd_per_second: float | None, max_concurrent: int, job_timeout_sec: int, poll_interval_sec: int, est_clip_generation_sec: int)`
  - `LimitsConfig(cost_cap_per_job_usd: float, cost_cap_per_day_usd: float, max_regenerations_per_scene: int)`
  - `DefaultsConfig(duration_sec, aspect, voice, style)`, `TTSConfig(price_usd_per_1k_chars: float | None)`, `AssemblerConfig(ffmpeg_path, ffprobe_path, output_width, output_height, subtitle_font, music_dir, logo_path, est_assembly_sec)`, `StorageConfig(data_dir)`
  - `AppConfig(claude, veo, limits, defaults, tts, assembler, storage)`
  - `Secrets` with `video_provider: Literal["fake","veo"]`, `tts_provider: Literal["fake","fpt","google"]`, methods `anthropic_key() -> str | None`, `gemini_key() -> str | None`.
  - `Settings(root: Path, config: AppConfig, secrets: Secrets)` with property `data_dir: Path`.
  - `load_config(root: Path) -> AppConfig`, `load_settings(root: Path | None = None) -> Settings`.
- Produces (pytest fixtures in `tests/conftest.py`): `project_root` (a tmp dir holding a copy of `config.example.yaml`), `settings` (`load_settings(project_root)`).

- [ ] **Step 1: Create the git repository and commit the existing docs**

The folder is not a git repository yet. `.gitignore` already excludes `.env`, `config.yaml`, `.venv/`, `data/`.

```powershell
git init
git add .
git commit -m "chore: import project docs and config templates"
```

Expected: a commit listing `CLAUDE.md`, `TASKS.md`, `docs/…`, `prompts/…`, `.env.example`, `config.example.yaml`, `requirements.txt`, `README.md`, `.gitignore`, `assets/music/.gitkeep`.

- [ ] **Step 2: Add the test-only dependency and create the virtualenv**

Append one line to `requirements.txt` so the file ends with:

```
pytest
pytest-asyncio
jsonschema
```

Create `pytest.ini`:

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
pythonpath = .
```

Then (Python 3.13 is installed; the default `python` is 3.14, which is newer than some wheels may support):

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt
```

Expected: install finishes without errors. All later commands use `.venv\Scripts\python` directly, so no activation is needed.

- [ ] **Step 3: Write the failing tests**

Create empty `tests/__init__.py`.

Create `tests/conftest.py`:

```python
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
```

Create `tests/test_config.py`:

```python
import pytest

from app.config import ConfigError, load_config, load_settings


def test_falls_back_to_example_when_config_yaml_is_missing(project_root):
    cfg = load_config(project_root)

    assert cfg.claude.model == "claude-sonnet-5-5"
    assert cfg.claude.max_tokens == 16000
    assert cfg.claude.effort == "medium"
    assert cfg.claude.refusal_fallback is True
    assert cfg.claude.price_usd_per_mtok_input == 2.0
    assert cfg.claude.price_usd_per_mtok_output == 10.0
    assert cfg.veo.model == "veo-3.1-generate-preview"
    assert cfg.veo.price_usd_per_second is None
    assert cfg.veo.max_concurrent == 3
    assert cfg.veo.est_clip_generation_sec == 120
    assert cfg.limits.cost_cap_per_job_usd == 5
    assert cfg.limits.max_regenerations_per_scene == 1
    assert cfg.defaults.duration_sec == 30
    assert cfg.defaults.aspect == "9:16"
    assert cfg.assembler.est_assembly_sec == 90


def test_config_yaml_wins_and_missing_sections_use_defaults(project_root):
    (project_root / "config.yaml").write_text(
        "claude:\n  model: claude-opus-5-5\nveo:\n  model: veo-x\n  price_usd_per_second: 0.4\n",
        encoding="utf-8",
    )

    cfg = load_config(project_root)

    assert cfg.claude.model == "claude-opus-5-5"
    assert cfg.veo.price_usd_per_second == 0.4
    assert cfg.limits.cost_cap_per_day_usd == 20
    assert cfg.assembler.ffmpeg_path == "ffmpeg"


def test_reads_utf8_with_bom_and_vietnamese_text(project_root):
    text = 'claude:\n  model: m\nveo:\n  model: v\ndefaults:\n  style: "văn phòng sáng sủa"\n'
    (project_root / "config.yaml").write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))

    assert load_config(project_root).defaults.style == "văn phòng sáng sủa"


def test_empty_config_file_is_a_clear_error(project_root):
    (project_root / "config.yaml").write_text("", encoding="utf-8")

    with pytest.raises(ConfigError, match="config.yaml"):
        load_config(project_root)


def test_misspelled_key_is_rejected(project_root):
    (project_root / "config.yaml").write_text(
        "claude:\n  model: m\nveo:\n  model: v\nlimits:\n  cost_cap_per_job: 5\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="cost_cap_per_job"):
        load_config(project_root)


def test_invalid_yaml_is_a_clear_error(project_root):
    (project_root / "config.yaml").write_text("claude: [unclosed", encoding="utf-8")

    with pytest.raises(ConfigError, match="YAML"):
        load_config(project_root)


def test_no_config_file_at_all_is_a_clear_error(tmp_path):
    with pytest.raises(ConfigError, match="config.example.yaml"):
        load_config(tmp_path)


def test_secrets_default_to_fake_providers_without_dotenv(settings):
    assert settings.secrets.video_provider == "fake"
    assert settings.secrets.tts_provider == "fake"
    assert settings.secrets.anthropic_key() is None
    assert settings.secrets.gemini_key() is None


def test_secrets_come_from_dotenv_and_blank_values_count_as_missing(project_root):
    (project_root / ".env").write_text(
        "ANTHROPIC_API_KEY=sk-test-123\nGEMINI_API_KEY=\nVIDEO_PROVIDER=veo\n",
        encoding="utf-8",
    )

    settings = load_settings(project_root)

    assert settings.secrets.anthropic_key() == "sk-test-123"
    assert settings.secrets.gemini_key() is None
    assert settings.secrets.video_provider == "veo"
    assert "sk-test-123" not in repr(settings.secrets)


def test_unknown_provider_in_dotenv_is_a_clear_error(project_root):
    (project_root / ".env").write_text("VIDEO_PROVIDER=flow\n", encoding="utf-8")

    with pytest.raises(ConfigError, match=".env"):
        load_settings(project_root)


def test_data_dir_is_resolved_against_the_project_root(settings, project_root):
    assert settings.data_dir == project_root / "data"
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_config.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'app'`.

- [ ] **Step 5: Update `config.example.yaml`**

Replace the `claude:` block with:

```yaml
claude:
  model: claude-sonnet-5-5        # đổi sang claude-opus-5-5 nếu cần chất lượng plan cao hơn
  max_tokens: 16000               # gồm cả phần "thinking" của model; đừng hạ xuống dưới 8000
  effort: medium                  # low | medium | high | xhigh | max
  refusal_fallback: true          # nếu model từ chối, API tự thử lại bằng model dự phòng (beta)
  price_usd_per_mtok_input: 2.0   # đơn giá của model ở trên; sửa lại nếu đổi model
  price_usd_per_mtok_output: 10.0
```

In the `veo:` block add one line after `poll_interval_sec: 10`:

```yaml
  est_clip_generation_sec: 120    # ước lượng thời gian sinh 1 clip, dùng cho màn duyệt plan
```

In the `assembler:` block add one line after `logo_path: assets/logo.png`:

```yaml
  est_assembly_sec: 90            # ước lượng thời gian TTS + ghép video
```

- [ ] **Step 6: Implement the config module**

Create empty `app/__init__.py`.

Create `app/config.py`:

```python
"""Settings: secrets from .env, everything else (models, prices, limits) from config.yaml."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# utf-8-sig also accepts plain UTF-8; it tolerates the BOM Notepad adds on Windows.
_USER_FILE_ENCODING = "utf-8-sig"


class ConfigError(Exception):
    """config.yaml or .env is missing, unreadable or has invalid values."""


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClaudeConfig(_Section):
    model: str
    max_tokens: int = 16000
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    refusal_fallback: bool = True
    price_usd_per_mtok_input: float | None = None
    price_usd_per_mtok_output: float | None = None


class VeoConfig(_Section):
    model: str
    resolution: str = "720p"
    generate_audio: bool = False
    price_usd_per_second: float | None = None
    max_concurrent: int = Field(default=3, ge=1)
    job_timeout_sec: int = 600
    poll_interval_sec: int = 10
    est_clip_generation_sec: int = 120


class LimitsConfig(_Section):
    cost_cap_per_job_usd: float = 5
    cost_cap_per_day_usd: float = 20
    max_regenerations_per_scene: int = Field(default=1, ge=0)


class DefaultsConfig(_Section):
    duration_sec: Literal[15, 30, 60] = 30
    aspect: Literal["9:16", "1:1", "16:9"] = "9:16"
    voice: str = "vi-female-north"
    style: str = "clean corporate office, soft daylight, muted blue palette"


class TTSConfig(_Section):
    price_usd_per_1k_chars: float | None = None


class AssemblerConfig(_Section):
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    output_width: int = 1080
    output_height: int = 1920
    subtitle_font: str = "Be Vietnam Pro"
    music_dir: str = "assets/music"
    logo_path: str = "assets/logo.png"
    est_assembly_sec: int = 90


class StorageConfig(_Section):
    data_dir: str = "data"


class AppConfig(_Section):
    claude: ClaudeConfig
    veo: VeoConfig
    # default_factory: each AppConfig gets its own section objects (they are mutable).
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    assembler: AssemblerConfig = Field(default_factory=AssemblerConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)


def _reveal(secret: SecretStr | None) -> str | None:
    value = secret.get_secret_value().strip() if secret else ""
    return value or None


class Secrets(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    anthropic_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    video_provider: Literal["fake", "veo"] = "fake"
    tts_provider: Literal["fake", "fpt", "google"] = "fake"
    fpt_tts_api_key: SecretStr | None = None

    def anthropic_key(self) -> str | None:
        return _reveal(self.anthropic_api_key)

    def gemini_key(self) -> str | None:
        return _reveal(self.gemini_api_key)


@dataclass(frozen=True)
class Settings:
    root: Path
    config: AppConfig
    secrets: Secrets

    @property
    def data_dir(self) -> Path:
        path = Path(self.config.storage.data_dir)
        return path if path.is_absolute() else self.root / path


def load_config(root: Path) -> AppConfig:
    path = root / "config.yaml"
    if not path.exists():
        path = root / "config.example.yaml"
    if not path.exists():
        raise ConfigError(f"Không tìm thấy config.yaml hoặc config.example.yaml trong {root}")
    try:
        raw = yaml.safe_load(path.read_text(encoding=_USER_FILE_ENCODING))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path.name} không phải YAML hợp lệ: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path.name} trống hoặc sai định dạng")
    try:
        return AppConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"{path.name} có giá trị không hợp lệ:\n{exc}") from exc


def load_settings(root: Path | None = None) -> Settings:
    root = root or PROJECT_ROOT
    try:
        secrets = Secrets(_env_file=root / ".env", _env_file_encoding=_USER_FILE_ENCODING)
    except ValidationError as exc:
        # Report field names only: the message must never echo a key value.
        fields = ", ".join(str(e["loc"][0]).upper() for e in exc.errors())
        raise ConfigError(f"File .env có giá trị không hợp lệ: {fields}") from exc
    return Settings(root=root, config=load_config(root), secrets=secrets)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_config.py -v`
Expected: 11 passed.

- [ ] **Step 8: Commit**

```powershell
git add pytest.ini requirements.txt config.example.yaml app tests
git commit -m "feat: project scaffold and typed config loading"
```

---

### Task 2: FFmpeg / ffprobe availability check

**Files:**
- Create: `app/assembler/__init__.py`, `app/assembler/ffmpeg.py`
- Test: `tests/test_ffmpeg_check.py`

**Interfaces:**
- Consumes: `app.config.AssemblerConfig` (fields `ffmpeg_path: str`, `ffprobe_path: str`).
- Produces (from `app.assembler.ffmpeg`):
  - `class FFmpegNotFoundError(Exception)` — message is Vietnamese and names the config key to fix.
  - `check_binaries(cfg: AssemblerConfig) -> dict[str, str]` — returns `{"ffmpeg": <first version line>, "ffprobe": <first version line>}` or raises `FFmpegNotFoundError`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ffmpeg_check.py`:

```python
import shutil
import subprocess

import pytest

from app.assembler import ffmpeg
from app.assembler.ffmpeg import FFmpegNotFoundError, check_binaries
from app.config import AssemblerConfig


def test_missing_binary_names_the_config_key_to_fix():
    cfg = AssemblerConfig(ffmpeg_path="no-such-ffmpeg-binary-xyz")

    with pytest.raises(FFmpegNotFoundError, match="assembler.ffmpeg_path"):
        check_binaries(cfg)


def test_runs_each_binary_with_an_argument_list_and_no_shell(monkeypatch):
    seen = []

    def fake_run(cmd, **kwargs):
        seen.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, stdout="ffmpeg version 7.1\nbuilt with gcc\n", stderr="")

    monkeypatch.setattr(ffmpeg.subprocess, "run", fake_run)
    cfg = AssemblerConfig(ffmpeg_path="C:/tools/ffmpeg.exe", ffprobe_path="C:/tools/ffprobe.exe")

    versions = check_binaries(cfg)

    assert versions == {"ffmpeg": "ffmpeg version 7.1", "ffprobe": "ffmpeg version 7.1"}
    assert [cmd for cmd, _ in seen] == [
        ["C:/tools/ffmpeg.exe", "-version"],
        ["C:/tools/ffprobe.exe", "-version"],
    ]
    assert all(kwargs.get("shell", False) is False for _, kwargs in seen)


def test_non_zero_exit_is_reported_as_not_runnable(monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")

    monkeypatch.setattr(ffmpeg.subprocess, "run", fake_run)

    with pytest.raises(FFmpegNotFoundError, match="assembler.ffmpeg_path"):
        check_binaries(AssemblerConfig())


def test_hung_binary_is_reported_as_not_runnable(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(ffmpeg.subprocess, "run", fake_run)

    with pytest.raises(FFmpegNotFoundError):
        check_binaries(AssemblerConfig())


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg is not installed on this machine",
)
def test_real_binaries_report_their_version():
    versions = check_binaries(AssemblerConfig())

    assert versions["ffmpeg"].startswith("ffmpeg version")
    assert versions["ffprobe"].startswith("ffprobe version")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_ffmpeg_check.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'app.assembler'`.

- [ ] **Step 3: Implement**

Create empty `app/assembler/__init__.py`.

Create `app/assembler/ffmpeg.py`:

```python
"""FFmpeg helpers. Phase 0 only checks that the binaries run; assembly comes in Phase 4."""
from __future__ import annotations

import subprocess

from app.config import AssemblerConfig

_CHECK_TIMEOUT_SEC = 10


class FFmpegNotFoundError(Exception):
    """ffmpeg or ffprobe cannot be executed."""


def _version(binary: str, name: str) -> str:
    hint = (
        f"Không chạy được {name} tại '{binary}'. Hãy cài FFmpeg và thêm vào PATH, "
        f"hoặc sửa assembler.{name}_path trong config.yaml."
    )
    try:
        proc = subprocess.run(
            [binary, "-version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_CHECK_TIMEOUT_SEC,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FFmpegNotFoundError(hint) from exc
    if proc.returncode != 0 or not proc.stdout:
        raise FFmpegNotFoundError(hint)
    return proc.stdout.splitlines()[0].strip()


def check_binaries(cfg: AssemblerConfig) -> dict[str, str]:
    return {
        "ffmpeg": _version(cfg.ffmpeg_path, "ffmpeg"),
        "ffprobe": _version(cfg.ffprobe_path, "ffprobe"),
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_ffmpeg_check.py -v`
Expected: 5 passed (FFmpeg is installed on this machine; on a machine without it, 4 passed and 1 skipped).

- [ ] **Step 5: Commit**

```powershell
git add app/assembler tests/test_ffmpeg_check.py
git commit -m "feat: check that ffmpeg and ffprobe are runnable"
```

---

### Task 3: SQLite models

**Files:**
- Create: `app/models.py`, `app/db.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces (from `app.models`):
  - `JobStatus(str, Enum)`: `draft, planning, awaiting_approval, generating, assembling, done, failed, cancelled`.
  - `SceneStatus(str, Enum)`: `planned, generating, generated, qc_failed, regenerating, approved, failed`.
  - `Job` table: `id: str` (12 hex chars, auto), `idea: str`, `duration_sec: int`, `aspect: str`, `voice: str`, `style: str`, `cost_cap_usd: float`, `status: JobStatus = draft`, `plan_json: str | None`, `plan_version: int = 0`, `failed_step: str | None`, `error: str | None`, `created_at`, `updated_at`.
  - `Scene` table: `id: int | None`, `job_id: str`, `scene_no: int`, `status: SceneStatus = planned`, `attempts: int = 0`, `clip_path: str | None`, `error: str | None`.
  - `CostEntry` table: `id: int | None`, `job_id: str`, `kind: str` (`"claude" | "veo" | "tts"`), `detail: str = ""`, `units: float`, `unit: str` (`"tokens_in" | "tokens_out" | "seconds" | "chars"`), `usd: float`, `created_at`.
- Produces (from `app.db`): `make_engine(data_dir: Path) -> Engine` (creates `data_dir`, DB file is `data_dir / "app.db"`), `init_db(engine) -> None` (idempotent).
- Note: `app.models.Scene` (DB row: generation state of a scene) and `app.schemas.Scene` (Task 5, plan content) share a name, as `CLAUDE.md` prescribes. Always import them through their module (`from app import models, schemas`) when both are needed.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_models.py`:

```python
import pytest
from sqlalchemy import inspect
from sqlmodel import Session, select

from app.db import init_db, make_engine
from app.models import CostEntry, Job, JobStatus, Scene, SceneStatus


@pytest.fixture
def engine(tmp_path):
    engine = make_engine(tmp_path / "data")
    init_db(engine)
    yield engine
    engine.dispose()


def _job(**overrides):
    fields = dict(
        idea="5 việc sếp không biết bạn đang làm bằng AI",
        duration_sec=30,
        aspect="9:16",
        voice="vi-female-north",
        style="clean corporate office",
        cost_cap_usd=5.0,
    )
    return Job(**(fields | overrides))


def test_init_db_creates_the_file_and_all_tables(engine, tmp_path):
    assert (tmp_path / "data" / "app.db").exists()
    assert set(inspect(engine).get_table_names()) == {"job", "scene", "costentry"}


def test_job_defaults():
    first, second = _job(), _job()

    assert first.status == JobStatus.draft
    assert first.plan_json is None
    assert first.plan_version == 0
    assert len(first.id) == 12
    assert first.id != second.id


def test_job_scene_and_cost_round_trip_with_vietnamese_text(engine):
    job = _job()
    with Session(engine) as session:
        session.add(job)
        session.add(Scene(job_id=job.id, scene_no=1))
        session.add(CostEntry(job_id=job.id, kind="claude", units=1200, unit="tokens_in", usd=0.0024))
        session.commit()
        job_id = job.id

    with Session(engine) as session:
        stored = session.get(Job, job_id)
        scene = session.exec(select(Scene).where(Scene.job_id == job_id)).one()
        cost = session.exec(select(CostEntry).where(CostEntry.job_id == job_id)).one()

    assert stored.idea == "5 việc sếp không biết bạn đang làm bằng AI"
    assert stored.status == JobStatus.draft
    assert scene.status == SceneStatus.planned
    assert scene.attempts == 0
    assert scene.clip_path is None
    assert (cost.kind, cost.unit, cost.usd) == ("claude", "tokens_in", 0.0024)
    assert cost.created_at is not None


def test_init_db_twice_keeps_existing_rows(engine):
    with Session(engine) as session:
        session.add(_job())
        session.commit()

    init_db(engine)

    with Session(engine) as session:
        assert len(session.exec(select(Job)).all()) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_models.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'app.db'`.

- [ ] **Step 3: Implement**

Create `app/models.py`:

```python
"""SQLModel tables: Job, Scene (generation state), CostEntry."""
# No `from __future__ import annotations` here: SQLModel reads the real annotation types.
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _job_id() -> str:
    return uuid4().hex[:12]


class JobStatus(str, Enum):
    draft = "draft"
    planning = "planning"
    awaiting_approval = "awaiting_approval"
    generating = "generating"
    assembling = "assembling"
    done = "done"
    failed = "failed"
    cancelled = "cancelled"


class SceneStatus(str, Enum):
    planned = "planned"
    generating = "generating"
    generated = "generated"
    qc_failed = "qc_failed"
    regenerating = "regenerating"
    approved = "approved"
    failed = "failed"


class Job(SQLModel, table=True):
    id: str = Field(default_factory=_job_id, primary_key=True)
    idea: str
    duration_sec: int
    aspect: str
    voice: str
    style: str
    cost_cap_usd: float
    status: JobStatus = JobStatus.draft
    plan_json: str | None = None
    plan_version: int = 0
    failed_step: str | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class Scene(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    job_id: str = Field(foreign_key="job.id", index=True)
    scene_no: int
    status: SceneStatus = SceneStatus.planned
    attempts: int = 0
    clip_path: str | None = None
    error: str | None = None


class CostEntry(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    job_id: str = Field(foreign_key="job.id", index=True)
    kind: str  # "claude" | "veo" | "tts"
    detail: str = ""
    units: float
    unit: str  # "tokens_in" | "tokens_out" | "seconds" | "chars"
    usd: float
    created_at: datetime = Field(default_factory=_now)
```

Create `app/db.py`:

```python
"""SQLite engine and table creation."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import SQLModel, create_engine

from app import models  # noqa: F401  (importing registers the tables on SQLModel.metadata)


def make_engine(data_dir: Path) -> Engine:
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "app.db"
    return create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )


def init_db(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_models.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```powershell
git add app/models.py app/db.py tests/test_models.py
git commit -m "feat: SQLModel tables for jobs, scenes and cost entries"
```

---

### Task 4: FastAPI app with an empty Vietnamese page (ends Giai đoạn 0)

**Files:**
- Create: `app/main.py`, `app/templates/base.html`, `app/templates/index.html`, `app/static/app.css`
- Modify: `TASKS.md` (tick Giai đoạn 0)
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `app.config.Settings`, `load_settings()`; `app.db.make_engine(data_dir)`, `init_db(engine)`; `app.assembler.ffmpeg.check_binaries(cfg)`, `FFmpegNotFoundError`; fixture `settings`.
- Produces (from `app.main`):
  - `create_app(settings: Settings | None = None) -> FastAPI`. On startup it sets `app.state.settings`, `app.state.engine`, `app.state.ffmpeg_error: str | None`.
  - `app` — module-level instance for `uvicorn app.main:app`.
  - `templates` — the shared `Jinja2Templates` instance (Phase 2 reuses it).
  - `GET /` → HTML page. `GET /static/...` → static files.
- Behaviour: a missing FFmpeg does **not** stop the app (Phases 1–2 do not need it); the page shows an orange warning banner instead.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_main.py`:

```python
from fastapi.testclient import TestClient

import app.main as main
from app.main import create_app


def test_index_is_a_vietnamese_html_page(settings):
    with TestClient(create_app(settings)) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert '<html lang="vi">' in response.text
    assert "AI Văn Phòng · Video Agent" in response.text


def test_startup_creates_the_sqlite_database(settings):
    with TestClient(create_app(settings)):
        assert (settings.data_dir / "app.db").exists()


def test_static_css_is_served(settings):
    with TestClient(create_app(settings)) as client:
        response = client.get("/static/app.css")

    assert response.status_code == 200
    assert "#F4F2EC" in response.text


def test_missing_ffmpeg_shows_a_banner_but_the_app_still_starts(settings):
    settings.config.assembler.ffmpeg_path = "no-such-ffmpeg-binary-xyz"

    with TestClient(create_app(settings)) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert 'class="banner-warn"' in response.text
    assert "Không chạy được ffmpeg" in response.text


def test_no_banner_when_ffmpeg_is_available(settings, monkeypatch):
    monkeypatch.setattr(main, "check_binaries", lambda cfg: {"ffmpeg": "x", "ffprobe": "x"})

    with TestClient(create_app(settings)) as client:
        response = client.get("/")

    assert 'class="banner-warn"' not in response.text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_main.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'app.main'`.

- [ ] **Step 3: Create the template and stylesheet**

Create `app/static/app.css`:

```css
:root {
  --bg: #F4F2EC;
  --surface: #FFFFFF;
  --border: #DAD6CC;
  --text: #17181C;
  --text-muted: #5B5E66;
  --accent: #1D4ED8;
  --accent-soft: #E3EAFB;
  --warn: #C2410C;
  --warn-soft: #FDF0E1;
  --warn-text: #9A3412;
  --font-ui: 'Be Vietnam Pro', system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', ui-monospace, monospace;
}

body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-ui);
}

.site-header {
  height: 72px;
  box-sizing: border-box;
  padding: 0 40px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  font-weight: 600;
  font-size: 16px;
}

.brand-logo {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: var(--text);
  color: var(--surface);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 13px;
}

.header-meta {
  font-size: 13px;
  color: var(--text-muted);
}

.banner-warn {
  margin: 16px 40px 0;
  padding: 12px 16px;
  border-radius: 12px;
  background: var(--warn-soft);
  color: var(--warn-text);
  border: 1px solid var(--warn);
  font-size: 14px;
}

main {
  padding: 40px;
}
```

Create `app/templates/base.html`:

```html
<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{% block title %}AI Văn Phòng · Video Agent{% endblock %}</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700&family=JetBrains+Mono:wght@400&display=swap">
<link rel="stylesheet" href="{{ url_for('static', path='app.css') }}">
</head>
<body>
<header class="site-header">
  <div class="brand"><span class="brand-logo">AV</span>AI Văn Phòng · Video Agent</div>
  <div class="header-meta">Veo 3.1 · Gemini API</div>
</header>
{% if ffmpeg_error %}<div class="banner-warn" role="alert">{{ ffmpeg_error }}</div>{% endif %}
<main>{% block content %}{% endblock %}</main>
</body>
</html>
```

Create `app/templates/index.html`:

```html
{% extends "base.html" %}
{% block content %}{% endblock %}
```

- [ ] **Step 4: Implement the app**

Create `app/main.py`:

```python
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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_main.py -v`
Expected: 5 passed.

- [ ] **Step 6: Run the whole suite and start the server once**

Run: `.venv\Scripts\python -m pytest`
Expected: 25 passed.

Run: `.venv\Scripts\python -m uvicorn app.main:app --port 8000`, open `http://127.0.0.1:8000/`.
Expected: a cream page with the white header "AV  AI Văn Phòng · Video Agent" and no orange banner. Stop the server with Ctrl+C. (`data/app.db` now exists; `data/` is git-ignored.)

- [ ] **Step 7: Tick Giai đoạn 0 in `TASKS.md` and commit**

In `TASKS.md`, change the four `- [ ]` items under `## Giai đoạn 0 — Khung dự án` to `- [x]`.

```powershell
git add app/main.py app/templates app/static tests/test_main.py TASKS.md
git commit -m "feat: FastAPI app with startup checks and empty index page"
```

**Checkpoint — Giai đoạn 0 is complete.** `CLAUDE.md` rule 1: report to the user (what was built, test count) before starting Task 5.

---

### Task 5: Plan schemas (Pydantic mirror of `docs/plan.schema.json`)

**Files:**
- Create: `app/schemas.py`, `tests/fixtures/plan_30s.json`
- Modify: `tests/conftest.py` (add the `plan_dict` fixture)
- Test: `tests/test_schemas.py`

**Interfaces:**
- Consumes: `app.config.PROJECT_ROOT`.
- Produces (from `app.schemas`):
  - `Target(duration_sec: Literal[15, 30, 60], aspect: Literal["9:16", "1:1", "16:9"], platform: str = "facebook_reels")`
  - `Brief(audience: str, key_message: str, hook: str, cta: str)`
  - `Scene(id: int >= 1, duration_sec: Literal[4, 6, 8], voiceover_vi: str, subtitle_vi: str, visual: str, camera: str, veo_prompt_en: str <= 1000 chars)`
  - `Plan(idea: str >= 3 chars, target: Target, brief: Brief, style_guide: str, scenes: list[Scene] (2..12), caption_vi: str, music_mood: str | None = None)` with method `to_dict() -> dict` (JSON-ready, omits `music_mood` when it is `None`, so the output always validates against the JSON schema).
  - `PLAN_SCHEMA_PATH: Path`, `load_plan_json_schema() -> dict`.
  - All models forbid unknown fields, and integers are not coerced from strings (`"6"` is rejected), so Pydantic accepts exactly what the JSON schema accepts.
- Produces (fixture): `plan_dict` — a fresh `dict` loaded from `tests/fixtures/plan_30s.json`; a valid 30-second, 5-scene plan with 83 voiceover words. Tests mutate their own copy.

- [ ] **Step 1: Create the fixture plan**

Create `tests/fixtures/plan_30s.json` (UTF-8). The voiceover word counts are 17, 16, 16, 17, 17 — later tasks depend on these exact sentences:

```json
{
  "idea": "5 việc sếp không biết bạn đang làm bằng AI",
  "target": { "duration_sec": 30, "aspect": "9:16", "platform": "facebook_reels" },
  "brief": {
    "audience": "Dân văn phòng 25–40 tuổi muốn làm việc nhanh hơn nhờ AI",
    "key_message": "AI giúp bạn xử lý việc lặp lại trong vài giây",
    "hook": "Sếp không hề biết bạn đang dùng AI làm năm việc này.",
    "cta": "Theo dõi kênh để xem thêm mẹo AI"
  },
  "style_guide": "Clean corporate office, soft daylight, muted blue palette, smooth handheld camera, shallow depth of field.",
  "scenes": [
    {
      "id": 1,
      "duration_sec": 6,
      "voiceover_vi": "Sếp không hề biết bạn đang dùng AI làm năm việc này mỗi ngày ở công ty.",
      "subtitle_vi": "5 việc sếp không biết bạn làm bằng AI",
      "visual": "Nhân viên văn phòng mỉm cười trước laptop, sếp đi ngang phía sau",
      "camera": "Trung cảnh, đẩy máy chậm vào nhân vật",
      "veo_prompt_en": "Vertical shot of a young office worker smiling slightly at a laptop at a tidy desk while a manager walks past out of focus in the background, soft daylight from large windows, slow push-in, no on-screen text, no logos"
    },
    {
      "id": 2,
      "duration_sec": 6,
      "voiceover_vi": "Việc một: để AI tóm tắt email dài thành ba ý chính chỉ trong vài giây.",
      "subtitle_vi": "1. Tóm tắt email dài trong vài giây",
      "visual": "Cận cảnh bàn tay gõ phím, màn hình mờ phía sau",
      "camera": "Cận cảnh, lia nhẹ từ trái sang phải",
      "veo_prompt_en": "Vertical close-up of hands typing on a laptop keyboard, the screen softly out of focus, a coffee cup beside it, muted blue palette, gentle left-to-right pan, no on-screen text, no logos"
    },
    {
      "id": 3,
      "duration_sec": 6,
      "voiceover_vi": "Việc hai: nhờ AI viết nháp báo cáo tuần, bạn chỉ cần sửa lại số liệu.",
      "subtitle_vi": "2. Viết nháp báo cáo tuần",
      "visual": "Chồng giấy báo cáo trên bàn, người nhân viên thư thả uống cà phê",
      "camera": "Trung cảnh, máy tĩnh",
      "veo_prompt_en": "Vertical medium shot of a relaxed office worker sipping coffee next to a neat stack of printed reports, soft daylight, static camera, shallow depth of field, no on-screen text, no logos"
    },
    {
      "id": 4,
      "duration_sec": 6,
      "voiceover_vi": "Việc ba: biến ghi chú cuộc họp lộn xộn thành danh sách việc cần làm rõ ràng.",
      "subtitle_vi": "3. Biến ghi chú họp thành việc cần làm",
      "visual": "Sổ tay viết nguệch ngoạc cạnh laptop trong phòng họp",
      "camera": "Cận cảnh từ trên xuống, kéo máy ra chậm",
      "veo_prompt_en": "Vertical top-down close-up of a notebook with messy handwritten scribbles beside a laptop on a meeting room table, soft daylight, slow pull-back, no on-screen text, no logos"
    },
    {
      "id": 5,
      "duration_sec": 6,
      "voiceover_vi": "Còn hai việc nữa ở phần sau. Theo dõi kênh để không bỏ lỡ mẹo AI mới.",
      "subtitle_vi": "Theo dõi để xem 2 việc còn lại",
      "visual": "Nhân viên đóng laptop, đứng dậy rời bàn với vẻ hài lòng",
      "camera": "Toàn cảnh, máy lùi nhẹ",
      "veo_prompt_en": "Vertical wide shot of an office worker closing a laptop and standing up from the desk with a satisfied look, warm late-afternoon light, gentle dolly back, no on-screen text, no logos"
    }
  ],
  "caption_vi": "5 việc AI làm thay bạn mỗi ngày ở văn phòng. Bạn đã thử việc nào rồi?",
  "music_mood": "upbeat corporate"
}
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/conftest.py` (add `import json` to the imports at the top):

```python
@pytest.fixture
def plan_dict():
    path = PROJECT_ROOT / "tests" / "fixtures" / "plan_30s.json"
    return json.loads(path.read_text(encoding="utf-8"))
```

Create `tests/test_schemas.py`:

```python
import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from app.schemas import Plan, load_plan_json_schema

VALIDATOR = Draft202012Validator(load_plan_json_schema())


def _json_schema_errors(data):
    return list(VALIDATOR.iter_errors(data))


def test_fixture_is_valid_for_both_pydantic_and_the_json_schema(plan_dict):
    plan = Plan.model_validate(plan_dict)

    assert _json_schema_errors(plan_dict) == []
    assert len(plan.scenes) == 5
    assert plan.scenes[0].duration_sec == 6
    assert plan.brief.hook.startswith("Sếp không hề biết")


def test_to_dict_round_trips_the_fixture(plan_dict):
    assert Plan.model_validate(plan_dict).to_dict() == plan_dict


def test_optional_fields_are_omitted_or_defaulted(plan_dict):
    del plan_dict["music_mood"]
    del plan_dict["target"]["platform"]

    out = Plan.model_validate(plan_dict).to_dict()

    assert "music_mood" not in out
    assert out["target"]["platform"] == "facebook_reels"
    assert _json_schema_errors(out) == []


def _set(path, value):
    def mutate(data):
        target = data
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value

    return mutate


def _delete(path):
    def mutate(data):
        target = data
        for key in path[:-1]:
            target = target[key]
        del target[path[-1]]

    return mutate


def _keep_scenes(count):
    def mutate(data):
        scenes = data["scenes"]
        data["scenes"] = (scenes * 3)[:count]

    return mutate


INVALID = [
    ("scene_duration_5", _set(["scenes", 0, "duration_sec"], 5)),
    ("scene_duration_as_string", _set(["scenes", 0, "duration_sec"], "6")),
    ("target_duration_20", _set(["target", "duration_sec"], 20)),
    ("aspect_4_3", _set(["target", "aspect"], "4:3")),
    ("unknown_top_level_key", _set(["notes"], "x")),
    ("unknown_scene_key", _set(["scenes", 0, "notes"], "x")),
    ("missing_hook", _delete(["brief", "hook"])),
    ("missing_caption", _delete(["caption_vi"])),
    ("one_scene", _keep_scenes(1)),
    ("thirteen_scenes", _keep_scenes(13)),
    ("veo_prompt_1001_chars", _set(["scenes", 0, "veo_prompt_en"], "x" * 1001)),
    ("idea_two_chars", _set(["idea"], "ab")),
    ("scene_id_zero", _set(["scenes", 0, "id"], 0)),
    ("scene_id_as_string", _set(["scenes", 0, "id"], "1")),
]


@pytest.mark.parametrize("mutate", [m for _, m in INVALID], ids=[name for name, _ in INVALID])
def test_invalid_plans_are_rejected_by_both_pydantic_and_the_json_schema(plan_dict, mutate):
    mutate(plan_dict)

    assert _json_schema_errors(plan_dict), "docs/plan.schema.json accepts this; the test case is wrong"
    with pytest.raises(ValidationError):
        Plan.model_validate(plan_dict)


def test_veo_prompt_of_exactly_1000_chars_is_accepted(plan_dict):
    plan_dict["scenes"][0]["veo_prompt_en"] = "x" * 1000

    assert Plan.model_validate(plan_dict).scenes[0].veo_prompt_en == "x" * 1000
    assert _json_schema_errors(plan_dict) == []
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_schemas.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'app.schemas'`.

- [ ] **Step 4: Implement**

Create `app/schemas.py`:

```python
"""Pydantic models for the video plan. Must stay in sync with docs/plan.schema.json."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.config import PROJECT_ROOT

PLAN_SCHEMA_PATH: Path = PROJECT_ROOT / "docs" / "plan.schema.json"


def load_plan_json_schema() -> dict[str, Any]:
    return json.loads(PLAN_SCHEMA_PATH.read_text(encoding="utf-8"))


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Target(_Model):
    duration_sec: Literal[15, 30, 60]
    aspect: Literal["9:16", "1:1", "16:9"]
    platform: str = "facebook_reels"


class Brief(_Model):
    audience: str
    key_message: str
    hook: str
    cta: str


class Scene(_Model):
    # StrictInt: "1" must not be coerced to 1, matching the JSON schema. (Literal never coerces.)
    id: StrictInt = Field(ge=1)
    duration_sec: Literal[4, 6, 8]
    voiceover_vi: str
    subtitle_vi: str
    visual: str
    camera: str
    veo_prompt_en: str = Field(max_length=1000)


class Plan(_Model):
    idea: str = Field(min_length=3)
    target: Target
    brief: Brief
    style_guide: str
    scenes: list[Scene] = Field(min_length=2, max_length=12)
    caption_vi: str
    music_mood: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready dict that validates against docs/plan.schema.json."""
        return self.model_dump(mode="json", exclude_none=True)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_schemas.py -v`
Expected: 18 passed.

- [ ] **Step 6: Commit**

```powershell
git add app/schemas.py tests/conftest.py tests/test_schemas.py tests/fixtures
git commit -m "feat: Pydantic plan schemas mirroring plan.schema.json"
```

---

### Task 6: Plan business rules

**Files:**
- Create: `app/agent/__init__.py`, `app/agent/plan_rules.py`
- Test: `tests/test_plan_rules.py`

**Interfaces:**
- Consumes: `app.schemas.Plan`; fixture `plan_dict`.
- Produces (from `app.agent.plan_rules`):
  - `count_words(text: str) -> int` — whitespace-separated tokens that contain at least one letter or digit (Vietnamese syllables; this is what "từ" means for reading speed).
  - `word_bounds(seconds: int) -> tuple[int, int]` — inclusive `(min_words, max_words)` for a voiceover of that length: 2.5 words/s minus 10% up to 3 words/s plus 10%.
  - `validate_plan(plan: Plan, *, duration_sec: int, aspect: str) -> list[str]` — empty list means valid. Messages are English (they are sent back to Claude) and each starts with the thing that is wrong (`"target.duration_sec ..."`, `"scene ids ..."`, `"total scene duration ..."`, `"total voiceover ..."`, `"brief.hook ..."`, `"scene 2: voiceover_vi ..."`, `"scene 2: subtitle_vi ..."`, `"scene 2: veo_prompt_en ..."`).
- Rules (from FR-03, FR-04, FR-05 and `prompts/planner_system.md`):
  1. `plan.target` equals the requested duration and aspect.
  2. Scene ids are exactly `1..n` in order.
  3. Sum of scene durations is within ±2 s of the requested duration.
  4. Total voiceover words are within `word_bounds(sum of scene durations)`.
  5. Each scene's voiceover is non-empty and at most `word_bounds(scene.duration_sec)[1]` words (so the audio fits its clip).
  6. Each `subtitle_vi` is at most 12 words.
  7. Each `veo_prompt_en` contains `no on-screen text` (case-insensitive).
  8. The four brief fields are not blank.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_plan_rules.py`:

```python
import pytest

from app.agent.plan_rules import count_words, validate_plan, word_bounds
from app.schemas import Plan


def _errors(plan_dict, duration_sec=30, aspect="9:16"):
    return validate_plan(Plan.model_validate(plan_dict), duration_sec=duration_sec, aspect=aspect)


def _has(errors, prefix):
    return any(error.startswith(prefix) for error in errors)


def _words(count):
    return " ".join(["từ"] * count)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Sếp không biết", 3),
        ("  nhiều   khoảng\ntrắng\t", 3),
        ("AI – trợ lý", 3),
        ("5 việc: một, hai!", 4),
        ("...", 0),
        ("", 0),
    ],
)
def test_count_words(text, expected):
    assert count_words(text) == expected


@pytest.mark.parametrize(
    "seconds, expected",
    [(4, (9, 13)), (6, (14, 19)), (8, (18, 26)), (16, (36, 52)), (30, (68, 99))],
)
def test_word_bounds(seconds, expected):
    assert word_bounds(seconds) == expected


def test_fixture_plan_is_valid(plan_dict):
    assert _errors(plan_dict) == []


def test_total_duration_two_seconds_over_is_still_valid(plan_dict):
    plan_dict["scenes"][0]["duration_sec"] = 8

    assert _errors(plan_dict) == []


def test_total_duration_far_from_target_is_reported(plan_dict):
    for scene in plan_dict["scenes"]:
        scene["duration_sec"] = 4

    assert _has(_errors(plan_dict), "total scene duration")


def test_target_must_match_the_request(plan_dict):
    errors = _errors(plan_dict, duration_sec=60, aspect="1:1")

    assert _has(errors, "target.duration_sec")
    assert _has(errors, "target.aspect")


def test_too_few_voiceover_words_is_reported(plan_dict):
    for scene in plan_dict["scenes"]:
        scene["voiceover_vi"] = "Xin chào các bạn."

    assert _has(_errors(plan_dict), "total voiceover")


def test_one_overlong_scene_is_reported_even_when_the_total_is_fine(plan_dict):
    plan_dict["scenes"][0]["voiceover_vi"] = _words(20)  # was 17
    plan_dict["scenes"][1]["voiceover_vi"] = _words(13)  # was 16; total stays 83

    errors = _errors(plan_dict)

    assert errors == ["scene 1: voiceover_vi has 20 words, at most 19 fit a 6s scene"]


def test_empty_scene_voiceover_is_reported(plan_dict):
    plan_dict["scenes"][2]["voiceover_vi"] = "   "
    plan_dict["scenes"][0]["voiceover_vi"] = _words(19)
    plan_dict["scenes"][1]["voiceover_vi"] = _words(19)

    assert _has(_errors(plan_dict), "scene 3: voiceover_vi must not be empty")


def test_duplicate_scene_ids_are_reported(plan_dict):
    plan_dict["scenes"][1]["id"] = 1

    assert _has(_errors(plan_dict), "scene ids")


def test_out_of_order_scene_ids_are_reported(plan_dict):
    plan_dict["scenes"].reverse()

    assert _has(_errors(plan_dict), "scene ids")


def test_long_subtitle_is_reported(plan_dict):
    plan_dict["scenes"][3]["subtitle_vi"] = _words(13)

    assert _errors(plan_dict) == ["scene 4: subtitle_vi has 13 words, at most 12 allowed"]


def test_veo_prompt_without_the_no_text_marker_is_reported(plan_dict):
    plan_dict["scenes"][4]["veo_prompt_en"] = "Vertical wide shot of an office at dusk"

    assert _has(_errors(plan_dict), "scene 5: veo_prompt_en")


def test_no_text_marker_is_case_insensitive(plan_dict):
    plan_dict["scenes"][4]["veo_prompt_en"] = "Office at dusk. No On-Screen Text, no logos"

    assert _errors(plan_dict) == []


def test_blank_brief_field_is_reported(plan_dict):
    plan_dict["brief"]["hook"] = "  "

    assert _errors(plan_dict) == ["brief.hook must not be empty"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_plan_rules.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'app.agent'`.

- [ ] **Step 3: Implement**

Create empty `app/agent/__init__.py`.

Create `app/agent/plan_rules.py`:

```python
"""Business rules a plan must satisfy beyond its JSON structure (FR-03, FR-04, FR-05)."""
from __future__ import annotations

from app.schemas import Plan

# Reading speed is 2.5-3 words/second with 10% tolerance. Kept as integers per 100 seconds
# so the bounds are exact (2.5 * 0.9 = 2.25, 3.0 * 1.1 = 3.30) with no float rounding.
_MIN_WORDS_PER_100_SEC = 225
_MAX_WORDS_PER_100_SEC = 330
DURATION_TOLERANCE_SEC = 2
SUBTITLE_MAX_WORDS = 12
NO_TEXT_MARKER = "no on-screen text"


def count_words(text: str) -> int:
    return sum(1 for token in text.split() if any(ch.isalnum() for ch in token))


def word_bounds(seconds: int) -> tuple[int, int]:
    low = -(-seconds * _MIN_WORDS_PER_100_SEC // 100)  # ceiling division
    high = seconds * _MAX_WORDS_PER_100_SEC // 100
    return low, high


def validate_plan(plan: Plan, *, duration_sec: int, aspect: str) -> list[str]:
    errors: list[str] = []

    if plan.target.duration_sec != duration_sec:
        errors.append(f"target.duration_sec must be {duration_sec}, got {plan.target.duration_sec}")
    if plan.target.aspect != aspect:
        errors.append(f"target.aspect must be {aspect}, got {plan.target.aspect}")

    ids = [scene.id for scene in plan.scenes]
    if ids != list(range(1, len(ids) + 1)):
        errors.append(f"scene ids must be 1..{len(ids)} in order, got {ids}")

    total_sec = sum(scene.duration_sec for scene in plan.scenes)
    if abs(total_sec - duration_sec) > DURATION_TOLERANCE_SEC:
        errors.append(
            f"total scene duration is {total_sec}s, must be within "
            f"{DURATION_TOLERANCE_SEC}s of {duration_sec}s"
        )

    low, high = word_bounds(total_sec)
    total_words = sum(count_words(scene.voiceover_vi) for scene in plan.scenes)
    if not low <= total_words <= high:
        errors.append(
            f"total voiceover is {total_words} words, must be {low}-{high} words "
            f"for {total_sec}s of scenes (2.5-3 words/second)"
        )

    for name in ("audience", "key_message", "hook", "cta"):
        if not getattr(plan.brief, name).strip():
            errors.append(f"brief.{name} must not be empty")

    for scene in plan.scenes:
        words = count_words(scene.voiceover_vi)
        scene_high = word_bounds(scene.duration_sec)[1]
        if words == 0:
            errors.append(f"scene {scene.id}: voiceover_vi must not be empty")
        elif words > scene_high:
            errors.append(
                f"scene {scene.id}: voiceover_vi has {words} words, "
                f"at most {scene_high} fit a {scene.duration_sec}s scene"
            )
        subtitle_words = count_words(scene.subtitle_vi)
        if subtitle_words > SUBTITLE_MAX_WORDS:
            errors.append(
                f"scene {scene.id}: subtitle_vi has {subtitle_words} words, "
                f"at most {SUBTITLE_MAX_WORDS} allowed"
            )
        if NO_TEXT_MARKER not in scene.veo_prompt_en.lower():
            errors.append(
                f"scene {scene.id}: veo_prompt_en must end with 'no on-screen text, no logos'"
            )

    return errors
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_plan_rules.py -v`
Expected: 24 passed.

If `test_fixture_plan_is_valid` fails with a word-count error, the fixture JSON was mistyped: fix `tests/fixtures/plan_30s.json` to match Task 5 Step 1 exactly — do not loosen the rules.

- [ ] **Step 5: Commit**

```powershell
git add app/agent tests/test_plan_rules.py
git commit -m "feat: plan business rules (durations, word counts, scene ids)"
```

---

### Task 7: Planner — `create_plan` with validation feedback loop

**Files:**
- Create: `app/agent/planner.py`
- Test: `tests/test_planner.py`

**Interfaces:**
- Consumes: `app.config.ClaudeConfig`, `Settings`, `PROJECT_ROOT`; `app.schemas.Plan`, `load_plan_json_schema()`; `app.agent.plan_rules.validate_plan(plan, *, duration_sec, aspect) -> list[str]`; fixtures `plan_dict`, `settings`.
- Produces (from `app.agent.planner`):
  - `TOOL_NAME = "submit_plan"`, `MAX_FIX_ATTEMPTS = 2`.
  - `strict_tool_schema(schema: dict) -> dict` — copy of a JSON schema without the keywords strict tool use rejects.
  - `build_tool() -> dict` — the `submit_plan` tool definition (`strict: True`).
  - `PlanOptions(duration_sec: int, aspect: str, voice: str, style: str)` — frozen dataclass.
  - `PlannerResult(plan: Plan, model: str, calls: int, input_tokens: int, output_tokens: int)` — frozen dataclass; token counts are summed over all calls so Phase 2 can write `CostEntry` rows.
  - `PlannerError(Exception)` with attributes `input_tokens: int`, `output_tokens: int` (tokens already spent); message is Vietnamese. `PlannerRefusedError(PlannerError)`.
  - `class Planner: __init__(self, client, config: ClaudeConfig, system_prompt: str)`; `async create_plan(self, idea: str, options: PlanOptions) -> PlannerResult`.
  - `build_planner(settings: Settings) -> Planner` — real `AsyncAnthropic` client; raises `PlannerError` when `ANTHROPIC_API_KEY` is missing.
- Errors that are **not** wrapped: `ValueError` for a blank idea (caller bug); `anthropic.APIError` subclasses (auth, rate limit, network — the SDK already retries 429/5xx twice). Phase 2's API layer turns those into a failed job.
- Flow of one planner run: send the request → if `stop_reason` is `refusal` or `max_tokens`, raise → if there is no `tool_use` block, append the assistant turn and a user reminder, retry → validate the tool input (Pydantic, then `validate_plan`) → if invalid, append the assistant turn and a `tool_result` with `is_error: True` listing the errors, retry. At most `1 + MAX_FIX_ATTEMPTS` = 3 calls.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_planner.py`:

```python
import copy
from types import SimpleNamespace as NS

import pytest

from app.agent.planner import (
    PlanOptions,
    Planner,
    PlannerError,
    PlannerRefusedError,
    build_planner,
    build_tool,
    strict_tool_schema,
)
from app.config import ClaudeConfig, load_settings
from app.schemas import load_plan_json_schema

OPTIONS = PlanOptions(duration_sec=30, aspect="9:16", voice="vi-female-north", style="clean corporate office")
IDEA = "5 việc sếp không biết bạn đang làm bằng AI"


def tool_use(plan, block_id="toolu_1"):
    return NS(type="tool_use", id=block_id, name="submit_plan", input=plan)


def text(value):
    return NS(type="text", text=value)


def reply(*blocks, stop_reason="tool_use", input_tokens=100, output_tokens=200):
    return NS(
        content=list(blocks),
        stop_reason=stop_reason,
        usage=NS(input_tokens=input_tokens, output_tokens=output_tokens),
        model="claude-sonnet-5-5",
    )


class FakeClient:
    """Stands in for AsyncAnthropic: returns queued replies and records every request."""

    def __init__(self, *replies):
        self._replies = list(replies)
        self.calls = []  # (endpoint, kwargs) with a snapshot of `messages`
        self.messages = NS(create=self._endpoint("messages"))
        self.beta = NS(messages=NS(create=self._endpoint("beta.messages")))

    def _endpoint(self, name):
        async def create(**kwargs):
            self.calls.append((name, {**kwargs, "messages": list(kwargs["messages"])}))
            return self._replies.pop(0)

        return create


def make_planner(client, **config_overrides):
    config = ClaudeConfig(**({"model": "claude-sonnet-5-5", "refusal_fallback": False} | config_overrides))
    return Planner(client, config, "SYSTEM PROMPT")


def short_voiceovers(plan_dict):
    bad = copy.deepcopy(plan_dict)
    for scene in bad["scenes"]:
        scene["voiceover_vi"] = "Xin chào các bạn."
    return bad


# --- tool schema -----------------------------------------------------------------

UNSUPPORTED = {"$schema", "title", "default", "minLength", "maxLength", "minimum", "maximum", "minItems", "maxItems"}


def _keywords(schema):
    """All JSON Schema keywords used anywhere in the schema (property names excluded)."""
    found = set()
    for key, value in schema.items():
        found.add(key)
        if key == "properties":
            for sub in value.values():
                found |= _keywords(sub)
        elif isinstance(value, dict):
            found |= _keywords(value)
    return found


def test_strict_schema_drops_unsupported_keywords_and_keeps_the_rest():
    original = load_plan_json_schema()
    strict = strict_tool_schema(original)

    assert _keywords(strict).isdisjoint(UNSUPPORTED)
    assert strict["additionalProperties"] is False
    assert strict["required"] == original["required"]
    assert set(strict["properties"]) == set(original["properties"])
    scene = strict["properties"]["scenes"]["items"]
    assert scene["additionalProperties"] is False
    assert scene["properties"]["duration_sec"] == {"type": "integer", "enum": [4, 6, 8]}
    assert scene["properties"]["veo_prompt_en"] == {"type": "string"}
    assert "minLength" in original["properties"]["idea"]  # the file on disk is not modified


def test_strict_schema_keeps_properties_that_are_named_like_keywords():
    schema = {"type": "object", "title": "T", "properties": {"title": {"type": "string", "minLength": 1}}}

    assert strict_tool_schema(schema) == {"type": "object", "properties": {"title": {"type": "string"}}}


def test_tool_definition_is_strict():
    tool = build_tool()

    assert tool["name"] == "submit_plan"
    assert tool["strict"] is True
    assert tool["input_schema"]["type"] == "object"


# --- create_plan -----------------------------------------------------------------


async def test_create_plan_returns_the_validated_plan(plan_dict):
    client = FakeClient(reply(tool_use(plan_dict)))

    result = await make_planner(client).create_plan(IDEA, OPTIONS)

    assert result.plan.to_dict() == plan_dict
    assert (result.calls, result.input_tokens, result.output_tokens) == (1, 100, 200)
    assert result.model == "claude-sonnet-5-5"


async def test_request_follows_the_claude_api_constraints(plan_dict):
    client = FakeClient(reply(tool_use(plan_dict)))

    await make_planner(client).create_plan(IDEA, OPTIONS)

    endpoint, request = client.calls[0]
    assert endpoint == "messages"
    assert request["model"] == "claude-sonnet-5-5"
    assert request["max_tokens"] == 16000
    assert request["system"] == "SYSTEM PROMPT"
    assert request["output_config"] == {"effort": "medium"}
    assert request["tool_choice"] == {"type": "auto", "disable_parallel_tool_use": True}
    assert [tool["name"] for tool in request["tools"]] == ["submit_plan"]
    assert request["tools"][0]["strict"] is True
    assert not {"thinking", "temperature", "top_p", "top_k", "fallbacks", "betas"} & set(request)
    prompt = request["messages"][0]["content"]
    assert request["messages"][0]["role"] == "user"
    assert IDEA in prompt and "30 giây" in prompt and "9:16" in prompt
    assert "clean corporate office" in prompt and "submit_plan" in prompt


async def test_invalid_plan_is_sent_back_to_claude_and_the_fix_is_accepted(plan_dict):
    first = reply(tool_use(short_voiceovers(plan_dict), "toolu_bad"))
    client = FakeClient(first, reply(tool_use(plan_dict, "toolu_ok")))

    result = await make_planner(client).create_plan(IDEA, OPTIONS)

    assert result.plan.to_dict() == plan_dict
    assert (result.calls, result.input_tokens, result.output_tokens) == (2, 200, 400)
    messages = client.calls[1][1]["messages"]
    assert len(messages) == 3
    assert messages[1] == {"role": "assistant", "content": first.content}
    assert messages[2]["role"] == "user"
    (tool_result,) = messages[2]["content"]
    assert tool_result["type"] == "tool_result"
    assert tool_result["tool_use_id"] == "toolu_bad"
    assert tool_result["is_error"] is True
    assert "total voiceover is 20 words" in tool_result["content"]


async def test_structural_errors_are_reported_with_the_field_path(plan_dict):
    bad = copy.deepcopy(plan_dict)
    bad["scenes"][0]["duration_sec"] = 5
    client = FakeClient(reply(tool_use(bad)), reply(tool_use(plan_dict)))

    await make_planner(client).create_plan(IDEA, OPTIONS)

    tool_result = client.calls[1][1]["messages"][2]["content"][0]
    assert "scenes.0.duration_sec" in tool_result["content"]


async def test_gives_up_after_two_fix_attempts(plan_dict):
    bad = short_voiceovers(plan_dict)
    client = FakeClient(reply(tool_use(bad)), reply(tool_use(bad)), reply(tool_use(bad)))

    with pytest.raises(PlannerError, match="3 lần") as excinfo:
        await make_planner(client).create_plan(IDEA, OPTIONS)

    assert len(client.calls) == 3
    assert (excinfo.value.input_tokens, excinfo.value.output_tokens) == (300, 600)
    assert "total voiceover" in str(excinfo.value)


async def test_reply_without_a_tool_call_is_reprompted(plan_dict):
    chatty = reply(text("Đây là plan của tôi..."), stop_reason="end_turn")
    client = FakeClient(chatty, reply(tool_use(plan_dict)))

    result = await make_planner(client).create_plan(IDEA, OPTIONS)

    assert result.calls == 2
    messages = client.calls[1][1]["messages"]
    assert messages[1] == {"role": "assistant", "content": chatty.content}
    assert messages[2]["role"] == "user"
    assert "submit_plan" in messages[2]["content"]


async def test_refusal_raises_immediately(plan_dict):
    client = FakeClient(reply(stop_reason="refusal"), reply(tool_use(plan_dict)))

    with pytest.raises(PlannerRefusedError) as excinfo:
        await make_planner(client).create_plan(IDEA, OPTIONS)

    assert len(client.calls) == 1
    assert excinfo.value.input_tokens == 100


async def test_truncated_reply_is_never_accepted_as_a_plan(plan_dict):
    client = FakeClient(reply(tool_use(plan_dict), stop_reason="max_tokens"))

    with pytest.raises(PlannerError, match="max_tokens"):
        await make_planner(client).create_plan(IDEA, OPTIONS)

    assert len(client.calls) == 1


async def test_refusal_fallback_uses_the_beta_endpoint(plan_dict):
    client = FakeClient(reply(tool_use(plan_dict)))

    await make_planner(client, refusal_fallback=True).create_plan(IDEA, OPTIONS)

    endpoint, request = client.calls[0]
    assert endpoint == "beta.messages"
    assert request["betas"] == ["server-side-fallback-2026-07-01"]
    assert request["fallbacks"] == "default"


@pytest.mark.parametrize("idea", ["", "   ", "ab"])
async def test_blank_idea_is_rejected_before_any_api_call(idea):
    client = FakeClient()

    with pytest.raises(ValueError):
        await make_planner(client).create_plan(idea, OPTIONS)

    assert client.calls == []


def test_build_planner_requires_an_api_key(settings):
    with pytest.raises(PlannerError, match="ANTHROPIC_API_KEY"):
        build_planner(settings)


def test_build_planner_loads_the_system_prompt_file(project_root):
    (project_root / ".env").write_text("ANTHROPIC_API_KEY=sk-test\n", encoding="utf-8")

    planner = build_planner(load_settings(project_root))

    assert "submit_plan" in planner.system_prompt
    assert "AI Văn Phòng" in planner.system_prompt
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_planner.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'app.agent.planner'`.

- [ ] **Step 3: Implement**

Create `app/agent/planner.py`:

```python
"""Claude planner: idea -> validated Plan, through the strict `submit_plan` tool."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from anthropic import AsyncAnthropic
from pydantic import ValidationError

from app.agent.plan_rules import validate_plan
from app.config import PROJECT_ROOT, ClaudeConfig, Settings
from app.schemas import Plan, load_plan_json_schema

TOOL_NAME = "submit_plan"
MAX_FIX_ATTEMPTS = 2
SYSTEM_PROMPT_PATH = PROJECT_ROOT / "prompts" / "planner_system.md"
_FALLBACK_BETA = "server-side-fallback-2026-07-01"

# Strict tool use rejects these JSON Schema keywords. Pydantic (app.schemas) enforces
# the same constraints after the call, so nothing is lost by not sending them.
_UNSUPPORTED_KEYWORDS = frozenset(
    {"$schema", "title", "default", "minLength", "maxLength", "minimum", "maximum", "minItems", "maxItems"}
)


class PlannerError(Exception):
    """Planning failed. `input_tokens` / `output_tokens` are what was spent before failing."""

    def __init__(self, message: str, *, input_tokens: int = 0, output_tokens: int = 0) -> None:
        super().__init__(message)
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class PlannerRefusedError(PlannerError):
    """Claude declined the request (stop_reason == "refusal")."""


@dataclass(frozen=True)
class PlanOptions:
    duration_sec: int
    aspect: str
    voice: str
    style: str


@dataclass(frozen=True)
class PlannerResult:
    plan: Plan
    model: str
    calls: int
    input_tokens: int
    output_tokens: int


def strict_tool_schema(schema: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key in _UNSUPPORTED_KEYWORDS:
            continue
        if key == "properties":
            # Keys here are property names, not keywords: keep them all, clean their schemas.
            out[key] = {name: strict_tool_schema(sub) for name, sub in value.items()}
        elif isinstance(value, dict):
            out[key] = strict_tool_schema(value)
        else:
            out[key] = value
    return out


def build_tool() -> dict[str, Any]:
    return {
        "name": TOOL_NAME,
        "description": (
            "Submit the complete video production plan. Call exactly once per turn. "
            "Limits the schema cannot express: 2-12 scenes, scene ids 1..n in order, "
            "veo_prompt_en at most 1000 characters."
        ),
        "strict": True,
        "input_schema": strict_tool_schema(load_plan_json_schema()),
    }


class Planner:
    def __init__(self, client: Any, config: ClaudeConfig, system_prompt: str) -> None:
        self._client = client
        self._config = config
        self.system_prompt = system_prompt
        self._tool = build_tool()

    async def create_plan(self, idea: str, options: PlanOptions) -> PlannerResult:
        idea = idea.strip()
        if len(idea) < 3:
            raise ValueError("idea must be at least 3 characters")
        prompt = (
            f"<idea>{idea}</idea>\n"
            f"Thời lượng mục tiêu: {options.duration_sec} giây\n"
            f"Tỉ lệ khung hình: {options.aspect}\n"
            f"Phong cách hình ảnh: {options.style}\n"
            f"Giọng đọc: {options.voice}\n\n"
            f"Lập plan cho ý tưởng trên rồi gọi tool {TOOL_NAME}."
        )
        return await self._run(prompt, duration_sec=options.duration_sec, aspect=options.aspect)

    async def _run(self, prompt: str, *, duration_sec: int, aspect: str) -> PlannerResult:
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        calls = input_tokens = output_tokens = 0
        errors: list[str] = []

        for _ in range(1 + MAX_FIX_ATTEMPTS):
            response = await self._call(messages)
            calls += 1
            input_tokens += response.usage.input_tokens
            output_tokens += response.usage.output_tokens
            spent = {"input_tokens": input_tokens, "output_tokens": output_tokens}

            if response.stop_reason == "refusal":
                raise PlannerRefusedError(
                    "Claude từ chối lập plan cho ý tưởng này. Hãy thử diễn đạt lại ý tưởng.", **spent
                )
            if response.stop_reason == "max_tokens":
                raise PlannerError(
                    "Plan bị cắt giữa chừng vì chạm claude.max_tokens. "
                    "Hãy tăng giá trị này trong config.yaml.",
                    **spent,
                )

            tool_uses = [block for block in response.content if block.type == "tool_use"]
            # Pass the content back unchanged: it carries the model's thinking blocks.
            messages.append({"role": "assistant", "content": response.content})

            if not tool_uses:
                errors = [f"no {TOOL_NAME} tool call in the reply"]
                messages.append(
                    {
                        "role": "user",
                        "content": f"Bạn chưa gọi tool {TOOL_NAME}. Hãy gọi tool {TOOL_NAME} với plan đầy đủ.",
                    }
                )
                continue

            plan, errors = self._check(tool_uses[0].input, duration_sec, aspect)
            if plan is not None:
                return PlannerResult(
                    plan=plan,
                    model=response.model,
                    calls=calls,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
            feedback = (
                "Plan chưa hợp lệ. Sửa các lỗi sau rồi gọi lại tool, giữ nguyên các phần không liên quan:\n"
                + "\n".join(f"- {error}" for error in errors)
            )
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": block.id, "is_error": True, "content": feedback}
                        for block in tool_uses
                    ],
                }
            )

        raise PlannerError(
            f"Claude không tạo được plan hợp lệ sau {calls} lần thử: " + "; ".join(errors),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def _check(self, raw: Any, duration_sec: int, aspect: str) -> tuple[Plan | None, list[str]]:
        try:
            plan = Plan.model_validate(raw)
        except ValidationError as exc:
            return None, [
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors()
            ]
        errors = validate_plan(plan, duration_sec=duration_sec, aspect=aspect)
        return (None, errors) if errors else (plan, [])

    async def _call(self, messages: list[dict[str, Any]]) -> Any:
        request: dict[str, Any] = {
            "model": self._config.model,
            "max_tokens": self._config.max_tokens,
            "system": self.system_prompt,
            "tools": [self._tool],
            # Current Claude models reject forced tool choice; `auto` + strict schema + the
            # prompt instruction replaces it, and _run re-prompts when no call comes back.
            "tool_choice": {"type": "auto", "disable_parallel_tool_use": True},
            "output_config": {"effort": self._config.effort},
            "messages": messages,
        }
        if self._config.refusal_fallback:
            return await self._client.beta.messages.create(
                betas=[_FALLBACK_BETA], fallbacks="default", **request
            )
        return await self._client.messages.create(**request)


def build_planner(settings: Settings) -> Planner:
    api_key = settings.secrets.anthropic_key()
    if not api_key:
        raise PlannerError("Thiếu ANTHROPIC_API_KEY trong file .env.")
    return Planner(
        AsyncAnthropic(api_key=api_key),
        settings.config.claude,
        SYSTEM_PROMPT_PATH.read_text(encoding="utf-8"),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_planner.py -v`
Expected: 17 passed.

- [ ] **Step 5: Commit**

```powershell
git add app/agent/planner.py tests/test_planner.py
git commit -m "feat: Claude planner with strict tool use and validation feedback loop"
```

---

### Task 8: Planner — `revise` and `rewrite_scene`

**Files:**
- Modify: `app/agent/planner.py` (imports, new `PlanMergeError`, `Planner._run` signature, `Planner._check`, two new methods)
- Test: `tests/test_planner_revise.py`

**Interfaces:**
- Consumes: everything from Task 7 (`Planner`, `PlannerResult`, `PlannerError`, `TOOL_NAME`, `Planner._run(prompt, *, duration_sec, aspect)`, `Planner._check(raw, duration_sec, aspect)`).
- Produces (methods on `Planner`):
  - `async revise(self, plan: Plan, feedback: str) -> PlannerResult` — Claude rewrites the whole plan following the user's feedback. The plan's own `target` (duration, aspect) is what the result is validated against. Blank feedback → `ValueError`.
  - `async rewrite_scene(self, plan: Plan, scene_id: int, feedback: str = "") -> PlannerResult` — Claude rewrites one scene. The result is the **original plan with only that scene replaced**: whatever else Claude changed in its reply is discarded, so "rewrite scene 2" can never silently alter scene 4 or the brief. The merged plan is re-validated (a rewritten scene with too many words is sent back to Claude). Unknown `scene_id` → `ValueError`. `feedback` may be empty (the UI's "Viết lại" button) or carry a reason (Phase 3: QC failure, safety-filter block).
- Internal change: `_run` gains `finalize: Callable[[Plan], Plan] | None = None`, applied to a structurally valid plan before the business rules; it may raise `PlanMergeError(str)`, which is reported to Claude like any validation error.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_planner_revise.py`:

```python
import copy

import pytest

from app.schemas import Plan
from tests.test_planner import FakeClient, make_planner, reply, tool_use


def _words(count):
    return " ".join(["từ"] * count)


# --- revise ----------------------------------------------------------------------


async def test_revise_sends_the_current_plan_and_feedback_and_returns_the_new_plan(plan_dict):
    revised = copy.deepcopy(plan_dict)
    revised["brief"]["cta"] = "Lưu video để xem lại"
    client = FakeClient(reply(tool_use(revised)))
    plan = Plan.model_validate(plan_dict)

    result = await make_planner(client).revise(plan, "Đổi CTA thành lưu video")

    assert result.plan.brief.cta == "Lưu video để xem lại"
    prompt = client.calls[0][1]["messages"][0]["content"]
    assert "Đổi CTA thành lưu video" in prompt
    assert '"cta": "Theo dõi kênh để xem thêm mẹo AI"' in prompt  # current plan, readable Vietnamese
    assert "submit_plan" in prompt


async def test_revise_validates_against_the_plans_own_target(plan_dict):
    changed_target = copy.deepcopy(plan_dict)
    changed_target["target"]["duration_sec"] = 15
    client = FakeClient(reply(tool_use(changed_target)), reply(tool_use(plan_dict)))

    result = await make_planner(client).revise(Plan.model_validate(plan_dict), "Ngắn gọn hơn")

    assert result.calls == 2
    tool_result = client.calls[1][1]["messages"][2]["content"][0]
    assert "target.duration_sec must be 30" in tool_result["content"]


@pytest.mark.parametrize("feedback", ["", "   \n"])
async def test_revise_requires_feedback(plan_dict, feedback):
    client = FakeClient()

    with pytest.raises(ValueError):
        await make_planner(client).revise(Plan.model_validate(plan_dict), feedback)

    assert client.calls == []


# --- rewrite_scene ---------------------------------------------------------------


async def test_rewrite_scene_replaces_only_that_scene(plan_dict):
    original = Plan.model_validate(plan_dict)
    from_claude = copy.deepcopy(plan_dict)
    from_claude["scenes"][1]["voiceover_vi"] = _words(16)
    from_claude["scenes"][1]["veo_prompt_en"] = "Vertical shot of an inbox, no on-screen text, no logos"
    from_claude["scenes"][0]["voiceover_vi"] = _words(15)  # not asked for
    from_claude["brief"]["cta"] = "Changed without being asked"  # not asked for
    client = FakeClient(reply(tool_use(from_claude)))

    result = await make_planner(client).rewrite_scene(original, 2, "Cảnh này cần sinh động hơn")

    assert result.plan.scenes[1].voiceover_vi == _words(16)
    assert result.plan.scenes[1].veo_prompt_en.startswith("Vertical shot of an inbox")
    assert result.plan.scenes[0] == original.scenes[0]
    assert result.plan.scenes[2:] == original.scenes[2:]
    assert result.plan.brief == original.brief
    prompt = client.calls[0][1]["messages"][0]["content"]
    assert "cảnh 2" in prompt and "Cảnh này cần sinh động hơn" in prompt


async def test_rewrite_scene_works_without_feedback(plan_dict):
    client = FakeClient(reply(tool_use(plan_dict)))

    result = await make_planner(client).rewrite_scene(Plan.model_validate(plan_dict), 2)

    assert result.calls == 1
    assert "cảnh 2" in client.calls[0][1]["messages"][0]["content"]


async def test_rewrite_scene_revalidates_the_merged_plan(plan_dict):
    too_long = copy.deepcopy(plan_dict)
    too_long["scenes"][1]["voiceover_vi"] = _words(25)
    client = FakeClient(reply(tool_use(too_long)), reply(tool_use(plan_dict)))

    result = await make_planner(client).rewrite_scene(Plan.model_validate(plan_dict), 2, "Dài hơn")

    assert result.calls == 2
    tool_result = client.calls[1][1]["messages"][2]["content"][0]
    assert "scene 2: voiceover_vi has 25 words" in tool_result["content"]


async def test_rewrite_scene_reports_a_reply_that_dropped_the_scene(plan_dict):
    without_scene_5 = copy.deepcopy(plan_dict)
    without_scene_5["scenes"].pop()
    client = FakeClient(reply(tool_use(without_scene_5)), reply(tool_use(plan_dict)))

    result = await make_planner(client).rewrite_scene(Plan.model_validate(plan_dict), 5, "Kết mạnh hơn")

    assert result.calls == 2
    tool_result = client.calls[1][1]["messages"][2]["content"][0]
    assert "scene 5 is missing" in tool_result["content"]


async def test_rewrite_scene_rejects_an_unknown_scene_before_any_api_call(plan_dict):
    client = FakeClient()

    with pytest.raises(ValueError, match="scene 9"):
        await make_planner(client).rewrite_scene(Plan.model_validate(plan_dict), 9, "x")

    assert client.calls == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_planner_revise.py -v`
Expected: 9 failed with `AttributeError: 'Planner' object has no attribute 'revise'` / `'rewrite_scene'`.

- [ ] **Step 3: Implement**

All edits are in `app/agent/planner.py`.

(a) Replace the import block at the top (adds `json` and `Callable`):

```python
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
```

(b) Add after the `PlannerRefusedError` class:

```python
class PlanMergeError(Exception):
    """A structurally valid reply could not be merged into the plan being edited."""
```

(c) Add two module-level helpers just above `class Planner`:

```python
def _plan_json(plan: Plan) -> str:
    return json.dumps(plan.to_dict(), ensure_ascii=False, indent=2)


def _keep_target_note(plan: Plan) -> str:
    return (
        f"Giữ nguyên thời lượng mục tiêu {plan.target.duration_sec} giây "
        f"và tỉ lệ {plan.target.aspect}."
    )
```

(d) In `Planner`, add these two methods after `create_plan`:

```python
    async def revise(self, plan: Plan, feedback: str) -> PlannerResult:
        feedback = feedback.strip()
        if not feedback:
            raise ValueError("feedback must not be empty")
        prompt = (
            f"Đây là plan hiện tại:\n<plan>\n{_plan_json(plan)}\n</plan>\n\n"
            f"Góp ý của người dùng:\n<feedback>{feedback}</feedback>\n\n"
            "Sửa plan theo góp ý, giữ nguyên những phần không bị nhắc đến. "
            f"{_keep_target_note(plan)} Sau đó gọi tool {TOOL_NAME} với plan đầy đủ."
        )
        return await self._run(prompt, duration_sec=plan.target.duration_sec, aspect=plan.target.aspect)

    async def rewrite_scene(self, plan: Plan, scene_id: int, feedback: str = "") -> PlannerResult:
        if scene_id not in {scene.id for scene in plan.scenes}:
            raise ValueError(f"scene {scene_id} is not in the plan")
        feedback = feedback.strip() or "Viết lại cảnh này theo một hướng khác, hay hơn."
        prompt = (
            f"Đây là plan hiện tại:\n<plan>\n{_plan_json(plan)}\n</plan>\n\n"
            f"Chỉ viết lại cảnh {scene_id}, giữ nguyên thời lượng của cảnh đó và mọi phần khác của plan.\n"
            f"Yêu cầu:\n<feedback>{feedback}</feedback>\n\n"
            f"Sau đó gọi tool {TOOL_NAME} với plan đầy đủ."
        )

        def keep_only_rewritten_scene(candidate: Plan) -> Plan:
            rewritten = next((scene for scene in candidate.scenes if scene.id == scene_id), None)
            if rewritten is None:
                raise PlanMergeError(f"scene {scene_id} is missing from the submitted plan")
            scenes = [rewritten if scene.id == scene_id else scene for scene in plan.scenes]
            return plan.model_copy(update={"scenes": scenes})

        return await self._run(
            prompt,
            duration_sec=plan.target.duration_sec,
            aspect=plan.target.aspect,
            finalize=keep_only_rewritten_scene,
        )
```

(e) Change the signature of `_run` to:

```python
    async def _run(
        self,
        prompt: str,
        *,
        duration_sec: int,
        aspect: str,
        finalize: Callable[[Plan], Plan] | None = None,
    ) -> PlannerResult:
```

and, inside `_run`, change the one line that calls `_check` to:

```python
            plan, errors = self._check(tool_uses[0].input, duration_sec, aspect, finalize)
```

(f) Replace the whole `_check` method with:

```python
    def _check(
        self,
        raw: Any,
        duration_sec: int,
        aspect: str,
        finalize: Callable[[Plan], Plan] | None = None,
    ) -> tuple[Plan | None, list[str]]:
        try:
            plan = Plan.model_validate(raw)
            if finalize is not None:
                plan = finalize(plan)
        except ValidationError as exc:
            return None, [
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors()
            ]
        except PlanMergeError as exc:
            return None, [str(exc)]
        errors = validate_plan(plan, duration_sec=duration_sec, aspect=aspect)
        return (None, errors) if errors else (plan, [])
```

- [ ] **Step 4: Run the planner tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_planner.py tests/test_planner_revise.py -v`
Expected: 26 passed (17 from Task 7 + 9 new).

- [ ] **Step 5: Commit**

```powershell
git add app/agent/planner.py tests/test_planner_revise.py
git commit -m "feat: planner revise and single-scene rewrite"
```

---

### Task 9: Estimator, manual smoke script (ends Giai đoạn 1)

**Files:**
- Create: `app/agent/estimator.py`, `scripts/try_planner.py`
- Modify: `TASKS.md` (tick Giai đoạn 1)
- Test: `tests/test_estimator.py`

**Interfaces:**
- Consumes: `app.config.AppConfig`, `ClaudeConfig`, `load_settings()`; `app.schemas.Plan`; `app.agent.planner.build_planner(settings)`, `PlanOptions`, `PlannerResult`; fixtures `plan_dict`, `settings`.
- Produces (from `app.agent.estimator`):
  - `class PriceNotConfiguredError(Exception)` — Vietnamese message naming the config key.
  - `Estimate` (Pydantic model): `total_video_sec: int`, `veo_calls: int` (one per scene), `veo_calls_max: int` (including allowed regenerations), `cost_usd: float` (expected: each scene generated once, plus TTS), `cost_usd_max: float` (every scene regenerated the allowed number of times), `minutes: float`, `cap_usd: float`, `over_cap: bool`.
  - `estimate(plan: Plan, config: AppConfig, *, video_provider: str, cap_usd: float | None = None) -> Estimate`.
  - `claude_cost_usd(input_tokens: int, output_tokens: int, config: ClaudeConfig) -> float`.
- Decisions:
  - `over_cap` compares the **expected** cost (`cost_usd`) with the cap — FR-06 says "USD dự kiến". The worst case is shown next to it (`cost_usd_max`); the hard stop during generation is the runner's job in Phase 3.
  - `cap_usd` defaults to `limits.cost_cap_per_job_usd`; a job passes its own cap (FR-01 lets the user set it per job).
  - `video_provider == "fake"` costs 0. With the real provider and `price_usd_per_second: null`, raise instead of reporting $0.
  - TTS cost is added only when `tts.price_usd_per_1k_chars` is set (the TTS service is still an open question in REQUIREMENTS §8).
  - Time: clips run in batches of `veo.max_concurrent`, each batch takes `veo.est_clip_generation_sec`, plus `assembler.est_assembly_sec`.
  - Costs are rounded to 4 decimals before comparing with the cap (`30 * 0.1` is `3.0000000000000004` in floats).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_estimator.py`:

```python
import pytest

from app.agent.estimator import PriceNotConfiguredError, claude_cost_usd, estimate
from app.config import ClaudeConfig
from app.schemas import Plan


@pytest.fixture
def plan(plan_dict):
    return Plan.model_validate(plan_dict)


def test_fake_provider_costs_nothing(plan, settings):
    result = estimate(plan, settings.config, video_provider="fake")

    assert result.total_video_sec == 30
    assert result.veo_calls == 5
    assert result.veo_calls_max == 10
    assert result.cost_usd == 0
    assert result.cost_usd_max == 0
    assert result.cap_usd == 5
    assert result.over_cap is False


def test_real_provider_cost_and_cap(plan, settings):
    settings.config.veo.price_usd_per_second = 0.4

    result = estimate(plan, settings.config, video_provider="veo")

    assert result.cost_usd == 12.0
    assert result.cost_usd_max == 24.0
    assert result.over_cap is True


def test_job_specific_cap_overrides_the_config_cap(plan, settings):
    settings.config.veo.price_usd_per_second = 0.4

    result = estimate(plan, settings.config, video_provider="veo", cap_usd=15)

    assert result.cap_usd == 15
    assert result.over_cap is False


def test_cost_exactly_at_the_cap_is_allowed(plan, settings):
    settings.config.veo.price_usd_per_second = 0.1  # 30 * 0.1 is 3.0000000000000004 as a float

    result = estimate(plan, settings.config, video_provider="veo", cap_usd=3.0)

    assert result.cost_usd == 3.0
    assert result.over_cap is False


def test_real_provider_without_a_price_refuses_to_estimate(plan, settings):
    assert settings.config.veo.price_usd_per_second is None

    with pytest.raises(PriceNotConfiguredError, match="veo.price_usd_per_second"):
        estimate(plan, settings.config, video_provider="veo")


def test_no_regenerations_means_max_equals_expected(plan, settings):
    settings.config.veo.price_usd_per_second = 0.4
    settings.config.limits.max_regenerations_per_scene = 0

    result = estimate(plan, settings.config, video_provider="veo")

    assert result.veo_calls_max == result.veo_calls == 5
    assert result.cost_usd_max == result.cost_usd == 12.0


def test_time_is_batches_of_concurrent_clips_plus_assembly(plan, settings):
    # 5 scenes, 3 at a time -> 2 batches * 120s + 90s assembly = 330s
    assert estimate(plan, settings.config, video_provider="fake").minutes == 5.5

    settings.config.veo.max_concurrent = 5
    assert estimate(plan, settings.config, video_provider="fake").minutes == 3.5


def test_tts_cost_is_added_when_a_price_is_configured(plan, settings):
    settings.config.tts.price_usd_per_1k_chars = 0.5
    chars = sum(len(scene.voiceover_vi) for scene in plan.scenes)

    result = estimate(plan, settings.config, video_provider="fake")

    assert result.cost_usd == round(chars / 1000 * 0.5, 4)
    assert result.cost_usd_max == result.cost_usd


def test_claude_cost_from_token_counts():
    config = ClaudeConfig(model="m", price_usd_per_mtok_input=2.0, price_usd_per_mtok_output=10.0)

    assert claude_cost_usd(1_000_000, 100_000, config) == 3.0
    assert claude_cost_usd(0, 0, config) == 0


def test_claude_cost_without_prices_is_an_error():
    with pytest.raises(PriceNotConfiguredError, match="claude.price_usd_per_mtok"):
        claude_cost_usd(1000, 1000, ClaudeConfig(model="m"))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_estimator.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'app.agent.estimator'`.

- [ ] **Step 3: Implement the estimator**

Create `app/agent/estimator.py`:

```python
"""Cost (USD) and time estimate for a plan, shown before the user approves it (FR-06)."""
from __future__ import annotations

import math

from pydantic import BaseModel

from app.config import AppConfig, ClaudeConfig
from app.schemas import Plan


class PriceNotConfiguredError(Exception):
    """A unit price needed for the estimate is missing from config.yaml."""


class Estimate(BaseModel):
    total_video_sec: int
    veo_calls: int
    veo_calls_max: int
    cost_usd: float
    cost_usd_max: float
    minutes: float
    cap_usd: float
    over_cap: bool


def estimate(
    plan: Plan,
    config: AppConfig,
    *,
    video_provider: str,
    cap_usd: float | None = None,
) -> Estimate:
    scene_count = len(plan.scenes)
    total_sec = sum(scene.duration_sec for scene in plan.scenes)
    max_attempts = 1 + config.limits.max_regenerations_per_scene

    if video_provider == "fake":
        price_per_sec = 0.0
    elif config.veo.price_usd_per_second is None:
        raise PriceNotConfiguredError(
            "Chưa điền veo.price_usd_per_second trong config.yaml nên không ước tính được chi phí."
        )
    else:
        price_per_sec = config.veo.price_usd_per_second

    video_cost = total_sec * price_per_sec
    # The TTS service is not chosen yet; its cost counts only once a price is configured.
    chars = sum(len(scene.voiceover_vi) for scene in plan.scenes)
    tts_cost = chars / 1000 * (config.tts.price_usd_per_1k_chars or 0.0)

    cost = round(video_cost + tts_cost, 4)
    cost_max = round(video_cost * max_attempts + tts_cost, 4)

    batches = math.ceil(scene_count / config.veo.max_concurrent)
    seconds = batches * config.veo.est_clip_generation_sec + config.assembler.est_assembly_sec

    cap = config.limits.cost_cap_per_job_usd if cap_usd is None else cap_usd
    return Estimate(
        total_video_sec=total_sec,
        veo_calls=scene_count,
        veo_calls_max=scene_count * max_attempts,
        cost_usd=cost,
        cost_usd_max=cost_max,
        minutes=round(seconds / 60, 1),
        cap_usd=cap,
        over_cap=cost > cap,
    )


def claude_cost_usd(input_tokens: int, output_tokens: int, config: ClaudeConfig) -> float:
    if config.price_usd_per_mtok_input is None or config.price_usd_per_mtok_output is None:
        raise PriceNotConfiguredError(
            "Chưa điền claude.price_usd_per_mtok_input / claude.price_usd_per_mtok_output trong config.yaml."
        )
    cost = (
        input_tokens * config.price_usd_per_mtok_input
        + output_tokens * config.price_usd_per_mtok_output
    ) / 1_000_000
    return round(cost, 6)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_estimator.py -v`
Expected: 10 passed.

- [ ] **Step 5: Add the manual smoke script**

This is not a test and is never run by pytest. It makes real Claude calls (a few US cents per run).

Create `scripts/try_planner.py`:

```python
"""Manual smoke run of the planner against the real Claude API (costs a few cents).

Usage:  .venv\\Scripts\\python scripts\\try_planner.py "5 việc sếp không biết bạn đang làm bằng AI"
Needs ANTHROPIC_API_KEY in .env.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.estimator import claude_cost_usd, estimate  # noqa: E402
from app.agent.planner import PlanOptions, build_planner  # noqa: E402
from app.config import load_settings  # noqa: E402


async def main(idea: str) -> None:
    settings = load_settings()
    defaults = settings.config.defaults
    options = PlanOptions(defaults.duration_sec, defaults.aspect, defaults.voice, defaults.style)

    result = await build_planner(settings).create_plan(idea, options)

    print(json.dumps(result.plan.to_dict(), ensure_ascii=False, indent=2))
    print(f"\nmodel={result.model} calls={result.calls} "
          f"tokens_in={result.input_tokens} tokens_out={result.output_tokens}")
    print(f"claude cost: ${claude_cost_usd(result.input_tokens, result.output_tokens, settings.config.claude)}")
    print(estimate(result.plan, settings.config, video_provider=settings.secrets.video_provider))


if __name__ == "__main__":
    # The Windows console defaults to a legacy codepage that cannot print Vietnamese.
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) != 2:
        sys.exit('Usage: python scripts/try_planner.py "ý tưởng"')
    asyncio.run(main(sys.argv[1]))
```

- [ ] **Step 6: Run the whole suite**

Run: `.venv\Scripts\python -m pytest`
Expected: 103 passed (config 11, ffmpeg 5, models 4, main 5, schemas 18, plan rules 24, planner 17, revise 9, estimator 10).

- [ ] **Step 7: Smoke run against the real API (needs the user's go-ahead)**

Ask the user before running: this spends a few cents of Claude credit and needs `ANTHROPIC_API_KEY` in `.env`. If they decline or there is no key, skip this step and say so in the phase report.

Run: `.venv\Scripts\python scripts\try_planner.py "5 việc sếp không biết bạn đang làm bằng AI"`
Expected: a Vietnamese plan as JSON, a line `model=claude-sonnet-5-5 calls=1 …` (1–3 calls), a Claude cost, and an `Estimate` with `cost_usd=0.0` (fake video provider).

If the API answers HTTP 400:
- message mentions `fallbacks` or the beta header → set `claude.refusal_fallback: false` in `config.yaml`, re-run, and report it;
- message mentions the tool `input_schema` → add the keyword it names to `_UNSUPPORTED_KEYWORDS` in `app/agent/planner.py` and to `UNSUPPORTED` in `tests/test_planner.py`, re-run the tests, re-run the script.

- [ ] **Step 8: Tick Giai đoạn 1 in `TASKS.md` and commit**

In `TASKS.md`, change the six `- [ ]` items under `## Giai đoạn 1 — Planner (Claude)` to `- [x]`.

```powershell
git add app/agent/estimator.py scripts/try_planner.py tests/test_estimator.py TASKS.md
git commit -m "feat: cost and time estimator, planner smoke script"
```

**Checkpoint — Giai đoạn 1 is complete.** Report to the user: what was built, the test count, the smoke-run result (or that it was skipped), and that Giai đoạn 2 needs its own plan.
