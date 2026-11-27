"""F17 routing: a session opens with its menu or hears the person, enters a choice by code, and otherwise routes the turn
to the core's routing run, whose one tool is `enter` (GW-4a to GW-8, SCOPE-6, NODE-8a, NODE-8b, NODE-13; E1, E2, E4)."""

import pytest
from session_support import ScriptedPerson

from agent_core.contracts.errors import RunCannotStart
from agent_core.contracts.events import ModelRequested, NodeStarted, ToolReturned

ASK = [[["ask", {"question": "Which colour?"}]], [["exit", {"outcome": "done", "outputs": {"colour": "red"}}]]]
RECORD = [[["exit", {"outcome": "done", "outputs": {"note": "n"}}]]]
LOOKUP = [[["lookup_revision", {}]], [["exit", {"outcome": "done", "outputs": {}}]]]
MENU = "menu:\n  - {label: Record, node: record}\n  - {label: Ask, node: ask}\n"
NODES = "lookup, ask, record, count"
SEQUENCES = "tallies, rosters, tolerates, lookup_then_count, pairs, singles"


def with_menu(copied):
    (copied / "topology.yaml").write_text((copied / "topology.yaml").read_text() + MENU)
    return copied


def started(h):
    return [e.node for e in h.events.record() if isinstance(e, NodeStarted)]


def routed(h):
    return [e for e in h.events.record() if isinstance(e, ModelRequested) and e.label.startswith("@routing")]


def returned(h, name):
    return [e.text for e in h.events.record() if isinstance(e, ToolReturned) and e.call.name == name]


@pytest.mark.feature("F17")
async def test_a_session_with_a_menu_shows_it_and_enters_a_choice_by_code(harness, copied):   # E1, GW-8
    person = ScriptedPerson(["2", "red", None])
    h = harness({"ask": ASK, "record": RECORD}, instance=with_menu(copied), person=person)
    result = await h.sessions.start()
    assert result.state == "waiting"
    menus = [text for text in person.told if "1. Record" in text and "2. Ask" in text]
    assert len(menus) == 2   # shown when the session opened, and again after `ask` ended
    assert [q.text for q in person.asked] == ["Which colour?"] and started(h) == ["ask"] and routed(h) == []
    assert result.facts == {"colour": "red"}


@pytest.mark.feature("F17")
async def test_a_menu_reply_is_matched_without_case_or_spaces(harness, copied):   # Review Focus 3, GW-8
    person = ScriptedPerson(["  ASK ", "red", None])
    h = harness({"ask": ASK, "record": RECORD}, instance=with_menu(copied), person=person)
    await h.sessions.start()
    assert started(h) == ["ask"] and routed(h) == []


@pytest.mark.feature("F17")
async def test_a_reply_that_is_no_item_goes_to_the_routing_run(harness):   # E2, SCOPE-6
    person = ScriptedPerson(["look up alpha", None])
    h = harness({"@routing": [[["enter", {"node": "lookup", "inputs": {"name": "alpha"}}]]], "lookup": LOOKUP}, person=person)
    result = await h.sessions.start()
    first = routed(h)[0]
    conversation = next(p for p in first.parts if p.kind == "conversation").messages
    assert conversation[-1].text == "look up alpha"
    assert '"name": "enter"' in next(p for p in first.parts if p.kind == "tools").text
    assert [n for n in started(h) if n != "@routing"] == ["lookup"] and result.facts == {"revision": "r1"}


async def _refused(harness, call):
    h = harness({"@routing": [[["enter", call]], "I cannot."]}, person=ScriptedPerson(["do it", None]))
    await h.sessions.start()
    return returned(h, "enter")


@pytest.mark.feature("F17")
async def test_routing_to_a_node_whose_check_cannot_be_run_is_an_error_the_run_reads(harness, copied):   # NODE-12, final review 5
    node = copied / "nodes" / "record.md"
    checks = "preconditions:\n  - {tool: lookup_revision, args: {name: nope}, message: never shown}\n"
    node.write_text(node.read_text().replace("allowed-tools: []\n", f"allowed-tools: []\n{checks}", 1))
    h = harness({"@routing": [[["enter", {"node": "record"}]], "I cannot."]}, instance=copied, person=ScriptedPerson(["do it", None]))
    result = await h.sessions.start()
    assert result.state == "waiting"
    [text] = returned(h, "enter")
    assert text.startswith("error: the precondition check for `record` could not be run")


