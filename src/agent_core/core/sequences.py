"""Walking a named sequence of the topology: a lookup from outcome to next step, run in a loop (design §4.2).

The walk is shared by jobs and sessions (SEQ-11): the runner supplies how a node runs and how a tool is called, and a
journal supplies `Steps`, which records each step so that a crashed run can be resumed.
"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from agent_core.contracts.journal import Steps
from agent_core.core.instance import Instance

RunNode = Callable[[str, dict], Awaitable[dict]]          # (node, inputs) -> the node's result, as Run.run_node gives it
CallTool = Callable[[str, dict], Awaitable[object]]       # (tool, args) -> its value, as Run.call gives it
Check = Callable[[Sequence[dict], dict, str], Awaitable[tuple[dict | None, dict]]]   # (checks, facts, owner), as unmet_check


class SequenceError(RuntimeError):
    """The sequence cannot go on. The message says why."""


@dataclass
class SequenceRunner:
    instance: Instance
    run_node: RunNode
    call_tool: CallTool
    check: Check

    async def walk(self, steps: Steps, name: str, facts: dict) -> dict:
        """Walk the sequence `name` from `facts`. Returns its end state, the steps it took, the facts and the summary."""
        return await _Walk(self, steps).sequence(name, dict(facts))


def _summary(result: dict) -> object:
    """A node's outputs, or, when it has none, what else its result says (a reason, a message)."""
    return result.get("outputs") or {k: v for k, v in result.items() if k not in ("outcome", "outputs")}


class _Walk:
    def __init__(self, runner: SequenceRunner, steps: Steps):
        self.runner, self.steps = runner, steps
        self.taken = 0                      # step numbers taken so far; DBOS numbers its steps the same way
        self.trail: list[dict] = []

    def _number(self, count: int = 1) -> int:
        first = self.taken + 1
        self.taken += count
        return first

    def _end(self, end: str, facts: dict, summary: object) -> dict:
        return {"end": end, "trail": self.trail, "facts": facts, "summary": summary}

    def _inputs(self, node: str, facts: dict, mapping: dict) -> dict:
        """Each declared input of the node that has a fact, by its own name or the name the mapping gives (SEQ-5)."""
        declared = self.runner.instance.nodes[node].inputs
        return {name: facts[mapping.get(name, name)] for name in declared if mapping.get(name, name) in facts}

    async def _checks(self, checks: list[dict], facts: dict, owner: str) -> list:
        unmet, writes = await self.runner.check(checks, facts, owner)
        return [unmet, writes]

    async def sequence(self, name: str, facts: dict) -> dict:
        found = self.runner.instance.sequences[name]
        for key, value in (found.get("inputs") or {}).items():  # fixed inputs fill only names not yet facts
            facts.setdefault(key, value)
        rows, target, summary = found["transitions"], found["start"], None
        if found.get("checks"):  # SEQ-9: one step for the sequence's checks
            number = self._number()
            unmet, writes = await self.steps.step("checks", lambda: self._checks(found["checks"], facts, name))
            if unmet is None:
                facts.update(writes)
                self.trail.append({"step": number, "name": "checks", "outcome": "met"})
            else:
                outcome, summary = unmet.get("outcome", "failed"), unmet["message"]
                self.trail.append({"step": number, "name": "checks", "outcome": outcome})
                if "outcome" not in unmet:
                    return self._end("failed", facts, summary)
                target = rows.get("check", {}).get(outcome)
                if target is None:
                    return self._end("failed", facts, _no_transition("checks", outcome))
        outcome = None
        while True:
            if target == "end":
                return self._end("failed" if outcome == "failed" else "done", facts, summary)
            if isinstance(target, dict) and "link" in target:  # SEQ-4: the linked sequence ends the walk
                return await self.sequence(target["link"], facts)
            if isinstance(target, dict) and "fan_out" in target:
                node = target["fan_out"]
                outcome, outputs = await self._fan_out(target, facts)
                summary = outputs
            else:
                node, mapping = (target["node"], target["inputs"]) if isinstance(target, dict) else (target, {})
                inputs = self._inputs(node, facts, mapping)
                number = self._number()
                result = await self.steps.step(node, lambda: self.runner.run_node(node, inputs))
                outcome, summary = result["outcome"], _summary(result)
                declared = self.runner.instance.nodes[node].outputs
                outputs = {k: v for k, v in (result.get("outputs") or {}).items() if k in declared}   # SEQ-6
                self.trail.append({"step": number, "name": node, "outcome": outcome})
            facts.update(outputs)
            if outcome == "stopped":  # SEQ-7
                return self._end("stopped", facts, summary)
            target = rows.get(node, {}).get(outcome)
            if target is None:  # SEQ-10
                return self._end("failed", facts, _no_transition(node, outcome))

    async def _fan_out(self, spec: dict, facts: dict) -> tuple[str, dict]:
        """One run of the node per item, at most `max_concurrency` at once (FAN-1); the results in item order (FAN-3)."""
        node, over, into = spec["fan_out"], spec["over"], spec["into"]
        if isinstance(over, dict):  # FAN-5, FAN-6: a list computed by a tool is a step of its own
            name, number = f"{node}[list]", self._number()
            items = await self.steps.step(name, lambda: self.runner.call_tool(over["tool"], over.get("args") or {}))
            self.trail.append({"step": number, "name": name, "outcome": "done"})
        else:
            items = facts.get(over)
        if not isinstance(items, list):
            named = over["tool"] if isinstance(over, dict) else over
            raise SequenceError(f"the fan-out over `{named}` needs a list; it got {type(items).__name__}")
        reserved = self.steps.reserve(len(items))  # numbered in item order before any run starts
        first = self._number(len(items))
        gate = asyncio.Semaphore(spec.get("max_concurrency", 4))
        stop = False

        async def one(n: int, slot, item) -> dict | None:
            nonlocal stop
            async with gate:
                if stop:  # a run stopped: runs not yet started do not start
                    return None
                inputs = self._inputs(node, {**facts, spec["as"]: item}, {})
                result = await slot.run(f"{node}[{n}]", lambda: self._caught(node, inputs))
                stop = stop or result["outcome"] == "stopped"
                return result

        results = await asyncio.gather(*(one(n, slot, item) for n, (slot, item) in enumerate(zip(reserved, items), 1)))
        declared = self.runner.instance.nodes[node].outputs
        done, failures = [], []
        for n, (item, result) in enumerate(zip(items, results), 1):
            if result is None:
                continue
            self.trail.append({"step": first + n - 1, "name": f"{node}[{n}]", "outcome": result["outcome"]})
            outputs = result.get("outputs") or {}
            if result["outcome"] == "done":
                done.append({k: v for k, v in outputs.items() if k in declared})
            elif result["outcome"] != "stopped":
                failures.append({"item": item, "outcome": result["outcome"], "reason": outputs.get("reason", result.get("reason"))})
        if any(result is not None and result["outcome"] == "stopped" for result in results):
            outcome = "stopped"
        else:
            outcome = "done" if done or not items else "failed"   # FAN-4
        self.trail.append({"step": None, "name": node, "outcome": outcome})
        return outcome, {into: done, f"{into}_failures": failures}

    async def _caught(self, node: str, inputs: dict) -> dict:
        """A run that raises is a failed item, so the journal records a result, not an exception."""
        try:
            return await self.runner.run_node(node, inputs)
        except Exception as e:
            return {"outcome": "failed", "outputs": {"reason": f"{type(e).__name__}: {e}"}}


def _no_transition(node: str, outcome: str) -> str:
    return f"`{node}` exited `{outcome}` and the sequence has no transition for it"
