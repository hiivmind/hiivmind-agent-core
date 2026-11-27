from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Question:
    """A question a node run puts to the person (JOB-6): its text, the node, the node's run number in the harness, and
    the inputs the run was given. How it is shown is the person's own (RP-8)."""

    text: str
    node: str
    number: int
    inputs: Mapping[str, object]


class Person(Protocol):
    async def tell(self, text: str) -> None: ...
    async def ask(self, question: Question) -> str | None: ...  # None: nobody is there
    async def hear(self) -> str | None: ...  # a turn that answers no question; None: nobody is there
