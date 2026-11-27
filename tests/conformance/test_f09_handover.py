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


def with_context(copied, node, strategy):
    file = copied / "nodes" / f"{node}.md"
    file.write_text(file.read_text().replace("allowed-tools: []\n", f"allowed-tools: []\ncontext: {strategy}\n", 1))
    return copied


def session_port(tmp_path, person=None):
    from session_support import ScriptedPerson

    from agent_core.core.session import SessionPort, new_state
    from agent_core.stores.file import FileStore

    port = SessionPort(new_state(), FileStore(tmp_path / "runs"), "s", person or ScriptedPerson())
    port.state["transcript"] = [{"user": "add a note"}, {"agent": "Which note?"}]
    return port


async def run_in_session(h, port, node, intent="start", thread="s/1"):
    run = await h.begin(h.runs / "s", session=port)
    try:
        return await h.backend(None).run_node(run.unit(node, {}, intent, thread))
    finally:
        await run.end()


def summaries(h):
    return [e for e in requested(h) if e.label.startswith("@summary")]


@pytest.mark.feature("F9")
async def test_a_node_with_context_all_is_handed_the_transcript(harness, copied, tmp_path):   # NODE-15, CTX-5
    h = harness({"record": [[["exit", {"outcome": "done", "outputs": {"note": "n"}}]]]}, instance=with_context(copied, "record", "all"))
    await run_in_session(h, session_port(tmp_path), "record")
    hand_over = [part.messages for e in requested(h) for part in e.parts if part.kind == "hand-over"]
    assert hand_over == [(Message("user", "add a note"), Message("agent", "Which note?"))]


@pytest.mark.feature("F9")
async def test_a_node_with_context_summary_is_handed_one_note_made_once(harness, copied, tmp_path):   # NODE-15, CTX-4
    record = [[["state_get", {"key": "x"}]], [["exit", {"outcome": "done", "outputs": {"note": "n"}}]]]
    scripts = {"record": record, "@summary": ["The user asked for alpha."]}
    h = harness(scripts, instance=with_context(copied, "record", "summary"))
    await run_in_session(h, session_port(tmp_path), "record")
    note = (Message("user", "(The harness: a summary of the session so far. The user asked for alpha.)"),)
    node_requests = [e for e in requested(h) if e.label.startswith("record")]
    assert [[p.messages for p in e.parts if p.kind == "hand-over"] for e in node_requests] == [[note], [note]]
    assert len(summaries(h)) == 1


@pytest.mark.feature("F9")
async def test_a_summary_is_not_told_to_the_person(harness, copied, tmp_path):   # CTX-4
    from session_support import ScriptedPerson

    person = ScriptedPerson()
    scripts = {"record": [[["exit", {"outcome": "done", "outputs": {"note": "n"}}]]], "@summary": ["The user asked for alpha."]}
    h = harness(scripts, instance=with_context(copied, "record", "summary"))
    await run_in_session(h, session_port(tmp_path, person), "record")
    assert person.told == []


@pytest.mark.feature("F9")
async def test_each_summary_of_a_harness_has_a_label_of_its_own(harness, copied, tmp_path):   # SCOPE-7, final review 10
    scripts = {"record": [[["exit", {"outcome": "done", "outputs": {"note": "n"}}]]], "@summary": ["The user asked for alpha."]}
    h = harness(scripts, instance=with_context(copied, "record", "summary"))
    await run_in_session(h, session_port(tmp_path), "record")
    await run_in_session(h, session_port(tmp_path), "record", thread="s/2")
    assert len({e.label for e in summaries(h)}) == 2


@pytest.mark.feature("F9")
async def test_a_continued_unit_does_not_summarise_again(harness, copied, tmp_path):   # SS-14
    from session_support import ScriptedPerson

    from agent_core.contracts.errors import SessionWaits

    ask = [[["ask", {"question": "Which colour?"}]], [["exit", {"outcome": "done", "outputs": {"colour": "red"}}]]]
    scripts = {"ask": ask, "@summary": ["The user asked for alpha."]}
    instance = with_context(copied, "ask", "summary")
    person = ScriptedPerson([])
    port = session_port(tmp_path, person)
    first = harness(scripts, instance=instance)
    with pytest.raises(SessionWaits):
        await run_in_session(first, port, "ask")
    person.replies.append("red")
    second = harness(scripts, instance=instance)
    result = await run_in_session(second, port, "ask", intent="continue")
    assert result.exit == "done"
    assert (len(summaries(first)), len(summaries(second))) == (1, 0)
