# Phase 3: Video Generation (Veo, runner, QC, screen 3) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After the user approves a plan, each scene's clip is generated (in parallel, within the cost cap), checked with ffprobe, regenerated once with a rewritten prompt when it fails, and the user watches it happen live on screen 3.

**Architecture:** A `VideoProvider` protocol (`submit` / `poll` / `download`) with two implementations: `FakeVideoProvider` (FFmpeg test clips, free) and `VeoProvider` (Veo 3.1 through `google-genai`). A `GenerationService` owns one asyncio task per job; inside it each scene runs its own pipeline under a process-wide semaphore. Every state change is written to SQLite and appended to `data/jobs/<id>/log.jsonl`, then published on an in-memory `EventHub`; the SSE endpoint relays hub events and screen 3 re-fetches a server-rendered progress fragment whenever one arrives, so the page is always a view of the database.

**Tech Stack:** FastAPI, sse-starlette, HTMX + a few lines of `EventSource` JS, `google-genai` (Veo), FFmpeg/ffprobe via `asyncio.create_subprocess_exec`, SQLModel, pytest.

**Spec:** `CLAUDE.md`, `TASKS.md` (Giai đoạn 3), `docs/REQUIREMENTS.md` (FR-08, FR-09, FR-12, §5, §6), `docs/ARCHITECTURE.md` (trạng thái cảnh, thư mục job, API), `docs/UI_SPEC.md` (Màn 3, Trạng thái lỗi), `docs/ui-mockups/03-dang-tao.dc.html`.

**Format note:** unlike the Phase 0–2 plans, this plan fixes the design, the interfaces and the tests each task must have, but does not pre-write every line of code. The executor is the plan's author working in the same session under TDD; FFmpeg, SSE and asyncio behaviour is better settled one failing test at a time than typed blind. Every task still follows RED → GREEN → commit.

**Scope:** `TASKS.md` Giai đoạn 3. Not here: TTS, subtitles, assembly, screen 4 (Phase 4); cancel, resume from the failed step, the daily cost cap (Phase 5). When every clip is approved the job moves to `assembling` and screen 3 says the next step is not built yet.

## Global Constraints

