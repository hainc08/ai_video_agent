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
