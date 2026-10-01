import asyncio

from app.agent.planner import PlannerResult
from app.providers.base import ContentFilteredError, PollResult
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


class ScriptedProvider:
    """A provider whose every attempt is scripted per scene.

    Outcomes: "ok", "bad" (clip fails QC), "filtered", "op_failed", "timeout" (never finishes),
    or an exception instance raised by submit.
    """

    name = "veo"

    def __init__(self, script=None, *, price=0.1, aspects=("9:16", "16:9")):
        self.script = {scene: list(outcomes) for scene, outcomes in (script or {}).items()}
        self.price_usd_per_second = price
        self.supported_aspects = frozenset(aspects)
        self.submitted = []  # (scene_no, prompt) of every accepted submit
        self.download_script = {}  # scene_no -> exceptions raised by successive downloads
        self.downloads = 0
        self._scenes = {}
        self.submit_attempts = 0
        self._operations = {}
        self._polls = {}
        self.active = 0
        self.max_active = 0

    async def submit(self, request):
        self.submit_attempts += 1
        outcomes = self.script.get(request.scene_no, [])
        outcome = outcomes.pop(0) if outcomes else "ok"
        if isinstance(outcome, Exception):
            raise outcome
        operation_id = f"op-{len(self.submitted) + 1}"
        self.submitted.append((request.scene_no, request.prompt))
        self._operations[operation_id] = outcome
        self._scenes[operation_id] = request.scene_no
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        return operation_id

    async def poll(self, operation_id):
        await asyncio.sleep(0)
        outcome = self._operations[operation_id]
        if outcome == "poll_crash":
            raise RuntimeError("boom")
        polls = self._polls[operation_id] = self._polls.get(operation_id, 0) + 1
        if outcome == "timeout" or polls < 3:
            return PollResult("running")
        if outcome == "filtered":
            self.active -= 1
            raise ContentFilteredError("Prompt bị bộ lọc an toàn của Veo chặn: violence")
        if outcome == "op_failed":
            self.active -= 1
            return PollResult("failed", "Veo không sinh được clip: internal error")
        return PollResult("done")

    async def download(self, operation_id, path):
        self.downloads += 1
        errors = self.download_script.get(self._scenes[operation_id], [])
        if errors:
            raise errors.pop(0)
        self.active -= 1
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"bad" if self._operations[operation_id] == "bad" else b"ok")


class HeldProvider(ScriptedProvider):
    """Accepts nothing: every submit waits forever, so a job stays `generating` until shutdown."""

    async def submit(self, request):
        self.submit_attempts += 1
        await asyncio.Event().wait()