- **Tests never call a paid API.** Veo is tested against a fake `google-genai` client; the runner against scripted providers. Default `VIDEO_PROVIDER=fake`.
- **No real Veo call without the user's explicit go-ahead** (CLAUDE.md rule 3). The plan ends at a checkpoint that asks for it.
- Windows, Python 3.11+, `pathlib`; FFmpeg/ffprobe run with an argument list, never a shell.
- Facts about Veo 3.1 on the Gemini API (from https://ai.google.dev/gemini-api/docs/veo and the pricing page, checked 01/10/2026):
  - models `veo-3.1-generate-preview` ($0.40/s at 720p/1080p), `veo-3.1-fast-generate-preview` ($0.10/s at 720p, $0.12/s at 1080p), `veo-3.1-lite-generate-preview` ($0.05/s at 720p, $0.08/s at 1080p); no free tier;
  - aspect ratio **only `16:9` and `9:16`** (no `1:1`);
  - duration 4, 6 or 8 seconds; **1080p and 4k require 8 seconds**;
  - audio is always generated and cannot be switched off (the assembler drops it in Phase 4);
  - one video per request; latency 11 s – 6 min; files stay on the server 2 days;
  - `client.aio.models.generate_videos(model=, prompt=, config=GenerateVideosConfig(aspect_ratio=, duration_seconds=, resolution=))` → operation; `client.aio.operations.get(operation)` until `.done`; `operation.error`; `operation.response.generated_videos[0].video`; `operation.response.rai_media_filtered_count` / `rai_media_filtered_reasons`; `client.aio.files.download(file=video)` then `video.save(path)`.
- Every runner step is idempotent: a scene whose row is `approved` and whose clip file exists is skipped on a re-run.
- The real cost of every Veo clip and every LLM rewrite is written to `CostEntry`.
- The job's cost cap is a hard stop: no clip is submitted if spent + in-flight + this clip would exceed it.
- A background task must never leave a job in `generating` without a running task: every failure path writes a final state, and jobs found in `generating` at startup are failed with an explanation.
- A blocked (safety-filtered) prompt is never retried verbatim: it goes to the LLM for a rewrite, at most `limits.max_regenerations_per_scene` times.
- Code and comments in English; log lines, statuses and messages shown to the user in Vietnamese. No provider name hard-coded in UI text except "Veo" where the mockup names the step.
- Model names and prices stay in config.

## Review Focus

1. **Veo fails in ways that are not "bad clip"** — a submit that errors (quota, auth, 5xx), a poll that never finishes, an operation that ends with `error`, a response with zero videos, a download that fails: the scene and job end in a final state with a Vietnamese reason; transient errors are retried with backoff; nothing loops forever. [Tasks 3, 5]
2. **Money** — the cap is not overshot by clips submitted in parallel; a regeneration counts; a job already at its cap submits nothing; cost is recorded even when the clip later fails QC. [Task 5]
3. **A restart or crash mid-generation** — jobs left in `generating` are failed at startup with an explanation; finished clips are kept; re-running skips approved scenes. [Tasks 4, 5]
4. **Clips that are wrong** — wrong aspect ratio, wrong duration, zero-byte or non-video file: caught by QC, regenerated once with a rewritten prompt, and the job fails clearly if the second clip is also wrong. A rewrite that itself fails does not hang the job. [Tasks 2, 5]
5. **What the form allows but Veo does not** — a `1:1` job or a `1080p` setting with 4/6-second scenes when the real provider is selected: refused before any money is spent (1:1) or handled without an API error (resolution). The SSE stream for a finished, unknown or reconnecting client ends cleanly instead of hanging. [Tasks 3, 6]

---

## File Structure

| File | Responsibility |
| --- | --- |
| `app/providers/base.py` | `ClipRequest`, `PollResult`, `VideoProvider` protocol, `ProviderError`, `ContentFilteredError` |
| `app/providers/fake_video.py` | FFmpeg-made clip: solid colour, scene number, silent audio, right size and length |
| `app/providers/veo_gemini.py` | Veo 3.1 via `google-genai`; `build_video_provider(settings)` lives in `app/providers/__init__.py` |
| `app/agent/qc.py` | `probe_clip`, `check_clip` (ffprobe) |
| `app/events.py` | `EventHub`: per-job fan-out of events to SSE subscribers |
| `app/jobstore.py` (modify) | scene state changes, plan update that keeps job state, Veo cost, job log, recovery of `generating` jobs |
| `app/agent/runner.py` | `GenerationService`: per-job task, per-scene pipeline, semaphore, retries, timeout, cap, QC → rewrite → regenerate |
| `app/web/api.py` (modify) | approve starts the runner; clip file route; SSE route; 1:1 guard |
| `app/web/pages.py`, `views.py` (modify) | screen 3 and its progress fragment |
| `app/main.py` (modify) | wires hub, provider, runner; same-origin check for non-GET requests |
| `app/templates/job_progress.html`, `_progress.html` | screen 3 |
| `app/static/app.js`, `app.css` (modify) | `EventSource` hook, screen 3 styles |
| `config.example.yaml`, `.env.example` (modify) | Veo model table with prices |

---

### Task 1: Provider contract and the fake provider

**Interfaces (produced):**
- `app.providers.base`:
  - `ClipRequest(scene_no: int, prompt: str, aspect: str, duration_sec: int)` — frozen dataclass.
  - `PollResult(state: Literal["running", "done", "failed"], message: str | None = None)`.
  - `class ProviderError(Exception)` with `retryable: bool`; `class ContentFilteredError(ProviderError)` (never retryable; the prompt must be rewritten).
  - `class VideoProvider(Protocol)`: `name: str`; `price_usd_per_second: float`; `supported_aspects: frozenset[str]`; `async submit(request: ClipRequest) -> str`; `async poll(operation_id: str) -> PollResult`; `async download(operation_id: str, path: Path) -> None`.
  - `frame_size(aspect: str) -> tuple[int, int]` — `9:16 → (720, 1280)`, `16:9 → (1280, 720)`, `1:1 → (720, 720)`.
- `app.providers.fake_video.FakeVideoProvider(ffmpeg_path: str)`: `name = "fake"`, price 0, supports all three aspects. `download` runs FFmpeg (`color` + `drawtext` scene number when a font is found, `anullsrc` silent audio, H.264/yuv420p) and writes the file.

- [ ] Tests (`tests/test_fake_video.py`, skipped when FFmpeg is missing): a 4 s 9:16 clip has a 720×1280 video stream of 4.0 s (±0.2) and an audio stream; 16:9 and 1:1 sizes; `poll` of a submitted id is `done`; `poll`/`download` of an unknown id raise `ProviderError`; a wrong FFmpeg path raises `ProviderError` with a Vietnamese message; the output folder is created.
- [ ] RED → implement → GREEN → commit `feat: video provider contract and FFmpeg fake provider`.

### Task 2: Clip QC

**Interfaces (produced, `app.agent.qc`):**
- `ClipInfo(width: int, height: int, duration_sec: float)`.
- `async probe_clip(path: Path, ffprobe_path: str) -> ClipInfo` — raises `QCError` (Vietnamese message) for a missing/empty/unreadable file or a file with no video stream.
- `async check_clip(path, *, aspect: str, duration_sec: int, ffprobe_path: str) -> list[str]` — Vietnamese problems, empty when the clip passes. Aspect within 2 % of the requested ratio; duration within ±1.0 s.

- [ ] Tests (`tests/test_qc.py`, real ffprobe on clips from `FakeVideoProvider`): a correct clip passes; a 16:9 clip checked as 9:16 reports "sai tỉ lệ khung hình"; a 4 s clip checked as 8 s reports "sai thời lượng"; missing file, zero-byte file and a text file renamed `.mp4` each report one clear problem instead of raising; ffprobe missing → `QCError`.
- [ ] RED → implement → GREEN → commit `feat: clip QC with ffprobe`.

### Task 3: Veo provider

**Interfaces (produced, `app.providers.veo_gemini`):**
- `VeoProvider(client, config: VeoConfig)`: `name = "veo"`; `price_usd_per_second = config.price_usd_per_second`; `supported_aspects = {"9:16", "16:9"}`.
  - `submit`: refuses an unsupported aspect with `ProviderError` (not retryable) before calling the API; sends `resolution = config.resolution` only for 8-second clips, otherwise `720p` (1080p/4k require 8 s); returns the operation name and remembers the operation.
  - `poll`: `running` until `operation.done`; `operation.error` → `PollResult("failed", …)`; zero videos with `rai_media_filtered_count` → raises `ContentFilteredError` carrying the reasons; zero videos otherwise → `failed`.
  - `download`: `await client.aio.files.download(file=video)`, then `video.save(path)`; a missing operation → `ProviderError`.
  - API errors: `google.genai.errors.APIError` with code 429/5xx → `ProviderError(retryable=True)`; other codes → `ProviderError(retryable=False)` naming class and code, never the exception text.
- `app.providers.build_video_provider(settings) -> VideoProvider`: `fake` → `FakeVideoProvider`; `veo` → needs `GEMINI_API_KEY` and `veo.price_usd_per_second`, else `ProviderError` with a Vietnamese message.
- `config.example.yaml`: comment table of the three Veo models and prices; `.env.example` notes that `veo` spends money.

- [ ] Tests (`tests/test_veo_provider.py`, fake client): request shape (model, prompt, aspect, duration, resolution rule for 4/6/8 s); poll running → done; operation error; safety-filtered → `ContentFilteredError` with reasons; no videos → failed; download saves the file; 1:1 refused without an API call; 503 retryable, 400 not, no secret text in messages; factory: fake by default, veo without key / without price → clear error.
- [ ] RED → implement → GREEN → commit `feat: Veo 3.1 provider through google-genai`.

### Task 4: Job store, log and event hub for generation

**Interfaces (produced):**
- `app.events.EventHub`: `subscribe(job_id) -> AsyncIterator[dict]` (ends when `close(job_id)` is called), `publish(job_id, event: dict)`, `close(job_id)`. Slow or gone subscribers never block the publisher.
- `app.jobstore`:
  - `get_scene(session, job_id, scene_no) -> Scene | None`; `set_scene(session, scene, *, status, attempts=None, clip_path=..., error=...)`.
  - `update_plan(session, data_dir, job, plan)` — new plan version on disk and in `plan_json`; **keeps** job status and scene rows (used when the runner rewrites one scene's prompt). `save_plan` keeps its current behaviour and shares the file-writing code.
  - `record_video_cost(session, job_id, *, provider: str, model: str, seconds: int, price_usd_per_second: float, detail: str)`.
  - `clip_path(data_dir, job_id, scene_no) -> Path` → `data/jobs/<id>/clips/scene_01.mp4`.
  - `append_log(data_dir, job_id, tag, message) -> dict` and `read_log(data_dir, job_id, limit=200) -> list[dict]` (`log.jsonl`, UTF-8, one JSON object per line with `ts`, `tag`, `message`; unreadable lines are skipped).
  - `mark_generation_failed(session, job, message)` → `failed`, `failed_step="generating"`; `mark_generated(session, job)` → `assembling`.
  - `mark_approved` also clears `job.error`.
  - `recover_interrupted` also fails jobs found in `generating` (their scenes and clips are kept) with `GENERATION_INTERRUPTED_MESSAGE`.

- [ ] Tests (`tests/test_jobstore.py`, `tests/test_events.py`): each function above; `update_plan` leaves status and scene statuses untouched and bumps the version; log round-trips Vietnamese and survives a corrupt line; hub delivers in order to two subscribers, ends on `close`, drops nothing for a subscriber that joined late (it only sees later events), and `publish` with no subscribers is a no-op.
- [ ] RED → implement → GREEN → commit `feat: job store, log and event hub for generation`.

### Task 5: Generation runner

**Interfaces (produced, `app.agent.runner`):**
- `GenerationService(settings, engine, hub, provider_factory, planner_factory)`: `spawn(coro)`, `async shutdown()`, `async run(job_id)`.
- `run(job_id)` for a job in `generating`:
  1. build the provider (a failure → job failed with that message);
  2. for every scene not already `approved` with its clip on disk, run the scene pipeline concurrently, each holding the service-wide `asyncio.Semaphore(veo.max_concurrent)` while it talks to the provider;
  3. scene pipeline, at most `1 + limits.max_regenerations_per_scene` attempts:
     - **cap check** under a lock: `spent + reserved + duration × price > cap` → stop the job (`failed`, "chạm trần chi phí") and submit nothing more;
     - `submit` with up to 3 tries and exponential backoff for retryable errors;
     - `poll` every `veo.poll_interval_sec` until done or `veo.job_timeout_sec` (timeout = failed attempt);
     - on `done`: record the Veo cost, `download` to a temp name then replace the final file, run `check_clip`;
     - pass → scene `approved`; problems / failed operation / `ContentFilteredError` → if attempts remain: scene `regenerating`, ask the planner to rewrite that scene with the reason (one job-wide lock around read-plan → `rewrite_scene` → `update_plan`; LLM cost recorded), then try again with the new prompt; a failed rewrite or no attempts left → scene `failed` and the job fails;
  4. all scenes approved → `mark_generated` (job `assembling`);
  5. any unexpected exception → job failed with a generic Vietnamese message; nothing stays `generating`.
- Each step writes a log line (`[veo] cảnh 2 → hoàn tất, đạt kiểm tra`, …) and publishes `{"type": "update"}`; the end of the run publishes `{"type": "end"}` and closes the hub channel.
- The prompt sent to the provider is `scene.veo_prompt_en` followed by the plan's `style_guide`.

- [ ] Tests (`tests/test_runner.py`, scripted provider + `FakePlanner`, `poll_interval_sec` and backoff patched to ~0): happy path (all approved, clips on disk, job `assembling`, cost entries = seconds × price, log lines, `end` event); concurrency never exceeds `max_concurrent`; QC failure → rewrite → second clip approved, plan version bumped, job state untouched by the rewrite; second failure → scene and job failed with the reason; content-filtered → rewrite, not a verbatim retry; rewrite failure → job failed, not stuck; retryable submit error retried then succeeds; non-retryable → attempt failed; poll timeout; cap: a job whose cap allows only two clips submits exactly two and fails with the cap message; cap not overshot under parallelism; idempotent re-run skips approved scenes and submits only the rest; provider factory error → job failed; unexpected exception → job failed.
- [ ] RED → implement → GREEN → commit `feat: generation runner with QC, one regeneration and a hard cost cap`.

### Task 6: API wiring, SSE, same-origin check

- `create_app(settings, planner_factory=None, provider_factory=None)`; lifespan builds `EventHub` and `GenerationService`, shuts both down.
- `POST /api/jobs/{id}/approve`: additionally refuses (409) an aspect the selected provider does not support, **before** changing state; on success spawns `generation.run(job.id)`.
- Review page: the same aspect problem locks the approve button and is explained in the estimate card.
- `GET /api/jobs/{id}/clips/{scene_no}` → the clip file (404 until the scene has one).
- `GET /api/jobs/{id}/events` → SSE: first an `update` event; then hub events; ends with `end` when the job is not (or no longer) `generating`. Unknown job → 404.
- `job_detail` gains scene `clip_url` and `error`, and `log` (last lines).
- Middleware: a non-GET request whose `Origin` header names a different host than `Host` → 403 (blocks cross-site form posts to the local server).

- [ ] Tests (`tests/test_api_generation.py`): approve with the fake provider runs to `assembling` (real FFmpeg; skipped without it) and clips are served; approve of a 1:1 job with a provider that lacks 1:1 → 409 and nothing spawned; SSE for a finished job yields `update` then `end` and closes; SSE for an unknown job is 404; clip 404 before generation; cross-origin POST → 403, same-origin and no-Origin POST still work.
- [ ] RED → implement → GREEN → commit `feat: approve starts generation; SSE events and clip files`.

### Task 7: Screen 3

- `/jobs/{id}` for `generating` and `assembling` renders `job_progress.html`: left column — title "Đang tạo video", the idea, six steps (Lập plan, Duyệt plan, Sinh clip bằng Veo "x/N cảnh xong", Kiểm tra clip, Giọng đọc + phụ đề, Ghép MP4) with done / running / waiting marks, cost bar "đã dùng / trần"; right column — "Clip theo cảnh" grid of 9:16 tiles (Đạt with a small looping `<video>`, Đang sinh, Đang kiểm tra, Sinh lại · lần k/max, Hàng đợi, Lỗi + reason) and the dark monospace log.
- `/jobs/{id}/progress` returns only the fragment (`_progress.html`, element `#progress`).
- `app.js`: on a page with `data-events-url`, open an `EventSource`; on `update` re-fetch the fragment with `htmx.ajax` and keep the log scrolled to the end; on `end` reload the page. `EventSource` reconnects by itself.
- `assembling`: steps 3–4 done, a note that voice-over and assembly are not built yet (Giai đoạn 4).
- Failed job page: when the failed step is `generating`, show which scenes failed and why.

- [ ] Tests (`tests/test_pages_progress.py`): step states and "x/N cảnh xong" for a mixed job; each scene status label; cost bar numbers; log lines rendered and escaped; `<video>` only for approved scenes; fragment route returns `#progress` without the page shell; `assembling` note; failed page lists the failed scene.
- [ ] RED → implement → GREEN → commit `feat: screen 3 with live progress`.

### Task 8: End-to-end check, then the real-Veo checkpoint

- [ ] Run the server with `VIDEO_PROVIDER=fake`, approve the demo job in a real browser: tiles go Hàng đợi → Đang sinh → Đạt without a manual reload, the log grows, the cost bar stays at 0, the page ends on the `assembling` note, clips play. Check 1280 px and 400 px, and the browser console.
- [ ] Full suite green; tick Giai đoạn 3 in `TASKS.md` except the last item; commit.
- [ ] **Stop and ask the user** before the first real Veo run: which model (standard $0.40/s, fast $0.10/s, lite $0.05/s — a 30 s video is $12 / $3 / $1.50 before regenerations, against the default $5 cap) and confirmation to spend. Only then set `VIDEO_PROVIDER=veo`, the model and its price, and run one short job.
