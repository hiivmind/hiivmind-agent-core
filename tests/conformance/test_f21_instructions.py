"""F21 instructions: a node run is given its brief: the engine's rules, the policy and the node's procedure, filled."""

import json

import pytest

from agent_core.contracts.events import ModelRequested, NodeStarted
from agent_core.contracts.values import Message

LOOKUP = [["lookup_revision", {"name": "alpha"}]]
EXIT = [["exit", {"outcome": "done", "outputs": {}}]]


def requests(h):
    return [e for e in h.events.record() if isinstance(e, ModelRequested)]


def part(request: ModelRequested, kind: str):
    [found] = [p for p in request.parts if p.kind == kind]
    return found


@pytest.mark.feature("F21")
async def test_the_instructions_hold_the_policy_and_the_nodes_procedure_with_its_placeholders_filled(harness):
    h = harness({"lookup": [LOOKUP, EXIT]})
    await h.nodes.run("lookup", {"name": "alpha"})
    text = part(requests(h)[0], "instructions").text
    assert "Conformance policy. Do what the procedure says, and nothing else." in text
    assert "# Procedure of the node that is running: `lookup`" in text and "Name to look up: alpha." in text
    assert "{{input" not in text


@pytest.mark.feature("F21")
async def test_the_parts_of_the_instructions_are_named_with_their_lengths(harness):   # CTX-6
    h = harness({"lookup": [EXIT]})
    await h.nodes.run("lookup", {"name": "alpha"})
    [started] = [e for e in h.events.record() if isinstance(e, NodeStarted)]
    assert [source for source, _ in started.parts] == [
        "engine: rules", "engine: inside a node", "procedure conventions", "policy", "node file: nodes/lookup.md",
    ]
    text = part(requests(h)[0], "instructions").text
    assert sum(length for _, length in started.parts) + 2 * (len(started.parts) - 1) == len(text)   # joined by blank lines


@pytest.mark.feature("F21")
async def test_the_instructions_and_the_tools_do_not_change_while_the_run_lasts(harness):   # SCOPE-2
    h = harness({"lookup": [LOOKUP, EXIT]})
    await h.nodes.run("lookup", {"name": "alpha"})
    first, second = requests(h)
    assert part(first, "instructions") == part(second, "instructions")
    assert part(first, "tools") == part(second, "tools")


@pytest.mark.feature("F21")
async def test_the_tools_offered_are_the_verbs_then_the_nodes_own(harness):   # NODE-6a
    h = harness({"lookup": [EXIT]})
    await h.nodes.run("lookup", {"name": "alpha"})
    offered = json.loads(part(requests(h)[0], "tools").text)
    assert [tool["name"] for tool in offered] == ["exit", "ask", "state_set", "state_get", "load", "lookup_revision"]
    assert offered[-1]["description"] == "Look up the revision of a name in the register; by default the name this node was given."


@pytest.mark.feature("F21")
async def test_the_conversation_opens_with_the_instruction_to_run_the_node(harness):
    h = harness({"lookup": [EXIT]})
    await h.nodes.run("lookup", {"name": "alpha"})
    assert part(requests(h)[0], "conversation").messages == (Message("user", "Run the node."),)
