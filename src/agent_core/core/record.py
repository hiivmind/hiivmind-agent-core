"""What is kept of a run, for its record (JOB-9a, SCOPE-7): the notes of its node runs, its failures, and the record."""

import json
from collections.abc import Collection, Iterable, Mapping
from datetime import datetime, timezone

from pydantic import SecretBytes, SecretStr

from agent_core.contracts.events import Event, ModelRequested, ModelResponded, NodeStarted, RequestPart
from agent_core.contracts.facade import RunRecord
from agent_core.contracts.unit import UnitResult
from agent_core.contracts.values import NodeNote, Usage
from agent_core.contracts.walk import WalkResult


def now() -> str:
    """The time, as a record writes it."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _total(counts: list[int | None]) -> int | None:
    """A count is None, "not known", as soon as one response reports it as None; it is never read as zero."""
    return None if any(c is None for c in counts) else sum(counts)


def _length(part: RequestPart) -> int:
    """The characters of a request part: its text, and what each message of it says, returns and calls with."""
    return len(part.text) + sum(
        len(m.text) + len(m.result) + (len(json.dumps(m.args)) if m.args else 0) for m in part.messages
    )


def notes(events: Iterable[Event], labels: Collection[str]) -> tuple[NodeNote, ...]:
    """The note of each node run in `labels` that started, in that order: where each part of its instructions came from
    and how long it was, the tools it was offered, how many model calls it made and what they cost. A request is not
    kept: the note holds the kind and the length of each part of each request, and where the parts of the node's
    instructions came from and how long they were, never what any of them said (Q4)."""
    started: dict[str, NodeStarted] = {}
    responses: dict[str, list[Usage]] = {}
    requests: dict[str, list[tuple[tuple[str, int], ...]]] = {}
    for event in events:
        if isinstance(event, NodeStarted):
            started[event.label] = event
        elif isinstance(event, ModelRequested):
            requests.setdefault(event.label, []).append(tuple((p.kind, _length(p)) for p in event.parts))
        elif isinstance(event, ModelResponded):
            responses.setdefault(event.label, []).append(event.response.usage)
    found = []
    for label in labels:
        if label not in started:   # the node did not start: no model was called for it
            continue
        used = responses.get(label, [])
        usage = Usage(_total([u.sent for u in used]), _total([u.cache_read for u in used]), _total([u.cache_written for u in used]))
        found.append(NodeNote(
            label, started[label].node, started[label].parts, started[label].tools, len(used), usage,
            tuple(requests.get(label, ())),
        ))
    return tuple(found)


def failure(node: str, result: UnitResult) -> dict:
    """A failed node run as the record keeps it: the node, and what the result said."""
    return {
        "node": node,
        "outcome": result.exit,
        **({"reason": result.reason} if result.reason else {}),
        **result.detail,
        "outputs": result.outputs,
    }


def masked(params: Mapping[str, str], settings: object | None) -> dict[str, str]:
    """The params as the record keeps them: a value of a setting that is a secret is not written."""
    return {
        key: "********" if isinstance(getattr(settings, key, None), (SecretStr, SecretBytes)) else value
        for key, value in params.items()
    }


def build(
    *,
    params: dict,
    settings_files: list[str],
    backend: str,
    attended: bool,
    start: str,
    end: str,
    failures: list[dict],
    events: Iterable[Event],
    labels: Collection[str],
    run_id: str,
    sequence: str | None,
    result: WalkResult | None = None,
    error: str | None = None,
    progress: Mapping | None = None,
) -> RunRecord:
    """The record of a sequence run that ended with `result`, or raised `error` (`Type: message`). `sequence` is the name of the sequence run (None if it is not known). `labels` are the node
    runs of this process: a resumed run's finished steps are in `steps`, not in `notes`. A run that raised keeps what the
    walk had reached, from `progress`: the steps it took (the one that was running with no outcome) and its facts."""
    if error is not None:
        progress = progress or {}
        status, end_state, summary = "failed", "failed", error
        steps = list(progress.get("trail", []))
        facts = dict(progress["facts"]) if progress.get("facts") is not None else None
    else:
        status = "failed" if result["end"] == "failed" else "ok"
        end_state, summary, steps, facts = result["end"], result["summary"], result["trail"], result["facts"]
    return RunRecord(
        params=params,
        settings_files=settings_files,
        backend=backend,
        attended=attended,
        start=start,
        end=end,
        status=status,
        summary=summary,
        failures=failures,
        notes=list(notes(events, labels)),
        run_id=run_id,
        sequence=sequence,
        end_state=end_state,
        steps=steps,
        facts=facts,
    )


def session_record(
    *,
    params: dict,
    settings_files: list[str],
    backend: str,
    attended: bool,
    start: str,
    end: str,
    failures: list[dict],
    events: Iterable[Event],
    labels: Collection[str],
    session_id: str,
    end_state: str,
    facts: dict,
) -> RunRecord:
    """The record of this process's part of a session (design §3.6): the notes of its node runs, routing and summary runs
    included (SCOPE-7), its failures, and the session facts. `end_state` is `ended` or `waiting`; `sequence` is None."""
    return RunRecord(
        params=params,
        settings_files=settings_files,
        backend=backend,
        attended=attended,
        start=start,
        end=end,
        status="ok",
        summary=None,
        failures=failures,
        notes=list(notes(events, labels)),
        run_id=session_id,
        sequence=None,
        end_state=end_state,
        steps=None,
        facts=dict(facts),
    )
