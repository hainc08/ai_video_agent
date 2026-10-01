import pytest

from app.agent.factory import build_planner
from app.agent.gemini_planner import GeminiPlanner
from app.agent.planner import Planner, PlannerError
from app.config import load_settings


def test_gemini_is_built_by_default_and_needs_its_key(settings):
    with pytest.raises(PlannerError, match="GEMINI_API_KEY"):
        build_planner(settings)


def test_gemini_planner_is_told_to_answer_with_json_not_a_tool(project_root):
    (project_root / ".env").write_text("GEMINI_API_KEY=test-key\n", encoding="utf-8")

    planner = build_planner(load_settings(project_root))

    assert isinstance(planner, GeminiPlanner)
    assert "AI Văn Phòng" in planner.system_prompt
    assert "JSON" in planner.system_prompt
    assert "submit_plan" not in planner.system_prompt


def test_claude_planner_is_built_when_selected(project_root):
    (project_root / ".env").write_text("LLM_PROVIDER=claude\nANTHROPIC_API_KEY=sk-test\n", encoding="utf-8")

    planner = build_planner(load_settings(project_root))

    assert isinstance(planner, Planner)
    assert "submit_plan" in planner.system_prompt


def test_claude_selected_without_its_key_is_a_clear_error(project_root):
    (project_root / ".env").write_text("LLM_PROVIDER=claude\nGEMINI_API_KEY=test-key\n", encoding="utf-8")

    with pytest.raises(PlannerError, match="ANTHROPIC_API_KEY"):
        build_planner(load_settings(project_root))
