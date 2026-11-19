"""F5 state: a node's working values, the outputs recorded while it ran, and the count of rejected exits."""

import pytest

from agent_core.contracts.events import ToolReturned


def returned(h) -> list[tuple[str, str]]:
    return [(e.call.name, e.text) for e in h.events.record() if isinstance(e, ToolReturned)]


@pytest.mark.feature("F5")
async def test_a_value_recorded_by_one_response_is_read_by_the_next(harness):
    h = harness({"record": [
        [["state_set", {"key": "colour", "value": "red"}]],
        [["state_get", {"key": "colour"}]],
        [["exit", {"outcome": "done", "outputs": {"note": "n"}}]],
    ]})
    await h.nodes.run("record")
    assert returned(h)[:2] == [("state_set", 'recorded colour = "red"'), ("state_get", '"red"')]


@pytest.mark.feature("F5")
async def test_the_calls_of_one_response_see_the_state_as_it_was_before_the_response(harness):   # CTL-5
    h = harness({"record": [
        [["state_set", {"key": "colour", "value": "red"}], ["state_get", {"key": "colour"}]],
        [["state_get", {"key": "colour"}]],
        [["exit", {"outcome": "done", "outputs": {"note": "n"}}]],
    ]})
    await h.nodes.run("record")
    assert [text for name, text in returned(h) if name == "state_get"] == ["not set", '"red"']


@pytest.mark.feature("F5")
async def test_when_two_calls_of_a_response_write_one_name_the_later_call_wins(harness):   # CTL-5
    h = harness({"record": [
        [["state_set", {"key": "colour", "value": "red"}], ["state_set", {"key": "colour", "value": "blue"}]],
        [["state_get", {"key": "colour"}]],
        [["exit", {"outcome": "done", "outputs": {"note": "n"}}]],
    ]})
    await h.nodes.run("record")
    assert returned(h)[2] == ("state_get", '"blue"')


@pytest.mark.feature("F5")
async def test_an_output_recorded_while_the_node_ran_counts_when_it_exits(harness):   # JOB-7a
    h = harness({"record": [
        [["state_set", {"key": "note", "value": "kept"}]],
        [["exit", {"outcome": "done", "outputs": {}}]],
    ]})
    outcome = await h.nodes.run("record")
    assert (outcome.exit, outcome.outputs) == ("done", {"note": "kept"})


@pytest.mark.feature("F5")
async def test_a_node_run_does_not_see_the_state_of_another(harness):
    h = harness({"record": [
        [["state_set", {"key": "colour", "value": "red"}]], [["exit", {"outcome": "done", "outputs": {"note": "n"}}]],
    ]})
    await h.nodes.run("record")
    h = harness({"record": [[["state_get", {"key": "colour"}]], [["exit", {"outcome": "done", "outputs": {"note": "n"}}]]]})
    await h.nodes.run("record")
    assert returned(h)[0] == ("state_get", "not set")
