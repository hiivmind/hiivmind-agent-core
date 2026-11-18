"""A toy backend and a topology for driving `Macro`, in this process or in a subprocess that dies (macro_harness.py)."""

import dataclasses
import json
import os
from pathlib import Path

from support import SEQUENCES, FolderSource

from agent_core.core.registry import provider
from agent_core.contracts.topology import END, FanOut, SequenceDef, Step
from agent_core.contracts.unit import Unit, UnitResult
from agent_core.contracts.walk import StepRef, WalkPort
from agent_core.core.instance import load_instance

RESULTS = {
    "first": UnitResult("done", {"first_done": "yes"}),
    "wrap": UnitResult("done", {"wrapped": "yes"}),
    "close": UnitResult("done", {"closed": "yes"}),
    "update-sources": UnitResult("updated", {"rescan_batches": ["b1", "b2"]}),
    "scan": UnitResult("done", {"entries": ["e1"]}),
}


def topology():
    """The sequences fixture, with `with-tail` given its end after the fragment and `fan` a node then a fan-out."""
    base = load_instance(SEQUENCES / "instance.yaml", FolderSource(SEQUENCES)).topology
    tail_done = dict(base.sequences["with-tail"].transitions, tail={"done": END, "failed": END})
    fan = SequenceDef(
        "fan", "a node, then a fan-out", Step("update-sources"), {}, (),
        {
            "update-sources": {"updated": FanOut("scan", "rescan_batches", "batch", "scans", 1), "failed": END},
            "scan": {"done": END, "failed": END},
        },
    )
    return dataclasses.replace(
        base,
        sequences={**base.sequences, "with-tail": dataclasses.replace(base.sequences["with-tail"], transitions=tail_done), "fan": fan},
    )


def make_unit(topo):
    def make(name, inputs, intent, thread, fragment):
        return Unit(name, inputs, intent, thread, None, None, None, topo, None, fragment)

    return make


async def no_check(checks, facts, owner):
    return None, {}


async def no_tool(tool, args):
    return None


class _NoSteps:
    async def step(self, name, call):
        return await call()

    def reserve(self, count):
        return [self] * count

    async def run(self, name, call):
        return await call()


class Toy:
    """A backend that records each unit it is given, one JSON line per unit, in `log`, and plays RESULTS.
    `die_in` names a unit whose run ends the process; a fragment is walked by the walk helper, as a real backend does."""

    def __init__(self, log: Path, die_in: str | None = None):
        self.log, self.die_in, self.units = Path(log), die_in, []

    def _record(self, unit: Unit) -> None:
        self.units.append(unit)
        with open(self.log, "a") as f:
            f.write(json.dumps({"name": unit.name, "intent": unit.intent, "thread": unit.thread}) + "\n")
        if unit.name == self.die_in:
            os._exit(3)

    def logged(self) -> list[dict]:
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    async def run_node(self, unit: Unit) -> UnitResult:
        self._record(unit)
        return RESULTS[unit.name]

    async def run_fragment(self, unit: Unit) -> UnitResult:
        self._record(unit)

        async def run_step(name, inputs, ref: StepRef, intent):
            return RESULTS[name]

        port = WalkPort(unit.topology, run_step, no_tool, no_check, _NoSteps(), 0)
        return await provider("walk", "topology").walk_fragment(port, unit.fragment, unit.inputs)

    def features(self):
        raise NotImplementedError

    def servers(self, declared, root):
        raise NotImplementedError

    async def close(self) -> None:
        pass
