"""Cost (USD) and time estimate for a plan, shown before the user approves it (FR-06)."""
from __future__ import annotations

import math

from pydantic import BaseModel

from app.config import AppConfig, ClaudeConfig, GeminiConfig
from app.schemas import Plan


class PriceNotConfiguredError(Exception):
    """A unit price needed for the estimate is missing from config.yaml."""


class Estimate(BaseModel):
    total_video_sec: int
    veo_calls: int
    veo_calls_max: int
    cost_usd: float
    cost_usd_max: float
    minutes: float
    cap_usd: float
    over_cap: bool


def estimate(
    plan: Plan,
    config: AppConfig,
    *,
    video_provider: str,
    cap_usd: float | None = None,
) -> Estimate:
    scene_count = len(plan.scenes)
    total_sec = sum(scene.duration_sec for scene in plan.scenes)
    max_attempts = 1 + config.limits.max_regenerations_per_scene

    if video_provider == "fake":
        price_per_sec = 0.0
    elif config.veo.price_usd_per_second is None:
        raise PriceNotConfiguredError(
            "Chưa điền veo.price_usd_per_second trong config.yaml nên không ước tính được chi phí."
        )
    else:
        price_per_sec = config.veo.price_usd_per_second

    video_cost = total_sec * price_per_sec
    # The TTS service is not chosen yet; its cost counts only once a price is configured.
    chars = sum(len(scene.voiceover_vi) for scene in plan.scenes)
    tts_cost = chars / 1000 * (config.tts.price_usd_per_1k_chars or 0.0)

    cost = round(video_cost + tts_cost, 4)
    cost_max = round(video_cost * max_attempts + tts_cost, 4)

    batches = math.ceil(scene_count / config.veo.max_concurrent)
    seconds = batches * config.veo.est_clip_generation_sec + config.assembler.est_assembly_sec

    cap = config.limits.cost_cap_per_job_usd if cap_usd is None else cap_usd
    return Estimate(
        total_video_sec=total_sec,
        veo_calls=scene_count,
        veo_calls_max=scene_count * max_attempts,
        cost_usd=cost,
        cost_usd_max=cost_max,
        minutes=round(seconds / 60, 1),
        cap_usd=cap,
        over_cap=cost > cap,
    )


def llm_cost_usd(input_tokens: int, output_tokens: int, config: ClaudeConfig | GeminiConfig) -> float:
    if config.price_usd_per_mtok_input is None or config.price_usd_per_mtok_output is None:
        raise PriceNotConfiguredError(
            "Chưa điền price_usd_per_mtok_input / price_usd_per_mtok_output cho model lập plan trong config.yaml."
        )
    cost = (
        input_tokens * config.price_usd_per_mtok_input
        + output_tokens * config.price_usd_per_mtok_output
    ) / 1_000_000
    return round(cost, 6)
