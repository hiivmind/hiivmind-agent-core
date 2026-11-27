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


@pytest.mark.feature("F9")
async def test_a_node_with_context_all_is_handed_the_transcript(harness, copied, tmp_path):   # NODE-15, CTX-5
    from session_support import ScriptedPerson

    from agent_core.core.session import SessionPort, new_state
    from agent_core.stores.file import FileStore

    node = copied / "nodes" / "record.md"
    node.write_text(node.read_text().replace("allowed-tools: []\n", "allowed-tools: []\ncontext: all\n", 1))
    h = harness({"record": [[["exit", {"outcome": "done", "outputs": {"note": "n"}}]]]}, instance=copied)
    port = SessionPort(new_state(), FileStore(tmp_path / "runs"), "s", ScriptedPerson())
    port.state["transcript"] = [{"user": "add a note"}, {"agent": "Which note?"}]
    run = await h.begin(tmp_path / "runs" / "s", session=port)
    try:
        await h.backend(None).run_node(run.unit("record", {}, "start", "s/1"))
    finally:
        await run.end()
    hand_over = [part.messages for e in requested(h) for part in e.parts if part.kind == "hand-over"]
    assert hand_over == [(Message("user", "add a note"), Message("agent", "Which note?"))]
