from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

BUILT_IN_OUTCOMES = ("skipped", "stopped")
HARNESS_REASONS = ("needs_input", "invalid_output", "no_exit", "unknown_placeholder", "precondition_unmet")


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    schema: dict


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass(frozen=True)
class Message:
    kind: Literal["user", "agent", "call"]
    text: str = ""
    call_id: str = ""
    name: str = ""
    args: dict = field(default_factory=dict)
    result: str = ""


@dataclass(frozen=True)
class Usage:
    sent: int | None = None
    cache_read: int | None = None
    cache_written: int | None = None


@dataclass(frozen=True)
class ModelResponse:
    text: str
    calls: tuple[ToolCall, ...]
    usage: Usage = field(default_factory=Usage)


@dataclass(frozen=True)
class NodeNote:
    label: str
    node: str
    parts: tuple[tuple[str, int], ...]   # each part's source and length in characters (the record keeps lengths only)
    tools: tuple[str, ...]
    model_calls: int = 0
    usage: Usage = field(default_factory=lambda: Usage(0, 0, 0))
    requests: tuple[tuple[tuple[str, int], ...], ...] = ()   # each model request: its parts' kind and length in characters, never their content


@dataclass(frozen=True)
class Outcome:
    exit: str
    outputs: dict
    reason: str | None = None   # a harness reason (beside the outputs); a node's own `reason` stays inside `outputs`
    detail: dict = field(default_factory=dict)
    notes: tuple[NodeNote, ...] = ()
