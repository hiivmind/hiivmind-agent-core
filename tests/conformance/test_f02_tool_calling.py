"""F2 tool calling: each call of a response runs, and its result goes back to the model."""

import json

import pytest

from agent_core.contracts.events import ToolReturned

EXIT = [["exit", {"outcome": "done", "outputs": {}}]]


def returned(h) -> list[tuple[str, str, bool]]:
    return [(e.call.name, e.text, e.error) for e in h.events.record() if isinstance(e, ToolReturned)]


@pytest.mark.feature("F2")
async def test_a_calls_result_goes_back_to_the_model(harness):
    h = harness({"record": [[["state_get", {"key": "colour"}]], [["exit", {"outcome": "done", "outputs": {"note": "n"}}]]]})
    await h.nodes.run("record")
    assert returned(h)[0] == ("state_get", "not set", False)


@pytest.mark.feature("F2")
async def test_the_calls_of_one_response_all_run_and_return_in_the_order_given(harness):
    h = harness({"record": [
        [["state_get", {"key": "a"}], ["state_get", {"key": "b"}], ["state_get", {"key": "c"}]],
        [["exit", {"outcome": "done", "outputs": {"note": "n"}}]],
    ]})
    await h.nodes.run("record")
    assert [e for e in returned(h) if e[0] == "state_get"] == [("state_get", "not set", False)] * 3
    ids = [e.call.id for e in h.events.record() if isinstance(e, ToolReturned)]
    assert len(set(ids)) == len(ids) == 4   # each call has an id of its own


@pytest.mark.feature("F2")
async def test_a_call_that_fails_gives_the_model_its_error_and_the_run_goes_on(harness):
    h = harness({"record": [
        [["load", {"path": "no-such-file.md"}]], [["exit", {"outcome": "done", "outputs": {"note": "n"}}]],
    ]})
    outcome = await h.nodes.run("record")
    [(name, text, error), _] = returned(h)
    assert (name, error) == ("load", True) and text.startswith("error: ") and "no-such-file.md" in text
    assert outcome.exit == "done"


@pytest.mark.feature("F2")
async def test_a_load_call_reads_a_file_of_the_instance(harness):
    h = harness({"record": [[["load", {"path": "POLICY.md"}]], [["exit", {"outcome": "done", "outputs": {"note": "n"}}]]]})
    await h.nodes.run("record")
    assert returned(h)[0] == ("load", "Conformance policy. Do what the procedure says, and nothing else.\n", False)
