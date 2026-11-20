"""What the provider is sent, with a real model: the Anthropic request bodies against what the facade says it sent."""

import os
import time

import pytest

from agent_core.contracts.events import ModelRequested, ModelResponded

pytestmark = [
    pytest.mark.model,
    pytest.mark.skipif(
        not (os.environ.get("AGENT_CORE_LANGGRAPH_MODEL") or "anthropic:").startswith("anthropic:"),
        reason="reads Anthropic's wire; another provider's has no reader here",
    ),
]


def requested(h) -> list[ModelRequested]:
    return [e for e in h.events.record() if isinstance(e, ModelRequested)]


def responded(h) -> list[ModelResponded]:
    return [e for e in h.events.record() if isinstance(e, ModelResponded)]


def part(request: ModelRequested, kind: str):
    [found] = [p for p in request.parts if p.kind == kind]
    return found


async def test_the_wire_carries_the_brief_and_nothing_else(harness, wire):   # KIT-4
    h = harness()
    outcome = await h.nodes.run("lookup", {"name": "alpha"})
    assert outcome.exit == "done"

    first, body = requested(h)[0], wire.requests[0]
    assert wire.system_text(body) == part(first, "instructions").text
    offered = [t[0] for t in wire.tools(body)]
    assert offered == [t["name"] for t in __import__("json").loads(part(first, "tools").text)]
    assert "lookup_revision" in offered and "exit" in offered
    [opening] = wire.messages(body)
    assert opening["role"] == "user"
    assert wire.text_of(opening["content"]) == "\n".join(m.text for m in part(first, "conversation").messages)


async def test_instructions_and_tools_do_not_change_during_a_run(harness, wire):   # SCOPE-2
    h = harness()
    outcome = await h.nodes.run("sweep")
    assert outcome.exit == "done"

    assert len(wire.requests) == len(responded(h)) >= 6
    for body in wire.requests:
        assert wire.system_text(body) == wire.system_text(wire.requests[0])
        assert wire.tools(body) == wire.tools(wire.requests[0])
    for before, after in zip(wire.requests, wire.requests[1:]):
        kept = wire.messages(before)
        assert wire.messages(after)[: len(kept)] == kept
        assert len(wire.messages(after)) > len(kept)


async def test_most_of_each_request_is_read_from_cache(harness, wire):   # KIT-7
    h = harness()
    outcome = await h.nodes.run("steady", {"stamp": __import__("uuid").uuid4().hex})
    assert outcome.exit == "done"

    answers = responded(h)
    assert len(answers) >= 3
    assert answers[0].response.usage.sent >= 3000
    for answer in answers[1:]:
        assert answer.response.usage.sent
        assert (answer.response.usage.cache_read or 0) / answer.response.usage.sent >= 0.8


async def test_cache_counts_are_numbers_or_none(harness, wire):   # SCOPE-7
    h = harness()
    outcome = await h.nodes.run("steady", {"stamp": __import__("uuid").uuid4().hex})
    assert outcome.exit == "done"

    answers = responded(h)
    assert answers
    for answer in answers:
        usage = answer.response.usage
        for count in (usage.sent, usage.cache_read, usage.cache_written):
            assert count is None or (isinstance(count, int) and count >= 0)
    first = answers[0].response.usage
    # A first request is sometimes served as a cache read (the same instructions were sent by an earlier run).
    assert (first.cache_read or 0) + (first.cache_written or 0) > 0
    [note] = outcome.notes
    fields = ("sent", "cache_read", "cache_written")
    counts = {f: [getattr(a.response.usage, f) for a in answers] for f in fields}
    expected = tuple(None if None in counts[f] else sum(counts[f]) for f in fields)   # SCOPE-7: unreported once any count is
    assert (note.usage.sent, note.usage.cache_read, note.usage.cache_written) == expected

async def test_a_call_held_for_twenty_seconds_is_not_cut_off(harness, wire):   # VERB-5's long call
    h = harness()
    started = time.monotonic()
    outcome = await h.nodes.run("slow")

    assert time.monotonic() - started >= 20
    assert outcome.exit == "done"
    results = [
        block
        for message in wire.messages(wire.requests[1])
        if isinstance(message["content"], list)
        for block in message["content"]
        if block.get("type") == "tool_result"
    ]
    assert len(results) == 1
    assert "r1" in str(results[0]["content"])
    assert not results[0].get("is_error")
