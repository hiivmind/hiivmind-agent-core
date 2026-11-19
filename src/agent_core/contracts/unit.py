from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

from .events import EventSink
from .tools import ToolSource
from .topology import FragmentDef, Topology
from .values import ToolSpec

if TYPE_CHECKING:
    from .policy import Policy

Intent = Literal["start", "continue", "fresh"]


@dataclass(frozen=True)
class DeclaredTools:
    specs: Mapping[str, ToolSpec]
    functions: frozenset[str]
    servers: ToolSource


@dataclass(frozen=True)
class UnitResult:
    exit: str
    outputs: dict
    reason: str | None = None
    detail: dict = field(default_factory=dict)
    steps: tuple[dict, ...] = ()   # a fragment's inner trail, [{"name", "outcome"[, "outputs" of a failed step][, "reason"][, "detail"]}] in the order they ended


class NodeStart(Protocol):
    async def __call__(self, node: str, inputs: Mapping) -> Policy | UnitResult: ...   # a UnitResult when the node does not start


@dataclass(frozen=True)
class Unit:
    name: str
    inputs: Mapping
    intent: Intent
    thread: str
    start: NodeStart
    tools: DeclaredTools
    events: EventSink
    topology: Topology
    call_tool: Callable[[str, dict], Awaitable[object]]   # a declared tool called by the harness
    fragment: FragmentDef | None = None
    run_dir: Path | None = None   # where a backend keeps the unit's checkpoints; None outside a sequence
