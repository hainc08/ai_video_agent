import pytest

from app.agent.plan_rules import count_words, validate_plan, word_bounds
from app.schemas import Plan


def _errors(plan_dict, duration_sec=30, aspect="9:16"):
    return validate_plan(Plan.model_validate(plan_dict), duration_sec=duration_sec, aspect=aspect)


def _has(errors, prefix):
    return any(error.startswith(prefix) for error in errors)


def _words(count):
    return " ".join(["từ"] * count)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Sếp không biết", 3),
        ("  nhiều   khoảng\ntrắng\t", 3),
        ("AI – trợ lý", 3),
        ("5 việc: một, hai!", 4),
        ("...", 0),
        ("", 0),
    ],
)
def test_count_words(text, expected):
    assert count_words(text) == expected


@pytest.mark.parametrize(
    "seconds, expected",
    [(4, (9, 13)), (6, (14, 19)), (8, (18, 26)), (16, (36, 52)), (30, (68, 99))],
)
def test_word_bounds(seconds, expected):
    assert word_bounds(seconds) == expected


def test_fixture_plan_is_valid(plan_dict):
    assert _errors(plan_dict) == []


def test_total_duration_two_seconds_over_is_still_valid(plan_dict):
    plan_dict["scenes"][0]["duration_sec"] = 8

    assert _errors(plan_dict) == []


def test_total_duration_far_from_target_is_reported(plan_dict):
    for scene in plan_dict["scenes"]:
        scene["duration_sec"] = 4

    assert _has(_errors(plan_dict), "total scene duration")


def test_target_must_match_the_request(plan_dict):
    errors = _errors(plan_dict, duration_sec=60, aspect="1:1")

    assert _has(errors, "target.duration_sec")
    assert _has(errors, "target.aspect")


def test_too_few_voiceover_words_is_reported(plan_dict):
    for scene in plan_dict["scenes"]:
        scene["voiceover_vi"] = "Xin chào các bạn."

    assert _has(_errors(plan_dict), "total voiceover")


def test_one_overlong_scene_is_reported_even_when_the_total_is_fine(plan_dict):
    plan_dict["scenes"][0]["voiceover_vi"] = _words(20)  # was 17
    plan_dict["scenes"][1]["voiceover_vi"] = _words(13)  # was 16; total stays 83

    errors = _errors(plan_dict)

    assert errors == ["scene 1: voiceover_vi has 20 words, at most 19 fit a 6s scene"]


def test_empty_scene_voiceover_is_reported(plan_dict):
    plan_dict["scenes"][2]["voiceover_vi"] = "   "
    plan_dict["scenes"][0]["voiceover_vi"] = _words(19)
    plan_dict["scenes"][1]["voiceover_vi"] = _words(19)

    assert _has(_errors(plan_dict), "scene 3: voiceover_vi must not be empty")


def test_duplicate_scene_ids_are_reported(plan_dict):
    plan_dict["scenes"][1]["id"] = 1

    assert _has(_errors(plan_dict), "scene ids")


def test_out_of_order_scene_ids_are_reported(plan_dict):
    plan_dict["scenes"].reverse()

    assert _has(_errors(plan_dict), "scene ids")


def test_long_subtitle_is_reported(plan_dict):
    plan_dict["scenes"][3]["subtitle_vi"] = _words(13)

    assert _errors(plan_dict) == ["scene 4: subtitle_vi has 13 words, at most 12 allowed"]


def test_veo_prompt_without_the_no_text_marker_is_reported(plan_dict):
    plan_dict["scenes"][4]["veo_prompt_en"] = "Vertical wide shot of an office at dusk"

    assert _has(_errors(plan_dict), "scene 5: veo_prompt_en")


def test_no_text_marker_is_case_insensitive(plan_dict):
    plan_dict["scenes"][4]["veo_prompt_en"] = "Office at dusk. No On-Screen Text, no logos"

    assert _errors(plan_dict) == []


def test_blank_brief_field_is_reported(plan_dict):
    plan_dict["brief"]["hook"] = "  "

    assert _errors(plan_dict) == ["brief.hook must not be empty"]
