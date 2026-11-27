from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, TypedDict

from .values import HarnessReason, Message, ModelResponse, ToolCall, ToolSpec

if TYPE_CHECKING:
    from .unit import UnitResult


class NodeState(TypedDict):
    inputs: dict
    values: dict
    outputs: dict
    session: dict
    rejections: int
    ending: dict | None


@dataclass(frozen=True)
class Ending:
    outcome: str
    outputs: dict
    reason: HarnessReason | None = None
    detail: dict = field(default_factory=dict)


@dataclass(frozen=True)
class StateUpdate:
    inputs: dict = field(default_factory=dict)
    values: dict = field(default_factory=dict)
    outputs: dict = field(default_factory=dict)
    session: dict = field(default_factory=dict)
    rejected: bool = False
    ending: Ending | None = None


@dataclass(frozen=True)
class CallResult:
    text: str
    error: bool = False
    update: StateUpdate | None = None


@dataclass(frozen=True)
class Review:
    refused: Mapping[str, str]   # call id -> refusal text; a call not in it runs


def merge(state: NodeState, update: StateUpdate) -> NodeState:
    new: NodeState = copy.deepcopy(state)
    for part in ("inputs", "values", "outputs", "session"):
        new[part].update(copy.deepcopy(getattr(update, part)))
    if update.rejected:
        new["rejections"] += 1
    if update.ending is not None:
        e = update.ending
        new["ending"] = {"outcome": e.outcome, "outputs": copy.deepcopy(e.outputs), "reason": e.reason,
                         "detail": copy.deepcopy(e.detail)}
    return new


class Policy(Protocol):
    label: str
    node: str
    instructions: str
    tools: tuple[ToolSpec, ...]
    handover: tuple[Message, ...]
    opening: str

    def initial(self) -> NodeState: ...
    def review(self, response: ModelResponse, state: NodeState) -> Review: ...
    async def call(self, call: ToolCall, state: NodeState) -> CallResult: ...   # a verb, a function tool, or a server tool
    async def responded(self, response: ModelResponse, state: NodeState) -> str | None: ...   # once for each response, before any of its calls runs; what to tell the model when it made no call; None ends the run
    def finish(self, state: NodeState, said: str) -> UnitResult: ...   # emits NodeEnded
