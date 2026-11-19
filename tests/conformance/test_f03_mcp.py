"""F3 MCP: the tools of the instance's tool servers are offered by `server__tool` and called through one connection."""

import json

import pytest

from agent_core.contracts.events import NodeStarted, ToolReturned

DONE = [["exit", {"outcome": "done", "outputs": {"total": 1}}]]


@pytest.mark.feature("F3")
async def test_a_server_tool_is_offered_to_the_node_that_declares_it(harness):
    h = harness({"count": [DONE]})
    await h.nodes.run("count", {"revisions": ["r1"]})
    [started] = [e for e in h.events.record() if isinstance(e, NodeStarted)]
    assert started.tools == ("exit", "ask", "state_set", "state_get", "load", "shell__run", "crash_once")


@pytest.mark.feature("F3")
async def test_a_call_of_a_server_tool_runs_there_and_its_result_goes_back(harness):
    h = harness({"count": [[["shell__run", {"command": "echo hello"}]], DONE]})
    outcome = await h.nodes.run("count", {"revisions": ["r1"]})
    [first, _] = [e for e in h.events.record() if isinstance(e, ToolReturned)]
    assert first.error is False and json.loads(first.text) == {"exit": 0, "stdout": "hello\n", "stderr": "", "cut": 0}
    assert outcome.exit == "done"


@pytest.mark.feature("F3")
async def test_a_command_that_fails_in_the_server_is_a_result_not_an_error(harness):
    h = harness({"count": [[["shell__run", {"command": "exit 3"}]], DONE]})
    await h.nodes.run("count", {"revisions": ["r1"]})
    [first, _] = [e for e in h.events.record() if isinstance(e, ToolReturned)]
    assert first.error is False and json.loads(first.text)["exit"] == 3

