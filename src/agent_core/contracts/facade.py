from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from .events import Event
from .values import NodeNote, Outcome


@dataclass(frozen=True)
class RunRecord:
    params: dict
    settings_files: list[str]
    backend: str
    attended: bool
    start: str
    end: str | None
    status: str | None
    summary: object
    failures: list[dict]
    notes: list[NodeNote]
    run_id: str | None
    sequence: str | None   # the sequence run; None for a node run outside a sequence
    end_state: str | None
    steps: list | None
    facts: dict | None

    def to_json(self) -> str:
        """The record as `record.json` holds it. A value that is not JSON is a `TypeError` naming its field (Q7)."""
        fields = dataclasses.asdict(self)
        try:
            return json.dumps(fields, indent=2)
        except TypeError:
            for name, value in fields.items():
                try:
                    json.dumps(value)
                except TypeError as e:
                    raise TypeError(f"{name}: {e}") from None
            raise


@dataclass(frozen=True)
class SequenceResult:
    end: str
    facts: dict
    steps: list[dict]
    run_id: str
    summary: object
    record: RunRecord
    run_dir: Path   # where the run kept its files; the CLI writes `record.json` there (RP-6)
    outputs: dict   # the declared outputs its steps returned, whether or not the run raised (SS-10)


@dataclass(frozen=True)
class SessionResult:
    session_id: str
    state: Literal["ended", "waiting"]   # waiting: saved, for a person who has gone; resume it by its id (SS-5)
    facts: dict
    record: RunRecord   # this process's part of the session (RP-5)
    session_dir: Path   # where the session is kept; the CLI writes `record.json` there


@runtime_checkable
class Nodes(Protocol):
    async def run(self, node: str, inputs: Mapping | None = None, *, backend: str | None = None) -> Outcome: ...


@runtime_checkable
class Sequences(Protocol):
    async def run(self, name: str, inputs: Mapping | None = None, *, run_id: str | None = None) -> SequenceResult: ...
    async def resume(self, run_id: str, *, name: str | None = None, run_dir: Path | None = None) -> SequenceResult: ...
    async def rerun(
        self, run_id: str, from_step: int, *, new_run_id: str | None = None, name: str | None = None, run_dir: Path | None = None
    ) -> SequenceResult: ...


@runtime_checkable
class Tools(Protocol):
    def register(self, fn: Callable, name: str | None = None) -> None: ...
    def register_server(self, name: str, spec: dict) -> None: ...


@runtime_checkable
class Events(Protocol):
    def record(self) -> tuple[Event, ...]: ...


@runtime_checkable
class Extensions(Protocol):
    def register(self, kind: str, name: str, provider: object) -> None: ...   # kinds: backend, context, person, resources, journal, store


@runtime_checkable
class Sessions(Protocol):
    async def start(self, name: str | None = None, *, session_id: str | None = None) -> SessionResult: ...
    async def resume(self, session_id: str) -> SessionResult: ...


@runtime_checkable
class Harness(Protocol):
    nodes: Nodes
    sequences: Sequences
    tools: Tools
    events: Events
    extensions: Extensions

    @property
    def sessions(self) -> Sessions: ...   # raises FeatureNotSupported where the backend builds no sessions (FAC-5)

    async def close(self) -> None: ...
    async def __aenter__(self) -> Harness: ...
    async def __aexit__(self, *exc: object) -> None: ...
