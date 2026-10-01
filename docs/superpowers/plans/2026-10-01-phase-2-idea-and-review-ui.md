# Phase 2: Idea Form + Plan Review UI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A user can type an idea on screen 1, watch "Claude đang lập plan…", then review the plan on screen 2 — edit a scene by hand, ask Claude to rewrite a scene or the whole plan, see the cost estimate, and approve (the approve button is locked when the estimate exceeds the job's cap).

**Architecture:** Jobs live in SQLite plus `data/jobs/<id>/plan*.json` (`app/jobstore.py`). Claude calls run as asyncio background tasks owned by a `PlanningService`, so every request returns immediately and the page polls with HTMX until the job leaves `planning`. HTML pages (`app/web/pages.py`) render from the database; the API (`app/web/api.py`) accepts form-encoded bodies, returns JSON, and answers successful mutations with an `HX-Refresh: true` header so the HTMX page reloads itself.

**Tech Stack:** FastAPI, Jinja2, HTMX 2 (vendored file, no build step), plain CSS + ~25 lines of vanilla JS, SQLModel/SQLite, pytest with FastAPI `TestClient` and a fake planner.

**Spec:** `CLAUDE.md`, `TASKS.md` (Giai đoạn 2), `docs/UI_SPEC.md` (Màn 1, Màn 2, Trạng thái lỗi), `docs/ARCHITECTURE.md` (Trạng thái job, API), `docs/ui-mockups/01-nhap-y-tuong.dc.html`, `docs/ui-mockups/02-duyet-plan.dc.html`. Executors read these alongside this plan.

**Builds on:** Phase 0–1 (`docs/superpowers/plans/2026-10-01-phase-0-1-skeleton-and-planner.md`), including any fixes from its final review. If a file quoted here differs from the repository because of those fixes, keep the fix and apply this plan's change on top of it.

**Scope:** `TASKS.md` Giai đoạn 2. Not in this plan: the video runner, SSE, screens 3 and 4 (Phase 3–4); cancel, resume-from-failed-step and the daily cost cap (Phase 5). After "Duyệt & tạo video" the job moves to `generating` and shows a plain status page saying generation is not built yet.

**Working directory:** the project root (the folder containing `CLAUDE.md`). Commands are PowerShell. Work on a new branch `phase-2` created from the tip of `phase-0-1`.

## Global Constraints

- Python 3.11+, Windows. `pathlib` for paths; every text file read/written with an explicit `encoding="utf-8"`.
- **Tests never call a paid API.** Every test that reaches the planner uses `tests.fakes.FakePlanner`.
- API keys only from `.env`; never log or render a key. Error messages built from exceptions use the exception class name, not its text.
- Code, identifiers, comments in English. Everything the user reads (templates, error messages returned by the API, labels) in Vietnamese.
- No frontend build step: Jinja2 templates + HTMX + plain CSS. HTMX is a vendored file at `app/static/htmx.min.js`.
- Design tokens: background `#F4F2EC`; card `#FFFFFF`, border `#DAD6CC`, radius 12–16px; text `#17181C` / `#5B5E66`; accent `#1D4ED8` on `#E3EAFB`; warning `#C2410C` on `#FDF0E1`, warning text `#9A3412`; fonts Be Vietnam Pro (UI) and JetBrains Mono (prompts); buttons and inputs at least 44px high. Mockup syntax (`{{...}}`, `<sc-for>`, `<x-dc>`) is not copied.
- Job states used here: `planning -> awaiting_approval -> generating`, `planning -> failed`. A Claude call on a job that already has a plan (revise, rewrite scene) that fails returns the job to `awaiting_approval` with the old plan intact and an error message.
- A background task must never leave a job stuck in `planning`: every failure path writes a final state.
- All Jinja output is auto-escaped; never use `|safe` on user or Claude text.
- Model names and prices stay in `config.yaml`.
- Commit after every task.

## Review Focus

Input classes the spec implies but does not spell out, most likely first. Each has a test in the task named in brackets.

1. **The Claude call fails for a reason other than a bad plan** — missing `ANTHROPIC_API_KEY`, network or auth error, an unexpected exception: the job does not spin forever; the user sees a Vietnamese message; a failed revise keeps the previous plan. [Task 3]
2. **The server restarts (or `--reload` fires) while a job is `planning`** — on the next start the job is moved out of `planning` with an explanation instead of polling forever. [Tasks 2, 4]
3. **How people actually type the form** — cap `2,5` with a decimal comma, blank cap, `0`, `abc`, whitespace-only idea, a 1,001-character idea, missing optional fields: defaults apply or a clear error appears next to the field, and what the user typed is still in the form. [Task 5]
4. **Actions against the wrong state or the wrong thing** — approve twice, revise while planning, unknown job id, unknown scene number, approving an over-cap plan by calling the API directly (the disabled button is only client-side): 404 / 409, never 500, and the cap is enforced on the server. [Tasks 5, 7]
5. **A manual edit that breaks the plan, and text with HTML in it** — a 25-word voiceover in a 6-second scene, a 1,001-character prompt, an emptied voiceover: rejected with a Vietnamese message and the stored plan unchanged; `<script>` in an idea or a voiceover is rendered as text. [Tasks 4, 6, 7]

---

## File Structure

| File | Responsibility |
| --- | --- |
| `app/agent/plan_rules.py` (modify) | each rule violation carries an English message (for Claude) and a Vietnamese one (for the user) |
| `app/options.py` | choices on the idea form: durations, aspects, voices, styles (label + prompt) |
| `app/jobstore.py` | job persistence: rows, plan versions on disk, scene rows, Claude cost entries, restart recovery |
| `app/agent/planning.py` | `PlanningService`: runs planner calls in the background and persists the outcome |
| `app/web/forms.py` | parse and validate the idea form |
| `app/web/views.py` | Jinja setup, view models (steps, timeline, estimate, JSON job detail), DB session dependency |
| `app/web/pages.py` | HTML routes: `/`, `/jobs/{id}` |
| `app/web/api.py` | `/api/jobs…` routes |
| `app/main.py` (modify) | app factory: wires service, routers, restart recovery |
| `app/templates/*.html` | `base`, `index`, `job_planning`, `job_review`, `job_status`, `job_failed`, `not_found` |
| `app/static/app.css`, `app.js`, `htmx.min.js` | styles, 3 small behaviours, vendored HTMX |
| `scripts/seed_demo_job.py` | insert a demo job with the fixture plan (to see screen 2 without an API key) |
| `tests/fakes.py`, `tests/helpers.py` | fake planner; `seed_job`, `wait_until_planned` |

`CLAUDE.md` lists routes inside `app/main.py`; with eleven routes they move to `app/web/`, and Task 4 updates the structure listing in `CLAUDE.md`.

---

### Task 1: Vietnamese messages for plan rule violations

**Files:**
- Modify: `app/agent/plan_rules.py` (whole file)
- Test: `tests/test_plan_rules.py` (import line + 3 new tests)

**Interfaces:**
- Consumes: `app.schemas.Plan`.
- Produces (from `app.agent.plan_rules`):
  - `PlanIssue(en: str, vi: str)` — frozen dataclass. `en` is the existing English message; `vi` is for the user.
  - `find_issues(plan: Plan, *, duration_sec: int, aspect: str) -> list[PlanIssue]`.
  - `validate_plan(plan, *, duration_sec, aspect) -> list[str]` — unchanged behaviour: `[issue.en for issue in find_issues(...)]`. Every existing test must keep passing untouched.
  - `count_words`, `word_bounds` — unchanged.

- [ ] **Step 1: Write the failing tests**

In `tests/test_plan_rules.py` change the import line

```python
from app.agent.plan_rules import count_words, validate_plan, word_bounds
```

to

```python
from app.agent.plan_rules import count_words, find_issues, validate_plan, word_bounds
```

and append at the end of the file:

```python
def _vi(plan_dict):
    plan = Plan.model_validate(plan_dict)
    return [issue.vi for issue in find_issues(plan, duration_sec=30, aspect="9:16")]


def test_scene_issue_has_a_vietnamese_message_for_the_user(plan_dict):
    plan_dict["scenes"][0]["voiceover_vi"] = _words(20)
    plan_dict["scenes"][1]["voiceover_vi"] = _words(13)

    assert _vi(plan_dict) == ["Cảnh 1: lời thoại có 20 từ, tối đa 19 từ cho cảnh 6 giây"]


def test_plan_level_issue_has_a_vietnamese_message(plan_dict):
    for scene in plan_dict["scenes"]:
        scene["duration_sec"] = 4
        scene["voiceover_vi"] = _words(10)

    assert _vi(plan_dict) == ["Tổng thời lượng các cảnh là 20 giây, cần trong khoảng 28–32 giây"]


def test_every_issue_has_both_languages_and_validate_plan_returns_the_english_ones(plan_dict):
    plan_dict["brief"]["cta"] = ""
    plan_dict["scenes"][1]["id"] = 1
    plan_dict["scenes"][2]["voiceover_vi"] = ""
    plan_dict["scenes"][3]["subtitle_vi"] = _words(13)
    plan_dict["scenes"][4]["veo_prompt_en"] = "An office"
    plan = Plan.model_validate(plan_dict)

    issues = find_issues(plan, duration_sec=60, aspect="1:1")

    assert len(issues) >= 8
    assert all(issue.en and issue.vi for issue in issues)
    assert validate_plan(plan, duration_sec=60, aspect="1:1") == [issue.en for issue in issues]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_plan_rules.py -q`
Expected: collection error — `ImportError: cannot import name 'find_issues'`.

- [ ] **Step 3: Implement**

Replace `app/agent/plan_rules.py` with:

```python
"""Business rules a plan must satisfy beyond its JSON structure (FR-03, FR-04, FR-05)."""
from __future__ import annotations

from dataclasses import dataclass

from app.schemas import Plan

# Reading speed is 2.5-3 words/second with 10% tolerance. Kept as integers per 100 seconds
# so the bounds are exact (2.5 * 0.9 = 2.25, 3.0 * 1.1 = 3.30) with no float rounding.
_MIN_WORDS_PER_100_SEC = 225
_MAX_WORDS_PER_100_SEC = 330
DURATION_TOLERANCE_SEC = 2
SUBTITLE_MAX_WORDS = 12
NO_TEXT_MARKER = "no on-screen text"

_BRIEF_LABELS = {
    "audience": "Khán giả",
    "key_message": "Thông điệp",
    "hook": "Hook 3 giây",
    "cta": "CTA",
}


@dataclass(frozen=True)
class PlanIssue:
    en: str  # sent back to Claude so it can fix the plan
    vi: str  # shown to the user when a manual edit breaks a rule


def count_words(text: str) -> int:
    return sum(1 for token in text.split() if any(ch.isalnum() for ch in token))


def word_bounds(seconds: int) -> tuple[int, int]:
    low = -(-seconds * _MIN_WORDS_PER_100_SEC // 100)  # ceiling division
    high = seconds * _MAX_WORDS_PER_100_SEC // 100
    return low, high


def find_issues(plan: Plan, *, duration_sec: int, aspect: str) -> list[PlanIssue]:
    issues: list[PlanIssue] = []

    def add(en: str, vi: str) -> None:
        issues.append(PlanIssue(en=en, vi=vi))

    if plan.target.duration_sec != duration_sec:
        add(
            f"target.duration_sec must be {duration_sec}, got {plan.target.duration_sec}",
            f"Thời lượng mục tiêu phải là {duration_sec} giây",
        )
    if plan.target.aspect != aspect:
        add(
            f"target.aspect must be {aspect}, got {plan.target.aspect}",
            f"Tỉ lệ khung hình phải là {aspect}",
        )

    ids = [scene.id for scene in plan.scenes]
    if ids != list(range(1, len(ids) + 1)):
        add(
            f"scene ids must be 1..{len(ids)} in order, got {ids}",
            f"Số thứ tự cảnh phải liên tục từ 1 đến {len(ids)}",
        )

    total_sec = sum(scene.duration_sec for scene in plan.scenes)
    if abs(total_sec - duration_sec) > DURATION_TOLERANCE_SEC:
        add(
            f"total scene duration is {total_sec}s, must be within "
            f"{DURATION_TOLERANCE_SEC}s of {duration_sec}s",
            f"Tổng thời lượng các cảnh là {total_sec} giây, cần trong khoảng "
            f"{duration_sec - DURATION_TOLERANCE_SEC}–{duration_sec + DURATION_TOLERANCE_SEC} giây",
        )

    low, high = word_bounds(total_sec)
    total_words = sum(count_words(scene.voiceover_vi) for scene in plan.scenes)
    if not low <= total_words <= high:
        add(
            f"total voiceover is {total_words} words, must be {low}-{high} words "
            f"for {total_sec}s of scenes (2.5-3 words/second)",
            f"Tổng lời thoại có {total_words} từ, cần {low}–{high} từ cho {total_sec} giây",
        )

    for name, label in _BRIEF_LABELS.items():
        if not getattr(plan.brief, name).strip():
            add(f"brief.{name} must not be empty", f"Brief: mục {label} không được để trống")

    for scene in plan.scenes:
        words = count_words(scene.voiceover_vi)
        scene_high = word_bounds(scene.duration_sec)[1]
        if words == 0:
            add(
                f"scene {scene.id}: voiceover_vi must not be empty",
                f"Cảnh {scene.id}: lời thoại không được để trống",
            )
        elif words > scene_high:
            add(
                f"scene {scene.id}: voiceover_vi has {words} words, "
                f"at most {scene_high} fit a {scene.duration_sec}s scene",
                f"Cảnh {scene.id}: lời thoại có {words} từ, tối đa {scene_high} từ "
                f"cho cảnh {scene.duration_sec} giây",
            )
        subtitle_words = count_words(scene.subtitle_vi)
        if subtitle_words > SUBTITLE_MAX_WORDS:
            add(
                f"scene {scene.id}: subtitle_vi has {subtitle_words} words, "
                f"at most {SUBTITLE_MAX_WORDS} allowed",
                f"Cảnh {scene.id}: phụ đề có {subtitle_words} từ, tối đa {SUBTITLE_MAX_WORDS} từ",
            )
        if NO_TEXT_MARKER not in scene.veo_prompt_en.lower():
            add(
                f"scene {scene.id}: veo_prompt_en must end with 'no on-screen text, no logos'",
                f"Cảnh {scene.id}: prompt Veo phải kết thúc bằng 'no on-screen text, no logos'",
            )

    return issues


def validate_plan(plan: Plan, *, duration_sec: int, aspect: str) -> list[str]:
    return [issue.en for issue in find_issues(plan, duration_sec=duration_sec, aspect=aspect)]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_plan_rules.py tests/test_planner.py tests/test_planner_revise.py -q`
Expected: all pass (3 more than before in `test_plan_rules.py`; the planner tests prove the English messages are unchanged).

- [ ] **Step 5: Commit**

```powershell
git add app/agent/plan_rules.py tests/test_plan_rules.py
git commit -m "feat: Vietnamese messages for plan rule violations"
```

---

### Task 2: Form options and the job store

**Files:**
- Create: `app/options.py`, `app/jobstore.py`, `tests/test_options.py`, `tests/test_jobstore.py`
- Modify: `tests/conftest.py` (add `engine` and `session` fixtures), `tests/test_models.py` (delete its local `engine` fixture and the imports only that fixture used)

**Interfaces:**
- Consumes: `app.models.Job`, `JobStatus`, `Scene`, `CostEntry`; `app.db.make_engine`, `init_db`; `app.schemas.Plan` (`to_dict()`); `app.agent.estimator.claude_cost_usd(input_tokens, output_tokens, config) -> float`, `PriceNotConfiguredError`; `app.config.AppConfig`, `ClaudeConfig`.
- Produces (from `app.options`):
  - `DURATIONS = (15, 30, 60)`, `ASPECTS = ("9:16", "1:1", "16:9")`
  - `VOICES: dict[str, str]` — key → Vietnamese label; keys `vi-female-north`, `vi-male-north`, `vi-female-south`.
  - `STYLES: dict[str, str]` — key → Vietnamese label; keys `office`, `minimal`, `cinematic`. `DEFAULT_STYLE = "office"`.
  - `voice_label(key: str) -> str` (unknown key → the key itself).
  - `style_prompt(key: str, config: AppConfig) -> str` — English description for the planner; `office` and unknown keys → `config.defaults.style`.
- Produces (from `app.jobstore`), all synchronous, all taking an open `sqlmodel.Session`:
  - `INTERRUPTED_MESSAGE: str`
  - `job_dir(data_dir: Path, job_id: str) -> Path` → `data_dir / "jobs" / job_id`
  - `create_job(session, *, idea: str, duration_sec: int, aspect: str, voice: str, style: str, cost_cap_usd: float) -> Job` — status `planning`. `Job.style` stores the style **key**.
  - `get_job(session, job_id: str) -> Job | None`
  - `list_recent_jobs(session, limit: int = 10) -> list[Job]` — newest first.
  - `list_scenes(session, job_id: str) -> list[Scene]` — ordered by `scene_no`.
  - `load_plan(job: Job) -> Plan | None`
  - `save_plan(session, data_dir: Path, job: Job, plan: Plan) -> None` — stores `plan_json`, increments `plan_version`, writes `plan.v<N>.json` and `plan.json` (UTF-8, readable Vietnamese), replaces the job's `Scene` rows, sets status `awaiting_approval`, clears `error` / `failed_step`.
  - `mark_planning(session, job) -> None` — status `planning`, clears `error`.
  - `mark_planning_failed(session, job, message: str) -> None` — with a plan: `awaiting_approval` + `error`; without: `failed`, `failed_step="planning"`, `error`.
  - `mark_approved(session, job) -> None` — status `generating`.
  - `record_claude_usage(session, job_id: str, *, action: str, model: str, input_tokens: int, output_tokens: int, config: ClaudeConfig) -> None` — one `CostEntry` per non-zero token count (`unit` `tokens_in` / `tokens_out`).
  - `job_cost_usd(session, job_id: str) -> float`
  - `recover_interrupted(session) -> int` — every job in `planning` goes through `mark_planning_failed(..., INTERRUPTED_MESSAGE)`; returns how many.
