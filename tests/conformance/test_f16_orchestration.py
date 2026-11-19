"""F16 orchestration: a sequence walks its transitions, and a declared fragment is one step that runs its nodes.

The fragment's contract is architecture §4.3's, written once here for every backend: its inputs are found by name, its
outputs are the declared ones, a fan-out's results come back in item order with its failures beside them, and a stop
ends it.
"""

import pytest

from agent_core.contracts.events import NodeStarted, ToolReturned

LOOKUP = [[["lookup_revision", {}]], [["exit", {"outcome": "done", "outputs": {}}]]]
COUNT = [[["exit", {"outcome": "done", "outputs": {"total": 7}}]]]
SCRIPTS = {"lookup": LOOKUP, "count": COUNT}


@pytest.mark.feature("F16")
async def test_a_sequence_walks_from_node_to_node_on_each_outcome(harness):
    result = await harness({"lookup": LOOKUP, "count": COUNT}).sequences.run("lookup_then_count", {"name": "beta"})
    assert (result.end, result.facts["revision"], result.facts["total"]) == ("done", "r2", 7)
    assert [(s["name"], s["outcome"]) for s in result.steps] == [("lookup", "done"), ("count", "done")]


@pytest.mark.feature("F16")
async def test_a_transitions_mapping_gives_a_node_the_fact_it_names(harness):   # SEQ-5
    h = harness({"lookup": LOOKUP, "count": [[["state_get", {"key": "revisions"}]], *COUNT]})
    await h.sequences.run("lookup_then_count", {"name": "beta"})
    assert [e.text for e in h.events.record() if isinstance(e, ToolReturned) and e.call.name == "state_get"] == ['"r2"']


@pytest.mark.feature("F16")
async def test_a_sequence_whose_node_fails_ends_failed(harness):
    result = await harness(SCRIPTS).sequences.run("lookup_then_count", {"name": "nope"})
    assert (result.end, [(s["name"], s["outcome"]) for s in result.steps]) == ("failed", [("lookup", "failed")])


@pytest.mark.feature("F16")
async def test_the_fragment_contract(harness):
    h = harness(SCRIPTS)
    result = await h.sequences.run("pairs", {"names": ["alpha", "beta", "gamma"], "colour": "red"})
    assert result.end == "done"
    assert result.facts["revisions"] == [{"revision": "r1"}, {"revision": "r2"}, {"revision": "r3"}]   # in item order (FAN-3)
    assert (result.facts["revisions_failures"], result.facts["total"]) == ([], 7)
    [step] = result.steps   # at macro level the fragment is one step with its own steps listed
    assert (step["name"], step["outcome"]) == ("pair", "done")
    assert [s["name"] for s in step["steps"]] == ["lookup[1]", "lookup[2]", "lookup[3]", "lookup", "count"]


@pytest.mark.feature("F16")
async def test_a_fragments_nodes_get_only_the_inputs_they_declare_by_name(harness):   # SEQ-5, ORC-4
    h = harness({"lookup": LOOKUP, "count": [[["state_get", {"key": "revisions"}], ["state_get", {"key": "colour"}]], *COUNT]})
    await h.sequences.run("pairs", {"names": ["alpha"], "colour": "red"})
    assert [e.text for e in h.events.record() if isinstance(e, ToolReturned) and e.call.name == "state_get"] == [
        '[{"revision": "r1"}]', "not set",
    ]


@pytest.mark.feature("F16")
async def test_an_item_that_fails_is_listed_beside_the_results_and_the_fragment_goes_on(harness):   # FAN-2, FAN-4
    result = await harness(SCRIPTS).sequences.run("pairs", {"names": ["alpha", "nope", "gamma"]})
    assert result.end == "done"
    assert result.facts["revisions"] == [{"revision": "r1"}, {"revision": "r3"}]
    assert result.facts["revisions_failures"] == [{"item": "nope", "outcome": "failed", "reason": "precondition_unmet"}]


@pytest.mark.feature("F16")
async def test_a_fan_out_in_which_every_item_fails_ends_the_fragment_failed(harness):   # FAN-4
    result = await harness(SCRIPTS).sequences.run("pairs", {"names": ["nope", "never"]})
    assert result.end == "failed"
    assert result.facts["revisions"] == []
    assert [f["item"] for f in result.facts["revisions_failures"]] == ["nope", "never"]
    assert "total" not in result.facts   # `count` did not run


@pytest.mark.feature("F16")
async def test_a_fan_out_over_no_items_is_done(harness):   # FAN-4
    result = await harness(SCRIPTS).sequences.run("pairs", {"names": []})
    assert (result.end, result.facts["revisions"], result.facts["total"]) == ("done", [], 7)


@pytest.mark.feature("F16")
async def test_a_node_that_stops_ends_the_fragment_and_the_sequence_stopped(harness):   # SEQ-7
    h = harness({"lookup": [[["exit", {"outcome": "stopped", "outputs": {}}]]], "count": COUNT})
    result = await h.sequences.run("pairs", {"names": ["alpha", "beta"]})
    assert result.end == "stopped" and "total" not in result.facts
    assert "count" not in [e.node for e in h.events.record() if isinstance(e, NodeStarted)]


@pytest.mark.feature("F16")
async def test_a_nodes_own_preconditions_apply_inside_a_fragment(harness):   # NODE-13
    h = harness(SCRIPTS)
    await h.sequences.run("pairs", {"names": ["nope"]})
    assert [e.node for e in h.events.record() if isinstance(e, NodeStarted)] == []   # `nope` never started a model run


@pytest.mark.feature("F16")
async def test_a_fragment_outputs_are_the_declared_ones_and_the_nodes_other_outputs_stay_inside(harness):   # SEQ-6
    result = await harness(SCRIPTS).sequences.run("singles", {"name": "alpha"})
    assert result.end == "done"
    assert result.facts == {"name": "alpha", "total": 7}   # `lookup` produced `revision` and it is not the fragment's output
    assert result.summary == {"total": 7}   # what the backend returned, before the macro walk filters the facts


@pytest.mark.feature("F16")
async def test_a_transition_inside_a_fragment_maps_a_fact_to_the_input_a_node_declares(harness):   # SEQ-5
    h = harness({"lookup": LOOKUP, "count": [[["state_get", {"key": "revisions"}]], *COUNT]})
    await h.sequences.run("singles", {"name": "beta"})
    assert [e.text for e in h.events.record() if isinstance(e, ToolReturned) and e.call.name == "state_get"] == ['"r2"']


@pytest.mark.feature("F16")
async def test_a_node_that_exits_skipped_inside_a_fragment_follows_its_row(harness):   # SEQ-8
    h = harness({
        "lookup": [[["exit", {"outcome": "skipped", "outputs": {}}]]],
        "count": [[["state_get", {"key": "revisions"}]], *COUNT],
    })
    result = await h.sequences.run("singles", {"name": "alpha"})
    assert result.end == "done"
    [step] = result.steps
    assert step["steps"] == [{"name": "lookup", "outcome": "skipped"}, {"name": "count", "outcome": "done"}]
    assert [e.text for e in h.events.record() if isinstance(e, ToolReturned) and e.call.name == "state_get"] == ["not set"]   # nothing was found to map
