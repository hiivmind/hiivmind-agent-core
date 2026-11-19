from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from .values import BUILT_IN_OUTCOMES


def _outcomes(exits: tuple[str, ...]) -> tuple[str, ...]:
    return exits + tuple(o for o in BUILT_IN_OUTCOMES if o not in exits)


@dataclass(frozen=True)
class NodeContract:
    name: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    exits: tuple[str, ...]

    @property
    def outcomes(self) -> tuple[str, ...]:
        return _outcomes(self.exits)


@dataclass(frozen=True)
class Step:
    name: str   # a node or a fragment, by name
    mapping: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolList:
    tool: str
    args: dict = field(default_factory=dict)


@dataclass(frozen=True)
class FanOut:
    node: str
    over: str | ToolList
    as_: str
    into: str
    max_concurrency: int = 4


@dataclass(frozen=True)
class Link:
    sequence: str


END = "end"
Target = Step | FanOut | Link | Literal["end"]


@dataclass(frozen=True)
class Check:
    tool: str
    args: dict
    message: str
    outcome: str | None = None


@dataclass(frozen=True)
class SequenceDef:
    name: str
    description: str
    start: Target
    inputs: dict
    checks: tuple[Check, ...]
    transitions: Mapping[str, Mapping[str, Target]]


@dataclass(frozen=True)
class FragmentDef:
    name: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    exits: tuple[str, ...]
    start: Target
    transitions: Mapping[str, Mapping[str, Target]]

    @property
    def outcomes(self) -> tuple[str, ...]:
        return _outcomes(self.exits)


@dataclass(frozen=True)
class Topology:
    nodes: Mapping[str, NodeContract]
    sequences: Mapping[str, SequenceDef]
    fragments: Mapping[str, FragmentDef]
