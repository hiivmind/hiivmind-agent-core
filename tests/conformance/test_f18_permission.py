"""F18 permission: a node may call only the tools it declares; `ask`, `enter` and `exit` come alone, or none runs."""

import pytest

from agent_core.contracts.events import ToolReturned

TOGETHER = (                                                     # E1: a job offers `ask` and `exit` of the alone verbs
    "refused: `ask` and `exit` must be the only call in a response. "
    "None of the calls in this response ran. Send them again, separately."
)
EXIT = [["exit", {"outcome": "done", "outputs": {"total": 1}}]]


def touch(tmp_path):
    """A call that, if it ran, leaves a marker: the shell server runs in the instance directory, so the path is absolute."""
    return ["shell__run", {"command": f"touch {tmp_path / 'ran.marker'}"}]


def returned(h) -> list[tuple[str, str, bool]]:
    return [(e.call.name, e.text, e.error) for e in h.events.record() if isinstance(e, ToolReturned)]


@pytest.mark.feature("F18")
async def test_example_8_on_every_backend(harness, tmp_path):   # VERB-6a, VERB-6b
    h = harness({"count": [[touch(tmp_path), ["exit", {"outcome": "done", "outputs": {"total": 1}}]], EXIT]})
    outcome = await h.nodes.run("count", {"revisions": ["r1"]})
    assert returned(h) == [("shell__run", TOGETHER, True), ("exit", TOGETHER, True), ("exit", "exited with `done`", False)]
    assert not (tmp_path / "ran.marker").exists()   # neither call ran
    assert (outcome.exit, outcome.outputs) == ("done", {"total": 1})


@pytest.mark.feature("F18")
async def test_a_tool_the_node_declares_runs(harness, tmp_path):
    h = harness({"count": [[touch(tmp_path)], EXIT]})
    await h.nodes.run("count", {"revisions": ["r1"]})
    assert (tmp_path / "ran.marker").exists()


@pytest.mark.feature("F18")
async def test_a_tool_the_node_does_not_declare_is_refused_and_not_run(harness, tmp_path):   # NODE-6b
    h = harness({"record": [[touch(tmp_path)], [["exit", {"outcome": "done", "outputs": {"note": "n"}}]]]})
    outcome = await h.nodes.run("record")
    assert returned(h)[0] == ("shell__run", "refused: `shell__run` is not declared by the node that is running", True)
    assert not (tmp_path / "ran.marker").exists()
    assert outcome.exit == "done"   # the node went on


@pytest.mark.feature("F18")
async def test_a_tool_another_node_declares_is_refused(harness):
    h = harness({"count": [[["lookup_revision", {"name": "alpha"}]], EXIT]})
    await h.nodes.run("count", {"revisions": ["r1"]})
    assert returned(h)[0][1:] == ("refused: `lookup_revision` is not declared by the node that is running", True)


@pytest.mark.feature("F18")
async def test_a_job_node_is_not_offered_enter(harness):   # NODE-6a
    h = harness({"record": [[["enter", {"node": "lookup"}]], [["exit", {"outcome": "done", "outputs": {"note": "n"}}]]]})
    await h.nodes.run("record")
    assert returned(h)[0] == ("enter", "refused: `enter` is not declared by the node that is running", True)
