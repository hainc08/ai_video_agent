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