- Produces (fixtures in `tests/conftest.py`): `engine` (SQLite at `tmp_path / "data"`, the same folder as `settings.data_dir`), `session`.

- [ ] **Step 1: Move the `engine` fixture to `conftest.py`**

In `tests/conftest.py` add these imports below the existing ones:

```python
from sqlmodel import Session

from app.db import init_db, make_engine
```

and append:

```python
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
```

In `tests/test_models.py` delete the local fixture

```python
@pytest.fixture
def engine(tmp_path):
    engine = make_engine(tmp_path / "data")
    init_db(engine)
    yield engine
    engine.dispose()
```

and change its imports to:

```python
from sqlalchemy import inspect
from sqlmodel import Session, select

from app.db import init_db
from app.models import CostEntry, Job, JobStatus, Scene, SceneStatus
```

Run: `.venv\Scripts\python -m pytest tests/test_models.py -q`
Expected: 4 passed (same tests, shared fixture).

- [ ] **Step 2: Write the failing tests**

Create `tests/test_options.py`:

```python
from app.options import DEFAULT_STYLE, STYLES, VOICES, style_prompt, voice_label


def test_office_style_uses_the_prompt_from_config(settings):
    assert DEFAULT_STYLE == "office"
    assert style_prompt("office", settings.config) == settings.config.defaults.style


def test_other_styles_have_their_own_english_prompt(settings):
    prompts = {key: style_prompt(key, settings.config) for key in STYLES}

    assert len(set(prompts.values())) == len(STYLES)
    assert "cinematic" in prompts["cinematic"]


def test_unknown_keys_fall_back_instead_of_failing(settings):
    assert style_prompt("removed-style", settings.config) == settings.config.defaults.style
    assert voice_label("vi-female-north") == VOICES["vi-female-north"] == "Nữ · miền Bắc"
    assert voice_label("custom-voice") == "custom-voice"
```

Create `tests/test_jobstore.py`:

```python
from datetime import datetime, timezone

import pytest
from sqlmodel import select

from app import jobstore
from app.config import ClaudeConfig
from app.models import CostEntry, JobStatus, Scene
from app.schemas import Plan

FIELDS = dict(
    idea="5 việc sếp không biết bạn đang làm bằng AI",
    duration_sec=30,
    aspect="9:16",
    voice="vi-female-north",
    style="office",
    cost_cap_usd=5.0,
)
PRICED = ClaudeConfig(model="m", price_usd_per_mtok_input=2.0, price_usd_per_mtok_output=10.0)


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path / "data"


@pytest.fixture
def plan(plan_dict):
    return Plan.model_validate(plan_dict)


def test_create_job_starts_in_planning(session):
    job = jobstore.create_job(session, **FIELDS)

    stored = jobstore.get_job(session, job.id)
    assert stored.status == JobStatus.planning
    assert stored.idea == FIELDS["idea"]
    assert stored.cost_cap_usd == 5.0
    assert jobstore.load_plan(stored) is None
    assert jobstore.get_job(session, "missing") is None


def test_save_plan_stores_the_plan_its_files_and_scene_rows(session, data_dir, plan, plan_dict):
    job = jobstore.create_job(session, **FIELDS)

    jobstore.save_plan(session, data_dir, job, plan)

    assert job.status == JobStatus.awaiting_approval
    assert job.plan_version == 1
    assert jobstore.load_plan(job).to_dict() == plan_dict
    folder = jobstore.job_dir(data_dir, job.id)
    text = (folder / "plan.json").read_text(encoding="utf-8")
    assert "Sếp không hề biết" in text  # readable Vietnamese, not \u escapes
    assert (folder / "plan.v1.json").read_text(encoding="utf-8") == text
    scenes = jobstore.list_scenes(session, job.id)
    assert [scene.scene_no for scene in scenes] == [1, 2, 3, 4, 5]


def test_saving_again_keeps_old_versions_and_replaces_scene_rows(session, data_dir, plan):
    job = jobstore.create_job(session, **FIELDS)
    jobstore.save_plan(session, data_dir, job, plan)
    job.error = "lỗi cũ"
    shorter = plan.model_copy(update={"scenes": plan.scenes[:4]})

    jobstore.save_plan(session, data_dir, job, shorter)

    folder = jobstore.job_dir(data_dir, job.id)
    assert job.plan_version == 2
    assert job.error is None
    assert (folder / "plan.v1.json").exists() and (folder / "plan.v2.json").exists()
    assert (folder / "plan.json").read_text(encoding="utf-8") == (folder / "plan.v2.json").read_text(encoding="utf-8")
    assert len(session.exec(select(Scene).where(Scene.job_id == job.id)).all()) == 4


def test_planning_failure_without_a_plan_fails_the_job(session):
    job = jobstore.create_job(session, **FIELDS)

    jobstore.mark_planning_failed(session, job, "Claude từ chối")

    assert (job.status, job.failed_step, job.error) == (JobStatus.failed, "planning", "Claude từ chối")


def test_planning_failure_with_a_plan_returns_to_review_and_keeps_it(session, data_dir, plan, plan_dict):
    job = jobstore.create_job(session, **FIELDS)
    jobstore.save_plan(session, data_dir, job, plan)
    jobstore.mark_planning(session, job)
    assert job.status == JobStatus.planning

    jobstore.mark_planning_failed(session, job, "Không viết lại được")

    assert job.status == JobStatus.awaiting_approval
    assert job.error == "Không viết lại được"
    assert job.failed_step is None
    assert job.plan_version == 1
    assert jobstore.load_plan(job).to_dict() == plan_dict


def test_mark_planning_clears_a_previous_error(session, data_dir, plan):
    job = jobstore.create_job(session, **FIELDS)
    jobstore.save_plan(session, data_dir, job, plan)
    jobstore.mark_planning_failed(session, job, "lỗi")

    jobstore.mark_planning(session, job)

    assert (job.status, job.error) == (JobStatus.planning, None)


def test_mark_approved_moves_the_job_to_generating(session, data_dir, plan):
    job = jobstore.create_job(session, **FIELDS)
    jobstore.save_plan(session, data_dir, job, plan)

    jobstore.mark_approved(session, job)

    assert jobstore.get_job(session, job.id).status == JobStatus.generating


def test_claude_usage_is_recorded_as_cost_entries(session):
    job = jobstore.create_job(session, **FIELDS)

    jobstore.record_claude_usage(
        session, job.id, action="create_plan", model="claude-sonnet-5-5",
        input_tokens=1000, output_tokens=2000, config=PRICED,
    )

    rows = session.exec(select(CostEntry).where(CostEntry.job_id == job.id).order_by(CostEntry.id)).all()
    assert [(row.kind, row.unit, row.units, row.usd) for row in rows] == [
        ("claude", "tokens_in", 1000, 0.002),
        ("claude", "tokens_out", 2000, 0.02),
    ]
    assert all("create_plan" in row.detail and "claude-sonnet-5-5" in row.detail for row in rows)
    assert jobstore.job_cost_usd(session, job.id) == 0.022
    assert jobstore.job_cost_usd(session, "missing") == 0


def test_usage_without_configured_prices_is_recorded_at_zero_cost(session):
    job = jobstore.create_job(session, **FIELDS)

    jobstore.record_claude_usage(
        session, job.id, action="revise", model="m",
        input_tokens=10, output_tokens=20, config=ClaudeConfig(model="m"),
    )

    rows = session.exec(select(CostEntry).where(CostEntry.job_id == job.id)).all()
    assert [row.usd for row in rows] == [0.0, 0.0]
    assert all("price not configured" in row.detail for row in rows)


def test_zero_tokens_record_nothing(session):
    job = jobstore.create_job(session, **FIELDS)

    jobstore.record_claude_usage(
        session, job.id, action="create_plan", model="m", input_tokens=0, output_tokens=0, config=PRICED,
    )

    assert session.exec(select(CostEntry)).all() == []


def test_recent_jobs_are_newest_first_and_limited(session):
    for day in (1, 3, 2):
        job = jobstore.create_job(session, **(FIELDS | {"idea": f"ý tưởng {day}"}))
        job.created_at = datetime(2026, 1, day, tzinfo=timezone.utc)
        session.add(job)
    session.commit()

    assert [job.idea for job in jobstore.list_recent_jobs(session)] == ["ý tưởng 3", "ý tưởng 2", "ý tưởng 1"]
    assert [job.idea for job in jobstore.list_recent_jobs(session, limit=2)] == ["ý tưởng 3", "ý tưởng 2"]


def test_jobs_interrupted_while_planning_are_recovered(session, data_dir, plan):
    fresh = jobstore.create_job(session, **FIELDS)
    revising = jobstore.create_job(session, **FIELDS)
    jobstore.save_plan(session, data_dir, revising, plan)
    jobstore.mark_planning(session, revising)
    untouched = jobstore.create_job(session, **FIELDS)
    jobstore.save_plan(session, data_dir, untouched, plan)

    assert jobstore.recover_interrupted(session) == 2

    assert (fresh.status, fresh.error) == (JobStatus.failed, jobstore.INTERRUPTED_MESSAGE)
    assert (revising.status, revising.error) == (JobStatus.awaiting_approval, jobstore.INTERRUPTED_MESSAGE)
    assert (untouched.status, untouched.error) == (JobStatus.awaiting_approval, None)
    assert jobstore.recover_interrupted(session) == 0
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_options.py tests/test_jobstore.py -q`
Expected: collection errors — `ModuleNotFoundError: No module named 'app.options'` and `ImportError: cannot import name 'jobstore'`.

- [ ] **Step 4: Implement**

Create `app/options.py`:

```python
"""Choices offered on the idea form."""
from __future__ import annotations

from app.config import AppConfig

DURATIONS = (15, 30, 60)
ASPECTS = ("9:16", "1:1", "16:9")

VOICES: dict[str, str] = {
    "vi-female-north": "Nữ · miền Bắc",
    "vi-male-north": "Nam · miền Bắc",
    "vi-female-south": "Nữ · miền Nam",
}

DEFAULT_STYLE = "office"
STYLES: dict[str, str] = {
    "office": "Văn phòng · chuyên nghiệp",
    "minimal": "Tối giản · sáng",
    "cinematic": "Điện ảnh",
}
# "office" has no entry: its prompt is defaults.style from config.yaml.
_STYLE_PROMPTS: dict[str, str] = {
    "minimal": "minimal bright interior, white walls and light wood, soft diffused light",
    "cinematic": "cinematic look, shallow depth of field, warm contrast lighting, slow camera moves",
}


def voice_label(key: str) -> str:
    return VOICES.get(key, key)


def style_prompt(key: str, config: AppConfig) -> str:
    return _STYLE_PROMPTS.get(key, config.defaults.style)
```

Create `app/jobstore.py`:

```python
"""Job persistence: rows in SQLite, plan versions under data/jobs/<job_id>/."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func
from sqlmodel import Session, desc, select

from app.agent.estimator import PriceNotConfiguredError, claude_cost_usd
from app.config import ClaudeConfig
from app.models import CostEntry, Job, JobStatus, Scene
from app.schemas import Plan

INTERRUPTED_MESSAGE = "Việc lập plan bị gián đoạn vì máy chủ khởi động lại. Hãy thử lại."


def _save(session: Session, job: Job) -> None:
    job.updated_at = datetime.now(timezone.utc)
    session.add(job)
    session.commit()


def job_dir(data_dir: Path, job_id: str) -> Path:
    return data_dir / "jobs" / job_id


def create_job(
    session: Session,
    *,
    idea: str,
    duration_sec: int,
    aspect: str,
    voice: str,
    style: str,
    cost_cap_usd: float,
) -> Job:
    job = Job(
        idea=idea,
        duration_sec=duration_sec,
        aspect=aspect,
        voice=voice,
        style=style,
        cost_cap_usd=cost_cap_usd,
        status=JobStatus.planning,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def get_job(session: Session, job_id: str) -> Job | None:
    return session.get(Job, job_id)


def list_recent_jobs(session: Session, limit: int = 10) -> list[Job]:
    return list(session.exec(select(Job).order_by(desc(Job.created_at)).limit(limit)).all())


def list_scenes(session: Session, job_id: str) -> list[Scene]:
    return list(session.exec(select(Scene).where(Scene.job_id == job_id).order_by(Scene.scene_no)).all())


def load_plan(job: Job) -> Plan | None:
    if not job.plan_json:
        return None
    return Plan.model_validate(json.loads(job.plan_json))


def save_plan(session: Session, data_dir: Path, job: Job, plan: Plan) -> None:
    data = plan.to_dict()
    version = job.plan_version + 1

    # Files first: the database is the source of truth and is only updated once they exist.
    folder = job_dir(data_dir, job.id)
    folder.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2)
    (folder / f"plan.v{version}.json").write_text(text, encoding="utf-8")
    (folder / "plan.json").write_text(text, encoding="utf-8")

    for row in list_scenes(session, job.id):
        session.delete(row)
    for scene in plan.scenes:
        session.add(Scene(job_id=job.id, scene_no=scene.id))
    job.plan_json = json.dumps(data, ensure_ascii=False)
    job.plan_version = version
    job.status = JobStatus.awaiting_approval
    job.error = None
    job.failed_step = None
    _save(session, job)


def mark_planning(session: Session, job: Job) -> None:
    job.status = JobStatus.planning
    job.error = None
    _save(session, job)


def mark_planning_failed(session: Session, job: Job, message: str) -> None:
    if job.plan_json:
        # A revise or rewrite failed: the plan the user already had is still good.
        job.status = JobStatus.awaiting_approval
    else:
        job.status = JobStatus.failed
        job.failed_step = "planning"
    job.error = message
    _save(session, job)


def mark_approved(session: Session, job: Job) -> None:
    job.status = JobStatus.generating
    _save(session, job)


def record_claude_usage(
    session: Session,
    job_id: str,
    *,
    action: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    config: ClaudeConfig,
) -> None:
    detail = f"{action} ({model})"
    try:
        usd_in = claude_cost_usd(input_tokens, 0, config)
        usd_out = claude_cost_usd(0, output_tokens, config)
    except PriceNotConfiguredError:
        usd_in = usd_out = 0.0
        detail += " - price not configured"
    for unit, units, usd in (("tokens_in", input_tokens, usd_in), ("tokens_out", output_tokens, usd_out)):
        if units:
            session.add(CostEntry(job_id=job_id, kind="claude", detail=detail, units=units, unit=unit, usd=usd))
    session.commit()


def job_cost_usd(session: Session, job_id: str) -> float:
    total = session.exec(select(func.sum(CostEntry.usd)).where(CostEntry.job_id == job_id)).one()
    return round(float(total or 0.0), 6)


def recover_interrupted(session: Session) -> int:
    jobs = session.exec(select(Job).where(Job.status == JobStatus.planning)).all()
    for job in jobs:
        mark_planning_failed(session, job, INTERRUPTED_MESSAGE)
    return len(jobs)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_options.py tests/test_jobstore.py tests/test_models.py -q`
Expected: 19 passed (3 + 12 + 4).

- [ ] **Step 6: Commit**

```powershell
git add app/options.py app/jobstore.py tests/conftest.py tests/test_models.py tests/test_options.py tests/test_jobstore.py
git commit -m "feat: job store with plan versions, cost entries and restart recovery"
```

---

### Task 3: Planning service (background Claude calls)

**Files:**
- Create: `app/agent/planning.py`, `tests/fakes.py`, `tests/helpers.py`
- Test: `tests/test_planning_service.py`

**Interfaces:**
- Consumes: `app.jobstore` (Task 2: `get_job`, `load_plan`, `save_plan`, `mark_planning_failed`, `record_claude_usage`); `app.options.style_prompt(key, config)`; `app.agent.planner.Planner` (`create_plan(idea, options)`, `revise(plan, feedback)`, `rewrite_scene(plan, scene_id, feedback="")`), `PlanOptions(duration_sec, aspect, voice, style)`, `PlannerResult(plan, model, calls, input_tokens, output_tokens)`, `PlannerError` (attributes `input_tokens`, `output_tokens`); `app.config.Settings`; fixtures `settings`, `engine`, `plan_dict`.
- Produces (from `app.agent.planning`):
  - `PlannerFactory = Callable[[], Planner]` — called once per run, **inside** the error handling, so a missing API key becomes a failed job instead of an exception in a request.
  - `class PlanningService: __init__(self, settings: Settings, engine: Engine, planner_factory: PlannerFactory)`
  - `async create(self, job_id: str) -> None`, `async revise(self, job_id: str, feedback: str) -> None`, `async rewrite_scene(self, job_id: str, scene_id: int, feedback: str = "") -> None` — do the work and persist the outcome; they never raise for planner or unexpected errors (`Planner` already turns Claude API errors into `PlannerError`).
  - `spawn(self, work: Coroutine) -> None` — schedule one of the above on the running loop and keep a reference.
  - `async shutdown(self) -> None` — cancel and await everything spawned.
