"""Insert a demo job (fixture plan, awaiting approval) so screen 2 can be seen without an API key.

Usage:  .venv\\Scripts\\python scripts\\seed_demo_job.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlmodel import Session  # noqa: E402

from app import jobstore  # noqa: E402
from app.config import load_settings  # noqa: E402
from app.db import init_db, make_engine  # noqa: E402
from app.schemas import Plan  # noqa: E402


def main() -> None:
    settings = load_settings()
    plan_dict = json.loads((ROOT / "tests" / "fixtures" / "plan_30s.json").read_text(encoding="utf-8"))
    engine = make_engine(settings.data_dir)
    init_db(engine)
    with Session(engine) as session:
        job = jobstore.create_job(
            session,
            idea=plan_dict["idea"],
            duration_sec=plan_dict["target"]["duration_sec"],
            aspect=plan_dict["target"]["aspect"],
            voice=settings.config.defaults.voice,
            style="office",
            cost_cap_usd=settings.config.limits.cost_cap_per_job_usd,
        )
        jobstore.save_plan(session, settings.data_dir, job, Plan.model_validate(plan_dict))
        print(f"http://127.0.0.1:8000/jobs/{job.id}")
    engine.dispose()


if __name__ == "__main__":
    main()
