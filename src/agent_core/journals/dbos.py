"""The `dbos` journal: the walk of a sequence run is one DBOS workflow and each step a DBOS step (design §4.7).

DBOS is one per process. Each process launches it under an executor id of its own, so that starting a process never
recovers a run it does not name (RESUME-4), and listens only to a queue of its own, so that a run it resumes or
re-runs is run here, with this process's settings and tools, and by no other process sharing the journal.

DBOS is launched from the loop the run was opened on, and runs a resumed or re-run workflow on that loop, where the
run's tools and drivers live (tests/journals/test_dbos.py checks it).
"""

import importlib.metadata
import secrets
from collections.abc import Awaitable, Callable
from pathlib import Path

from dbos import DBOS, SetWorkflowID

from agent_core.contracts.journal import Walk
from agent_core.contracts.walk import WalkResult
from agent_core.contracts.registry import register

_RUN: dict = {}   # the walk this process runs; DBOS records a workflow's arguments, so the workflow reaches it here


def _awaited(call: Callable[[], Awaitable[object]]) -> Callable[[], Awaitable[object]]:
    """A coroutine function, so that DBOS awaits `call()` and records its result, not a coroutine."""

    async def awaited() -> object:
        return await call()

    return awaited


class _Reserved:
    def __init__(self, reservation):
        self._reservation = reservation

    async def run(self, name: str, call: Callable[[], Awaitable[object]]) -> object:
        return await self._reservation.run_async({"name": name}, _awaited(call))


class _Steps:
    async def step(self, name: str, call: Callable[[], Awaitable[object]]) -> object:
        return await DBOS.run_step_async({"name": name}, _awaited(call))

    def reserve(self, count: int) -> list[_Reserved]:
        return [_Reserved(DBOS.reserve_step()) for _ in range(count)]


@DBOS.workflow()
async def _sequence(name: str, facts: dict) -> WalkResult:
    return await _RUN["walk"](_Steps(), name, facts)


def _version() -> str:
    return importlib.metadata.version("agent-core")


@register("journal", "dbos")
class DbosJournal:
    """Keeps each step's result in the SQLite file `journal_file`, so that a crashed run can be resumed by its id."""

    def __init__(self, journal_file: Path | str, app_name: str, run_id: str):
        self._file, self._app, self._queue = Path(journal_file), app_name, f"run-{run_id}"
        self._launched = False

    def _launch(self, walk: Walk, executor_id: str) -> None:
        _RUN["walk"] = walk
        DBOS(config={
            "name": self._app,
            "system_database_url": f"sqlite:///{self._file}",
            "executor_id": executor_id,
            "application_version": _version(),
            "log_level": "WARNING",
        })
        DBOS.listen_queues([self._queue])
        DBOS.launch()
        self._launched = True

    async def _own_queue(self, walk: Walk, run_id: str) -> None:
        self._launch(walk, f"{run_id}~{secrets.token_hex(3)}")
        await DBOS.register_queue_async(self._queue)

    async def start(self, run_id: str, walk: Walk, name: str, facts: dict) -> WalkResult:
        self._launch(walk, run_id)
        with SetWorkflowID(run_id):
            return await _sequence(name, facts)

    async def resume(self, run_id: str, walk: Walk) -> WalkResult:
        await self._own_queue(walk, run_id)
        handle = await DBOS.resume_workflow_async(run_id, queue_name=self._queue)
        return await handle.get_result()

    async def rerun(self, run_id: str, from_run: str, step: int, walk: Walk) -> WalkResult:
        await self._own_queue(walk, run_id)
        with SetWorkflowID(run_id):
            handle = await DBOS.fork_workflow_async(
                from_run, step, application_version=_version(), queue_name=self._queue
            )
        return await handle.get_result()

    async def close(self) -> None:
        if self._launched:
            DBOS.destroy()
            self._launched = False
