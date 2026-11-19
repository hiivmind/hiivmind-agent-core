from collections.abc import Awaitable, Callable

from agent_core.contracts.journal import Walk
from agent_core.contracts.walk import WalkResult
from agent_core.contracts.registry import register


class _Reserved:
    async def run(self, name: str, call: Callable[[], Awaitable[object]]) -> object:
        return await call()


class _Steps:
    async def step(self, name: str, call: Callable[[], Awaitable[object]]) -> object:
        return await call()

    def reserve(self, count: int) -> list[_Reserved]:
        return [_Reserved() for _ in range(count)]


@register("journal", "none")
class NoJournal:
    """Runs each step and keeps nothing: there is nothing to resume."""

    async def start(self, run_id: str, walk: Walk, name: str, facts: dict) -> WalkResult:
        return await walk(_Steps(), name, facts)

    async def resume(self, run_id: str, walk: Walk) -> WalkResult:
        raise NotImplementedError

    async def rerun(self, run_id: str, from_run: str, step: int, walk: Walk) -> WalkResult:
        raise NotImplementedError

    async def sequence(self, run_id: str) -> str | None:
        return None   # nothing is kept

    async def close(self) -> None:
        pass