- Produces (test support):
  - `tests.fakes.FakePlanner(*outcomes)` — each planner method records a tuple in `.calls` (`("create_plan", idea, options)`, `("revise", plan, feedback)`, `("rewrite_scene", plan, scene_id, feedback)`) and returns the next outcome, or raises it if it is an exception.
  - `tests.fakes.planner_result(plan_dict, input_tokens=1000, output_tokens=2000) -> PlannerResult`
  - `tests.helpers.seed_job(engine, data_dir, *, plan_dict=None, **attrs) -> str` — creates a job (keys `idea`, `duration_sec`, `aspect`, `voice`, `style`, `cost_cap_usd` override the defaults), saves the plan if given, then sets any other attributes (`status`, `error`, `created_at`, …) directly. Returns the job id.
  - `tests.helpers.wait_until_planned(client, job_id, timeout=5.0) -> dict` — polls `GET /api/jobs/{id}` until the status is not `planning` (used from Task 5 on).

- [ ] **Step 1: Write the test support files**

Create `tests/fakes.py`:

```python
from app.agent.planner import PlannerResult
from app.schemas import Plan


def planner_result(plan_dict, input_tokens=1000, output_tokens=2000):
    return PlannerResult(
        plan=Plan.model_validate(plan_dict),
        model="claude-sonnet-5-5",
        calls=1,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


class FakePlanner:
    """Stands in for app.agent.planner.Planner: no network, scripted outcomes."""

    def __init__(self, *outcomes):
        self._outcomes = list(outcomes)
        self.calls = []

    def _next(self):
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    async def create_plan(self, idea, options):
        self.calls.append(("create_plan", idea, options))
        return self._next()

    async def revise(self, plan, feedback):
        self.calls.append(("revise", plan, feedback))
        return self._next()

    async def rewrite_scene(self, plan, scene_id, feedback=""):
        self.calls.append(("rewrite_scene", plan, scene_id, feedback))
        return self._next()
```

Create `tests/helpers.py`:

```python
import time

from sqlmodel import Session

from app import jobstore
from app.schemas import Plan

JOB_FIELDS = dict(
    idea="5 việc sếp không biết bạn đang làm bằng AI",
    duration_sec=30,
    aspect="9:16",
    voice="vi-female-north",
    style="office",
    cost_cap_usd=5.0,
)


def seed_job(engine, data_dir, *, plan_dict=None, **attrs):
    """Insert a job directly (no planner, no background task) and return its id."""
    fields = JOB_FIELDS | {key: attrs.pop(key) for key in list(attrs) if key in JOB_FIELDS}
    with Session(engine) as session:
        job = jobstore.create_job(session, **fields)
        if plan_dict is not None:
            jobstore.save_plan(session, data_dir, job, Plan.model_validate(plan_dict))
        for name, value in attrs.items():
            setattr(job, name, value)
        session.add(job)
        session.commit()
        return job.id


def wait_until_planned(client, job_id, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/jobs/{job_id}").json()
        if body["status"] != "planning":
            return body
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} is still planning after {timeout}s")
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_planning_service.py`:

```python
import asyncio
import copy

from sqlmodel import Session, select

from app import jobstore
from app.agent.planner import PlannerError, PlanOptions
from app.agent.planning import PlanningService
from app.models import CostEntry, JobStatus
from app.schemas import Plan
from tests.fakes import FakePlanner, planner_result
from tests.helpers import seed_job


def make_service(settings, engine, *outcomes):
    planner = FakePlanner(*outcomes)
    return PlanningService(settings, engine, lambda: planner), planner


def load(engine, job_id):
    with Session(engine) as session:
        job = jobstore.get_job(session, job_id)
        costs = session.exec(select(CostEntry).where(CostEntry.job_id == job_id)).all()
        return job, jobstore.load_plan(job), costs


async def test_create_stores_the_plan_and_the_claude_cost(settings, engine, plan_dict):
    service, planner = make_service(settings, engine, planner_result(plan_dict))
    job_id = seed_job(engine, settings.data_dir, duration_sec=60, aspect="1:1", style="cinematic")

    await service.create(job_id)

    job, plan, costs = load(engine, job_id)
    assert job.status == JobStatus.awaiting_approval
    assert plan.to_dict() == plan_dict
    assert (settings.data_dir / "jobs" / job_id / "plan.json").exists()
    assert sorted(cost.usd for cost in costs) == [0.002, 0.02]
    assert planner.calls == [
        (
            "create_plan",
            "5 việc sếp không biết bạn đang làm bằng AI",
            PlanOptions(
                duration_sec=60,
                aspect="1:1",
                voice="vi-female-north",
                style="cinematic look, shallow depth of field, warm contrast lighting, slow camera moves",
            ),
        )
    ]


async def test_planner_error_fails_the_job_and_still_records_what_was_spent(settings, engine):
    error = PlannerError("Claude không tạo được plan hợp lệ sau 3 lần thử", input_tokens=300, output_tokens=600)
    service, _ = make_service(settings, engine, error)
    job_id = seed_job(engine, settings.data_dir)

    await service.create(job_id)

    job, plan, costs = load(engine, job_id)
    assert (job.status, job.failed_step) == (JobStatus.failed, "planning")
    assert job.error == "Claude không tạo được plan hợp lệ sau 3 lần thử"
    assert plan is None
    assert sorted(cost.units for cost in costs) == [300, 600]


async def test_missing_api_key_fails_the_job_with_the_factory_message(settings, engine):
    def factory():
        raise PlannerError("Thiếu ANTHROPIC_API_KEY trong file .env.")

    service = PlanningService(settings, engine, factory)
    job_id = seed_job(engine, settings.data_dir)

    await service.create(job_id)

    job, _, costs = load(engine, job_id)
    assert job.status == JobStatus.failed
    assert job.error == "Thiếu ANTHROPIC_API_KEY trong file .env."
    assert costs == []


async def test_unexpected_error_fails_the_job_instead_of_leaving_it_planning(settings, engine):
    service, _ = make_service(settings, engine, RuntimeError("boom"))
    job_id = seed_job(engine, settings.data_dir)

    await service.create(job_id)

    job, _, _ = load(engine, job_id)
    assert job.status == JobStatus.failed
    assert "Lỗi không mong muốn" in job.error
    assert "boom" not in job.error


async def test_revise_saves_a_new_plan_version(settings, engine, plan_dict):
    revised = copy.deepcopy(plan_dict)
    revised["brief"]["cta"] = "Lưu video để xem lại"
    service, planner = make_service(settings, engine, planner_result(revised))
    job_id = seed_job(engine, settings.data_dir, plan_dict=plan_dict, status=JobStatus.planning)

    await service.revise(job_id, "Đổi CTA")

    job, plan, _ = load(engine, job_id)
    assert (job.status, job.plan_version) == (JobStatus.awaiting_approval, 2)
    assert plan.brief.cta == "Lưu video để xem lại"
    assert (settings.data_dir / "jobs" / job_id / "plan.v2.json").exists()
    assert planner.calls == [("revise", Plan.model_validate(plan_dict), "Đổi CTA")]


async def test_failed_revise_keeps_the_previous_plan(settings, engine, plan_dict):
    service, _ = make_service(settings, engine, PlannerError("Claude từ chối", input_tokens=50))
    job_id = seed_job(engine, settings.data_dir, plan_dict=plan_dict, status=JobStatus.planning)

    await service.revise(job_id, "Đổi CTA")

    job, plan, _ = load(engine, job_id)
    assert (job.status, job.plan_version, job.error) == (JobStatus.awaiting_approval, 1, "Claude từ chối")
    assert plan.to_dict() == plan_dict


async def test_rewrite_scene_passes_the_scene_and_feedback(settings, engine, plan_dict):
    service, planner = make_service(settings, engine, planner_result(plan_dict))
    job_id = seed_job(engine, settings.data_dir, plan_dict=plan_dict, status=JobStatus.planning)

    await service.rewrite_scene(job_id, 3, "sinh động hơn")

    job, _, _ = load(engine, job_id)
    assert (job.status, job.plan_version) == (JobStatus.awaiting_approval, 2)
    assert planner.calls == [("rewrite_scene", Plan.model_validate(plan_dict), 3, "sinh động hơn")]


async def test_unknown_job_is_ignored(settings, engine):
    service, planner = make_service(settings, engine)

    await service.create("missing")

    assert planner.calls == []


async def test_spawn_runs_the_work_in_the_background(settings, engine, plan_dict):
    service, _ = make_service(settings, engine, planner_result(plan_dict))
    job_id = seed_job(engine, settings.data_dir)

    service.spawn(service.create(job_id))
    assert load(engine, job_id)[0].status == JobStatus.planning  # not started yet
    for _ in range(100):
        await asyncio.sleep(0.01)
        if load(engine, job_id)[0].status != JobStatus.planning:
            break

    assert load(engine, job_id)[0].status == JobStatus.awaiting_approval


async def test_shutdown_cancels_work_that_is_still_running(settings, engine):
    class StuckPlanner:
        async def create_plan(self, idea, options):
            await asyncio.Event().wait()

    service = PlanningService(settings, engine, StuckPlanner)
    job_id = seed_job(engine, settings.data_dir)
    service.spawn(service.create(job_id))
    await asyncio.sleep(0.01)

    await asyncio.wait_for(service.shutdown(), timeout=2)

    # Still "planning": the next startup's recover_interrupted() resolves it.
    assert load(engine, job_id)[0].status == JobStatus.planning
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_planning_service.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'app.agent.planning'`.

- [ ] **Step 4: Implement**

Create `app/agent/planning.py`:

```python
"""Runs planner calls for a job in the background and persists the outcome."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

from sqlalchemy import Engine
from sqlmodel import Session

from app import jobstore
from app.agent.planner import PlanOptions, Planner, PlannerError, PlannerResult
from app.config import Settings
from app.models import Job
from app.options import style_prompt
from app.schemas import Plan

log = logging.getLogger("app.planning")

PlannerFactory = Callable[[], Planner]
_PlannerCall = Callable[[Planner, Job, Plan | None], Awaitable[PlannerResult]]


class PlanningService:
    def __init__(self, settings: Settings, engine: Engine, planner_factory: PlannerFactory) -> None:
        self._settings = settings
        self._engine = engine
        self._planner_factory = planner_factory
        self._tasks: set[asyncio.Task[None]] = set()

    def spawn(self, work: Coroutine[Any, Any, None]) -> None:
        task = asyncio.get_running_loop().create_task(work)
        self._tasks.add(task)  # the event loop only keeps weak references to tasks
        task.add_done_callback(self._tasks.discard)

    async def shutdown(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def create(self, job_id: str) -> None:
        async def call(planner: Planner, job: Job, plan: Plan | None) -> PlannerResult:
            options = PlanOptions(
                duration_sec=job.duration_sec,
                aspect=job.aspect,
                voice=job.voice,
                style=style_prompt(job.style, self._settings.config),
            )
            return await planner.create_plan(job.idea, options)

        await self._run(job_id, "create_plan", call)

    async def revise(self, job_id: str, feedback: str) -> None:
        async def call(planner: Planner, job: Job, plan: Plan | None) -> PlannerResult:
            return await planner.revise(plan, feedback)

        await self._run(job_id, "revise", call)

    async def rewrite_scene(self, job_id: str, scene_id: int, feedback: str = "") -> None:
        async def call(planner: Planner, job: Job, plan: Plan | None) -> PlannerResult:
            return await planner.rewrite_scene(plan, scene_id, feedback)

        await self._run(job_id, "rewrite_scene", call)

    async def _run(self, job_id: str, action: str, call: _PlannerCall) -> None:
        with Session(self._engine) as session:
            job = jobstore.get_job(session, job_id)
            if job is None:
                return
            plan = jobstore.load_plan(job)
        claude = self._settings.config.claude

        # Whatever goes wrong, the job must leave "planning": the page polls until it does.
        try:
            planner = self._planner_factory()
            result = await call(planner, job, plan)
            with Session(self._engine) as session:
                jobstore.record_claude_usage(
                    session, job_id, action=action, model=result.model,
                    input_tokens=result.input_tokens, output_tokens=result.output_tokens, config=claude,
                )
                jobstore.save_plan(session, self._settings.data_dir, jobstore.get_job(session, job_id), result.plan)
        except PlannerError as exc:
            self._fail(job_id, action, str(exc), exc.input_tokens, exc.output_tokens)
        except Exception:
            log.exception("Unexpected error while planning job %s", job_id)
            self._fail(job_id, action, "Lỗi không mong muốn khi lập plan. Xem log của máy chủ để biết chi tiết.")

    def _fail(self, job_id: str, action: str, message: str, input_tokens: int = 0, output_tokens: int = 0) -> None:
        claude = self._settings.config.claude
        with Session(self._engine) as session:
            jobstore.record_claude_usage(
                session, job_id, action=action, model=claude.model,
                input_tokens=input_tokens, output_tokens=output_tokens, config=claude,
            )
            jobstore.mark_planning_failed(session, jobstore.get_job(session, job_id), message)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_planning_service.py -q`
Expected: 10 passed.

- [ ] **Step 6: Commit**

```powershell
git add app/agent/planning.py tests/fakes.py tests/helpers.py tests/test_planning_service.py
git commit -m "feat: background planning service that never leaves a job stuck"
```

---

### Task 4: App wiring, base layout with the 4-step header, screen 1

**Files:**
- Create: `app/web/__init__.py` (empty), `app/web/forms.py`, `app/web/views.py`, `app/web/pages.py`, `app/static/app.js`, `app/static/htmx.min.js` (downloaded), `tests/test_pages_index.py`
- Modify: `app/main.py` (whole file), `app/templates/base.html` (whole file), `app/templates/index.html` (whole file), `app/static/app.css` (whole file), `tests/conftest.py` (add `start_app`), `CLAUDE.md` (structure listing)

**Interfaces:**
- Consumes: `app.jobstore` (`get_job`, `list_recent_jobs`, `recover_interrupted`, `INTERRUPTED_MESSAGE`); `app.agent.planning.PlanningService(settings, engine, planner_factory)`, `PlannerFactory`; `app.agent.planner.build_planner(settings)`; `app.options` (`DURATIONS`, `ASPECTS`, `VOICES`, `STYLES`, `DEFAULT_STYLE`); `app.models.Job`, `JobStatus`; `tests.fakes.FakePlanner`; `tests.helpers.seed_job`.
- Produces (from `app.main`): `create_app(settings: Settings | None = None, planner_factory: PlannerFactory | None = None) -> FastAPI`. On startup: `app.state.settings`, `app.state.engine`, `app.state.planning: PlanningService`, `app.state.ffmpeg_error`; interrupted jobs are recovered. `check_binaries` is still imported into `app.main` (an existing test patches `app.main.check_binaries`).
- Produces (from `app.web.forms`): `default_form_values(config: AppConfig) -> dict` with keys `idea`, `duration_sec` (int), `aspect`, `voice`, `style`, `cost_cap_usd` (display string, e.g. `"5"`). (`parse_job_form` is added in Task 5.)
- Produces (from `app.web.views`):
  - `templates` (Jinja2Templates; filters `num` and `clock`), `STEPS`, `STATUS_LABELS: dict[JobStatus, str]`
  - `async get_session(request)` — FastAPI dependency yielding a `Session` on `request.app.state.engine`
  - `current_step(job: Job | None) -> int` (1–4)
  - `fmt_number(value: float, digits: int = 2) -> str` (decimal comma), `fmt_clock(seconds: int) -> str` (`"1:04"`)
  - `job_summary(job) -> dict` — keys `id`, `idea`, `status`, `status_label`, `created_at`
  - `render(request, name: str, context: dict, *, step: int, status_code: int = 200) -> HTMLResponse` — adds `ffmpeg_error`, `steps`, `step`
  - `render_index(request, session, *, values: dict | None = None, errors: dict | None = None, status_code: int = 200) -> HTMLResponse`
- Produces (from `app.web.pages`): `router` with `GET /` (query `job=<id>` pre-fills the form from that job; an unknown id is ignored).
- Produces (fixture): `start_app(*outcomes) -> (TestClient, FakePlanner)` — a started app using the `settings` fixture and a `FakePlanner` with those outcomes; closed automatically.
- Markup contracts later tasks and tests rely on:
  - header step item, on one line: `<li class="step current"><span class="step-dot">1</span>Ý tưởng</li>` (`done` shows `✓` instead of the number; no extra class when pending);
  - `<div id="shell">` wraps header and `<main>`; `<div id="flash" class="flash" role="alert" hidden></div>` sits above `<main>`.

- [ ] **Step 1: Vendor HTMX**

```powershell
curl.exe -L --fail -o app/static/htmx.min.js https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js
(Get-Item app/static/htmx.min.js).Length
Select-String -Path app/static/htmx.min.js -Pattern "htmx" -Quiet
```

Expected: a size around 50,000 bytes and `True`. (If the download is blocked, stop and tell the user — do not substitute a CDN `<script>` tag, the spec asks for no external runtime dependency beyond fonts.)

- [ ] **Step 2: Write the failing tests**

In `tests/conftest.py` add these imports:

```python
from contextlib import ExitStack

from fastapi.testclient import TestClient

from app.main import create_app
from tests.fakes import FakePlanner
```

and append:

