"""F1 loop: a node's model is called again and again, until the node ends or the model stops."""

import pytest

from agent_core.contracts.events import ModelResponded, ToolReturned
from agent_core.contracts.values import HarnessReason

EXIT = [["exit", {"outcome": "done", "outputs": {}}]]
LOOKUP = [["lookup_revision", {"name": "alpha"}]]


@pytest.mark.feature("F1")
async def test_a_node_runs_its_steps_in_order_to_its_exit(harness):
    outcome = await harness({"lookup": [LOOKUP, EXIT]}).nodes.run("lookup", {"name": "alpha"})
    assert (outcome.exit, outcome.outputs, outcome.reason) == ("done", {"revision": "r1"}, None)
    assert outcome.notes[0].model_calls == 2


@pytest.mark.feature("F1")
async def test_a_node_whose_exit_is_accepted_makes_no_further_model_call(harness):   # KIT-6
    h = harness({"lookup": [[["exit", {"outcome": "done", "outputs": {"revision": "r9"}}]], LOOKUP, LOOKUP]})
    outcome = await h.nodes.run("lookup", {"name": "alpha"})
    assert (outcome.exit, outcome.outputs) == ("done", {"revision": "r9"})
    assert outcome.notes[0].model_calls == 1
    assert [e.call.name for e in h.events.record() if isinstance(e, ToolReturned)] == ["exit"]


@pytest.mark.feature("F1")
async def test_a_model_that_stops_without_an_exit_fails_the_node_with_what_it_said(harness):   # JOB-12
    outcome = await harness({"lookup": ["I cannot do that."]}).nodes.run("lookup", {"name": "alpha"})
    assert (outcome.exit, outcome.outputs, outcome.reason) == ("failed", {}, "no_exit")
    assert outcome.detail == {"said": "I cannot do that."}
    assert outcome.reason is HarnessReason.NO_EXIT   # E5: the enum, and its text


@pytest.mark.feature("F1")
async def test_a_script_that_runs_out_without_an_exit_is_the_model_stopping_with_nothing_said(harness):
    outcome = await harness({"lookup": [LOOKUP]}).nodes.run("lookup", {"name": "alpha"})
    assert (outcome.exit, outcome.reason, outcome.detail) == ("failed", "no_exit", {"said": ""})


@pytest.mark.feature("F1")
async def test_a_response_is_reported_before_its_calls_run(harness):
    h = harness({"lookup": [LOOKUP, EXIT]})
    await h.nodes.run("lookup", {"name": "alpha"})
    seen = [(type(e).__name__, e.call.name if isinstance(e, ToolReturned) else [c.name for c in e.response.calls])
            for e in h.events.record() if isinstance(e, (ModelResponded, ToolReturned))]
    assert seen == [
        ("ModelResponded", ["lookup_revision"]), ("ToolReturned", "lookup_revision"),
        ("ModelResponded", ["exit"]), ("ToolReturned", "exit"),
    ]
