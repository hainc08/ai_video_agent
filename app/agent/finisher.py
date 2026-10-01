"""Finishes a job whose clips are ready: voice-over per scene, subtitles, one final video."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import Session

from app import jobstore
from app.assembler.ffmpeg import AssemblyError, assemble, fit_audio, output_size
from app.assembler.subtitles import build_ass
from app.config import Settings
from app.models import JobStatus
from app.providers.base import ProviderError, TTSProvider
from app.schemas import Plan, Scene

log = logging.getLogger("app.finisher")

TTSFactory = Callable[[], TTSProvider]
LogLine = Callable[[str, str, str], None]  # (job_id, tag, message)

_TTS_TRIES = 3
_TTS_CONCURRENCY = 3
_BACKOFF_BASE_SEC = 2.0
_MUSIC_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".ogg"}


class Finisher:
    def __init__(self, settings: Settings, engine: Engine, tts_factory: TTSFactory, log_line: LogLine) -> None:
        self._settings = settings
        self._engine = engine
        self._tts_factory = tts_factory
        self._log_line = log_line

    async def run(self, job_id: str) -> None:
        """Take a job in `assembling` to `done`, or to `failed` with a reason. Never raises."""
        with Session(self._engine) as session:
            job = jobstore.get_job(session, job_id)
            if job is None or job.status != JobStatus.assembling:
                return
            plan = jobstore.load_plan(job)
            voice, aspect = job.voice, job.aspect

        # Whatever goes wrong, the job must leave "assembling": the page waits until it does.
        try:
            if plan is None:
                raise AssemblyError("Job không có plan để ghép video.")
            await self._finish(job_id, plan, voice, aspect)
        except (ProviderError, AssemblyError) as exc:
            self._fail(job_id, str(exc))
        except Exception:
            log.exception("Unexpected error while finishing job %s", job_id)
            self._fail(job_id, "Lỗi không mong muốn khi tạo giọng đọc và ghép video. Xem log của máy chủ.")

    async def _finish(self, job_id: str, plan: Plan, voice: str, aspect: str) -> None:
        data_dir = self._settings.data_dir
        cfg = self._settings.config.assembler
        folder = jobstore.job_dir(data_dir, job_id)

        clips = [jobstore.clip_path(data_dir, job_id, scene.id) for scene in plan.scenes]
        for scene, clip in zip(plan.scenes, clips):
            if not clip.exists():
                raise AssemblyError(f"Thiếu clip của cảnh {scene.id} nên không ghép được video.")

        # 1. Voice-over, one track per scene, each exactly as long as its clip.
        tts = self._tts_factory()
        slots = asyncio.Semaphore(_TTS_CONCURRENCY)
        self._log_line(job_id, "tts", f"tạo giọng đọc cho {len(plan.scenes)} cảnh ({tts.name})")
        results = await asyncio.gather(
            *(self._voice(job_id, tts, scene, voice, slots) for scene in plan.scenes), return_exceptions=True
        )
        for result in results:  # only after every scene has stopped, so none is still writing files
            if isinstance(result, BaseException):
                raise result
        voices = [jobstore.audio_path(data_dir, job_id, scene.id) for scene in plan.scenes]

        # 2. Subtitles, timed by the scenes' positions in the video.
        size = output_size(aspect, cfg)
        timeline, start = [], 0
        for scene in plan.scenes:
            timeline.append((start, start + scene.duration_sec, scene.subtitle_vi))
            start += scene.duration_sec
        subtitles = jobstore.subtitles_path(data_dir, job_id)
        subtitles.write_text(build_ass(timeline, size=size, font=cfg.subtitle_font), encoding="utf-8")

        # 3. The final video.
        self._log_line(job_id, "ffmpeg", f"ghép {len(clips)} clip thành video {size[0]}×{size[1]}…")
        final = jobstore.final_path(data_dir, job_id)
        await assemble(
            folder, clips=clips, voices=voices, subtitles=subtitles, output=final, size=size,
            music=self._music(), logo=self._asset(cfg.logo_path), fonts_dir=self._asset(cfg.fonts_dir), cfg=cfg,
        )
        megabytes = final.stat().st_size / 1024 / 1024
        with Session(self._engine) as session:
            job = jobstore.get_job(session, job_id)
            if job is not None and job.status == JobStatus.assembling:
                jobstore.mark_done(session, job)
        self._log_line(job_id, "ffmpeg", f"final.mp4 xong ({megabytes:.1f} MB, {start} giây)")

    async def _voice(self, job_id: str, tts: TTSProvider, scene: Scene, voice: str, slots: asyncio.Semaphore) -> None:
        data_dir = self._settings.data_dir
        target = jobstore.audio_path(data_dir, job_id, scene.id)
        if target.exists() and target.stat().st_size > 0:
            return  # made by an earlier run: reuse it
        raw = target.with_name(target.stem + ".raw.mp3")
        try:
            async with slots:
                await self._synthesize(tts, scene, voice, raw)
            if tts.price_usd_per_1k_chars > 0:
                with Session(self._engine) as session:
                    jobstore.record_tts_cost(
                        session, job_id, provider=tts.name, chars=len(scene.voiceover_vi),
                        price_usd_per_1k_chars=tts.price_usd_per_1k_chars, detail=f"cảnh {scene.id}",
                    )
            fit = await fit_audio(
                raw, target, target_sec=scene.duration_sec, cfg=self._settings.config.assembler
            )
        finally:
            raw.unlink(missing_ok=True)
        note = ""
        if fit.cut:
            note = f" — lời thoại quá dài: đã đọc nhanh ×{fit.speed:.2f} và cắt phần cuối"
        elif fit.speed > 1.02:
            note = f" — đọc nhanh ×{fit.speed:.2f} cho vừa {scene.duration_sec} giây"
        self._log_line(job_id, "tts", f"cảnh {scene.id} → giọng đọc xong{note}")

    async def _synthesize(self, tts: TTSProvider, scene: Scene, voice: str, raw: Path) -> None:
        for attempt in range(1, _TTS_TRIES + 1):
            try:
                await tts.synthesize(scene.voiceover_vi, voice, raw)
                return
            except ProviderError as exc:
                if not exc.retryable or attempt == _TTS_TRIES:
                    raise ProviderError(f"Không tạo được giọng đọc cho cảnh {scene.id}: {exc}") from exc
                await asyncio.sleep(_BACKOFF_BASE_SEC * 2 ** (attempt - 1))

    def _asset(self, relative: str) -> Path | None:
        path = Path(relative)
        path = path if path.is_absolute() else self._settings.root / path
        return path if path.exists() else None

    def _music(self) -> Path | None:
        folder = self._asset(self._settings.config.assembler.music_dir)
        if folder is None or not folder.is_dir():
            return None
        tracks = sorted(p for p in folder.iterdir() if p.suffix.lower() in _MUSIC_SUFFIXES)
        return tracks[0] if tracks else None

    def _fail(self, job_id: str, message: str) -> None:
        try:
            with Session(self._engine) as session:
                job = jobstore.get_job(session, job_id)
                if job is not None and job.status == JobStatus.assembling:
                    jobstore.mark_assembly_failed(session, job, message)
            self._log_line(job_id, "ffmpeg", f"dừng: {message}")
        except Exception:
            log.exception("Could not record the assembly failure for job %s", job_id)