```python
@pytest.fixture
def start_app(settings):
    """start_app(*planner_outcomes) -> (client, planner); every started app is closed after the test."""
    with ExitStack() as stack:

        def start(*outcomes):
            planner = FakePlanner(*outcomes)
            app = create_app(settings, planner_factory=lambda: planner)
            return stack.enter_context(TestClient(app)), planner

        yield start
```

Create `tests/test_pages_index.py`:

```python
from datetime import datetime, timezone

from sqlmodel import Session

from app import jobstore
from app.db import init_db, make_engine
from app.models import JobStatus
from tests.helpers import seed_job


def test_form_posts_to_the_api_with_the_defaults_selected(start_app):
    client, _ = start_app()

    text = client.get("/").text

    assert '<form method="post" action="/api/jobs"' in text
    assert '<textarea id="idea" name="idea"' in text
    assert 'id="duration-30" value="30" checked>' in text
    assert 'id="duration-15" value="15">' in text
    assert 'id="aspect-1" value="9:16" checked>' in text
    assert '<option value="vi-female-north" selected>Nữ · miền Bắc</option>' in text
    assert '<option value="office" selected>Văn phòng · chuyên nghiệp</option>' in text
    assert 'name="cost_cap_usd" value="5"' in text
    assert "Lập kế hoạch" in text


def test_header_marks_step_one_as_current(start_app):
    client, _ = start_app()

    text = client.get("/").text

    assert '<li class="step current"><span class="step-dot">1</span>Ý tưởng</li>' in text
    assert '<li class="step"><span class="step-dot">2</span>Duyệt plan</li>' in text
    assert '<li class="step"><span class="step-dot">4</span>Hoàn tất</li>' in text


def test_recent_videos_show_an_empty_state(start_app):
    client, _ = start_app()

    assert "Chưa có video nào" in client.get("/").text


def test_recent_videos_list_jobs_with_status_and_escaped_text(start_app, settings, plan_dict):
    client, _ = start_app()
    engine = client.app.state.engine
    old = seed_job(engine, settings.data_dir, idea="Mẹo <script>alert(1)</script>",
                   status=JobStatus.failed, created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    new = seed_job(engine, settings.data_dir, plan_dict=plan_dict, idea="Ý tưởng mới",
                   created_at=datetime(2026, 1, 2, tzinfo=timezone.utc))

    text = client.get("/").text

    assert "Chưa có video nào" not in text
    assert f'href="/jobs/{new}"' in text and f'href="/jobs/{old}"' in text
    assert text.index("Ý tưởng mới") < text.index("Mẹo")
    assert "Chờ duyệt" in text and "Lỗi" in text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text
    assert "<script>alert(1)</script>" not in text


def test_form_can_be_prefilled_from_an_existing_job(start_app, settings):
    client, _ = start_app()
    job_id = seed_job(client.app.state.engine, settings.data_dir, idea="ý tưởng cũ", duration_sec=60,
                      aspect="1:1", voice="vi-male-north", style="cinematic", cost_cap_usd=2.5)

    text = client.get(f"/?job={job_id}").text

    assert ">ý tưởng cũ</textarea>" in text
    assert 'id="duration-60" value="60" checked>' in text
    assert 'id="aspect-2" value="1:1" checked>' in text
    assert '<option value="vi-male-north" selected>' in text
    assert '<option value="cinematic" selected>' in text
    assert 'name="cost_cap_usd" value="2.5"' in text


def test_prefill_with_an_unknown_job_shows_the_default_form(start_app):
    client, _ = start_app()

    response = client.get("/?job=missing")

    assert response.status_code == 200
    assert 'id="duration-30" value="30" checked>' in response.text


def test_static_scripts_are_served(start_app):
    client, _ = start_app()

    assert "htmx" in client.get("/static/htmx.min.js").text
    assert "htmx:responseError" in client.get("/static/app.js").text


def test_jobs_left_planning_by_a_restart_are_recovered_on_startup(start_app, settings):
    engine = make_engine(settings.data_dir)
    init_db(engine)
    job_id = seed_job(engine, settings.data_dir)
    engine.dispose()

    client, _ = start_app()

    with Session(client.app.state.engine) as session:
        job = jobstore.get_job(session, job_id)
        assert (job.status, job.error) == (JobStatus.failed, jobstore.INTERRUPTED_MESSAGE)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_pages_index.py -q`
Expected: errors — `TypeError: create_app() got an unexpected keyword argument 'planner_factory'`.

- [ ] **Step 4: Write the stylesheet and script**

Replace `app/static/app.css` with:

```css
:root {
  --bg: #F4F2EC;
  --surface: #FFFFFF;
  --border: #DAD6CC;
  --border-soft: #ECE9E1;
  --line: #C9C4B8;
  --text: #17181C;
  --text-2: #33363D;
  --text-muted: #5B5E66;
  --accent: #1D4ED8;
  --accent-dark: #1E3A8A;
  --accent-soft: #E3EAFB;
  --warn: #C2410C;
  --warn-soft: #FDF0E1;
  --warn-text: #9A3412;
  --font-ui: 'Be Vietnam Pro', system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', ui-monospace, monospace;
}

* { box-sizing: border-box; }
[hidden] { display: none !important; }

body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-ui);
}

a { color: var(--accent); }
a:hover { color: var(--accent-dark); }
h1 { margin: 0; font-size: 28px; font-weight: 700; letter-spacing: -0.01em; }
p { margin: 0; }
.muted { color: var(--text-muted); }
.small { font-size: 13px; }

/* Header */
.site-header {
  min-height: 72px;
  padding: 12px 40px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
}
.brand { display: flex; align-items: center; gap: 12px; font-weight: 600; font-size: 16px; color: var(--text); text-decoration: none; }
.brand:hover { color: var(--text); }
.brand-logo {
  width: 32px; height: 32px; border-radius: 8px;
  background: var(--text); color: var(--surface);
  display: flex; align-items: center; justify-content: center;
  font-weight: 700; font-size: 13px;
}
.header-meta { font-size: 13px; color: var(--text-muted); }

.steps { list-style: none; margin: 0; padding: 0; display: flex; align-items: center; gap: 8px; font-size: 14px; }
.step {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 14px; border-radius: 999px;
  border: 1px solid var(--border); color: var(--text-muted);
}
.step + .step::before { content: ""; width: 20px; height: 1px; background: var(--line); margin-left: -36px; margin-right: 22px; }
.step-dot {
  width: 20px; height: 20px; border-radius: 999px;
  border: 1px solid var(--line);
  display: flex; align-items: center; justify-content: center; font-size: 12px;
}
.step.current { background: var(--text); border-color: var(--text); color: var(--surface); font-weight: 600; }
.step.current .step-dot { background: var(--surface); border-color: var(--surface); color: var(--text); }
.step.done { background: var(--accent-soft); border-color: var(--accent-soft); color: var(--accent); font-weight: 500; }
.step.done .step-dot { background: var(--accent); border-color: var(--accent); color: var(--surface); }
.steps { gap: 28px; }

/* Banners */
.banner-warn, .flash, .warn-box {
  padding: 12px 16px; border-radius: 12px;
  background: var(--warn-soft); color: var(--warn-text); border: 1px solid var(--warn);
  font-size: 14px; white-space: pre-line;
}
.banner-warn, .flash { margin: 16px 40px 0; }

/* Layout */
main { padding: 32px 40px 40px; }
.layout { display: flex; gap: 32px; align-items: flex-start; }
.layout > section { flex: 1 1 0; min-width: 0; }
.side { width: 350px; flex-shrink: 0; display: flex; flex-direction: column; gap: 20px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 16px; padding: 24px; }
.card-form { padding: 32px; display: flex; flex-direction: column; gap: 24px; }
.card-head { display: flex; flex-direction: column; gap: 6px; }
.card-title { font-size: 16px; font-weight: 600; }
.stack { display: flex; flex-direction: column; gap: 14px; }

/* Form controls */
.idea-form { display: flex; flex-direction: column; gap: 24px; }
.field { display: flex; flex-direction: column; gap: 8px; border: 0; padding: 0; margin: 0; min-width: 0; }
.field > label, .field > legend, .cap label { font-size: 14px; font-weight: 600; padding: 0; }
.field > legend { margin-bottom: 8px; }
.field-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 24px; }
.field-error { color: var(--warn-text); font-size: 13px; }
textarea, select, input[type="text"], .cap input {
  width: 100%; font-family: inherit; font-size: 15px; color: var(--text);
  background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
}
textarea { padding: 14px; line-height: 1.5; resize: vertical; }
select, input[type="text"], .cap input { height: 44px; padding: 0 12px; }
textarea:focus, select:focus, input:focus { outline: 2px solid var(--accent); outline-offset: -1px; }
#idea { font-size: 17px; border-radius: 12px; }

.segmented { display: flex; gap: 8px; }
.segmented input { position: absolute; opacity: 0; pointer-events: none; }
.segmented label {
  flex: 1; height: 44px; border-radius: 10px; border: 1px solid var(--border);
  display: flex; align-items: center; justify-content: center; font-size: 15px; cursor: pointer;
}
.segmented input:checked + label { border: 1.5px solid var(--accent); background: var(--accent-soft); color: var(--accent); font-weight: 600; }
.segmented input:focus-visible + label { outline: 2px solid var(--accent); }

.form-foot { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding-top: 16px; border-top: 1px solid var(--border-soft); }
.cap { display: flex; align-items: center; gap: 12px; }
.cap input { width: 80px; }

/* Buttons */
button { font-family: inherit; cursor: pointer; }
button:disabled { cursor: not-allowed; opacity: 0.45; }
.btn-primary {
  display: inline-flex; align-items: center; justify-content: center; gap: 10px;
  min-height: 52px; padding: 0 28px; border-radius: 12px; border: 0;
  background: var(--accent); color: var(--surface); font-size: 16px; font-weight: 600; text-decoration: none;
}
.btn-primary:hover:not(:disabled) { background: var(--accent-dark); color: var(--surface); }
.btn-outline {
  min-height: 44px; padding: 0 16px; border-radius: 10px; border: 1px solid var(--text);
  background: var(--surface); color: var(--text); font-size: 15px; font-weight: 600;
}
.btn-small {
  min-height: 44px; padding: 0 14px; border-radius: 8px; border: 1px solid var(--border);
  background: var(--surface); color: var(--text); font-size: 13px;
}
.btn-block { width: 100%; }
.link-center { text-align: center; font-size: 14px; }

/* Screen 1 side column */
.agent-steps { margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 12px; font-size: 14px; line-height: 1.5; color: var(--text-2); }
.empty { border: 1px dashed var(--line); border-radius: 12px; padding: 24px; text-align: center; display: flex; flex-direction: column; gap: 8px; }
.empty strong { font-size: 15px; font-weight: 500; }
.recent { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.recent a {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 10px 12px; border: 1px solid var(--border-soft); border-radius: 10px;
  color: var(--text); text-decoration: none; font-size: 14px;
}
.recent a:hover { border-color: var(--accent); }
.recent-idea { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
.badge { flex-shrink: 0; padding: 2px 10px; border-radius: 999px; font-size: 12px; background: var(--accent-soft); color: var(--accent); }
.badge-planning, .badge-generating, .badge-assembling, .badge-failed { background: var(--warn-soft); color: var(--warn-text); }

/* Planning / status / failed pages */
.center-card { max-width: 640px; margin: 48px auto; text-align: center; display: flex; flex-direction: column; align-items: center; gap: 14px; }
.spinner { width: 36px; height: 36px; border-radius: 999px; border: 3px solid var(--accent-soft); border-top-color: var(--accent); animation: spin 0.9s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spinner { animation: none; } }

/* Screen 2 */
.eyebrow { font-size: 13px; font-weight: 600; color: var(--accent); letter-spacing: 0.04em; }
.review { display: flex; flex-direction: column; gap: 20px; }
.review-head { display: flex; flex-direction: column; gap: 6px; }
.meta { font-size: 14px; color: var(--text-muted); }
.brief { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.brief-item { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 14px; display: flex; flex-direction: column; gap: 4px; }
.brief-label { font-size: 12px; font-weight: 600; color: var(--text-muted); }
.brief-value { font-size: 14px; line-height: 1.4; }
.scenes { display: flex; flex-direction: column; gap: 10px; }
.scene { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 16px 18px; display: flex; gap: 18px; align-items: flex-start; }
.scene-no { width: 80px; flex-shrink: 0; display: flex; flex-direction: column; gap: 2px; }
.scene-title { font-size: 15px; font-weight: 700; }
.scene-time { font-size: 12px; color: var(--text-muted); }
.scene-body { flex: 1 1 0; min-width: 0; display: flex; flex-direction: column; gap: 6px; }
.scene-vo { font-size: 15px; line-height: 1.45; }
.scene-visual { font-size: 13px; color: var(--text-muted); }
.scene-prompt {
  font-family: var(--font-mono); font-size: 12px; color: var(--text-2);
  background: var(--bg); border-radius: 8px; padding: 8px 10px; cursor: pointer;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.scene-prompt.expanded { white-space: normal; overflow-wrap: anywhere; }
.scene-actions { display: flex; gap: 6px; flex-shrink: 0; }
.scene-edit { display: flex; flex-direction: column; gap: 10px; margin-top: 8px; padding-top: 12px; border-top: 1px solid var(--border-soft); }
.scene-edit label { font-size: 13px; font-weight: 600; display: flex; flex-direction: column; gap: 4px; }
.scene-edit textarea { font-size: 14px; padding: 10px; }
.scene-edit .mono { font-family: var(--font-mono); font-size: 12px; }
.scene-edit select { width: 140px; }
.edit-actions { display: flex; gap: 8px; }

.est-row { display: flex; justify-content: space-between; gap: 12px; font-size: 14px; }
.est-row span { color: var(--text-muted); }
.est-row strong { font-weight: 600; text-align: right; }
.est-cost { display: flex; justify-content: space-between; align-items: baseline; padding-top: 14px; border-top: 1px solid var(--border-soft); }
.est-cost span { font-size: 14px; color: var(--text-muted); }
.est-cost strong { font-size: 26px; font-weight: 700; }

@media (max-width: 1000px) {
  .site-header { padding: 12px 20px; }
  .steps { display: none; }
  main { padding: 20px; }
  .layout { flex-direction: column; }
  .side { width: 100%; }
  .brief, .field-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .scene { flex-wrap: wrap; }
  .banner-warn, .flash { margin: 16px 20px 0; }
}
```

Create `app/static/app.js`:

```javascript
// Three small behaviours; everything else is server-rendered HTML + HTMX attributes.
(function () {
  function showFlash(message) {
    var flash = document.getElementById("flash");
    if (!flash) return;
    flash.textContent = message;
    flash.hidden = false;
    flash.scrollIntoView({ block: "nearest" });
  }

  // 1. "Sửa" buttons show/hide their form; a truncated prompt expands on click.
  document.addEventListener("click", function (event) {
    var toggle = event.target.closest("[data-toggle]");
    if (toggle) {
      var target = document.getElementById(toggle.dataset.toggle);
      if (target) target.hidden = !target.hidden;
      return;
    }
    var prompt = event.target.closest(".scene-prompt");
    if (prompt) prompt.classList.toggle("expanded");
  });

  // 2. API errors come back as JSON {"detail": "..."}; show the message above the page.
  document.addEventListener("htmx:responseError", function (event) {
    var message = "Có lỗi xảy ra. Hãy thử lại.";
    try {
      var detail = JSON.parse(event.detail.xhr.responseText).detail;
      if (typeof detail === "string" && detail) message = detail;
    } catch (ignored) {}
    showFlash(message);
  });

  // 3. The server is unreachable.
  document.addEventListener("htmx:sendError", function () {
    showFlash("Không kết nối được tới máy chủ. Hãy kiểm tra rồi thử lại.");
  });
})();
```

- [ ] **Step 5: Write the templates**

Replace `app/templates/base.html` with:

```html
<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{% block title %}AI Văn Phòng · Video Agent{% endblock %}</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700&family=JetBrains+Mono:wght@400&display=swap">
<link rel="stylesheet" href="{{ url_for('static', path='app.css') }}">
<script src="{{ url_for('static', path='htmx.min.js') }}" defer></script>
<script src="{{ url_for('static', path='app.js') }}" defer></script>
</head>
<body>
<div id="shell">
<header class="site-header">
  <a class="brand" href="/"><span class="brand-logo">AV</span>AI Văn Phòng · Video Agent</a>
  <ol class="steps" aria-label="Tiến trình">
    {% for number, label in steps %}
    <li class="step{% if number < step %} done{% elif number == step %} current{% endif %}"><span class="step-dot">{% if number < step %}✓{% else %}{{ number }}{% endif %}</span>{{ label }}</li>
    {% endfor %}
  </ol>
  <div class="header-meta">Veo 3.1 · Gemini API</div>
</header>
{% if ffmpeg_error %}<div class="banner-warn" role="alert">{{ ffmpeg_error }}</div>{% endif %}
<div id="flash" class="flash" role="alert" hidden></div>
<main>{% block content %}{% endblock %}</main>
</div>
</body>
</html>
```

Replace `app/templates/index.html` with:

