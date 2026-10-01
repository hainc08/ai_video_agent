"""The idea form: defaults, parsing and validation."""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from app.config import AppConfig
from app.options import ASPECTS, DEFAULT_STYLE, DURATIONS, STYLES, VOICES

MAX_IDEA_CHARS = 1000


def default_form_values(config: AppConfig) -> dict[str, Any]:
    return {
        "idea": "",
        "duration_sec": config.defaults.duration_sec,
        "aspect": config.defaults.aspect,
        "voice": config.defaults.voice,
        "style": DEFAULT_STYLE,
        "cost_cap_usd": f"{config.limits.cost_cap_per_job_usd:g}",
    }


def _choose(
    form: Mapping[str, Any],
    name: str,
    choices: Mapping[str, Any],
    message: str,
    values: dict[str, Any],
    errors: dict[str, str],
) -> None:
    raw = str(form.get(name) or "").strip()
    if not raw:
        return  # FR-01: a missing option takes its default
    if raw in choices:
        values[name] = choices[raw]
    else:
        errors[name] = message


def parse_job_form(
    form: Mapping[str, Any], config: AppConfig
) -> tuple[dict[str, Any], float | None, dict[str, str]]:
    """Return (values to show again, cost cap, errors by field name)."""
    values = default_form_values(config)
    errors: dict[str, str] = {}

    idea = str(form.get("idea") or "").strip()
    values["idea"] = idea
    if len(idea) < 3:
        errors["idea"] = "Hãy nhập ý tưởng (ít nhất 3 ký tự)."
    elif len(idea) > MAX_IDEA_CHARS:
        errors["idea"] = "Ý tưởng quá dài (tối đa 1.000 ký tự)."

    _choose(form, "duration_sec", {str(d): d for d in DURATIONS}, "Thời lượng không hợp lệ.", values, errors)
    _choose(form, "aspect", {a: a for a in ASPECTS}, "Tỉ lệ khung hình không hợp lệ.", values, errors)
    _choose(form, "voice", {key: key for key in VOICES}, "Giọng đọc không hợp lệ.", values, errors)
    _choose(form, "style", {key: key for key in STYLES}, "Phong cách không hợp lệ.", values, errors)

    cap: float | None = config.limits.cost_cap_per_job_usd
    raw_cap = str(form.get("cost_cap_usd") or "").strip()
    if raw_cap:
        values["cost_cap_usd"] = raw_cap
        try:
            cap = float(raw_cap.replace(",", "."))  # Vietnamese keyboards type 2,5
        except ValueError:
            cap = None
        if cap is None or not math.isfinite(cap) or cap <= 0:
            cap = None
            errors["cost_cap_usd"] = "Trần chi phí phải là số lớn hơn 0."

    return values, cap, errors
