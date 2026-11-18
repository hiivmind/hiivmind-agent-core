"""What is kept of a run, for its record (JOB-9a, SCOPE-7): the notes of its node runs, its failures, and the record."""

from collections.abc import Collection, Iterable, Mapping

from pydantic import SecretBytes, SecretStr

from agent_core.contracts.events import Event, ModelResponded, NodeStarted
from agent_core.contracts.facade import RunRecord
from agent_core.contracts.unit import UnitResult
from agent_core.contracts.values import NodeNote, Usage
from agent_core.contracts.walk import WalkResult


def _total(counts: list[int | None]) -> int | None:
    """A count is None, "not known", as soon as one response reports it as None; it is never read as zero."""
    return None if any(c is None for c in counts) else sum(counts)


def notes(events: Iterable[Event], labels: Collection[str]) -> tuple[NodeNote, ...]:
    """The note of each node run in `labels` that started, in that order: where each part of its instructions came from
    and how long it was, the tools it was offered, how many model calls it made and what they cost. A request is not
    kept: the note holds the lengths of the parts of the node's instructions only (Q4)."""
    started: dict[str, NodeStarted] = {}
    responses: dict[str, list[Usage]] = {}
    for event in events:
        if isinstance(event, NodeStarted):
            started[event.label] = event
        elif isinstance(event, ModelResponded):
            responses.setdefault(event.label, []).append(event.response.usage)
    found = []
    for label in labels:
        if label not in started:   # the node did not start: no model was called for it
            continue
        used = responses.get(label, [])
        usage = Usage(_total([u.sent for u in used]), _total([u.cache_read for u in used]), _total([u.cache_written for u in used]))
        found.append(NodeNote(label, started[label].node, started[label].parts, started[label].tools, len(used), usage))
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
    result: WalkResult | None = None,
    error: str | None = None,
) -> RunRecord:
    """The record of a sequence run that ended with `result`, or raised `error` (`Type: message`). `labels` are the node
    runs of this process: a resumed run's finished steps are in `steps`, not in `notes`."""
    if error is not None:
        status, end_state, summary, steps, facts = "failed", "failed", error, [], None
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
        end_state=end_state,
        steps=steps,
        facts=facts,
    )
