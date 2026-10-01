import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from app.schemas import Plan, load_plan_json_schema

VALIDATOR = Draft202012Validator(load_plan_json_schema())


def _json_schema_errors(data):
    return list(VALIDATOR.iter_errors(data))


def test_fixture_is_valid_for_both_pydantic_and_the_json_schema(plan_dict):
    plan = Plan.model_validate(plan_dict)

    assert _json_schema_errors(plan_dict) == []
    assert len(plan.scenes) == 5
    assert plan.scenes[0].duration_sec == 6
    assert plan.brief.hook.startswith("Sếp không hề biết")


def test_to_dict_round_trips_the_fixture(plan_dict):
    assert Plan.model_validate(plan_dict).to_dict() == plan_dict


def test_optional_fields_are_omitted_or_defaulted(plan_dict):
    del plan_dict["music_mood"]
    del plan_dict["target"]["platform"]

    out = Plan.model_validate(plan_dict).to_dict()

    assert "music_mood" not in out
    assert out["target"]["platform"] == "facebook_reels"
    assert _json_schema_errors(out) == []


def _set(path, value):
    def mutate(data):
        target = data
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value

    return mutate


def _delete(path):
    def mutate(data):
        target = data
        for key in path[:-1]:
            target = target[key]
        del target[path[-1]]

    return mutate


def _keep_scenes(count):
    def mutate(data):
        scenes = data["scenes"]
        data["scenes"] = (scenes * 3)[:count]

    return mutate


INVALID = [
    ("scene_duration_5", _set(["scenes", 0, "duration_sec"], 5)),
    ("scene_duration_as_string", _set(["scenes", 0, "duration_sec"], "6")),
    ("target_duration_20", _set(["target", "duration_sec"], 20)),
    ("aspect_4_3", _set(["target", "aspect"], "4:3")),
    ("unknown_top_level_key", _set(["notes"], "x")),
    ("unknown_scene_key", _set(["scenes", 0, "notes"], "x")),
    ("missing_hook", _delete(["brief", "hook"])),
    ("missing_caption", _delete(["caption_vi"])),
    ("one_scene", _keep_scenes(1)),
    ("thirteen_scenes", _keep_scenes(13)),
    ("veo_prompt_1001_chars", _set(["scenes", 0, "veo_prompt_en"], "x" * 1001)),
    ("idea_two_chars", _set(["idea"], "ab")),
    ("scene_id_zero", _set(["scenes", 0, "id"], 0)),
    ("scene_id_as_string", _set(["scenes", 0, "id"], "1")),
]


@pytest.mark.parametrize("mutate", [m for _, m in INVALID], ids=[name for name, _ in INVALID])
def test_invalid_plans_are_rejected_by_both_pydantic_and_the_json_schema(plan_dict, mutate):
    mutate(plan_dict)

    assert _json_schema_errors(plan_dict), "docs/plan.schema.json accepts this; the test case is wrong"
    with pytest.raises(ValidationError):
        Plan.model_validate(plan_dict)


def test_veo_prompt_of_exactly_1000_chars_is_accepted(plan_dict):
    plan_dict["scenes"][0]["veo_prompt_en"] = "x" * 1000

    assert Plan.model_validate(plan_dict).scenes[0].veo_prompt_en == "x" * 1000
    assert _json_schema_errors(plan_dict) == []
