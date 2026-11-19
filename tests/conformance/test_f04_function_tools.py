"""F4 function tools: a Python function the instance declares is a tool, its schema from its type hints."""

import pytest

from agent_core.contracts.events import ModelRequested, ToolReturned

EXIT = [["exit", {"outcome": "done", "outputs": {}}]]


def returned(h) -> list[tuple[str, str, bool]]:
    return [(e.call.name, e.text, e.error) for e in h.events.record() if isinstance(e, ToolReturned)]


@pytest.mark.feature("F4")
async def test_a_function_is_called_with_the_arguments_the_model_gave(harness):
    h = harness({"lookup": [[["lookup_revision", {"name": "beta"}]], EXIT]})
    outcome = await h.nodes.run("lookup", {"name": "alpha"})
    assert returned(h)[0][2] is False and '"revision": "r2"' in returned(h)[0][1]
    assert outcome.outputs == {"revision": "r2"}   # the function recorded an output the node declares


@pytest.mark.feature("F4")
async def test_a_parameter_the_harness_fills_is_filled_and_not_offered(harness):
    h = harness({"lookup": [[["lookup_revision", {}]], EXIT]})
    outcome = await h.nodes.run("lookup", {"name": "gamma"})   # no `name` given: the function reads the node's input
    assert outcome.outputs == {"revision": "r3"}
    assert not any('"state"' in part.text for e in h.events.record() if isinstance(e, ModelRequested)
                   for part in e.parts if part.kind == "tools")


@pytest.mark.feature("F4")
async def test_a_function_that_raises_gives_the_model_its_error_and_records_nothing(harness):   # TOOL-12
    h = harness({"lookup": [[["lookup_revision", {"name": "nope"}]], [["exit", {"outcome": "failed", "outputs": {}}]]]})
    outcome = await h.nodes.run("lookup", {"name": "alpha"})
    assert returned(h)[0] == ("lookup_revision", "error: lookup_revision raised KeyError: 'nope'", True)
    assert (outcome.exit, outcome.outputs) == ("failed", {})

