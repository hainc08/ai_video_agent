"""The idea form: defaults (parsing is added with the POST route)."""
from __future__ import annotations

from typing import Any

from app.config import AppConfig
from app.options import DEFAULT_STYLE


def default_form_values(config: AppConfig) -> dict[str, Any]:
    return {
        "idea": "",
        "duration_sec": config.defaults.duration_sec,
        "aspect": config.defaults.aspect,
        "voice": config.defaults.voice,
        "style": DEFAULT_STYLE,
        "cost_cap_usd": f"{config.limits.cost_cap_per_job_usd:g}",
    }
