"""What a context strategy is given and gives (CTX-4), and the session's transcript as a hand-over (CTX-5).

A function on plain values, as `policy.merge` is, so that a strategy and the core's routing run use the same one: a
provider may not import the core (LAYER-3)."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from .topology import NodeContract
from .values import Message

OPENING_NOTE = "(The harness: the conversation so far follows.)"


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


def _note(entry: Mapping) -> str:
    """A node's or a sequence's run, as a note from the harness."""
    inputs = json.dumps(entry.get("inputs") or {})
    if "sequence" in entry:
        return f"(The harness: the sequence `{entry['sequence']}` ran with inputs {inputs} and ended `{entry['end']}`.)"
    reason = f", reason: {entry['reason']}" if entry.get("reason") else ""
    return f"(The harness: the node `{entry['node']}` ran with inputs {inputs} and ended `{entry['outcome']}`{reason}.)"


def transcript_handover(transcript: Sequence[Mapping]) -> tuple[Message, ...]:
    """The transcript as hand-over items: what the person said as `user`, what they were told as `agent`, and each node or
    sequence run as a `user` note from the harness. One that would open with the agent opens with a note, so that every
    provider accepts it (design §8.3)."""
    handed = [
        Message("user", entry["user"]) if "user" in entry
        else Message("agent", entry["agent"]) if "agent" in entry
        else Message("user", _note(entry))
        for entry in transcript
    ]
    if handed and handed[0].kind == "agent":
        handed.insert(0, Message("user", OPENING_NOTE))
    return tuple(handed)
