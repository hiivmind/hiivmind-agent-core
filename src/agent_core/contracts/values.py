from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    schema: dict


@dataclass(frozen=True)
class Message:
    kind: Literal["user", "agent", "call"]
    text: str = ""
    call_id: str = ""
    name: str = ""
    args: dict = field(default_factory=dict)
    result: str = ""


@dataclass(frozen=True)
class Brief:
    instructions: str
    tools: tuple[ToolSpec, ...]
    handover: tuple[Message, ...]
    opening: str


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass(frozen=True)
class ModelResponse:
    text: str
    calls: tuple[ToolCall, ...]
    sent: int | None
    cache_read: int | None
    cache_written: int | None


@dataclass(frozen=True)
class Result:
    text: str
    error: bool = False


@dataclass(frozen=True)
class EndRun:
    pass


Outcome = Result | EndRun


@dataclass(frozen=True)
class RunEnd:
    by_controller: bool
    said: str


@dataclass(frozen=True)
class HandoverRequest:
    transcript: tuple[Message, ...]
    facts: dict
    node: str
    inputs: dict
    summarise: Callable[[str, str], Awaitable[str]]
