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
