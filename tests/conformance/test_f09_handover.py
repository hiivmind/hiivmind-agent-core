"""F9 hand-over: a node starts with what its context strategy hands it; the `none` strategy hands it nothing."""

import pytest

from agent_core.contracts.events import ModelRequested
from agent_core.contracts.values import Message

EXIT = [["exit", {"outcome": "done", "outputs": {"revision": "r1"}}]]


def requested(h):
    return [e for e in h.events.record() if isinstance(e, ModelRequested)]


@pytest.mark.feature("F9")
async def test_the_none_strategy_hands_a_node_nothing(harness):
    h = harness({"lookup": [EXIT]})
    await h.nodes.run("lookup", {"name": "alpha"})
    assert {part.kind for e in requested(h) for part in e.parts} == {"instructions", "tools", "conversation"}


@pytest.mark.feature("F9")
async def test_what_a_strategy_hands_over_is_in_each_request_of_the_node(harness):
    class Earlier:
        async def build(self, request):
            return (Message("user", "earlier question"), Message("agent", "earlier answer"))

    h = harness({"lookup": [[["lookup_revision", {"name": "alpha"}]], EXIT]})
    h.extensions.register("context", "none", Earlier)
    await h.nodes.run("lookup", {"name": "alpha"})
    hand_over = [[part.messages for part in e.parts if part.kind == "hand-over"] for e in requested(h)]
    both = (Message("user", "earlier question"), Message("agent", "earlier answer"))
    assert hand_over == [[both], [both]]
