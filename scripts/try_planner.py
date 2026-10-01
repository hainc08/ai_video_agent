"""Manual smoke run of the planner against the real Claude API (costs a few cents).

Usage:  .venv\\Scripts\\python scripts\\try_planner.py "5 việc sếp không biết bạn đang làm bằng AI"
Needs ANTHROPIC_API_KEY in .env.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.estimator import claude_cost_usd, estimate  # noqa: E402
from app.agent.planner import PlanOptions, build_planner  # noqa: E402
from app.config import load_settings  # noqa: E402


async def main(idea: str) -> None:
    settings = load_settings()
    defaults = settings.config.defaults
    options = PlanOptions(defaults.duration_sec, defaults.aspect, defaults.voice, defaults.style)

    result = await build_planner(settings).create_plan(idea, options)

    print(json.dumps(result.plan.to_dict(), ensure_ascii=False, indent=2))
    print(f"\nmodel={result.model} calls={result.calls} "
          f"tokens_in={result.input_tokens} tokens_out={result.output_tokens}")
    print(f"claude cost: ${claude_cost_usd(result.input_tokens, result.output_tokens, settings.config.claude)}")
    print(estimate(result.plan, settings.config, video_provider=settings.secrets.video_provider))


if __name__ == "__main__":
    # The Windows console defaults to a legacy codepage that cannot print Vietnamese.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    if len(sys.argv) != 2:
        sys.exit('Usage: python scripts/try_planner.py "ý tưởng"')
    asyncio.run(main(sys.argv[1]))
