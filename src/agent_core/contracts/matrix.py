from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Literal


class Feature(Enum):
    """A feature of the wiring matrix: the value is the id; `title` names it."""

    title: str

    F1 = ("F1", "loop")
    F2 = ("F2", "tool calling")
    F3 = ("F3", "MCP")
    F4 = ("F4", "function tools")
    F5 = ("F5", "state")
    F6 = ("F6", "session persistence")
    F7 = ("F7", "durable resume")
    F8 = ("F8", "ask a person")
    F9 = ("F9", "hand-over")
    F10 = ("F10", "compaction")
    F11 = ("F11", "output contract")
    F12 = ("F12", "retries")
    F13 = ("F13", "caching")
    F14 = ("F14", "usage")
    F15 = ("F15", "tracing")
    F16 = ("F16", "orchestration")
    F17 = ("F17", "routing")
    F18 = ("F18", "permission")
    F19 = ("F19", "streaming")
    F20 = ("F20", "model choice")
    F21 = ("F21", "instructions")
    F22 = ("F22", "skills")
    F23 = ("F23", "sub-agents")
    F24 = ("F24", "call limits")

    def __new__(cls, id: str, title: str) -> Feature:
        member = object.__new__(cls)
        member._value_ = id
        member.title = title
        return member

    @property
    def id(self) -> str:
        return self.value


@dataclass(frozen=True)
class Entry:
    state: Literal["native", "helper", "divergent", "not built"]
    means: str


Matrix = Mapping[Feature, Entry]
