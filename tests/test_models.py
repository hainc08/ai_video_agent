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
