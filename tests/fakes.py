from app.agent.planner import PlannerResult
from app.schemas import Plan


def planner_result(plan_dict, input_tokens=1000, output_tokens=2000):
    return PlannerResult(
        plan=Plan.model_validate(plan_dict),
        model="claude-sonnet-5-5",
        calls=1,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


class FakePlanner:
    """Stands in for app.agent.planner.Planner: no network, scripted outcomes."""

    def __init__(self, *outcomes):
        self._outcomes = list(outcomes)
        self.calls = []

    def _next(self):
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    async def create_plan(self, idea, options):
        self.calls.append(("create_plan", idea, options))
        return self._next()

    async def revise(self, plan, feedback):
        self.calls.append(("revise", plan, feedback))
        return self._next()

    async def rewrite_scene(self, plan, scene_id, feedback=""):
        self.calls.append(("rewrite_scene", plan, scene_id, feedback))
        return self._next()
