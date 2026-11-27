from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from .topology import NodeContract
from .values import Message


@dataclass(frozen=True)
class HandoverRequest:
    transcript: tuple[Mapping, ...]   # the session's transcript entries (CTX-5): {"user"}, {"agent"}, a node's or a sequence's
    facts: dict
    node: str
    inputs: dict
    contract: NodeContract
    summarise: Callable[[str, str], Awaitable[str]]


class ContextStrategy(Protocol):
    async def build(self, request: HandoverRequest) -> tuple[Message, ...]: ...