```html
{% extends "base.html" %}
{% block content %}
<div class="layout">
<section class="card card-form">
  <div class="card-head">
    <h1>Bạn muốn làm video về điều gì?</h1>
    <p class="muted">Nhập 1–3 câu. Agent sẽ tự viết kịch bản, chia cảnh và viết prompt cho Veo.</p>
  </div>
  <form method="post" action="/api/jobs" class="idea-form">
    <div class="field">
      <label for="idea">Ý tưởng</label>
      <textarea id="idea" name="idea" rows="4" required minlength="3" maxlength="1000">{{ values.idea }}</textarea>
      {% if errors.idea %}<p class="field-error">{{ errors.idea }}</p>{% endif %}
    </div>
    <div class="field-grid">
      <fieldset class="field">
        <legend>Thời lượng</legend>
        <div class="segmented">
          {% for duration in durations %}
          <input type="radio" name="duration_sec" id="duration-{{ duration }}" value="{{ duration }}"{% if duration == values.duration_sec %} checked{% endif %}>
          <label for="duration-{{ duration }}">{{ duration }} giây</label>
          {% endfor %}
        </div>
        {% if errors.duration_sec %}<p class="field-error">{{ errors.duration_sec }}</p>{% endif %}
      </fieldset>
      <fieldset class="field">
        <legend>Tỉ lệ khung hình</legend>
        <div class="segmented">
          {% for aspect in aspects %}
          <input type="radio" name="aspect" id="aspect-{{ loop.index }}" value="{{ aspect }}"{% if aspect == values.aspect %} checked{% endif %}>
          <label for="aspect-{{ loop.index }}">{{ aspect }}</label>
          {% endfor %}
        </div>
        {% if errors.aspect %}<p class="field-error">{{ errors.aspect }}</p>{% endif %}
      </fieldset>
      <div class="field">
        <label for="voice">Giọng đọc</label>
        <select id="voice" name="voice">
          {% for key, label in voices.items() %}
          <option value="{{ key }}"{% if key == values.voice %} selected{% endif %}>{{ label }}</option>
          {% endfor %}
        </select>
        {% if errors.voice %}<p class="field-error">{{ errors.voice }}</p>{% endif %}
      </div>
      <div class="field">
        <label for="style">Phong cách hình ảnh</label>
        <select id="style" name="style">
          {% for key, label in styles.items() %}
          <option value="{{ key }}"{% if key == values.style %} selected{% endif %}>{{ label }}</option>
          {% endfor %}
        </select>
        {% if errors.style %}<p class="field-error">{{ errors.style }}</p>{% endif %}
      </div>
    </div>
    <div class="form-foot">
      <div class="field">
        <div class="cap">
          <label for="cap">Trần chi phí</label>
          <input id="cap" name="cost_cap_usd" value="{{ values.cost_cap_usd }}" inputmode="decimal">
          <span class="muted">USD / video</span>
        </div>
        {% if errors.cost_cap_usd %}<p class="field-error">{{ errors.cost_cap_usd }}</p>{% endif %}
      </div>
      <button type="submit" class="btn-primary">Lập kế hoạch →</button>
    </div>
  </form>
</section>
<aside class="side">
  <div class="card stack">
    <div class="card-title">Agent sẽ làm gì</div>
    <ol class="agent-steps">
      <li>Claude phân tích ý tưởng, viết kịch bản và chia cảnh</li>
      <li>Bạn duyệt plan và chi phí dự kiến — chưa tốn tiền video</li>
      <li>Veo sinh từng clip, tự kiểm tra và sinh lại cảnh lỗi</li>
      <li>Lồng giọng đọc, phụ đề, nhạc nền rồi xuất MP4</li>
    </ol>
  </div>
  <div class="card stack">
    <div class="card-title">Video gần đây</div>
    {% if recent %}
    <ul class="recent">
      {% for item in recent %}
      <li><a href="/jobs/{{ item.id }}"><span class="recent-idea">{{ item.idea }}</span><span class="badge badge-{{ item.status }}">{{ item.status_label }}</span></a></li>
      {% endfor %}
    </ul>
    {% else %}
    <div class="empty">
      <strong>Chưa có video nào</strong>
      <span class="muted small">Video bạn tạo sẽ xuất hiện ở đây</span>
    </div>
    {% endif %}
  </div>
</aside>
</div>
{% endblock %}
```

- [ ] **Step 6: Implement the Python side**

Create empty `app/web/__init__.py`.

Create `app/web/forms.py`:

```python
"""The idea form: defaults (parsing is added with the POST route)."""
from __future__ import annotations

from typing import Any

from app.config import AppConfig
from app.options import DEFAULT_STYLE


def default_form_values(config: AppConfig) -> dict[str, Any]:
    return {
        "idea": "",
        "duration_sec": config.defaults.duration_sec,
        "aspect": config.defaults.aspect,
        "voice": config.defaults.voice,
        "style": DEFAULT_STYLE,
        "cost_cap_usd": f"{config.limits.cost_cap_per_job_usd:g}",
    }
```

Create `app/web/views.py`:

```python
"""Jinja setup and the view models shared by HTML pages and the JSON API."""
from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from app import jobstore
from app.models import Job, JobStatus
from app.options import ASPECTS, DURATIONS, STYLES, VOICES
from app.web.forms import default_form_values

APP_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=APP_DIR / "templates")

STEPS = ((1, "Ý tưởng"), (2, "Duyệt plan"), (3, "Đang tạo"), (4, "Hoàn tất"))

STATUS_LABELS: dict[JobStatus, str] = {
    JobStatus.draft: "Nháp",
    JobStatus.planning: "Đang lập plan",
    JobStatus.awaiting_approval: "Chờ duyệt",
    JobStatus.generating: "Đang tạo",
    JobStatus.assembling: "Đang ghép",
    JobStatus.done: "Hoàn tất",
    JobStatus.failed: "Lỗi",
    JobStatus.cancelled: "Đã hủy",
}


def fmt_number(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def fmt_clock(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


templates.env.filters["num"] = fmt_number
templates.env.filters["clock"] = fmt_clock


async def get_session(request: Request) -> AsyncIterator[Session]:
    with Session(request.app.state.engine) as session:
        yield session


def current_step(job: Job | None) -> int:
    if job is None:
        return 1
    if job.status in (JobStatus.generating, JobStatus.assembling, JobStatus.cancelled):
        return 3
    if job.status == JobStatus.done:
        return 4
    if job.status == JobStatus.failed and job.failed_step != "planning":
        return 3
    return 2


def job_summary(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "idea": job.idea,
        "status": job.status.value,
        "status_label": STATUS_LABELS[job.status],
        "created_at": job.created_at.isoformat(),
    }


def render(
    request: Request, name: str, context: dict[str, Any], *, step: int, status_code: int = 200
) -> HTMLResponse:
    base = {"ffmpeg_error": request.app.state.ffmpeg_error, "steps": STEPS, "step": step}
    return templates.TemplateResponse(request, name, base | context, status_code=status_code)


def render_index(
    request: Request,
    session: Session,
    *,
    values: dict[str, Any] | None = None,
    errors: dict[str, str] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    config = request.app.state.settings.config
    context = {
        "values": values or default_form_values(config),
        "errors": errors or {},
        "durations": DURATIONS,
        "aspects": ASPECTS,
        "voices": VOICES,
        "styles": STYLES,
        "recent": [job_summary(job) for job in jobstore.list_recent_jobs(session)],
    }
    return render(request, "index.html", context, step=1, status_code=status_code)
```

Create `app/web/pages.py`:

```python
"""HTML pages."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from app import jobstore
from app.web.forms import default_form_values
from app.web.views import get_session, render_index

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def index(request: Request, job: str | None = None, session: Session = Depends(get_session)):
    values = None
    source = jobstore.get_job(session, job) if job else None
    if source is not None:
        # "Quay lại sửa ý tưởng": start a new job from an earlier one's inputs.
        values = default_form_values(request.app.state.settings.config) | {
            "idea": source.idea,
            "duration_sec": source.duration_sec,
            "aspect": source.aspect,
            "voice": source.voice,
            "style": source.style,
            "cost_cap_usd": f"{source.cost_cap_usd:g}",
        }
    return render_index(request, session, values=values)
```

Replace `app/main.py` with:

```python
"""FastAPI application factory."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session

from app import jobstore
from app.agent.planner import build_planner
from app.agent.planning import PlannerFactory, PlanningService
from app.assembler.ffmpeg import FFmpegNotFoundError, check_binaries
from app.config import Settings, load_settings
from app.db import init_db, make_engine
from app.web import pages

APP_DIR = Path(__file__).resolve().parent
log = logging.getLogger("app")


def create_app(settings: Settings | None = None, planner_factory: PlannerFactory | None = None) -> FastAPI:
    settings = settings or load_settings()
    # Built on first use, not at startup: the app must start without an API key.
    factory = planner_factory or (lambda: build_planner(settings))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.engine = make_engine(settings.data_dir)
        init_db(app.state.engine)
        with Session(app.state.engine) as session:
            recovered = jobstore.recover_interrupted(session)
        if recovered:
            log.warning("Recovered %d job(s) that were planning when the server stopped", recovered)
        app.state.planning = PlanningService(settings, app.state.engine, factory)
        try:
            check_binaries(settings.config.assembler)
            app.state.ffmpeg_error = None
        except FFmpegNotFoundError as exc:
            # Planning and plan review work without FFmpeg, so warn instead of refusing to start.
            log.warning("%s", exc)
            app.state.ffmpeg_error = str(exc)
        yield
        await app.state.planning.shutdown()
        app.state.engine.dispose()

    app = FastAPI(title="AI Video Agent", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
    app.include_router(pages.router)
    return app


app = create_app()
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_pages_index.py tests/test_main.py -q`
Expected: 13 passed (8 new + the 5 existing `test_main.py` tests, unchanged).

- [ ] **Step 8: Update the structure listing in `CLAUDE.md`**

In the `## Cấu trúc thư mục mục tiêu` code block of `CLAUDE.md`, replace the line

```
  main.py              # FastAPI app, routes HTML + API
```

with

```
  main.py              # FastAPI app factory (lifespan, routers)
  options.py           # lựa chọn trên form: thời lượng, tỉ lệ, giọng, phong cách
  jobstore.py          # lưu job, phiên bản plan, chi phí
  web/
    pages.py           # routes HTML: /, /jobs/{id}
    api.py             # routes /api/jobs...
    views.py           # Jinja, view model
    forms.py           # đọc & kiểm tra form ý tưởng
```

and, under `agent/`, add after the `planner.py` line:

```
    plan_rules.py      # quy tắc nghiệp vụ của plan (thời lượng, số từ)
    planning.py        # chạy planner ở nền, lưu kết quả vào job
```

- [ ] **Step 9: Commit**

```powershell
git add app/main.py app/web app/templates app/static tests/conftest.py tests/test_pages_index.py CLAUDE.md
git commit -m "feat: idea form page, 4-step header and app wiring for background planning"
```

---

### Task 5: Create a job, the planning screen, job JSON

**Files:**
- Create: `app/web/api.py`, `app/templates/job_planning.html`, `app/templates/job_failed.html`, `app/templates/job_status.html`, `app/templates/not_found.html`, `tests/test_api_jobs.py`
- Modify: `app/web/forms.py` (add `parse_job_form`), `app/web/views.py` (add `plan_estimate`, `job_detail`), `app/web/pages.py` (add `GET /jobs/{job_id}`), `app/main.py` (include the API router)

**Interfaces:**
- Consumes: Task 4's `render`, `render_index`, `get_session`, `job_summary`, `current_step`, `default_form_values`; `app.jobstore` (`create_job`, `get_job`, `list_recent_jobs`, `list_scenes`, `load_plan`, `job_cost_usd`); `request.app.state.planning` (`spawn`, `create`); `app.agent.estimator.estimate(plan, config, *, video_provider, cap_usd) -> Estimate`, `PriceNotConfiguredError`; `app.options`; `tests.helpers.seed_job`, `wait_until_planned`; fixture `start_app`.
- Produces (from `app.web.forms`): `parse_job_form(form: Mapping[str, Any], config: AppConfig) -> tuple[dict[str, Any], float | None, dict[str, str]]` — `(values to re-render, cost cap, errors by field)`. Missing or blank optional fields take their defaults (FR-01). The cap accepts a decimal comma. The cap is `None` only when `errors` has `cost_cap_usd`.
- Produces (from `app.web.views`):
  - `plan_estimate(settings, job, plan) -> tuple[Estimate | None, str | None]` — `(estimate, None)` or `(None, Vietnamese reason)` when a price is not configured.
  - `job_detail(session, settings, job) -> dict` — `job_summary` plus `duration_sec`, `aspect`, `voice`, `style`, `cost_cap_usd`, `plan_version`, `failed_step`, `error`, `plan` (dict or `None`), `scenes` (`[{scene_no, status, attempts}]`), `cost_usd`, `estimate` (dict or `None`).
- Produces (routes):
  - `POST /api/jobs` (form-encoded) → `303` to `/jobs/{id}`; invalid input → `422` with the form re-rendered.
  - `GET /api/jobs` → JSON list of `job_summary`, newest first.
  - `GET /api/jobs/{job_id}` → JSON `job_detail`; unknown id → `404 {"detail": "Không tìm thấy job."}`.
  - `GET /jobs/{job_id}` → HTML by status: `planning` → `job_planning.html` (polls every 2 s); `failed` → `job_failed.html`; anything else → `job_status.html` (Task 6 adds the review screen for `awaiting_approval`); unknown id → `404` `not_found.html`.
- Produces (in `app.web.api`, used by Task 7): `router`, `job_or_404(session, job_id) -> Job`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_jobs.py`:

```python
from datetime import datetime, timezone

import pytest

from app.agent.planner import PlannerError, PlanOptions
from app.models import JobStatus
from tests.fakes import planner_result
from tests.helpers import seed_job, wait_until_planned

IDEA = "5 việc sếp không biết bạn đang làm bằng AI"


def post_job(client, **data):
    return client.post("/api/jobs", data=data, follow_redirects=False)


def job_id_of(response):
    assert response.status_code == 303, response.text
    location = response.headers["location"]
    assert location.startswith("/jobs/")
    return location.removeprefix("/jobs/")


def test_posting_an_idea_creates_a_job_and_plans_it_in_the_background(start_app, plan_dict):
    client, planner = start_app(planner_result(plan_dict))

    response = post_job(client, idea=f"  {IDEA}  ", duration_sec="60", aspect="1:1",
                        voice="vi-male-north", style="minimal", cost_cap_usd="8")
    job_id = job_id_of(response)
    body = wait_until_planned(client, job_id)

    assert body["status"] == "awaiting_approval"
    assert body["idea"] == IDEA
    assert (body["duration_sec"], body["aspect"], body["voice"], body["style"], body["cost_cap_usd"]) == (
        60, "1:1", "vi-male-north", "minimal", 8.0)
    assert body["plan"] == plan_dict
    assert body["cost_usd"] == 0.022
    assert planner.calls == [
        ("create_plan", IDEA, PlanOptions(
            duration_sec=60, aspect="1:1", voice="vi-male-north",
            style="minimal bright interior, white walls and light wood, soft diffused light")),
    ]


def test_missing_options_take_the_defaults(start_app, plan_dict):
    client, _ = start_app(planner_result(plan_dict))

    body = wait_until_planned(client, job_id_of(post_job(client, idea=IDEA, cost_cap_usd="")))

    assert (body["duration_sec"], body["aspect"], body["voice"], body["style"], body["cost_cap_usd"]) == (
        30, "9:16", "vi-female-north", "office", 5.0)


def test_cost_cap_accepts_a_decimal_comma(start_app, plan_dict):
    client, _ = start_app(planner_result(plan_dict))

    body = wait_until_planned(client, job_id_of(post_job(client, idea=IDEA, cost_cap_usd="2,5")))

    assert body["cost_cap_usd"] == 2.5


@pytest.mark.parametrize(
    "data, message",
    [
        ({"idea": ""}, "Hãy nhập ý tưởng"),
        ({"idea": "   "}, "Hãy nhập ý tưởng"),
        ({"idea": "ab"}, "Hãy nhập ý tưởng"),
        ({"idea": "x" * 1001}, "Ý tưởng quá dài"),
        ({"idea": IDEA, "cost_cap_usd": "0"}, "Trần chi phí phải là số lớn hơn 0"),
        ({"idea": IDEA, "cost_cap_usd": "-1"}, "Trần chi phí phải là số lớn hơn 0"),
        ({"idea": IDEA, "cost_cap_usd": "abc"}, "Trần chi phí phải là số lớn hơn 0"),
        ({"idea": IDEA, "cost_cap_usd": "nan"}, "Trần chi phí phải là số lớn hơn 0"),
        ({"idea": IDEA, "cost_cap_usd": "inf"}, "Trần chi phí phải là số lớn hơn 0"),
        ({"idea": IDEA, "duration_sec": "45"}, "Thời lượng không hợp lệ"),
        ({"idea": IDEA, "aspect": "4:3"}, "Tỉ lệ khung hình không hợp lệ"),
        ({"idea": IDEA, "voice": "robot"}, "Giọng đọc không hợp lệ"),
        ({"idea": IDEA, "style": "x"}, "Phong cách không hợp lệ"),
    ],
)
def test_invalid_input_re_renders_the_form_and_creates_nothing(start_app, data, message):
    client, planner = start_app()

    response = post_job(client, **data)

    assert response.status_code == 422
    assert message in response.text
    assert '<form method="post" action="/api/jobs"' in response.text
    assert client.get("/api/jobs").json() == []
    assert planner.calls == []


