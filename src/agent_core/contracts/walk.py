from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict

from .topology import Check, Topology
from .unit import Intent, UnitResult

if TYPE_CHECKING:
    from .journal import Steps

RETRY_PAUSE = 60   # seconds between a refused model call and its second run


@dataclass(frozen=True)
class StepRef:
    number: int
    item: int = 0
    attempt: int = 1


RunStep = Callable[[str, Mapping, StepRef, Intent], Awaitable[UnitResult]]   # a node or a fragment, by name


@dataclass
class WalkPort:
    topology: Topology
    run_step: RunStep
    call_tool: Callable[[str, dict], Awaitable[object]]
    check: Callable[[Sequence[Check], dict, str], Awaitable[tuple[dict | None, dict]]]
    steps: Steps
    pause: float = RETRY_PAUSE


class WalkResult(TypedDict):   # a TypedDict, so DBOS records it as the dict it was in v0
    end: str
    trail: list[dict]
    facts: dict
    summary: object
    sequence: str   # the sequence walked, kept with the result, so that a journal that hands a finished run's result back names it
    outputs: dict   # the declared outputs the steps returned, in the order they ended, apart from the other facts (SS-10)
