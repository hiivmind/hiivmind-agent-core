"""Walking a sequence or a fragment: a lookup from outcome to next step, run in a loop.

One implementation serves the macro level (a sequence, driven by the core with a journal) and a fragment (driven by a
backend with no graph). The port supplies how a step runs (a node or a fragment, by name), how a tool is called, how
the checks are made, and the `Steps` that record each step so that a crashed run can be resumed.
"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping

from agent_core.contracts.errors import ProviderRefused, ProviderUnavailable
from agent_core.contracts.registry import register
from agent_core.contracts.topology import END, FanOut, FragmentDef, Link, Step
from agent_core.contracts.unit import UnitResult
from agent_core.contracts.walk import StepRef, WalkPort, WalkResult


class SequenceError(RuntimeError):
    """The sequence cannot go on. The message says why."""


def _summary(result: UnitResult) -> object:
    """A step's outputs, or, when it has none, what else its result says (a reason)."""
    return result.outputs or ({"reason": result.reason} if result.reason else {})


def _no_transition(node: str, outcome: str) -> str:
    return f"`{node}` exited `{outcome}` and the sequence has no transition for it"


def _failed(reason: str) -> UnitResult:
    return UnitResult("failed", {"reason": reason})


# how a walk ends: (end, the last outcome, the summary, whether a transition led to `end`)
_Ended = tuple[str, str | None, object, bool]


class _Walk:
    def __init__(self, port: WalkPort):
        self.port = port
        self.taken = 0                      # step numbers taken so far; DBOS numbers its steps the same way
        self.trail: list[dict] = []

    def _number(self, count: int = 1) -> int:
        first = self.taken + 1
        self.taken += count
        return first

    async def _step(self, name: str, call: Callable[[], Awaitable[object]]) -> tuple[dict, object]:
        """Run one journalled step. Its trail entry is kept, with no outcome, if the step raises."""
        entry = {"step": self._number(), "name": name, "outcome": None}
        self.trail.append(entry)
        return entry, await self.port.steps.step(name, call)

    def _contract(self, name: str):
        """The declared inputs and outputs of a node or a fragment."""
        topology = self.port.topology
        return topology.nodes[name] if name in topology.nodes else topology.fragments[name]

    def _inputs(self, name: str, facts: dict, mapping: Mapping[str, str]) -> dict:
        """Each declared input of the step that has a fact, by its own name or the name the mapping gives (SEQ-5)."""
        return {n: facts[mapping.get(n, n)] for n in self._contract(name).inputs if mapping.get(n, n) in facts}

    def _declared(self, name: str, outputs: Mapping) -> dict:
        declared = self._contract(name).outputs
        return {k: v for k, v in outputs.items() if k in declared}   # SEQ-6

    async def _checks(self, checks, facts: dict, owner: str) -> list:
        unmet, writes = await self.port.check(checks, facts, owner)
        return [unmet, writes]

    async def sequence(self, name: str, facts: dict) -> _Ended:
        found = self.port.topology.sequences[name]
        for key, value in found.inputs.items():  # fixed inputs fill only names not yet facts
            facts.setdefault(key, value)
        rows, target, summary, outcome = found.transitions, found.start, None, None
        if found.checks:  # SEQ-9: one step for the sequence's checks
            entry, (unmet, writes) = await self._step("checks", lambda: self._checks(found.checks, facts, name))
            if unmet is None:
                facts.update(writes)
                entry["outcome"] = "met"
            else:
                outcome, summary = unmet.get("outcome", "failed"), unmet["message"]
                entry["outcome"] = outcome
                if "outcome" not in unmet:
                    return "failed", outcome, summary, False
                if outcome == "stopped":  # SEQ-7
                    return "stopped", outcome, summary, False
                target = rows.get("check", {}).get(outcome)
                if target is None:
                    return "failed", outcome, _no_transition("checks", outcome), False
        return await self.follow(rows, target, facts, outcome, summary)

    async def follow(self, rows: Mapping, target, facts: dict, outcome: str | None, summary: object) -> _Ended:
        while True:
            if target == END:
                return ("failed" if outcome == "failed" else "done"), outcome, summary, True
            if isinstance(target, Link):  # SEQ-4: the linked sequence ends the walk
                return await self.sequence(target.sequence, facts)
            if isinstance(target, FanOut):
                node = target.node
                outcome, outputs = await self._fan_out(target, facts)
                summary = outputs
            else:
                node = target.name
                inputs = self._inputs(node, facts, target.mapping)
                number = self._number()
                entry = {"step": number, "name": node, "outcome": None}
                self.trail.append(entry)
                result = await self.port.steps.step(node, lambda: self.port.run_step(node, inputs, StepRef(number), "start"))
                outcome, summary = result.exit, _summary(result)
                entry["outcome"] = outcome
                if node in self.port.topology.fragments:
                    entry["steps"] = list(result.steps)
                outputs = self._declared(node, result.outputs)
            facts.update(outputs)
            if outcome == "stopped":  # SEQ-7
                return "stopped", outcome, summary, False
            target = rows.get(node, {}).get(outcome)
            if target is None:  # SEQ-10
                return "failed", outcome, _no_transition(node, outcome), False

    async def _fan_out(self, spec: FanOut, facts: dict) -> tuple[str, dict]:
        """One run of the node per item, at most `max_concurrency` at once (FAN-1); the results in item order (FAN-3)."""
        node, over, into = spec.node, spec.over, spec.into
        if not isinstance(over, str):  # FAN-5, FAN-6: a list computed by a tool is a step of its own
            entry, items = await self._step(f"{node}[list]", lambda: self.port.call_tool(over.tool, dict(over.args)))
            entry["outcome"] = "done"
        else:
            items = facts.get(over)
        if not isinstance(items, list):
            named = over if isinstance(over, str) else over.tool
            raise SequenceError(f"the fan-out over `{named}` needs a list; it got {type(items).__name__}")
        reserved = self.port.steps.reserve(len(items))  # numbered in item order before any run starts
        first = self._number(len(items))
        gate = asyncio.Semaphore(spec.max_concurrency)
        stop = False

        async def one(n: int, slot, item) -> UnitResult | None:
            nonlocal stop
            async with gate:
                if stop:  # a run stopped: runs not yet started do not start
                    return None
                inputs = self._inputs(node, {**facts, spec.as_: item}, {})
                result = await slot.run(f"{node}[{n}]", lambda: self._caught(node, inputs, first + n - 1, n))
                stop = stop or result.exit == "stopped"
                return result

        results = await asyncio.gather(*(one(n, slot, item) for n, (slot, item) in enumerate(zip(reserved, items), 1)))
        done, failures = [], []
        for n, (item, result) in enumerate(zip(items, results), 1):
            if result is None:
                continue
            self.trail.append({"step": first + n - 1, "name": f"{node}[{n}]", "outcome": result.exit})
            if result.exit == "done":
                done.append(self._declared(node, result.outputs))
            elif result.exit != "stopped":
                failures.append({"item": item, "outcome": result.exit, "reason": result.outputs.get("reason", result.reason)})
        if any(result is not None and result.exit == "stopped" for result in results):
            outcome = "stopped"
        else:
            outcome = "done" if done or not items else "failed"   # FAN-4
        self.trail.append({"step": None, "name": node, "outcome": outcome})
        return outcome, {into: done, f"{into}_failures": failures}

    async def _caught(self, node: str, inputs: dict, number: int, item: int) -> UnitResult:
        """A run that raises is a failed item, so the journal records a result, not an exception. A run the provider
        found unavailable is run once more, fresh, after `port.pause` seconds, inside the same step (RTY-2, RTY-3). A
        run the provider refused for good is not run again (MOD-4, MOD-5)."""
        try:
            return await self.port.run_step(node, inputs, StepRef(number, item, 1), "start")
        except ProviderRefused as e:
            return _failed(str(e))
        except ProviderUnavailable:
            pass
        except Exception as e:
            return _failed(f"{type(e).__name__}: {e}")
        await asyncio.sleep(self.port.pause)
        try:
            return await self.port.run_step(node, inputs, StepRef(number, item, 2), "fresh")
        except ProviderRefused as e:
            return _failed(f"{e} (run twice)")   # RTY-5: any error of the second run
        except Exception as e:
            return _failed(f"{type(e).__name__}: {e} (run twice)")


