"""A backend that plays a script instead of calling a model.

A script is a list of steps: a step is a list of `[name, args]` pairs, which is one response's calls, or a string, which
is the model saying that and making no call. Each node has its script, `<node>.json` in the directory the setting
`SCRIPTS` names. The backend plays a node's script against its `Policy`; a fragment is walked by the walk helper.
"""

import dataclasses
import json
import os
from collections.abc import Mapping
from pathlib import Path

from mountainash_settings import MountainAshBaseSettings
from pydantic_settings import SettingsConfigDict

from agent_core.contracts.events import EventSink, ModelRequested, ModelResponded, RequestPart, ToolReturned
from agent_core.contracts.matrix import Entry, Feature, Matrix
from agent_core.contracts.policy import CallResult, Policy, merge
from agent_core.contracts.registry import register_backend
from agent_core.contracts.unit import Unit, UnitResult
from agent_core.contracts.values import Message, ModelResponse, ToolCall
from agent_core.contracts.walk import StepRef, WalkPort
from agent_core.helpers.mcp import McpServers
from agent_core.helpers.walk import walk_fragment

_HELPERS = {
    Feature.F1: "the script player",
    Feature.F2: "core policy",
    Feature.F3: "helpers.mcp",
    Feature.F4: "core policy",
    Feature.F5: "NodeState, in memory",
    Feature.F7: "macro resume by the core's journal; a unit in flight runs again from its start",
    Feature.F8: "the person",
    Feature.F9: "the none strategy",
    Feature.F11: "core policy",
    Feature.F15: "events",
    Feature.F16: "the walk",
    Feature.F18: "core policy",
    Feature.F21: "the brief",
}
_NOT_BUILT = {
    **dict.fromkeys(
        (Feature.F10, Feature.F12, Feature.F13, Feature.F14, Feature.F20, Feature.F24), "no model"
    ),
    Feature.F19: "deferred: no consumer in this delivery",
    Feature.F6: "sessions, step 7",
    Feature.F17: "sessions, step 7",
    Feature.F22: "reserved",
    Feature.F23: "deferred",
}
FEATURES: Matrix = {
    **{feature: Entry("helper", means) for feature, means in _HELPERS.items()},
    **{feature: Entry("not built", means) for feature, means in _NOT_BUILT.items()},
}


class ScriptedSettings(MountainAshBaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_CORE_SCRIPTED_")

    SCRIPTS: Path | None = None  # a directory holding <node>.json


class _InMemory:
    """The `Steps` of a fragment's walk: nothing is journalled inside a unit."""

    async def step(self, name, call):
        return await call()

    def reserve(self, count):
        return [self] * count

    async def run(self, name, call):
        return await call()


async def _no_checks(checks, facts, owner):
    return None, {}   # checks belong to a sequence's start, not to a fragment


@register_backend("scripted", settings=ScriptedSettings)
class ScriptedBackend:
    FEATURES = FEATURES   # the matrix is the class's: it is read without making a backend, which may need settings

    def __init__(self, settings: ScriptedSettings | None = None):
        self._settings = settings

    def features(self) -> Matrix:
        return self.FEATURES

    def servers(self, declared: Mapping[str, dict], root: Path) -> McpServers:
        return McpServers(declared, dict(os.environ), root)   # the environment as it is now: the facade has just set it

    def _steps(self, node: str) -> list:
        scripts = self._settings.SCRIPTS if self._settings is not None else None
        if scripts is None:
            raise ValueError("the scripted backend needs the setting SCRIPTS (a directory of <node>.json)")
        return json.loads((Path(scripts) / f"{node}.json").read_text())

    async def run_node(self, unit: Unit) -> UnitResult:
        policy = await unit.start(unit.name, unit.inputs)
        if isinstance(policy, UnitResult):  # the node did not start
            return policy
        return await self._play(policy, self._steps(policy.node), unit.events)

    async def run_fragment(self, unit: Unit) -> UnitResult:
        async def run_step(name, inputs, ref: StepRef, intent):
            thread = f"{unit.thread}/{ref.number}/{ref.item}/{ref.attempt}"
            return await self.run_node(dataclasses.replace(unit, name=name, inputs=inputs, intent=intent, thread=thread))

        port = WalkPort(unit.topology, run_step, unit.call_tool, _no_checks, _InMemory())
        return await walk_fragment(port, unit.fragment, unit.inputs)

    async def close(self) -> None:
        pass

    async def _play(self, policy: Policy, steps: list, events: EventSink) -> UnitResult:
        state, said, made = policy.initial(), "", 0
        conversation = [Message("user", policy.opening)]
        for step in steps:
            if state["ending"] is not None:  # the run has ended (KIT-6)
                break
            events.emit(ModelRequested(policy.label, _request(policy, conversation)))
            if isinstance(step, str):  # the model says something and makes no call
                events.emit(ModelResponded(policy.label, ModelResponse(step, ())))
                said = step
                reply = policy.stopped(step, state)
                if reply is None:
                    break
                conversation += [Message("agent", step), Message("user", reply)]
                continue
            said, calls = "", []
            for name, args in step:
                made += 1
                calls.append(ToolCall(f"{policy.label}-{made}", name, args))
            response = ModelResponse("", tuple(calls))
            events.emit(ModelResponded(policy.label, response))
            review = policy.review(response, state)  # the whole response, before any call of it runs
            updates = []
            for call in calls:
                if call.id in review.refused:
                    result = CallResult(review.refused[call.id], error=True)
                else:
                    result = await policy.call(call, state)  # every call sees the state as it was before the response
                events.emit(ToolReturned(policy.label, call, result.text, result.error))
                conversation.append(Message("call", call_id=call.id, name=call.name, args=call.args, result=result.text))
                updates.append(result.update)
            for update in updates:  # in the response's order, after the last call (CTL-5)
                if update is not None:
                    state = merge(state, update)
        return policy.finish(state, said)


def _request(policy: Policy, conversation: list[Message]) -> tuple[RequestPart, ...]:
    """What the model is sent: the instructions and the tools of the brief, what the strategy handed over, the conversation."""
    tools = json.dumps([{"name": t.name, "description": t.description, "schema": t.schema} for t in policy.tools])
    return (
        RequestPart("instructions", text=policy.instructions),
        RequestPart("tools", text=tools),
        *((RequestPart("hand-over", messages=policy.handover),) if policy.handover else ()),
        RequestPart("conversation", messages=tuple(conversation)),
    )
