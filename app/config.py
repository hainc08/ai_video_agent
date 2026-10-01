"""Settings: secrets from .env, everything else (models, prices, limits) from config.yaml."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

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


def _price() -> Any:
    # A price of 0 would make a paid run look free; leave it null until the real price is known.
    return Field(default=None, gt=0, allow_inf_nan=False)


class ClaudeConfig(_Section):
    model: str
    max_tokens: int = Field(default=16000, ge=1000)
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    refusal_fallback: bool = True
    price_usd_per_mtok_input: float | None = _price()
    price_usd_per_mtok_output: float | None = _price()


class GeminiConfig(_Section):
    model: str
    # Tried in order when the model above answers 503 (overloaded) or 429 (quota).
    fallback_models: list[str] = Field(default_factory=list)
    max_output_tokens: int = Field(default=16000, ge=1000)  # includes the model's thinking
    price_usd_per_mtok_input: float | None = _price()
    price_usd_per_mtok_output: float | None = _price()


class VeoConfig(_Section):
    model: str
    resolution: str = "720p"
    generate_audio: bool = False
    price_usd_per_second: float | None = _price()
    max_concurrent: int = Field(default=3, ge=1)
    job_timeout_sec: int = Field(default=600, gt=0)
    poll_interval_sec: int = Field(default=10, gt=0)
    est_clip_generation_sec: int = Field(default=120, ge=0)


class LimitsConfig(_Section):
    cost_cap_per_job_usd: float = Field(default=5, gt=0, allow_inf_nan=False)
    cost_cap_per_day_usd: float = Field(default=20, gt=0, allow_inf_nan=False)
    max_regenerations_per_scene: int = Field(default=1, ge=0)


class DefaultsConfig(_Section):
    duration_sec: Literal[15, 30, 60] = 30
    aspect: Literal["9:16", "1:1", "16:9"] = "9:16"
    voice: str = "vi-female-north"
    style: str = "clean corporate office, soft daylight, muted blue palette"


class TTSConfig(_Section):
    price_usd_per_1k_chars: float | None = _price()


class AssemblerConfig(_Section):
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    output_width: int = 1080
    output_height: int = 1920
    subtitle_font: str = "Be Vietnam Pro"
    music_dir: str = "assets/music"
    logo_path: str = "assets/logo.png"
    est_assembly_sec: int = Field(default=90, ge=0)


class StorageConfig(_Section):
    data_dir: str = "data"


class ServerConfig(_Section):
    # Host names the server answers to. Anything else is refused, so a web page that points
    # its own domain at 127.0.0.1 (DNS rebinding) cannot drive the app from the user's browser.
    allowed_hosts: list[str] = Field(default_factory=lambda: ["localhost", "127.0.0.1", "::1"])


class AppConfig(_Section):
    # Only the section of the provider chosen by LLM_PROVIDER is required (checked in load_settings).
    gemini: GeminiConfig | None = None
    claude: ClaudeConfig | None = None
    veo: VeoConfig
    # default_factory: each AppConfig gets its own section objects (they are mutable).
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    assembler: AssemblerConfig = Field(default_factory=AssemblerConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)


def _reveal(secret: SecretStr | None) -> str | None:
    value = secret.get_secret_value().strip() if secret else ""
    return value or None


class Secrets(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    anthropic_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    llm_provider: Literal["gemini", "claude"] = "gemini"
    video_provider: Literal["fake", "veo"] = "fake"
    tts_provider: Literal["edge", "fake"] = "edge"

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

    @property
    def llm(self) -> GeminiConfig | ClaudeConfig:
        """Model and prices of the LLM that writes plans (the provider chosen by LLM_PROVIDER)."""
        provider = self.secrets.llm_provider
        section = getattr(self.config, provider)
        if section is None:
            raise ConfigError(f"Thiếu mục '{provider}:' trong config.yaml (LLM_PROVIDER={provider}).")
        return section


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
    settings = Settings(root=root, config=load_config(root), secrets=secrets)
    settings.llm  # fail now, with a clear message, if the chosen provider has no config section
    return settings
