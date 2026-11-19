"""F15 tracing: each node run emits neutral events, in the order they happened, and the record keeps their counts."""

import pytest

from agent_core.contracts.events import ModelRequested, ModelResponded, NodeEnded, NodeStarted, ToolReturned

LOOKUP = [["lookup_revision", {"name": "alpha"}]]
EXIT = [["exit", {"outcome": "done", "outputs": {}}]]


@pytest.mark.feature("F15")
async def test_a_node_run_emits_its_events_in_order(harness):
    h = harness({"lookup": [LOOKUP, EXIT]})
    await h.nodes.run("lookup", {"name": "alpha"})
    assert [type(e) for e in h.events.record()] == [
        NodeStarted, ModelRequested, ModelResponded, ToolReturned, ModelRequested, ModelResponded, ToolReturned, NodeEnded,
    ]


@pytest.mark.feature("F15")
async def test_the_events_of_a_run_carry_its_label_and_what_happened(harness):
    h = harness({"lookup": [LOOKUP, EXIT]})
    outcome = await h.nodes.run("lookup", {"name": "alpha"})
    events = h.events.record()
    assert {e.label for e in events} == {"lookup#1"}
    started, ended = events[0], events[-1]
    assert (started.node, started.tools) == ("lookup", ("exit", "ask", "state_set", "state_get", "load", "lookup_revision"))
    assert (ended.node, ended.exit, ended.reason) == ("lookup", "done", None)
    [responded, _] = [e for e in events if isinstance(e, ModelResponded)]
    assert [(c.name, c.args) for c in responded.response.calls] == [("lookup_revision", {"name": "alpha"})]
    assert outcome.notes[0].label == "lookup#1"


@pytest.mark.feature("F15")
async def test_each_node_run_has_a_label_of_its_own_in_the_order_they_started(harness):
    h = harness({"lookup": [LOOKUP, EXIT]})
    await h.nodes.run("lookup", {"name": "alpha"})
    await h.nodes.run("lookup", {"name": "beta"})
    assert [e.label for e in h.events.record() if isinstance(e, NodeStarted)] == ["lookup#1", "lookup#2"]


@pytest.mark.feature("F15")
async def test_the_note_of_a_node_run_counts_its_model_calls_and_keeps_the_length_of_each_part_never_the_text(harness):
    h = harness({"lookup": [LOOKUP, EXIT]})
    [note] = (await h.nodes.run("lookup", {"name": "alpha"})).notes
    assert (note.node, note.model_calls, len(note.requests)) == ("lookup", 2, 2)
    assert [kind for kind, _ in note.requests[0]] == ["instructions", "tools", "conversation"]
    assert all(isinstance(length, int) for request in note.requests for _, length in request)
