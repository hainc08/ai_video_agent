import pytest

from app.agent.estimator import PriceNotConfiguredError, estimate, llm_cost_usd
from app.config import ClaudeConfig, GeminiConfig
from app.schemas import Plan


@pytest.fixture
def plan(plan_dict):
    return Plan.model_validate(plan_dict)


def test_fake_provider_costs_nothing(plan, settings):
    result = estimate(plan, settings.config, video_provider="fake")

    assert result.total_video_sec == 30
    assert result.veo_calls == 5
    assert result.veo_calls_max == 10
    assert result.cost_usd == 0
    assert result.cost_usd_max == 0
    assert result.cap_usd == 5
    assert result.over_cap is False


def test_real_provider_cost_and_cap(plan, settings):
    settings.config.veo.price_usd_per_second = 0.4

    result = estimate(plan, settings.config, video_provider="veo")

    assert result.cost_usd == 12.0
    assert result.cost_usd_max == 24.0
    assert result.over_cap is True


def test_job_specific_cap_overrides_the_config_cap(plan, settings):
    settings.config.veo.price_usd_per_second = 0.4

    result = estimate(plan, settings.config, video_provider="veo", cap_usd=15)

    assert result.cap_usd == 15
    assert result.over_cap is False


def test_cost_exactly_at_the_cap_is_allowed(plan, settings):
    settings.config.veo.price_usd_per_second = 0.1  # 30 * 0.1 is 3.0000000000000004 as a float

    result = estimate(plan, settings.config, video_provider="veo", cap_usd=3.0)

    assert result.cost_usd == 3.0
    assert result.over_cap is False


def test_real_provider_without_a_price_refuses_to_estimate(plan, settings):
    assert settings.config.veo.price_usd_per_second is None

    with pytest.raises(PriceNotConfiguredError, match="veo.price_usd_per_second"):
        estimate(plan, settings.config, video_provider="veo")


def test_no_regenerations_means_max_equals_expected(plan, settings):
    settings.config.veo.price_usd_per_second = 0.4
    settings.config.limits.max_regenerations_per_scene = 0

    result = estimate(plan, settings.config, video_provider="veo")

    assert result.veo_calls_max == result.veo_calls == 5
    assert result.cost_usd_max == result.cost_usd == 12.0


def test_time_is_batches_of_concurrent_clips_plus_assembly(plan, settings):
    # 5 scenes, 3 at a time -> 2 batches * 120s + 90s assembly = 330s
    assert estimate(plan, settings.config, video_provider="fake").minutes == 5.5

    settings.config.veo.max_concurrent = 5
    assert estimate(plan, settings.config, video_provider="fake").minutes == 3.5


def test_tts_cost_is_added_when_a_price_is_configured(plan, settings):
    settings.config.tts.price_usd_per_1k_chars = 0.5
    chars = sum(len(scene.voiceover_vi) for scene in plan.scenes)

    result = estimate(plan, settings.config, video_provider="fake")

    assert result.cost_usd == round(chars / 1000 * 0.5, 4)
    assert result.cost_usd_max == result.cost_usd


def test_llm_cost_from_token_counts():
    config = ClaudeConfig(model="m", price_usd_per_mtok_input=2.0, price_usd_per_mtok_output=10.0)

    assert llm_cost_usd(1_000_000, 100_000, config) == 3.0
    assert llm_cost_usd(0, 0, config) == 0

    gemini = GeminiConfig(model="g", price_usd_per_mtok_input=0.75, price_usd_per_mtok_output=3.75)
    assert llm_cost_usd(1_000_000, 1_000_000, gemini) == 4.5


def test_llm_cost_without_prices_is_an_error():
    with pytest.raises(PriceNotConfiguredError, match="price_usd_per_mtok"):
        llm_cost_usd(1000, 1000, ClaudeConfig(model="m"))
