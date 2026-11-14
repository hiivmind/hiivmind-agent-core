"""What is kept of each node run, for the record of a job (SCOPE-7)."""

from dataclasses import dataclass


@dataclass
class NodeRunNote:
    """One node run: where each part of its instructions came from and how long it was (in characters), the tools
    it was offered, the handover it was given, and what it cost.

    A count is None, "not known", as soon as one response of the run reports it as None; it is never read as zero.
    """

    label: str
    node: str
    parts: list[tuple[str, int]]
    tools: list[str]
    handover: list[str]
    model_calls: int = 0
    tokens_sent: int | None = 0
    cache_read: int | None = 0
    cache_written: int | None = 0
