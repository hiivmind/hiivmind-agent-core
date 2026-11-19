"""F24 call limits: a node that keeps calling tools is ended by the backend's recursion limit, and the error is not retried."""

import pytest
from langgraph.errors import GraphRecursionError

from agent_core.contracts.events import ModelRequested, ModelResponded, NodeStarted

LOOKUP = [["lookup_revision", {"name": "alpha"}]]


def counts(h) -> tuple[int, int, int]:
    events = h.events.record()
    return tuple(sum(isinstance(e, kind) for e in events) for kind in (NodeStarted, ModelRequested, ModelResponded))


@pytest.mark.feature("F24")
async def test_the_recursion_limit_ends_a_looping_node(harness, monkeypatch):
    monkeypatch.setenv("AGENT_CORE_LANGGRAPH_RECURSION_LIMIT", "6")
    h = harness({"lookup": [LOOKUP] * 20})
    with pytest.raises(GraphRecursionError):
        await h.nodes.run("lookup", {"name": "alpha"})
    assert counts(h) == (1, 2, 1)   # six steps reach the second model request; one run, never repeated


@pytest.mark.feature("F24", "F16")   # runs once the backend builds fragments (Plan 2, task 9); skipped until then
async def test_a_looping_fan_out_item_fails_with_the_limit_and_is_not_run_again(harness, monkeypatch):
    monkeypatch.setenv("AGENT_CORE_LANGGRAPH_RECURSION_LIMIT", "6")
    h = harness({"lookup": [LOOKUP] * 20})
    result = await h.sequences.run("pairs", {"names": ["alpha"]})
    assert result.end == "failed"
    [failure] = result.facts["revisions_failures"]
    assert failure["item"] == "alpha" and "GraphRecursionError" in str(failure)
    assert counts(h) == (1, 2, 1)   # the item ran once: the walk retries only ProviderUnavailable