@pytest.mark.feature("F17")
async def test_routing_to_an_unknown_name_is_refused_with_the_lists(harness):   # E4
    assert await _refused(harness, {"node": "refresh-all"}) == [
        f"no node or sequence `refresh-all`; the nodes are: {NODES}; the sequences are: {SEQUENCES}"
    ]


@pytest.mark.feature("F17")
async def test_routing_with_an_undeclared_input_is_refused(harness):   # NODE-8a
    assert await _refused(harness, {"node": "record", "inputs": {"x": 1}}) == ["`record` has no input `x`; it takes no inputs"]


@pytest.mark.feature("F17")
async def test_routing_to_a_node_whose_check_fails_is_refused_with_its_message(harness):   # NODE-13
    assert await _refused(harness, {"node": "lookup", "inputs": {"name": "nope"}}) == ["The register does not hold nope."]


@pytest.mark.feature("F17")
async def test_the_routing_run_lists_inputs_and_sequences(harness):   # NODE-8b
    h = harness({"@routing": ["Which?"]}, person=ScriptedPerson(["hello", None]))
    await h.sessions.start()
    first = routed(h)[0]
    instructions = next(p for p in first.parts if p.kind == "instructions").text
    assert "`lookup`: Look up the revision of a name in the register. Inputs: name" in instructions
    assert "`lookup_then_count`: Look a name up, then count what was found." in instructions
    sources = [source for e in h.events.record() if isinstance(e, NodeStarted) and e.node == "@routing" for source, _ in e.parts]
    assert {"engine: routing", "topology: nodes", "topology: sequences"} <= set(sources)


@pytest.mark.feature("F17")
async def test_a_session_started_with_a_name_that_is_neither_node_nor_sequence_is_refused(harness):   # GW-4c
    h = harness({}, person=ScriptedPerson())
    with pytest.raises(RunCannotStart) as refused:
        await h.sessions.start("nope")
    assert str(refused.value) == f"no node or sequence `nope`; the nodes are: {NODES}; the sequences are: {SEQUENCES}"


@pytest.mark.feature("F17")
async def test_an_outcome_with_no_exit_row_routes(harness):   # GW-3 as Q1 amends it
    person = ScriptedPerson([None])
    h = harness({"record": [[["exit", {"outcome": "skipped", "outputs": {}}]]]}, person=person)
    result = await h.sessions.start("record")
    assert result.state == "waiting" and person.seen[-1] == ("heard", None)   # back to the person, not ended


@pytest.mark.feature("F17")
async def test_an_end_row_ends_the_session(harness, copied, tmp_path):   # GW-3
    topology = copied / "topology.yaml"
    topology.write_text(topology.read_text().replace("  done: route", "  done: end"))
    h = harness({"record": RECORD}, instance=copied, person=ScriptedPerson())
    result = await h.sessions.start("record")
    assert (result.state, result.facts) == ("ended", {"note": "n"})
    from agent_core.stores.file import FileStore

    assert FileStore(tmp_path / "runs").load(result.session_id)["status"] == "ended"


SHARED = """sequences:
  lookup:
    description: Look up alpha.
    inputs: {name: alpha}
    start: lookup
    transitions:
      lookup: {done: end, failed: end}
"""


@pytest.mark.feature("F17")
async def test_a_command_line_name_shared_with_a_node_starts_the_sequence(harness, copied, tmp_path):   # SEQ-12, E2
    from agent_core.stores.file import FileStore

    topology = copied / "topology.yaml"
    topology.write_text(topology.read_text().replace("sequences:\n", SHARED, 1))
    result = await harness({"lookup": LOOKUP}, instance=copied, person=ScriptedPerson([None])).sessions.start("lookup")
    entries = FileStore(tmp_path / "runs").load(result.session_id)["transcript"]
    assert {"node": "lookup", "inputs": {"name": "alpha"}, "outcome": "done"} in entries
    assert {"sequence": "lookup", "inputs": {}, "end": "done"} in entries
    assert result.facts == {"revision": "r1"}
