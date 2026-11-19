"""How a sequence's steps are run and recorded, so that a crashed run can be resumed.

The walk calls `Steps`; a `RunJournal` runs the walk and decides what each step does
on a resume. No provider type appears here (LAYER-2).
"""

from collections.abc import Awaitable, Callable
from typing import Protocol

from .walk import WalkResult


class Reserved(Protocol):
    async def run(self, name: str, call: Callable[[], Awaitable[object]]) -> object: ...


class Steps(Protocol):
    async def step(self, name: str, call: Callable[[], Awaitable[object]]) -> object:
        """Run `call` once as one journalled step; return the awaited result of `call()`."""

    def reserve(self, count: int) -> list[Reserved]:
        """Take the next `count` step numbers at once, for steps that run concurrently."""


Walk = Callable[[Steps, str, dict], Awaitable[WalkResult]]   # (steps, sequence name, starting facts) -> the walk's result


class RunJournal(Protocol):
    async def start(self, run_id: str, walk: Walk, name: str, facts: dict) -> WalkResult: ...
    async def resume(self, run_id: str, walk: Walk) -> WalkResult: ...
    async def rerun(self, run_id: str, from_run: str, step: int, walk: Walk) -> WalkResult: ...
    async def sequence(self, run_id: str) -> str | None:
        """The sequence the run `run_id` was started with, from its stored arguments, whatever its status; None if the
        journal does not know the run. Nothing is run."""
        ...

    async def close(self) -> None: ...
