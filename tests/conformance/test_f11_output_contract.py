"""F11 output contract: an exit is accepted only with an outcome the node declares and the outputs its schema asks for."""

import pytest

from agent_core.contracts.events import ModelRequested, ToolReturned

GOOD = [["exit", {"outcome": "done", "outputs": {"revision": "r1"}}]]
NO_OUTPUT = [["exit", {"outcome": "done", "outputs": {}}]]
MISMATCH = "the outputs do not match the node's output schema: [\"outputs: 'revision' is a required property\"]."


def returned(h) -> list[tuple[str, bool]]:
    return [(e.text, e.error) for e in h.events.record() if isinstance(e, ToolReturned)]


@pytest.mark.feature("F11")
async def test_an_exit_that_matches_ends_the_node_with_its_outputs(harness):
    h = harness({"lookup": [GOOD]})
    outcome = await h.nodes.run("lookup", {"name": "alpha"})
    assert (outcome.exit, outcome.outputs, outcome.reason) == ("done", {"revision": "r1"}, None)
    assert returned(h) == [("exited with `done`", False)]


@pytest.mark.feature("F11")
async def test_an_exit_whose_outputs_do_not_match_is_refused_once_and_may_be_corrected(harness):   # JOB-7b
    h = harness({"lookup": [NO_OUTPUT, GOOD]})
    outcome = await h.nodes.run("lookup", {"name": "alpha"})
    assert returned(h) == [(f"{MISMATCH} Correct them and EXIT again.", True), ("exited with `done`", False)]
    assert (outcome.exit, outcome.outputs) == ("done", {"revision": "r1"})


@pytest.mark.feature("F11")
async def test_a_second_exit_that_does_not_match_fails_the_node_invalid_output(harness):   # JOB-7b
    h = harness({"lookup": [NO_OUTPUT, NO_OUTPUT, GOOD]})
    outcome = await h.nodes.run("lookup", {"name": "alpha"})
    assert (outcome.exit, outcome.reason) == ("failed", "invalid_output")
    assert outcome.detail == {"errors": ["outputs: 'revision' is a required property"]}
    assert returned(h)[-1] == (f"{MISMATCH}", True)
    assert outcome.notes[0].model_calls == 2   # the third step never ran


@pytest.mark.feature("F11")
async def test_an_output_the_node_does_not_declare_does_not_match(harness):
    h = harness({"lookup": [[["exit", {"outcome": "done", "outputs": {"revision": "r1", "extra": 1}}]], GOOD]})
    await h.nodes.run("lookup", {"name": "alpha"})
    assert returned(h)[0][0].startswith("the outputs do not match the node's output schema: [") and returned(h)[0][1]


@pytest.mark.feature("F11")
async def test_an_outcome_the_node_does_not_declare_is_refused_naming_its_outcomes(harness):
    h = harness({"lookup": [[["exit", {"outcome": "finished", "outputs": {}}]], GOOD]})
    outcome = await h.nodes.run("lookup", {"name": "alpha"})
    assert returned(h)[0] == ("`finished` is not an outcome of `lookup`; its outcomes are: done, failed, skipped, stopped", True)
    assert outcome.exit == "done"


@pytest.mark.feature("F11")
async def test_an_exit_other_than_done_needs_no_outputs_and_may_give_a_reason(harness):
    h = harness({"lookup": [[["exit", {"outcome": "failed", "outputs": {"reason": "not found"}}]]]})
    outcome = await h.nodes.run("lookup", {"name": "alpha"})
    assert (outcome.exit, outcome.outputs) == ("failed", {"reason": "not found"})


@pytest.mark.feature("F11")
async def test_a_second_bad_exit_ends_invalid_output_without_a_third_model_call(harness):   # JOB-7b
    h = harness({"lookup": [NO_OUTPUT, NO_OUTPUT, GOOD]})
    outcome = await h.nodes.run("lookup", {"name": "alpha"})
    assert (outcome.exit, outcome.reason) == ("failed", "invalid_output")
    assert len([e for e in h.events.record() if isinstance(e, ModelRequested)]) == 2
