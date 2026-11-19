from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from .values import Message, ModelResponse, ToolCall


@dataclass(frozen=True)
class RequestPart:
    kind: Literal["instructions", "tools", "hand-over", "conversation"]
    messages: tuple[Message, ...] = ()
    text: str = ""   # tools as their JSON in `text`


@dataclass(frozen=True)
class NodeStarted:
    label: str
    node: str
    parts: tuple[tuple[str, int], ...]
    tools: tuple[str, ...]


@dataclass(frozen=True)
class ModelRequested:
    label: str
    parts: tuple[RequestPart, ...]


@dataclass(frozen=True)
class ModelResponded:
    label: str
    response: ModelResponse


@dataclass(frozen=True)
class ToolReturned:
    label: str
    call: ToolCall
    text: str
    error: bool


@dataclass(frozen=True)
class NodeEnded:
    label: str
    node: str
    exit: str
    reason: str | None


Event = NodeStarted | ModelRequested | ModelResponded | ToolReturned | NodeEnded


class EventSink(Protocol):
    def emit(self, event: Event) -> None: ...
