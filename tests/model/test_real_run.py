"""A real `harness.nodes.run` of the toy `lookup` node on Haiku: F1 to F5 and F11 with a real model."""

import pytest

from agent_core.contracts.events import ModelResponded, ToolReturned

pytestmark = pytest.mark.model


async def test_the_lookup_node_ends_done_with_its_outputs(harness, wire):
    h = harness()
    outcome = await h.nodes.run("lookup", {"name": "beta"})

    assert (outcome.exit, outcome.reason) == ("done", None)
    assert outcome.outputs == {"revision": "r2"}
    [note] = outcome.notes
    assert note.node == "lookup" and note.model_calls == len(wire.requests) >= 2
    events = h.events.record()
    returned = [(e.call.name, e.error) for e in events if isinstance(e, ToolReturned)]
    assert returned[0] == ("lookup_revision", False) and returned[-1] == ("exit", False)
    assert sum(isinstance(e, ModelResponded) for e in events) == note.model_calls
