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
