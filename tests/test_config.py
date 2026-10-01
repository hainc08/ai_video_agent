import pytest

from app.config import ConfigError, load_config, load_settings


def test_falls_back_to_example_when_config_yaml_is_missing(project_root):
    cfg = load_config(project_root)

    assert cfg.claude.model == "claude-sonnet-5-5"
    assert cfg.claude.max_tokens == 16000
    assert cfg.claude.effort == "medium"
    assert cfg.claude.refusal_fallback is True
    assert cfg.claude.price_usd_per_mtok_input == 2.0
    assert cfg.claude.price_usd_per_mtok_output == 10.0
    assert cfg.veo.model == "veo-3.1-generate-preview"
    assert cfg.veo.price_usd_per_second is None
    assert cfg.veo.max_concurrent == 3
    assert cfg.veo.est_clip_generation_sec == 120
    assert cfg.limits.cost_cap_per_job_usd == 5
    assert cfg.limits.max_regenerations_per_scene == 1
    assert cfg.defaults.duration_sec == 30
    assert cfg.defaults.aspect == "9:16"
    assert cfg.assembler.est_assembly_sec == 90


def test_config_yaml_wins_and_missing_sections_use_defaults(project_root):
    (project_root / "config.yaml").write_text(
        "claude:\n  model: claude-opus-5-5\nveo:\n  model: veo-x\n  price_usd_per_second: 0.4\n",
        encoding="utf-8",
    )

    cfg = load_config(project_root)

    assert cfg.claude.model == "claude-opus-5-5"
    assert cfg.veo.price_usd_per_second == 0.4
    assert cfg.limits.cost_cap_per_day_usd == 20
    assert cfg.assembler.ffmpeg_path == "ffmpeg"


def test_reads_utf8_with_bom_and_vietnamese_text(project_root):
    text = 'claude:\n  model: m\nveo:\n  model: v\ndefaults:\n  style: "văn phòng sáng sủa"\n'
    (project_root / "config.yaml").write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))

    assert load_config(project_root).defaults.style == "văn phòng sáng sủa"


def test_empty_config_file_is_a_clear_error(project_root):
    (project_root / "config.yaml").write_text("", encoding="utf-8")

    with pytest.raises(ConfigError, match="config.yaml"):
        load_config(project_root)


def test_misspelled_key_is_rejected(project_root):
    (project_root / "config.yaml").write_text(
        "claude:\n  model: m\nveo:\n  model: v\nlimits:\n  cost_cap_per_job: 5\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="cost_cap_per_job"):
        load_config(project_root)


def test_invalid_yaml_is_a_clear_error(project_root):
    (project_root / "config.yaml").write_text("claude: [unclosed", encoding="utf-8")

    with pytest.raises(ConfigError, match="YAML"):
        load_config(project_root)


def test_no_config_file_at_all_is_a_clear_error(tmp_path):
    with pytest.raises(ConfigError, match="config.example.yaml"):
        load_config(tmp_path)


def test_secrets_default_to_the_free_providers_without_dotenv(settings):
    assert settings.secrets.video_provider == "fake"
    assert settings.secrets.tts_provider == "edge"  # free; tests never build it for real
    assert settings.secrets.anthropic_key() is None
    assert settings.secrets.gemini_key() is None


def test_secrets_come_from_dotenv_and_blank_values_count_as_missing(project_root):
    (project_root / ".env").write_text(
        "ANTHROPIC_API_KEY=sk-test-123\nGEMINI_API_KEY=\nVIDEO_PROVIDER=veo\n",
        encoding="utf-8",
    )

    settings = load_settings(project_root)

    assert settings.secrets.anthropic_key() == "sk-test-123"
    assert settings.secrets.gemini_key() is None
    assert settings.secrets.video_provider == "veo"
    assert "sk-test-123" not in repr(settings.secrets)


def test_unknown_provider_in_dotenv_is_a_clear_error(project_root):
    (project_root / ".env").write_text("VIDEO_PROVIDER=flow\n", encoding="utf-8")

    with pytest.raises(ConfigError, match=".env"):
        load_settings(project_root)


def test_data_dir_is_resolved_against_the_project_root(settings, project_root):
    assert settings.data_dir == project_root / "data"


@pytest.mark.parametrize(
    "section, line",
    [
        ("veo", "price_usd_per_second: 0"),
        ("veo", "price_usd_per_second: -0.5"),
        ("veo", "price_usd_per_second: .nan"),
        ("veo", "job_timeout_sec: 0"),
        ("claude", "max_tokens: 0"),
        ("claude", "price_usd_per_mtok_output: 0"),
        ("limits", "cost_cap_per_job_usd: -1"),
        ("limits", "cost_cap_per_day_usd: .inf"),
        ("tts", "price_usd_per_1k_chars: -1"),
    ],
)
def test_prices_caps_and_limits_must_be_positive_finite_numbers(project_root, section, line):
    sections = {"claude": ["model: m"], "veo": ["model: v"], "limits": [], "tts": []}
    sections[section].append(line)
    lines = []
    for name, entries in sections.items():
        if entries:
            lines.append(f"{name}:")
            lines.extend(f"  {entry}" for entry in entries)
    text = "\n".join(lines) + "\n"
    (project_root / "config.yaml").write_text(text, encoding="utf-8")

    with pytest.raises(ConfigError, match=line.split(":")[0]):
        load_config(project_root)


def test_gemini_is_the_default_llm(settings):
    assert settings.secrets.llm_provider == "gemini"
    assert settings.llm is settings.config.gemini
    assert settings.llm.model == "gemini-3.8-flash"
    assert settings.llm.max_output_tokens == 16000
    assert (settings.llm.price_usd_per_mtok_input, settings.llm.price_usd_per_mtok_output) == (0.75, 3.75)


def test_llm_provider_can_be_switched_to_claude(project_root):
    (project_root / ".env").write_text("LLM_PROVIDER=claude\n", encoding="utf-8")

    settings = load_settings(project_root)

    assert settings.llm is settings.config.claude
    assert settings.llm.model == "claude-sonnet-5-5"


def test_config_without_a_section_for_the_active_provider_is_a_clear_error(project_root):
    (project_root / "config.yaml").write_text("claude:\n  model: m\nveo:\n  model: v\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="gemini"):
        load_settings(project_root)


def test_claude_section_is_optional_when_gemini_is_used(project_root):
    (project_root / "config.yaml").write_text("gemini:\n  model: g\nveo:\n  model: v\n", encoding="utf-8")

    settings = load_settings(project_root)

    assert settings.config.claude is None
    assert settings.llm.model == "g"

