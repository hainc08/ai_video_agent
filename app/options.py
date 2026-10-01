"""Choices offered on the idea form."""
from __future__ import annotations

from app.config import AppConfig

DURATIONS = (15, 30, 60)
ASPECTS = ("9:16", "1:1", "16:9")

# The two Vietnamese voices the TTS service has. The keys predate that choice and are kept
# so jobs already stored keep resolving.
VOICES: dict[str, str] = {
    "vi-female-north": "Nữ (Hoài My)",
    "vi-male-north": "Nam (Nam Minh)",
}
# Voices the form once offered, shown under the voice that now reads them.
_RETIRED_VOICES = {"vi-female-south": "vi-female-north"}

DEFAULT_STYLE = "office"
STYLES: dict[str, str] = {
    "office": "Văn phòng · chuyên nghiệp",
    "minimal": "Tối giản · sáng",
    "cinematic": "Điện ảnh",
}
# "office" has no entry: its prompt is defaults.style from config.yaml.
_STYLE_PROMPTS: dict[str, str] = {
    "minimal": "minimal bright interior, white walls and light wood, soft diffused light",
    "cinematic": "cinematic look, shallow depth of field, warm contrast lighting, slow camera moves",
}


def voice_label(key: str) -> str:
    return VOICES.get(_RETIRED_VOICES.get(key, key), key)


def style_prompt(key: str, config: AppConfig) -> str:
    return _STYLE_PROMPTS.get(key, config.defaults.style)
