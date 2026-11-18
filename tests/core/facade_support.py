"""A toy backend that plays a script against core policy, a toy person, and the providers the facade reaches by name.

The scripted backend and the stolen providers arrive in Task 10; until then the facade tests register these stand-ins
(and `test_facade.py` registers `Files`, `Nobody` and `NoContext` under the names the registry's tables give).
"""

import asyncio
import os

from agent_core.contracts.events import ModelRequested, ModelResponded, RequestPart, ToolReturned
from agent_core.contracts.matrix import Entry, Feature
from agent_core.contracts.policy import CallResult, merge
from agent_core.contracts.unit import Unit, UnitResult
from agent_core.contracts.values import ModelResponse, ToolCall, Usage
from agent_core.helpers.mcp import McpServers


class Watched(McpServers):
    """MCP servers that say whether they were closed."""

    closed = False

    async def close(self):
        self.closed = True
        await super().close()


class Toy:
    """A backend. `scripts` maps a node to its steps: a step is a list of `[tool, args]` calls (one response), or a string
    (the model saying that, and stopping). `usage(n)` is what the n-th response of a unit reports; `raises` maps a node
    to an exception its run raises; `matrix` entries replace the toy's own."""

    def __init__(self, scripts=None, entries=None, usage=lambda n: Usage(10, 2, 0), raises=None):
        self.scripts, self.usage, self.raises = scripts or {}, usage, raises or {}
        self.matrix = {f: Entry("helper", "toy") for f in Feature}
        self.matrix[Feature.F6] = Entry("not built", "sessions, step 7")
        self.matrix.update(entries or {})
        self.units: list[Unit] = []
        self.briefs: list[str] = []
        self.handovers: list[tuple] = []
        self.served: dict | None = None
        self.sources: list[Watched] = []         # the server sources the harness had it make, one for each run
        self.environment: list[dict] = []        # AGENT_CORE_* as each unit saw them
        self.closed = False

    def features(self):
        return self.matrix

    def servers(self, declared, root):
        self.served = dict(declared)
        self.sources.append(Watched(declared, dict(os.environ), root))
        return self.sources[-1]

    async def run_fragment(self, unit):
        raise NotImplementedError

    async def close(self):
        self.closed = True

    async def run_node(self, unit: Unit) -> UnitResult:
        self.units.append(unit)
        self.environment.append({k: v for k, v in os.environ.items() if k.startswith("AGENT_CORE_")})
        if unit.name in self.raises:
            raise self.raises[unit.name]
        policy = await unit.start(unit.name, unit.inputs)
        if isinstance(policy, UnitResult):
            return policy
        self.briefs.append(policy.instructions)
        self.handovers.append(policy.handover)
        state, said, emit = policy.initial(), "", unit.events.emit
        for n, step in enumerate(self.scripts.get(unit.name, []), 1):
            if state["ending"] is not None:
                break
            emit(ModelRequested(policy.label, (RequestPart("instructions", text=policy.instructions),)))
            if isinstance(step, str):
                emit(ModelResponded(policy.label, ModelResponse(step, (), self.usage(n))))
                said = step
                break
            calls = tuple(ToolCall(f"{policy.label}-{n}-{i}", name, args) for i, (name, args) in enumerate(step))
            response = ModelResponse("", calls, self.usage(n))
            emit(ModelResponded(policy.label, response))
            review = policy.review(response, state)
            updates = []
            for call in calls:
                if call.id in review.refused:
                    result = CallResult(review.refused[call.id], error=True)
                else:
                    result = await policy.call(call, state)
                emit(ToolReturned(policy.label, call, result.text, result.error))
                updates.append(result.update)
            for update in updates:
                if update is not None:
                    state = merge(state, update)
        return policy.finish(state, said)


class ToyPerson:
    """A person who answers each question with `answer`, and remembers what was asked and how many were open at once."""

    def __init__(self, answer="red", pause=0.05):
        self.answer, self.pause = answer, pause
        self.asked: list[tuple[str, str]] = []   # (label, question)
        self.told: list[str] = []
        self.open = self.most = 0

    async def tell(self, text):
        self.told.append(text)

    async def ask(self, question, label=""):
        self.open += 1
        self.most = max(self.most, self.open)
        try:
            self.asked.append((label, question))
            await asyncio.sleep(self.pause)  # long enough for a second run to reach its own question meanwhile
            return self.answer
        finally:
            self.open -= 1


class Nobody:
    async def tell(self, text):
        pass

    async def ask(self, question, label=""):
        return None


class NoContext:
    async def build(self, request):
        return ()
