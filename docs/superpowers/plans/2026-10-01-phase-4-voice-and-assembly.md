# Phase 4: Voice-over, Subtitles, Assembly, Screen 4 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Once a job's clips are approved, it is finished automatically: a Vietnamese voice-over per scene, burned-in subtitles, optional background music and logo, one `final.mp4` — and screen 4 plays it and offers the downloads.

**Architecture:** A `TTSProvider` protocol with `EdgeTTSProvider` (the free `edge-tts` service, chosen by the project owner on 01/10/2026) and `FakeTTSProvider` (silence, for tests). A `Finisher` runs the three idempotent steps — voice (fitted to each scene's length), `subtitles.ass`, one FFmpeg assembly command — as the tail of the job task that `GenerationService` already owns, so logging, SSE and failure handling are shared with clip generation. Jobs found in `assembling` at startup are resumed, because this step costs nothing.

**Tech Stack:** `edge-tts`, FFmpeg/ffprobe (run in a thread with argument lists), libass via FFmpeg's `subtitles` filter, FastAPI, Jinja2, pytest.

**Spec:** `CLAUDE.md`, `TASKS.md` (Giai đoạn 4), `docs/REQUIREMENTS.md` (FR-10, FR-11, FR-12, FR-13), `docs/ARCHITECTURE.md` (thư mục job, API `/video`), `docs/UI_SPEC.md` (Màn 4), `docs/ui-mockups/04-hoan-tat.dc.html`.

**Format note:** design-level plan, as in Phase 3: interfaces, decisions and required tests are fixed here; code is written test-first during execution.

**Scope:** `TASKS.md` Giai đoạn 4. Not here: "Tạo lại một cảnh" on screen 4, cancel, resume-from-failed-step button, daily cost cap (Phase 5); posting to Facebook (after MVP).

## Global Constraints

- **Tests never touch the network.** `edge-tts` is free but is a network service: tests use `FakeTTSProvider` or a fake `Communicate`. Real FFmpeg/ffprobe are used in tests (skipped when missing).
- Facts checked on this machine on 01/10/2026: `edge-tts` 7.2.8; Vietnamese voices `vi-VN-HoaiMyNeural` (female) and `vi-VN-NamMinhNeural` (male) only; output is MP3, 24 kHz mono; an 18-word sentence came out at 6.0 s. It is an unofficial use of Microsoft Edge's read-aloud service: no key, no SLA, it can change or rate-limit without notice — every failure must end in a clear Vietnamese message and a job that can be resumed.
- Output (FR-11): H.264 + AAC MP4, `yuv420p`, `+faststart`; size from the job's aspect with the short side 1080 (9:16 → 1080×1920, 16:9 → 1920×1080, 1:1 → 1080×1080); must not exceed 100 MB.
- Veo clips carry their own audio; it is dropped. Clips may differ in resolution and frame rate (Veo 720p/24 fps); every clip is scaled, cropped and resampled to the output size and 30 fps.
- Each scene's voice track is exactly as long as its clip, so audio stays aligned with scene order (FR-10): shorter speech is padded with silence, longer speech is sped up (at most 1.5×) and, beyond that, cut — with a log line saying so.
- Every step is idempotent (FR-12): an existing `audio/scene_NN.wav` is reused; assembly rewrites `final.mp4` through a temporary name.
- No database schema change (existing `data/app.db` files have no migrations).
- FFmpeg filter paths on Windows contain a drive colon: FFmpeg runs with the job folder as its working directory and filters reference relative paths.
- Windows, `pathlib`, UTF-8 everywhere; `.ass` files are UTF-8.
- Code and comments in English; log lines and UI text in Vietnamese.

## Review Focus

1. **The free TTS misbehaves** — network error, empty audio, a voice key from an older job that no longer exists: retried, then a clear failure; the job is `failed` at step `assembling`, never stuck, and finished audio is reused on the next run. [Tasks 1, 3]
2. **Speech that does not fit its scene** — longer than the clip (sped up, then cut, logged), much shorter (padded), empty voiceover text: the scene track is always exactly the clip's length. [Task 2]
3. **Vietnamese text and awkward characters in subtitles** — diacritics, `{`, `}`, backslashes, line breaks, very long lines, an empty subtitle: rendered as text, never interpreted as ASS codes; a job folder path with spaces. [Tasks 2, 3]
4. **Optional assets are missing or odd** — no music, no logo, no bundled font, a music file shorter than the video: the video is still produced. [Task 3]
5. **A restart during assembly, and old jobs** — a job left in `assembling` (including the ones Phase 3 left there) is resumed at startup and finishes; a job whose clip files are gone fails clearly. Screen 4 for a job whose `final.mp4` was deleted does not 500. [Tasks 3, 4, 5]

---

## File Structure

| File | Responsibility |
| --- | --- |
| `app/providers/base.py` (modify) | adds `TTSProvider` protocol |
| `app/providers/tts_fake.py`, `tts_edge.py` | silence for tests; Edge TTS |
| `app/providers/__init__.py` (modify) | `build_tts_provider(settings)` |
| `app/assembler/ffmpeg.py` (modify) | `run_ffmpeg`, `probe_duration`, `fit_audio`, `output_size`, `assemble` |
| `app/assembler/subtitles.py` | build `subtitles.ass` |
| `app/agent/finisher.py` | `Finisher`: voice → subtitles → assembly → `done` |
| `app/agent/runner.py` (modify) | runs the finisher after generation; `run()` resumes `assembling` jobs |
| `app/jobstore.py` (modify) | paths, `mark_done`, `mark_assembly_failed`, TTS cost, jobs by status |
| `app/web/api.py`, `pages.py`, `views.py` (modify) | `/video`, caption save, screen 3 steps 5–6, screen 4 |
| `app/templates/job_done.html` | screen 4 |
| `app/options.py`, `app/config.py`, `.env.example`, `config.example.yaml` (modify) | two voices; `TTS_PROVIDER=edge`; x264 preset |
| `assets/fonts/` | Be Vietnam Pro (OFL) for subtitles, when it can be downloaded |

---

### Task 1: TTS providers

- `app.providers.base.TTSProvider` (Protocol): `name: str`; `price_usd_per_1k_chars: float`; `async synthesize(text: str, voice: str, path: Path) -> None` — writes an audio file FFmpeg can read; raises `ProviderError` (retryable for network trouble).
- `FakeTTSProvider(ffmpeg_path)`: silence whose length follows the word count (about 2.75 words/s, at least 0.5 s).
- `EdgeTTSProvider(communicate=edge_tts.Communicate)`: maps the app's voice keys to Edge voices (`vi-female-north` and the retired `vi-female-south` → `vi-VN-HoaiMyNeural`, `vi-male-north` → `vi-VN-NamMinhNeural`, anything unknown → the female voice); streams audio chunks to the file; no audio or an empty text → `ProviderError`; network errors → retryable `ProviderError`; a partial file is removed.
- `build_tts_provider(settings)`; `Secrets.tts_provider: Literal["edge", "fake"] = "edge"`.
- Form voices become the two that exist: `vi-female-north` "Nữ (Hoài My)", `vi-male-north` "Nam (Nam Minh)".

- [ ] Tests: fake TTS length and format; Edge provider with a fake `Communicate` (voice mapping incl. legacy and unknown keys, bytes written, no-audio error, network error retryable, partial file removed, empty text refused without a call); factory; options. RED → GREEN → commit.

### Task 2: Audio fitting and subtitles

- `app.assembler.ffmpeg`: `class AssemblyError(Exception)`; `run_ffmpeg(args, *, cwd=None, timeout)` (thread, no shell, Vietnamese error with FFmpeg's last lines); `probe_duration(path, ffprobe_path) -> float`; `fit_audio(src, dst, *, target_sec, cfg) -> FitResult(speed, cut)` → 48 kHz stereo WAV of exactly `target_sec`; `output_size(aspect, cfg) -> (w, h)`.
- `app.assembler.subtitles.build_ass(scenes: list[(start_sec, end_sec, text)], *, size, font) -> str`: ASS v4+, one `Dialogue` per non-empty subtitle, bottom-centre, white with black outline, font size and margins proportional to the frame height; `{`, `}`, `\` and line breaks neutralised.

- [ ] Tests: `fit_audio` on short, exact, long (≤1.5×) and far-too-long inputs — output duration equals the target ±0.05 s, `speed`/`cut` reported; unreadable input → `AssemblyError`; `output_size` for the three aspects; `build_ass` timestamps, escaping, empty subtitle skipped, Vietnamese preserved, play resolution = frame size. RED → GREEN → commit.

### Task 3: Assembly and the finisher

- `assemble(job_folder, *, clips, voices, subtitles, output, size, music, logo, fonts_dir, cfg) -> None`: one FFmpeg run — scale/crop/30 fps each clip, concat, burn subtitles, optional logo overlay (top-right), voice concat, optional looped music ducked under the voice (`sidechaincompress`), H.264/AAC, `+faststart`; written to `final.part.mp4` then renamed. Afterwards the result is probed: wrong size or duration → `AssemblyError`; larger than 100 MB → `AssemblyError`.
- `app.agent.finisher.Finisher(settings, engine, tts_factory, log)`: `async run(job_id)` for a job in `assembling`:
  1. per scene (up to 3 at a time): reuse `audio/scene_NN.wav` or synthesize (3 tries with backoff for retryable errors) to a temp file and `fit_audio`; record TTS cost when a price is configured; log each scene;
  2. write `subtitles.ass`;
  3. `assemble` → `final.mp4`; `mark_done`.
  Any `ProviderError` / `AssemblyError` / missing clip → `mark_assembly_failed` (`failed_step="assembling"`) with the reason; unexpected exception → generic message. Never leaves the job `assembling` without a task.
- `GenerationService(…, finisher=None)`: after the clips are approved, and whenever `run()` is called for a job already in `assembling`, runs the finisher (when one is given) before publishing `end`.
- `jobstore`: `audio_path`, `subtitles_path`, `final_path`, `mark_done`, `mark_assembly_failed`, `record_tts_cost`, `list_job_ids(session, status)`.
- Config: `assembler.x264_preset` (default `medium`), `assembler.fonts_dir` (default `assets/fonts`).

- [ ] Tests (real FFmpeg, fake TTS, small clips from `FakeVideoProvider`): assembled file has the right size, duration = sum of scenes ±0.3 s, one video + one audio stream, H.264/AAC; works with no music/logo/font dir; with a short music file and a logo; clips of different sizes and a 16:9 job; a job folder with a space in its path; finisher happy path → `done`, files on disk, log lines; reuses existing audio (TTS not called again); TTS failure → `failed` at `assembling` with the reason, a retryable error is retried; missing clip → `failed`; unexpected error → `failed`; runner + finisher end to end. RED → GREEN → commit.

### Task 4: API, startup resume, screen 3 steps 5–6

- `create_app(…, tts_factory=None, auto_assemble=True)`; at startup every job in `assembling` is resumed (`generation.run`) when `auto_assemble`.
- `GET /api/jobs/{id}/video` → `final.mp4` (`?download=1` → attachment `video-<id>.mp4`); 404 until the job is `done` and the file exists.
- `POST /api/jobs/{id}/caption` (field `caption`, 1–2,200 chars) → stored as a new plan version without changing job state; only for `done` jobs.
- SSE keeps streaming while the job is `generating` **or** `assembling`.
- Screen 3: step 5 "Giọng đọc + phụ đề" shows `x/N cảnh` while voices are made, step 6 "Ghép MP4" runs after; the Phase 3 "chưa được xây dựng" note is removed.
- `job_detail` gains `video_url`.

- [ ] Tests: approve with fake video + fake TTS runs to `done` and `/video` serves an MP4; `/video` 404 before; download header; caption save (valid, blank, too long, wrong state); startup resume of an `assembling` job; SSE for an assembling job stays open until `end`; screen 3 step states during assembly. RED → GREEN → commit.

### Task 5: Screen 4

- `/jobs/{id}` for `done` → `job_done.html`: `<video controls>` at the job's aspect, "Tải MP4", "Tải plan.json", caption textarea + "Lưu caption" + "Sao chép", three figures (thời gian thực from job creation to `final.mp4`'s timestamp, chi phí thực, số cảnh phải sinh lại), "Tạo video mới". If `final.mp4` is missing: a clear message instead of a broken player.

- [ ] Tests: player source, download links, caption text escaped, the three figures, header step 4 current, missing file message. RED → GREEN → commit.

### Task 6: Real run and finish

- [ ] Bundle the subtitle font if it can be downloaded (Be Vietnam Pro SemiBold + its OFL licence); otherwise subtitles fall back to a system font.
- [ ] Set `TTS_PROVIDER=edge` (the user asked for Edge) and finish the real job Phase 3 left in `assembling` (`b6245ef65564`, three paid Veo clips): real Edge voices, subtitles, `final.mp4`. Watch frames and listen for the checks a test cannot make: subtitle legibility and diacritics, voice present and aligned, no Veo audio left.
- [ ] Full suite green; tick Giai đoạn 4 in `TASKS.md`; update `CLAUDE.md` (TTS decision, structure); commit.
