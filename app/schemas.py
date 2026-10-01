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
