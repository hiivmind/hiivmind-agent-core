"""The macro level: a sequence walked by the walk helper, each step a unit run on the run's backend (architecture §4.4a).

The core reaches the walk by name through the registry. The journal records each step's result, so that a crashed run
can be resumed by its id (RESUME-1 to RESUME-5); nothing resumes unless `resume` is called (RESUME-4).
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence

from agent_core.contracts.backend import Backend
from agent_core.contracts.journal import RunJournal, Steps
from agent_core.contracts.topology import Check, Topology
from agent_core.contracts.unit import Intent, Unit, UnitResult
from agent_core.contracts.walk import StepRef, WalkPort, WalkResult
from agent_core.core.registry import provider


class Macro:
    """Walks sequences of `topology`. `make_unit(name, inputs, intent, thread, fragment)` builds the `Unit` of a step, with
    `fragment` the `FragmentDef` when the step is a fragment and None for a node."""

    def __init__(
        self,
        topology: Topology,
        *,
        backends: Callable[[str | None], Backend],
        default_backend: str,
        make_unit: Callable[..., Unit],
        journal: RunJournal,
        call_tool: Callable[[str, dict], Awaitable[object]],
        check: Callable[[Sequence[Check], dict, str], Awaitable[tuple[dict | None, dict]]],
    ):
        self._topology, self._backends, self._default = topology, backends, default_backend
        self._make_unit, self._journal, self._call_tool, self._check = make_unit, journal, call_tool, check
        self.progress: dict = {}   # the live `trail` and `facts` of the walk in this process, whether or not it ends

    def _walk(self, run_id: str, resuming: bool):
        """The walk the journal runs. On a resume every step runs with intent `continue` unless the walk says `fresh`: a
        backend with no checkpoint for the thread starts the unit, so no step need be known to have been running."""
        walker = provider("walk", "topology")

        async def run_step(name: str, inputs: Mapping, ref: StepRef, intent: Intent) -> UnitResult:
            if resuming and intent != "fresh":
                intent = "continue"
            fragment = self._topology.fragments.get(name)
            unit = self._make_unit(name, inputs, intent, f"{run_id}/{ref.number}/{ref.item}/{ref.attempt}", fragment)
            backend = self._backends(self._default)
            return await (backend.run_fragment(unit) if fragment else backend.run_node(unit))

        async def walk(steps: Steps, name: str, facts: dict) -> WalkResult:
            port = WalkPort(self._topology, run_step, self._call_tool, self._check, steps)
            return await walker.walk_sequence(port, name, facts, self.progress)

        return walk

    async def start(self, run_id: str, name: str, facts: dict) -> WalkResult:
        return await self._journal.start(run_id, self._walk(run_id, False), name, facts)

    async def resume(self, run_id: str) -> WalkResult:
        return await self._journal.resume(run_id, self._walk(run_id, True))

    async def rerun(self, run_id: str, from_run: str, step: int) -> WalkResult:
        return await self._journal.rerun(run_id, from_run, step, self._walk(run_id, False))