def test_the_form_keeps_what_the_user_typed_when_it_is_rejected(start_app):
    client, _ = start_app()

    response = post_job(client, idea=IDEA, duration_sec="60", cost_cap_usd="abc")

    assert f">{IDEA}</textarea>" in response.text
    assert 'id="duration-60" value="60" checked>' in response.text
    assert 'name="cost_cap_usd" value="abc"' in response.text


def test_a_failed_plan_shows_the_error_and_a_way_back(start_app):
    client, _ = start_app(PlannerError("Claude từ chối lập plan cho ý tưởng này."))

    job_id = job_id_of(post_job(client, idea=IDEA))
    body = wait_until_planned(client, job_id)
    page = client.get(f"/jobs/{job_id}")

    assert (body["status"], body["failed_step"]) == ("failed", "planning")
    assert page.status_code == 200
    assert "Claude từ chối lập plan cho ý tưởng này." in page.text
    assert f'href="/?job={job_id}"' in page.text
    assert "hx-trigger" not in page.text


def test_planning_page_polls_and_marks_step_two(start_app, settings):
    client, _ = start_app()
    job_id = seed_job(client.app.state.engine, settings.data_dir)

    text = client.get(f"/jobs/{job_id}").text

    assert "Claude đang lập plan…" in text
    assert f'hx-get="/jobs/{job_id}"' in text
    assert 'hx-trigger="every 2s"' in text
    assert 'hx-select="#shell"' in text
    assert '<li class="step done"><span class="step-dot">✓</span>Ý tưởng</li>' in text
    assert '<li class="step current"><span class="step-dot">2</span>Duyệt plan</li>' in text


def test_planning_page_says_rewriting_when_a_plan_already_exists(start_app, settings, plan_dict):
    client, _ = start_app()
    job_id = seed_job(client.app.state.engine, settings.data_dir, plan_dict=plan_dict, status=JobStatus.planning)

    assert "Claude đang viết lại plan…" in client.get(f"/jobs/{job_id}").text


