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