async def walk_sequence(port: WalkPort, name: str, facts: dict) -> WalkResult:
    """Walk the sequence `name` from `facts`. Returns its end state, the steps it took, the facts and the summary."""
    walk, facts = _Walk(port), dict(facts)
    end, _, summary, _ = await walk.sequence(name, facts)
    return {"end": end, "trail": walk.trail, "facts": facts, "summary": summary}


async def walk_fragment(port: WalkPort, fragment: FragmentDef, inputs: Mapping) -> UnitResult:
    """Walk a fragment from its declared inputs found in `inputs`. Its exit is the last step's outcome (SEQ-10); an
    outcome its transitions have no row for ends it `failed`, naming the node and the outcome."""
    walk = _Walk(port)
    facts = {name: inputs[name] for name in fragment.inputs if name in inputs}
    end, outcome, summary, clean = await walk.follow(fragment.transitions, fragment.start, facts, None, None)
    steps = tuple({"name": e["name"], "outcome": e["outcome"]} for e in walk.trail)
    outputs = {name: facts[name] for name in fragment.outputs if name in facts}
    if end == "stopped":  # SEQ-7
        return UnitResult("stopped", outputs, steps=steps)
    if not clean:
        return UnitResult("failed", outputs, reason=str(summary), steps=steps)
    return UnitResult(outcome or "done", outputs, steps=steps)


class Walking:
    """The `walk` helper as registered: the two functions."""

    walk_sequence = staticmethod(walk_sequence)
    walk_fragment = staticmethod(walk_fragment)


register("walk", "topology")(Walking())