def test_job_list_is_newest_first(start_app, settings):
    client, _ = start_app()
    engine = client.app.state.engine
    seed_job(engine, settings.data_dir, idea="cũ", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    seed_job(engine, settings.data_dir, idea="mới", created_at=datetime(2026, 1, 2, tzinfo=timezone.utc))

    jobs = client.get("/api/jobs").json()

    assert [(job["idea"], job["status"], job["status_label"]) for job in jobs] == [
        ("mới", "planning", "Đang lập plan"),
        ("cũ", "planning", "Đang lập plan"),
    ]


def test_job_detail_includes_plan_scenes_and_estimate(start_app, settings, plan_dict):
    client, _ = start_app()
    job_id = seed_job(client.app.state.engine, settings.data_dir, plan_dict=plan_dict)

    body = client.get(f"/api/jobs/{job_id}").json()

    assert body["status"] == "awaiting_approval"
    assert body["plan_version"] == 1
    assert body["plan"] == plan_dict
    assert body["scenes"] == [{"scene_no": n, "status": "planned", "attempts": 0} for n in range(1, 6)]
    assert body["estimate"]["total_video_sec"] == 30
    assert body["estimate"]["cost_usd"] == 0
    assert body["error"] is None


def test_unknown_job_is_a_404(start_app):
    client, _ = start_app()

    api = client.get("/api/jobs/missing")
    page = client.get("/jobs/missing")

    assert (api.status_code, api.json()) == (404, {"detail": "Không tìm thấy job."})
    assert page.status_code == 404
    assert "Không tìm thấy" in page.text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_api_jobs.py -q`
Expected: failures — `POST /api/jobs` and `GET /api/jobs…` answer `404`/`405` (the routes do not exist).

- [ ] **Step 3: Write the templates**

Create `app/templates/job_planning.html`:

```html
{% extends "base.html" %}
{% block content %}
<section class="card center-card" hx-get="/jobs/{{ job.id }}" hx-trigger="every 2s" hx-select="#shell" hx-target="#shell" hx-swap="outerHTML">
  <div class="spinner" aria-hidden="true"></div>
  <h1>{% if job.plan_version %}Claude đang viết lại plan…{% else %}Claude đang lập plan…{% endif %}</h1>
  <p>{{ job.idea }}</p>
  <p class="muted small">Thường mất dưới một phút. Trang sẽ tự cập nhật.</p>
</section>
{% endblock %}
```

Create `app/templates/job_failed.html`:

```html
{% extends "base.html" %}
{% block content %}
<section class="card center-card">
  <h1>Không tạo được video</h1>
  <p>{{ job.idea }}</p>
  <p class="muted small">Bước lỗi: {% if job.failed_step == "planning" %}Lập plan{% else %}{{ job.failed_step or "không rõ" }}{% endif %}</p>
  <div class="warn-box" role="alert">{{ job.error or "Không rõ nguyên nhân." }}</div>
  <a class="btn-primary" href="/?job={{ job.id }}">Quay lại sửa ý tưởng</a>
</section>
{% endblock %}
```

Create `app/templates/job_status.html`:

```html
{% extends "base.html" %}
{% block content %}
<section class="card center-card">
  <div class="eyebrow">{{ status_label|upper }}</div>
  <h1>{{ job.idea }}</h1>
  {% if job.status.value == "generating" %}
  <p>Plan đã được duyệt.</p>
  <p class="muted small">Bước sinh video bằng Veo chưa được xây dựng (Giai đoạn 3), nên job dừng ở đây.</p>
  {% endif %}
  <a class="link-center" href="/">Tạo video mới</a>
</section>
{% endblock %}
```

Create `app/templates/not_found.html`:

```html
{% extends "base.html" %}
{% block content %}
<section class="card center-card">
  <h1>Không tìm thấy video này</h1>
  <p class="muted">Đường dẫn không đúng hoặc job đã bị xóa.</p>
  <a class="btn-primary" href="/">Về trang nhập ý tưởng</a>
</section>
{% endblock %}
```

- [ ] **Step 4: Implement**

Replace `app/web/forms.py` with:

```python
"""The idea form: defaults, parsing and validation."""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from app.config import AppConfig
from app.options import ASPECTS, DEFAULT_STYLE, DURATIONS, STYLES, VOICES

MAX_IDEA_CHARS = 1000


def default_form_values(config: AppConfig) -> dict[str, Any]:
    return {
        "idea": "",
        "duration_sec": config.defaults.duration_sec,
        "aspect": config.defaults.aspect,
        "voice": config.defaults.voice,
        "style": DEFAULT_STYLE,
        "cost_cap_usd": f"{config.limits.cost_cap_per_job_usd:g}",
    }


def _choose(
    form: Mapping[str, Any],
    name: str,
    choices: Mapping[str, Any],
    message: str,
    values: dict[str, Any],
    errors: dict[str, str],
) -> None:
    raw = str(form.get(name) or "").strip()
    if not raw:
        return  # FR-01: a missing option takes its default
    if raw in choices:
        values[name] = choices[raw]
    else:
        errors[name] = message


def parse_job_form(
    form: Mapping[str, Any], config: AppConfig
) -> tuple[dict[str, Any], float | None, dict[str, str]]:
    """Return (values to show again, cost cap, errors by field name)."""
    values = default_form_values(config)
    errors: dict[str, str] = {}

    idea = str(form.get("idea") or "").strip()
    values["idea"] = idea
    if len(idea) < 3:
        errors["idea"] = "Hãy nhập ý tưởng (ít nhất 3 ký tự)."
    elif len(idea) > MAX_IDEA_CHARS:
        errors["idea"] = "Ý tưởng quá dài (tối đa 1.000 ký tự)."

    _choose(form, "duration_sec", {str(d): d for d in DURATIONS}, "Thời lượng không hợp lệ.", values, errors)
    _choose(form, "aspect", {a: a for a in ASPECTS}, "Tỉ lệ khung hình không hợp lệ.", values, errors)
    _choose(form, "voice", {key: key for key in VOICES}, "Giọng đọc không hợp lệ.", values, errors)
    _choose(form, "style", {key: key for key in STYLES}, "Phong cách không hợp lệ.", values, errors)

    cap: float | None = config.limits.cost_cap_per_job_usd
    raw_cap = str(form.get("cost_cap_usd") or "").strip()
    if raw_cap:
        values["cost_cap_usd"] = raw_cap
        try:
            cap = float(raw_cap.replace(",", "."))  # Vietnamese keyboards type 2,5
        except ValueError:
            cap = None
        if cap is None or not math.isfinite(cap) or cap <= 0:
            cap = None
            errors["cost_cap_usd"] = "Trần chi phí phải là số lớn hơn 0."

    return values, cap, errors
```

In `app/web/views.py` add these imports:

```python
from app.agent.estimator import Estimate, PriceNotConfiguredError, estimate
from app.config import Settings
from app.schemas import Plan
```

and append:

```python
def plan_estimate(settings: Settings, job: Job, plan: Plan) -> tuple[Estimate | None, str | None]:
    try:
        result = estimate(
            plan,
            settings.config,
            video_provider=settings.secrets.video_provider,
            cap_usd=job.cost_cap_usd,
        )
    except PriceNotConfiguredError as exc:
        return None, str(exc)
    return result, None


def job_detail(session: Session, settings: Settings, job: Job) -> dict[str, Any]:
    plan = jobstore.load_plan(job)
    estimated = plan_estimate(settings, job, plan)[0] if plan is not None else None
    return job_summary(job) | {
        "duration_sec": job.duration_sec,
        "aspect": job.aspect,
        "voice": job.voice,
        "style": job.style,
        "cost_cap_usd": job.cost_cap_usd,
        "plan_version": job.plan_version,
        "failed_step": job.failed_step,
        "error": job.error,
        "plan": plan.to_dict() if plan is not None else None,
        "scenes": [
            {"scene_no": scene.scene_no, "status": scene.status.value, "attempts": scene.attempts}
            for scene in jobstore.list_scenes(session, job.id)
        ],
        "cost_usd": jobstore.job_cost_usd(session, job.id),
        "estimate": estimated.model_dump() if estimated is not None else None,
    }
```

Create `app/web/api.py`:

```python
"""JSON API under /api. Bodies are form-encoded so plain forms and HTMX can both call it."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from app import jobstore
from app.models import Job
from app.web.forms import parse_job_form
from app.web.views import get_session, job_detail, job_summary, render_index

router = APIRouter(prefix="/api")


def job_or_404(session: Session, job_id: str) -> Job:
    job = jobstore.get_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy job.")
    return job


@router.post("/jobs")
async def create_job(request: Request, session: Session = Depends(get_session)):
    settings = request.app.state.settings
    values, cap, errors = parse_job_form(await request.form(), settings.config)
    if errors:
        return render_index(request, session, values=values, errors=errors, status_code=422)
    job = jobstore.create_job(
        session,
        idea=values["idea"],
        duration_sec=values["duration_sec"],
        aspect=values["aspect"],
        voice=values["voice"],
        style=values["style"],
        cost_cap_usd=cap,
    )
    planning = request.app.state.planning
    planning.spawn(planning.create(job.id))
    return RedirectResponse(f"/jobs/{job.id}", status_code=303)


@router.get("/jobs")
async def list_jobs(session: Session = Depends(get_session)):
    return [job_summary(job) for job in jobstore.list_recent_jobs(session, limit=50)]


@router.get("/jobs/{job_id}")
async def get_job(request: Request, job_id: str, session: Session = Depends(get_session)):
    return job_detail(session, request.app.state.settings, job_or_404(session, job_id))
```

In `app/web/pages.py` change the imports to:

```python
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from app import jobstore
from app.models import JobStatus
from app.web.forms import default_form_values
from app.web.views import STATUS_LABELS, current_step, get_session, render, render_index
```

and append:

```python
@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_page(request: Request, job_id: str, session: Session = Depends(get_session)):
    job = jobstore.get_job(session, job_id)
    if job is None:
        return render(request, "not_found.html", {}, step=1, status_code=404)
    step = current_step(job)
    if job.status == JobStatus.planning:
        return render(request, "job_planning.html", {"job": job}, step=step)
    if job.status == JobStatus.failed:
        return render(request, "job_failed.html", {"job": job}, step=step)
    return render(request, "job_status.html", {"job": job, "status_label": STATUS_LABELS[job.status]}, step=step)
```

In `app/main.py` change `from app.web import pages` to `from app.web import api, pages` and add after `app.include_router(pages.router)`:

```python
    app.include_router(api.router)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_api_jobs.py tests/test_pages_index.py -q`
Expected: 31 passed (23 + 8).

- [ ] **Step 6: Commit**

```powershell
git add app/web app/main.py app/templates tests/test_api_jobs.py
git commit -m "feat: create jobs from the idea form, planning screen with polling, job JSON"
```

---

### Task 6: Screen 2 — plan review page and `plan.json` download

**Files:**
- Create: `app/templates/job_review.html`, `tests/test_pages_review.py`
- Modify: `app/web/views.py` (add `scene_rows`, `review_context`), `app/web/pages.py` (render the review screen), `app/web/api.py` (add `GET /api/jobs/{job_id}/plan.json`)

**Interfaces:**
- Consumes: `plan_estimate(settings, job, plan)`, `render`, `current_step`, `fmt_clock`, `fmt_number` (filters `clock`, `num`); `app.options.voice_label`; `app.jobstore.load_plan`; `job_or_404`; `tests.helpers.seed_job`; fixture `start_app`.
- Produces (from `app.web.views`):
  - `scene_rows(plan: Plan) -> list[dict]` — one dict per scene: `scene` (the `app.schemas.Scene`), `time` (e.g. `"0:06–0:12"`, en dash).
  - `review_context(settings, job, plan) -> dict` — keys `job`, `plan`, `rows`, `voice` (label), `cap` (e.g. `"5"`), `estimate` (`Estimate | None`), `estimate_error` (`str | None`), `locked` (bool: no estimate, or over the cap), `fake_video` (bool).
- Produces (routes): `GET /jobs/{job_id}` renders `job_review.html` when the status is `awaiting_approval` and a plan exists; `GET /api/jobs/{job_id}/plan.json` → the plan as a JSON download (`404` when the job has no plan).
- Markup contracts (Task 7's endpoints are already referenced by this template):
  - approve button, on one line: `<button type="button" class="btn-primary btn-block" hx-post="/api/jobs/{id}/approve" hx-swap="none" hx-disabled-elt="this">Duyệt &amp; tạo video</button>`, with ` disabled` inserted before `>` when locked;
  - per scene: an edit form `id="edit-{n}"` (`hidden`, `hx-patch="/api/jobs/{id}/scenes/{n}"`), a `Sửa` button with `data-toggle="edit-{n}"`, a `Viết lại` button with `hx-post="/api/jobs/{id}/scenes/{n}/rewrite"`;
  - revise form: `hx-post="/api/jobs/{id}/revise"` with a `feedback` textarea.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pages_review.py`:

```python
from app.schemas import Plan
from app.web.views import fmt_clock, fmt_number, scene_rows
from tests.helpers import seed_job

APPROVE_OPEN = 'hx-disabled-elt="this">Duyệt &amp; tạo video</button>'
APPROVE_LOCKED = 'hx-disabled-elt="this" disabled>Duyệt &amp; tạo video</button>'


def review_page(start_app, settings, plan_dict, **attrs):
    client, _ = start_app()
    job_id = seed_job(client.app.state.engine, settings.data_dir, plan_dict=plan_dict, **attrs)
    response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    return job_id, response.text, client


def test_formatting_helpers():
    assert (fmt_clock(0), fmt_clock(6), fmt_clock(64)) == ("0:00", "0:06", "1:04")
    assert (fmt_number(12), fmt_number(5.5, 1), fmt_number(0)) == ("12,00", "5,5", "0,00")


def test_scene_timeline_adds_up_scene_durations(plan_dict):
    plan_dict["scenes"][0]["duration_sec"] = 4
    plan_dict["scenes"][1]["duration_sec"] = 8

    rows = scene_rows(Plan.model_validate(plan_dict))

    assert [row["time"] for row in rows] == ["0:00–0:04", "0:04–0:12", "0:12–0:18", "0:18–0:24", "0:24–0:30"]
    assert [row["scene"].id for row in rows] == [1, 2, 3, 4, 5]


def test_review_shows_the_idea_brief_and_every_scene(start_app, settings, plan_dict):
    job_id, text, _ = review_page(start_app, settings, plan_dict)

    assert "PLAN DO CLAUDE ĐỀ XUẤT" in text
    assert "<h1>5 việc sếp không biết bạn đang làm bằng AI</h1>" in text
    assert "30 giây · 9:16 · 5 cảnh · Giọng: Nữ · miền Bắc" in text
    for value in plan_dict["brief"].values():
        assert value in text
    for scene in plan_dict["scenes"]:
        assert f"Cảnh {scene['id']}" in text
        assert scene["voiceover_vi"] in text
        assert scene["visual"] in text
        assert scene["veo_prompt_en"] in text
    assert "0:00–0:06" in text and "0:24–0:30" in text
    assert '<li class="step current"><span class="step-dot">2</span>Duyệt plan</li>' in text
    assert "hx-trigger" not in text  # no polling once the plan is ready


def test_review_wires_the_actions_to_the_api(start_app, settings, plan_dict):
    job_id, text, _ = review_page(start_app, settings, plan_dict)

    assert f'hx-post="/api/jobs/{job_id}/revise"' in text
    assert f'hx-patch="/api/jobs/{job_id}/scenes/2"' in text
    assert f'hx-post="/api/jobs/{job_id}/scenes/2/rewrite"' in text
    assert f'hx-post="/api/jobs/{job_id}/approve"' in text
    assert 'data-toggle="edit-2"' in text and 'id="edit-2"' in text
    assert f'href="/?job={job_id}"' in text
    assert f'href="/api/jobs/{job_id}/plan.json"' in text


def test_estimate_with_the_fake_provider_is_free_and_approvable(start_app, settings, plan_dict):
    _, text, _ = review_page(start_app, settings, plan_dict)

    assert "<strong>30 giây</strong>" in text
    assert "<strong>5 (+ tối đa 5 lần sinh lại)</strong>" in text
    assert "<strong>~5,5 phút</strong>" in text
    assert "<strong>0,00 USD</strong>" in text
    assert "Trần của bạn: 5 USD" in text
    assert "VIDEO_PROVIDER=fake" in text
    assert APPROVE_OPEN in text


def test_estimate_over_the_cap_locks_the_approve_button(start_app, settings, plan_dict):
    settings.secrets.video_provider = "veo"
    settings.config.veo.price_usd_per_second = 0.4

    _, text, _ = review_page(start_app, settings, plan_dict)

    assert "<strong>12,00 USD</strong>" in text
    assert "Tối đa 24,00 USD" in text
    assert "vượt trần" in text
    assert APPROVE_LOCKED in text
    assert "VIDEO_PROVIDER=fake" not in text


def test_estimate_within_a_higher_job_cap_is_approvable(start_app, settings, plan_dict):
    settings.secrets.video_provider = "veo"
    settings.config.veo.price_usd_per_second = 0.4

    _, text, _ = review_page(start_app, settings, plan_dict, cost_cap_usd=15.0)

    assert "Trần của bạn: 15 USD" in text
    assert APPROVE_OPEN in text


def test_missing_veo_price_explains_and_locks(start_app, settings, plan_dict):
    settings.secrets.video_provider = "veo"

    _, text, _ = review_page(start_app, settings, plan_dict)

    assert "veo.price_usd_per_second" in text
    assert APPROVE_LOCKED in text


def test_error_from_a_failed_rewrite_is_shown_above_the_plan(start_app, settings, plan_dict):
    _, text, _ = review_page(start_app, settings, plan_dict, error="Claude từ chối viết lại.")

    assert "Claude từ chối viết lại." in text
    assert "<h1>5 việc sếp" in text


def test_text_from_the_plan_is_escaped(start_app, settings, plan_dict):
    plan_dict["scenes"][0]["visual"] = '<script>alert("x")</script>'
    plan_dict["brief"]["cta"] = "Theo dõi <b>ngay</b>"

    _, text, _ = review_page(start_app, settings, plan_dict, idea="<img src=x onerror=alert(1)>")

    assert "<script>alert" not in text and "<img src=x" not in text and "<b>ngay</b>" not in text
    assert "&lt;script&gt;" in text and "&lt;b&gt;ngay&lt;/b&gt;" in text


def test_plan_json_download(start_app, settings, plan_dict):
    job_id, _, client = review_page(start_app, settings, plan_dict)

    response = client.get(f"/api/jobs/{job_id}/plan.json")

    assert response.status_code == 200
    assert response.json() == plan_dict
    assert response.headers["content-disposition"] == f'attachment; filename="plan-{job_id}.json"'


def test_plan_json_for_a_job_without_a_plan_is_a_404(start_app, settings):
    client, _ = start_app()
    job_id = seed_job(client.app.state.engine, settings.data_dir)

    response = client.get(f"/api/jobs/{job_id}/plan.json")

    assert (response.status_code, response.json()) == (404, {"detail": "Job này chưa có plan."})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_pages_review.py -q`
Expected: collection error — `ImportError: cannot import name 'scene_rows' from 'app.web.views'`.

- [ ] **Step 3: Write the template**

Create `app/templates/job_review.html`:

```html
{% extends "base.html" %}
{% block content %}
<div class="layout">
<section class="review">
  {% if job.error %}<div class="warn-box" role="alert">{{ job.error }}</div>{% endif %}
  <div class="review-head">
    <div class="eyebrow">PLAN DO CLAUDE ĐỀ XUẤT</div>
    <h1>{{ job.idea }}</h1>
    <div class="meta">{{ job.duration_sec }} giây · {{ job.aspect }} · {{ rows|length }} cảnh · Giọng: {{ voice }}</div>
  </div>
  <div class="brief">
    <div class="brief-item"><div class="brief-label">KHÁN GIẢ</div><div class="brief-value">{{ plan.brief.audience }}</div></div>
    <div class="brief-item"><div class="brief-label">HOOK 3 GIÂY</div><div class="brief-value">{{ plan.brief.hook }}</div></div>
    <div class="brief-item"><div class="brief-label">THÔNG ĐIỆP</div><div class="brief-value">{{ plan.brief.key_message }}</div></div>
    <div class="brief-item"><div class="brief-label">CTA</div><div class="brief-value">{{ plan.brief.cta }}</div></div>
  </div>
  <div class="scenes">
    {% for row in rows %}
    {% set scene = row.scene %}
    <article class="scene" id="scene-{{ scene.id }}">
      <div class="scene-no">
        <div class="scene-title">Cảnh {{ scene.id }}</div>
        <div class="scene-time">{{ row.time }}</div>
      </div>
      <div class="scene-body">
        <div class="scene-vo">“{{ scene.voiceover_vi }}”</div>
        <div class="scene-visual">Hình ảnh: {{ scene.visual }}</div>
        <div class="scene-prompt" role="button" tabindex="0" title="Bấm để xem đủ prompt">{{ scene.veo_prompt_en }}</div>
        <form class="scene-edit" id="edit-{{ scene.id }}" hidden hx-patch="/api/jobs/{{ job.id }}/scenes/{{ scene.id }}" hx-swap="none">
          <label>Lời thoại<textarea name="voiceover_vi" rows="2">{{ scene.voiceover_vi }}</textarea></label>
          <label>Phụ đề<input type="text" name="subtitle_vi" value="{{ scene.subtitle_vi }}"></label>
          <label>Mô tả hình ảnh<input type="text" name="visual" value="{{ scene.visual }}"></label>
          <label>Góc máy<input type="text" name="camera" value="{{ scene.camera }}"></label>
          <label>Prompt Veo (tiếng Anh, tối đa 1.000 ký tự)<textarea class="mono" name="veo_prompt_en" rows="4">{{ scene.veo_prompt_en }}</textarea></label>
          <label>Thời lượng
            <select name="duration_sec">
              {% for seconds in (4, 6, 8) %}<option value="{{ seconds }}"{% if seconds == scene.duration_sec %} selected{% endif %}>{{ seconds }} giây</option>{% endfor %}
            </select>
          </label>
          <div class="edit-actions">
            <button type="submit" class="btn-outline">Lưu cảnh {{ scene.id }}</button>
            <button type="button" class="btn-small" data-toggle="edit-{{ scene.id }}">Hủy</button>
          </div>
        </form>
      </div>
      <div class="scene-actions">
        <button type="button" class="btn-small" data-toggle="edit-{{ scene.id }}">Sửa</button>
        <button type="button" class="btn-small" hx-post="/api/jobs/{{ job.id }}/scenes/{{ scene.id }}/rewrite" hx-swap="none" hx-disabled-elt="this">Viết lại</button>
      </div>
    </article>
    {% endfor %}
  </div>
</section>
<aside class="side">
  <div class="card stack">
    <div class="card-title">Ước tính trước khi chạy</div>
    {% if estimate %}
    <div class="est-row"><span>Tổng thời lượng clip</span><strong>{{ estimate.total_video_sec }} giây</strong></div>
    <div class="est-row"><span>Số lượt gọi Veo</span><strong>{{ estimate.veo_calls }} (+ tối đa {{ estimate.veo_calls_max - estimate.veo_calls }} lần sinh lại)</strong></div>
    <div class="est-row"><span>Thời gian dự kiến</span><strong>~{{ estimate.minutes|num(1) }} phút</strong></div>
    <div class="est-cost"><span>Chi phí dự kiến</span><strong>{{ estimate.cost_usd|num }} USD</strong></div>
    {% if estimate.cost_usd_max > estimate.cost_usd %}<p class="muted small">Tối đa {{ estimate.cost_usd_max|num }} USD nếu mọi cảnh đều phải sinh lại.</p>{% endif %}
    <p class="muted small">Trần của bạn: {{ cap }} USD. Agent dừng lại nếu sắp vượt.</p>
    {% if fake_video %}<p class="muted small">Đang dùng provider giả (VIDEO_PROVIDER=fake) nên không tốn tiền video.</p>{% endif %}
    {% if estimate.over_cap %}<div class="warn-box" role="alert">Chi phí dự kiến vượt trần {{ cap }} USD. Hãy rút ngắn video hoặc tạo lại với trần cao hơn.</div>{% endif %}
    {% else %}
    <div class="warn-box" role="alert">{{ estimate_error }}</div>
    {% endif %}
  </div>
  <form class="card stack" hx-post="/api/jobs/{{ job.id }}/revise" hx-swap="none">
    <label class="card-title" for="feedback">Góp ý cho Claude</label>
    <textarea id="feedback" name="feedback" rows="3" required maxlength="2000" placeholder="Ví dụ: hook mạnh hơn, cảnh 3 dùng bảng tính Excel"></textarea>
    <button type="submit" class="btn-outline">Yêu cầu viết lại plan</button>
  </form>
  <button type="button" class="btn-primary btn-block" hx-post="/api/jobs/{{ job.id }}/approve" hx-swap="none" hx-disabled-elt="this"{% if locked %} disabled{% endif %}>Duyệt &amp; tạo video</button>
  <a class="link-center" href="/?job={{ job.id }}">Quay lại sửa ý tưởng</a>
  <a class="link-center" href="/api/jobs/{{ job.id }}/plan.json">Tải plan.json</a>
</aside>
</div>
{% endblock %}
```

- [ ] **Step 4: Implement**

In `app/web/views.py` change the options import to

```python
from app.options import ASPECTS, DURATIONS, STYLES, VOICES, voice_label
```

and append:

```python
def scene_rows(plan: Plan) -> list[dict[str, Any]]:
    rows = []
    start = 0
    for scene in plan.scenes:
        end = start + scene.duration_sec
        rows.append({"scene": scene, "time": f"{fmt_clock(start)}–{fmt_clock(end)}"})
        start = end
    return rows


def review_context(settings: Settings, job: Job, plan: Plan) -> dict[str, Any]:
    estimated, estimate_error = plan_estimate(settings, job, plan)
    return {
        "job": job,
        "plan": plan,
        "rows": scene_rows(plan),
        "voice": voice_label(job.voice),
        "cap": f"{job.cost_cap_usd:g}",
        "estimate": estimated,
        "estimate_error": estimate_error,
        # The server enforces the same rule in POST /approve; this only disables the button.
        "locked": estimated is None or estimated.over_cap,
        "fake_video": settings.secrets.video_provider == "fake",
    }
```

In `app/web/pages.py` add `review_context` to the `app.web.views` import and, in `job_page`, insert before the final `return render(request, "job_status.html", ...)`:

```python
    plan = jobstore.load_plan(job)
    if job.status == JobStatus.awaiting_approval and plan is not None:
        context = review_context(request.app.state.settings, job, plan)
        return render(request, "job_review.html", context, step=step)
```

In `app/web/api.py` change the responses import to

```python
from fastapi.responses import JSONResponse, RedirectResponse
```

and append:

```python
@router.get("/jobs/{job_id}/plan.json")
async def download_plan(job_id: str, session: Session = Depends(get_session)):
    job = job_or_404(session, job_id)
    plan = jobstore.load_plan(job)
    if plan is None:
        raise HTTPException(status_code=404, detail="Job này chưa có plan.")
    return JSONResponse(
        plan.to_dict(),
        headers={"Content-Disposition": f'attachment; filename="plan-{job.id}.json"'},
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_pages_review.py tests/test_api_jobs.py -q`
Expected: 35 passed (12 + 23).

- [ ] **Step 6: Commit**

```powershell
git add app/web app/templates/job_review.html tests/test_pages_review.py
git commit -m "feat: plan review screen with estimate, cap lock and plan.json download"
```

---

### Task 7: Review actions — revise, edit a scene, rewrite a scene, approve

**Files:**
- Modify: `app/web/api.py` (4 routes + 2 helpers)
- Test: `tests/test_api_actions.py`

**Interfaces:**
- Consumes: `job_or_404`; `app.jobstore` (`load_plan`, `save_plan`, `mark_planning`, `mark_approved`); `request.app.state.planning` (`spawn`, `revise(job_id, feedback)`, `rewrite_scene(job_id, scene_id, feedback)`); `app.agent.plan_rules.find_issues(plan, *, duration_sec, aspect) -> list[PlanIssue]` (`.vi`); `app.schemas.Plan`; `plan_estimate`, `job_detail`, `fmt_number` from `app.web.views`; `tests.fakes.planner_result`; `tests.helpers.seed_job`, `wait_until_planned`.
- Produces (routes; bodies form-encoded; success = `200` JSON `job_detail` with header `HX-Refresh: true`; errors = JSON `{"detail": "<Vietnamese>"}`):
  - `POST /api/jobs/{job_id}/revise` — field `feedback` (required, ≤ 2,000 chars) → job `planning`, Claude rewrites in the background.
  - `PATCH /api/jobs/{job_id}/scenes/{scene_no}` — any of `voiceover_vi`, `subtitle_vi`, `visual`, `camera`, `veo_prompt_en`, `duration_sec`; the edited plan must pass the same rules as a Claude plan, otherwise `422` and nothing is saved.
  - `POST /api/jobs/{job_id}/scenes/{scene_no}/rewrite` — optional `feedback` → job `planning`.
  - `POST /api/jobs/{job_id}/approve` — re-checks the estimate on the server; over the cap or no price → `409`; otherwise job `generating`.
  - All four: unknown job → `404`; job not in `awaiting_approval` → `409`; unknown scene → `404`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_actions.py`:

```python
import copy

import pytest

from app.agent.planner import PlannerError
from app.models import JobStatus
from app.schemas import Plan
from tests.fakes import planner_result
from tests.helpers import seed_job, wait_until_planned

ACTIONS = [
    ("POST", "/api/jobs/{id}/revise", {"feedback": "hook mạnh hơn"}),
    ("PATCH", "/api/jobs/{id}/scenes/2", {"visual": "bàn làm việc"}),
    ("POST", "/api/jobs/{id}/scenes/2/rewrite", {}),
    ("POST", "/api/jobs/{id}/approve", {}),
]
ACTION_IDS = ["revise", "edit", "rewrite", "approve"]


def words(count):
    return " ".join(["từ"] * count)


def reviewable(start_app, settings, plan_dict, *outcomes, **attrs):
    client, planner = start_app(*outcomes)
    job_id = seed_job(client.app.state.engine, settings.data_dir, plan_dict=plan_dict, **attrs)
    return client, planner, job_id


def detail(client, job_id):
    return client.get(f"/api/jobs/{job_id}").json()


# --- every action: wrong state, unknown job ---------------------------------------


@pytest.mark.parametrize("method, url, data", ACTIONS, ids=ACTION_IDS)
def test_actions_are_refused_while_the_job_is_not_awaiting_approval(start_app, settings, plan_dict, method, url, data):
    client, planner, job_id = reviewable(start_app, settings, plan_dict, status=JobStatus.planning)

    response = client.request(method, url.format(id=job_id), data=data)

    assert response.status_code == 409
    assert "không ở bước duyệt plan" in response.json()["detail"]
    assert detail(client, job_id)["status"] == "planning"
    assert planner.calls == []


@pytest.mark.parametrize("method, url, data", ACTIONS, ids=ACTION_IDS)
def test_actions_on_an_unknown_job_are_404(start_app, method, url, data):
    client, _ = start_app()

    response = client.request(method, url.format(id="missing"), data=data)

    assert (response.status_code, response.json()) == (404, {"detail": "Không tìm thấy job."})


@pytest.mark.parametrize("method, path", [("PATCH", "scenes/99"), ("POST", "scenes/99/rewrite")])
def test_unknown_scene_is_a_404(start_app, settings, plan_dict, method, path):
    client, planner, job_id = reviewable(start_app, settings, plan_dict)

    response = client.request(method, f"/api/jobs/{job_id}/{path}", data={"visual": "x"})

    assert (response.status_code, response.json()) == (404, {"detail": "Không tìm thấy cảnh 99."})
    assert planner.calls == []
    assert detail(client, job_id)["status"] == "awaiting_approval"


# --- revise ---------------------------------------------------------------------


def test_revise_sends_the_feedback_to_claude_and_stores_the_new_version(start_app, settings, plan_dict):
    revised = copy.deepcopy(plan_dict)
    revised["brief"]["cta"] = "Lưu video để xem lại"
    client, planner, job_id = reviewable(start_app, settings, plan_dict, planner_result(revised))

    response = client.post(f"/api/jobs/{job_id}/revise", data={"feedback": "  Đổi CTA  "})
    body = wait_until_planned(client, job_id)

    assert response.status_code == 200
    assert response.headers["hx-refresh"] == "true"
    assert response.json()["status"] == "planning"
    assert (body["status"], body["plan_version"]) == ("awaiting_approval", 2)
    assert body["plan"]["brief"]["cta"] == "Lưu video để xem lại"
    assert planner.calls == [("revise", Plan.model_validate(plan_dict), "Đổi CTA")]


@pytest.mark.parametrize("feedback, message", [("", "Hãy nhập góp ý"), ("   ", "Hãy nhập góp ý"), ("x" * 2001, "quá dài")])
def test_revise_needs_usable_feedback(start_app, settings, plan_dict, feedback, message):
    client, planner, job_id = reviewable(start_app, settings, plan_dict)

    response = client.post(f"/api/jobs/{job_id}/revise", data={"feedback": feedback})

    assert response.status_code == 422
    assert message in response.json()["detail"]
    assert planner.calls == []
    assert detail(client, job_id)["status"] == "awaiting_approval"


def test_a_failed_revise_keeps_the_plan_and_shows_the_error(start_app, settings, plan_dict):
    client, _, job_id = reviewable(start_app, settings, plan_dict, PlannerError("Claude từ chối viết lại."))

    client.post(f"/api/jobs/{job_id}/revise", data={"feedback": "Đổi CTA"})
    body = wait_until_planned(client, job_id)
    page = client.get(f"/jobs/{job_id}").text

    assert (body["status"], body["plan_version"], body["error"]) == ("awaiting_approval", 1, "Claude từ chối viết lại.")
    assert body["plan"] == plan_dict
    assert "Claude từ chối viết lại." in page and "PLAN DO CLAUDE ĐỀ XUẤT" in page


# --- manual scene edit ----------------------------------------------------------


def test_editing_a_scene_saves_a_new_plan_version(start_app, settings, plan_dict):
    client, planner, job_id = reviewable(start_app, settings, plan_dict)

    response = client.patch(
        f"/api/jobs/{job_id}/scenes/2",
        data={"voiceover_vi": f"  {words(16)}  ", "subtitle_vi": "Phụ đề mới", "camera": "Máy tĩnh"},
    )

    body = response.json()
    scene = body["plan"]["scenes"][1]
    assert response.status_code == 200
    assert response.headers["hx-refresh"] == "true"
    assert (body["status"], body["plan_version"]) == ("awaiting_approval", 2)
    assert (scene["voiceover_vi"], scene["subtitle_vi"], scene["camera"]) == (words(16), "Phụ đề mới", "Máy tĩnh")
    assert scene["visual"] == plan_dict["scenes"][1]["visual"]
    assert body["plan"]["scenes"][0] == plan_dict["scenes"][0]
    assert "Phụ đề mới" in (settings.data_dir / "jobs" / job_id / "plan.json").read_text(encoding="utf-8")
    assert planner.calls == []


def test_editing_a_scene_duration_within_tolerance_is_allowed(start_app, settings, plan_dict):
    client, _, job_id = reviewable(start_app, settings, plan_dict)

    response = client.patch(f"/api/jobs/{job_id}/scenes/1", data={"duration_sec": "8"})

    assert response.status_code == 200
    assert response.json()["plan"]["scenes"][0]["duration_sec"] == 8


@pytest.mark.parametrize(
    "data, message",
    [
        ({"voiceover_vi": words(25)}, "Cảnh 2: lời thoại có 25 từ, tối đa 19 từ cho cảnh 6 giây"),
        ({"voiceover_vi": "   "}, "Cảnh 2: lời thoại không được để trống"),
        ({"subtitle_vi": words(13)}, "Cảnh 2: phụ đề có 13 từ, tối đa 12 từ"),
        ({"veo_prompt_en": "x" * 1001}, "Prompt Veo dài quá 1.000 ký tự."),
        ({"veo_prompt_en": "An office with a big sign"}, "Cảnh 2: prompt Veo phải kết thúc bằng"),
        ({"duration_sec": "5"}, "Thời lượng cảnh phải là 4, 6 hoặc 8 giây."),
        ({"duration_sec": "abc"}, "Thời lượng cảnh phải là 4, 6 hoặc 8 giây."),
    ],
    ids=["too-many-words", "empty-voiceover", "long-subtitle", "long-prompt", "prompt-allows-text", "duration-5", "duration-text"],
)
def test_an_edit_that_breaks_the_plan_is_rejected_and_nothing_is_saved(start_app, settings, plan_dict, data, message):
    client, _, job_id = reviewable(start_app, settings, plan_dict)

    response = client.patch(f"/api/jobs/{job_id}/scenes/2", data=data)

    assert response.status_code == 422
    assert message in response.json()["detail"]
    body = detail(client, job_id)
    assert (body["plan_version"], body["plan"]) == (1, plan_dict)


# --- rewrite one scene ----------------------------------------------------------


def test_rewrite_scene_asks_claude_for_that_scene(start_app, settings, plan_dict):
    rewritten = copy.deepcopy(plan_dict)
    rewritten["scenes"][2]["visual"] = "Màn hình biểu đồ"
    client, planner, job_id = reviewable(start_app, settings, plan_dict, planner_result(rewritten))

    response = client.post(f"/api/jobs/{job_id}/scenes/3/rewrite", data={"feedback": " sinh động hơn "})
    body = wait_until_planned(client, job_id)

    assert response.status_code == 200
    assert response.headers["hx-refresh"] == "true"
    assert (body["status"], body["plan_version"]) == ("awaiting_approval", 2)
    assert body["plan"]["scenes"][2]["visual"] == "Màn hình biểu đồ"
    assert planner.calls == [("rewrite_scene", Plan.model_validate(plan_dict), 3, "sinh động hơn")]


def test_rewrite_scene_works_without_feedback(start_app, settings, plan_dict):
    client, planner, job_id = reviewable(start_app, settings, plan_dict, planner_result(plan_dict))

    client.post(f"/api/jobs/{job_id}/scenes/3/rewrite")
    wait_until_planned(client, job_id)

    assert planner.calls == [("rewrite_scene", Plan.model_validate(plan_dict), 3, "")]


# --- approve --------------------------------------------------------------------


def test_approve_moves_the_job_to_generating(start_app, settings, plan_dict):
    client, _, job_id = reviewable(start_app, settings, plan_dict)

    response = client.post(f"/api/jobs/{job_id}/approve")
    page = client.get(f"/jobs/{job_id}").text

    assert response.status_code == 200
    assert response.headers["hx-refresh"] == "true"
    assert response.json()["status"] == "generating"
    assert "Plan đã được duyệt." in page
    assert '<li class="step current"><span class="step-dot">3</span>Đang tạo</li>' in page


def test_approving_twice_is_refused(start_app, settings, plan_dict):
    client, _, job_id = reviewable(start_app, settings, plan_dict)
    client.post(f"/api/jobs/{job_id}/approve")

    assert client.post(f"/api/jobs/{job_id}/approve").status_code == 409


def test_approve_is_refused_on_the_server_when_over_the_cap(start_app, settings, plan_dict):
    settings.secrets.video_provider = "veo"
    settings.config.veo.price_usd_per_second = 0.4
    client, _, job_id = reviewable(start_app, settings, plan_dict)

    response = client.post(f"/api/jobs/{job_id}/approve")

    assert response.status_code == 409
    assert response.json()["detail"] == "Chi phí dự kiến 12,00 USD vượt trần 5 USD của video này."
    assert detail(client, job_id)["status"] == "awaiting_approval"


def test_approve_is_refused_when_the_veo_price_is_not_configured(start_app, settings, plan_dict):
    settings.secrets.video_provider = "veo"
    client, _, job_id = reviewable(start_app, settings, plan_dict)

    response = client.post(f"/api/jobs/{job_id}/approve")

    assert response.status_code == 409
    assert "veo.price_usd_per_second" in response.json()["detail"]
    assert detail(client, job_id)["status"] == "awaiting_approval"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_api_actions.py -q`
Expected: failures — the four action routes answer `404` / `405` because they do not exist yet.

- [ ] **Step 3: Implement**

In `app/web/api.py` replace the import block with:

```python
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import ValidationError
from sqlmodel import Session

from app import jobstore
from app.agent.plan_rules import find_issues
from app.models import Job, JobStatus
from app.schemas import Plan
from app.web.forms import parse_job_form
from app.web.views import fmt_number, get_session, job_detail, job_summary, plan_estimate, render_index

router = APIRouter(prefix="/api")

MAX_FEEDBACK_CHARS = 2000
_SCENE_TEXT_FIELDS = ("voiceover_vi", "subtitle_vi", "visual", "camera", "veo_prompt_en")
_SCENE_DURATIONS = {"4": 4, "6": 6, "8": 8}
```

(the existing `router = APIRouter(prefix="/api")` line is part of this block — do not define it twice), and append at the end of the file:

```python
def _reviewable_plan(job: Job) -> Plan:
    plan = jobstore.load_plan(job)
    if job.status != JobStatus.awaiting_approval or plan is None:
        raise HTTPException(
            status_code=409,
            detail="Job không ở bước duyệt plan nên không thực hiện được thao tác này.",
        )
    return plan


def _scene_or_404(plan: Plan, scene_no: int) -> None:
    if scene_no not in {scene.id for scene in plan.scenes}:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy cảnh {scene_no}.")


def _changed(request: Request, session: Session, job: Job) -> JSONResponse:
    # HX-Refresh makes the HTMX page reload itself and re-render from the database.
    body = job_detail(session, request.app.state.settings, job)
    return JSONResponse(body, headers={"HX-Refresh": "true"})


@router.post("/jobs/{job_id}/revise")
async def revise_plan(request: Request, job_id: str, session: Session = Depends(get_session)):
    job = job_or_404(session, job_id)
    _reviewable_plan(job)
    feedback = str((await request.form()).get("feedback") or "").strip()
    if not feedback:
        raise HTTPException(status_code=422, detail="Hãy nhập góp ý cho Claude trước khi yêu cầu viết lại.")
    if len(feedback) > MAX_FEEDBACK_CHARS:
        raise HTTPException(status_code=422, detail="Góp ý quá dài (tối đa 2.000 ký tự).")
    jobstore.mark_planning(session, job)
    planning = request.app.state.planning
    planning.spawn(planning.revise(job.id, feedback))
    return _changed(request, session, job)


@router.patch("/jobs/{job_id}/scenes/{scene_no}")
async def edit_scene(request: Request, job_id: str, scene_no: int, session: Session = Depends(get_session)):
    job = job_or_404(session, job_id)
    plan = _reviewable_plan(job)
    _scene_or_404(plan, scene_no)
    form = await request.form()

    data = plan.to_dict()
    scene = next(item for item in data["scenes"] if item["id"] == scene_no)
    for field in _SCENE_TEXT_FIELDS:
        if field in form:
            scene[field] = str(form[field]).strip()
    if "duration_sec" in form:
        duration = _SCENE_DURATIONS.get(str(form["duration_sec"]).strip())
        if duration is None:
            raise HTTPException(status_code=422, detail="Thời lượng cảnh phải là 4, 6 hoặc 8 giây.")
        scene["duration_sec"] = duration
    if len(scene["veo_prompt_en"]) > 1000:
        raise HTTPException(status_code=422, detail="Prompt Veo dài quá 1.000 ký tự.")

    try:
        edited = Plan.model_validate(data)
    except ValidationError:
        raise HTTPException(status_code=422, detail="Dữ liệu cảnh không hợp lệ.") from None
    # A hand-edited plan must meet the same rules as one from Claude: later phases rely on them.
    issues = find_issues(edited, duration_sec=job.duration_sec, aspect=job.aspect)
    if issues:
        raise HTTPException(status_code=422, detail="\n".join(issue.vi for issue in issues))

    jobstore.save_plan(session, request.app.state.settings.data_dir, job, edited)
    return _changed(request, session, job)


@router.post("/jobs/{job_id}/scenes/{scene_no}/rewrite")
async def rewrite_scene(request: Request, job_id: str, scene_no: int, session: Session = Depends(get_session)):
    job = job_or_404(session, job_id)
    plan = _reviewable_plan(job)
    _scene_or_404(plan, scene_no)
    feedback = str((await request.form()).get("feedback") or "").strip()[:MAX_FEEDBACK_CHARS]
    jobstore.mark_planning(session, job)
    planning = request.app.state.planning
    planning.spawn(planning.rewrite_scene(job.id, scene_no, feedback))
    return _changed(request, session, job)


@router.post("/jobs/{job_id}/approve")
async def approve_plan(request: Request, job_id: str, session: Session = Depends(get_session)):
    job = job_or_404(session, job_id)
    plan = _reviewable_plan(job)
    # The disabled button is only a hint: the cap is enforced here.
    estimated, reason = plan_estimate(request.app.state.settings, job, plan)
    if estimated is None:
        raise HTTPException(status_code=409, detail=reason)
    if estimated.over_cap:
        raise HTTPException(
            status_code=409,
            detail=f"Chi phí dự kiến {fmt_number(estimated.cost_usd)} USD vượt trần "
            f"{job.cost_cap_usd:g} USD của video này.",
        )
    jobstore.mark_approved(session, job)
    return _changed(request, session, job)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/test_api_actions.py -q`
Expected: 30 passed.

- [ ] **Step 5: Run the whole suite**

Run: `.venv\Scripts\python -m pytest -q`
Expected: every test passes — the Phase 0–1 tests plus the new files in this plan (`test_options` 3, `test_jobstore` 12, `test_planning_service` 10, `test_pages_index` 8, `test_api_jobs` 23, `test_pages_review` 12, `test_api_actions` 30, and 3 added to `test_plan_rules`).

- [ ] **Step 6: Commit**

```powershell
git add app/web/api.py tests/test_api_actions.py
git commit -m "feat: revise plan, edit and rewrite a scene, approve with server-side cap check"
```

---

### Task 8: Demo seed script, check in a real browser, finish Giai đoạn 2

**Files:**
- Create: `scripts/seed_demo_job.py`
- Modify: `TASKS.md` (tick Giai đoạn 2)

**Interfaces:**
- Consumes: `app.config.load_settings`, `app.db.make_engine` / `init_db`, `app.jobstore.create_job` / `save_plan`, `app.schemas.Plan`, `tests/fixtures/plan_30s.json`.
- Produces: `scripts/seed_demo_job.py` — inserts one `awaiting_approval` job with the fixture plan into the real `data/` database and prints its URL. Lets anyone see screen 2 without an API key.

The JavaScript in `app/static/app.js` and the CSS have no automated tests; this task is where they are checked.

- [ ] **Step 1: Write the seed script**

Create `scripts/seed_demo_job.py`:

```python
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
```

- [ ] **Step 2: Seed a job and start the server**

```powershell
.venv\Scripts\python scripts\seed_demo_job.py
.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

Expected: the first command prints a URL like `http://127.0.0.1:8000/jobs/1a2b3c4d5e6f`; the second starts the server (run it in the background).

- [ ] **Step 3: Check both screens in a browser against the mockups**

Open the pages in a real browser (browser automation is fine) at 1280 px width and compare with `docs/ui-mockups/01-nhap-y-tuong.dc.html` and `02-duyet-plan.dc.html`. Check each item and fix any that fail (CSS / template only; re-run `pytest -q` after a fix):

1. `http://127.0.0.1:8000/` — cream background, white header with the "AV" logo and four step pills (step 1 black, others outlined); a white card with the idea textarea, the two segmented controls (30 giây and 9:16 highlighted in blue), two selects, the cap input and a blue "Lập kế hoạch →" button; right column with "Agent sẽ làm gì" and "Video gần đây" listing the demo job with a "Chờ duyệt" badge. The font is Be Vietnam Pro.
2. Clicking a different duration highlights it and un-highlights the previous one.
3. The seeded job URL — step 1 pill blue with ✓, step 2 black; the eyebrow, title and meta line; four brief cards in a row; five scene cards with time ranges, voiceover in quotes, "Hình ảnh: …", a single-line monospace prompt cut with an ellipsis; "Sửa" and "Viết lại" on the right; the estimate card, the feedback card, the blue approve button and the two links.
4. Clicking a prompt expands it to full text; clicking again collapses it.
5. Clicking "Sửa" on scene 2 opens the edit form; "Hủy" closes it.
6. In that form, replace the voiceover with 25 words and save → an orange message "Cảnh 2: lời thoại có 25 từ, tối đa 19 từ cho cảnh 6 giây" appears at the top and the scene is unchanged after a reload.
7. Change scene 2's subtitle to `Phụ đề thử` and save → the page reloads; re-open the form and the subtitle shows the new text.
8. Click "Viết lại" on a scene (no API key configured) → the page shows "Claude đang viết lại plan…", then returns to the review screen with the orange message "Thiếu ANTHROPIC_API_KEY trong file .env." and the plan intact.
9. Click "Duyệt & tạo video" → the status page "Plan đã được duyệt." with step 3 black.
10. The browser console shows no JavaScript errors on any of these pages.
11. Narrow the window to about 400 px: the two columns stack and nothing overflows horizontally.

Expected: all eleven hold. Stop the server afterwards.

- [ ] **Step 4: Run the whole suite**

Run: `.venv\Scripts\python -m pytest -q`
Expected: every test passes.

- [ ] **Step 5: Tick Giai đoạn 2 in `TASKS.md` and commit**

In `TASKS.md`, change the five `- [ ]` items under `## Giai đoạn 2 — Giao diện màn 1 & 2` to `- [x]`.

```powershell
git add scripts/seed_demo_job.py TASKS.md app
git commit -m "feat: demo seed script; screens 1 and 2 verified in the browser"
```

**Checkpoint — Giai đoạn 2 is complete.** Report to the user: what was built, the test count, the result of the browser check (with screenshots if taken), and that a real end-to-end run still needs `ANTHROPIC_API_KEY` in `.env`.
