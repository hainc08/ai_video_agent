"""Builds the planner for the LLM provider chosen by LLM_PROVIDER in .env."""
from __future__ import annotations

from app.agent.gemini_planner import build_gemini_planner
from app.agent.planner import PlannerBase, build_claude_planner
from app.config import Settings


def build_planner(settings: Settings) -> PlannerBase:
    if settings.secrets.llm_provider == "claude":
        return build_claude_planner(settings)
    return build_gemini_planner(settings)
