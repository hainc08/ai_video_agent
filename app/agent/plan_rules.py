"""Business rules a plan must satisfy beyond its JSON structure (FR-03, FR-04, FR-05)."""
from __future__ import annotations

from app.schemas import Plan

# Reading speed is 2.5-3 words/second with 10% tolerance. Kept as integers per 100 seconds
# so the bounds are exact (2.5 * 0.9 = 2.25, 3.0 * 1.1 = 3.30) with no float rounding.
_MIN_WORDS_PER_100_SEC = 225
_MAX_WORDS_PER_100_SEC = 330
DURATION_TOLERANCE_SEC = 2
SUBTITLE_MAX_WORDS = 12
NO_TEXT_MARKER = "no on-screen text"


def count_words(text: str) -> int:
    return sum(1 for token in text.split() if any(ch.isalnum() for ch in token))


def word_bounds(seconds: int) -> tuple[int, int]:
    low = -(-seconds * _MIN_WORDS_PER_100_SEC // 100)  # ceiling division
    high = seconds * _MAX_WORDS_PER_100_SEC // 100
    return low, high


def validate_plan(plan: Plan, *, duration_sec: int, aspect: str) -> list[str]:
    errors: list[str] = []

    if plan.target.duration_sec != duration_sec:
        errors.append(f"target.duration_sec must be {duration_sec}, got {plan.target.duration_sec}")
    if plan.target.aspect != aspect:
        errors.append(f"target.aspect must be {aspect}, got {plan.target.aspect}")

    ids = [scene.id for scene in plan.scenes]
    if ids != list(range(1, len(ids) + 1)):
        errors.append(f"scene ids must be 1..{len(ids)} in order, got {ids}")

    total_sec = sum(scene.duration_sec for scene in plan.scenes)
    if abs(total_sec - duration_sec) > DURATION_TOLERANCE_SEC:
        errors.append(
            f"total scene duration is {total_sec}s, must be within "
            f"{DURATION_TOLERANCE_SEC}s of {duration_sec}s"
        )

    low, high = word_bounds(total_sec)
    total_words = sum(count_words(scene.voiceover_vi) for scene in plan.scenes)
    if not low <= total_words <= high:
        errors.append(
            f"total voiceover is {total_words} words, must be {low}-{high} words "
            f"for {total_sec}s of scenes (2.5-3 words/second)"
        )

    for name in ("audience", "key_message", "hook", "cta"):
        if not getattr(plan.brief, name).strip():
            errors.append(f"brief.{name} must not be empty")

    for scene in plan.scenes:
        words = count_words(scene.voiceover_vi)
        scene_high = word_bounds(scene.duration_sec)[1]
        if words == 0:
            errors.append(f"scene {scene.id}: voiceover_vi must not be empty")
        elif words > scene_high:
            errors.append(
                f"scene {scene.id}: voiceover_vi has {words} words, "
                f"at most {scene_high} fit a {scene.duration_sec}s scene"
            )
        subtitle_words = count_words(scene.subtitle_vi)
        if subtitle_words > SUBTITLE_MAX_WORDS:
            errors.append(
                f"scene {scene.id}: subtitle_vi has {subtitle_words} words, "
                f"at most {SUBTITLE_MAX_WORDS} allowed"
            )
        if NO_TEXT_MARKER not in scene.veo_prompt_en.lower():
            errors.append(
                f"scene {scene.id}: veo_prompt_en must end with 'no on-screen text, no logos'"
            )

    return errors
