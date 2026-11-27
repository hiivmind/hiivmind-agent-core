"""A session resumed on LangGraph: a unit in flight continues from its checkpoint, on the backend that started it (SS-11,
ST-4, P25; E8, Review Focus 2)."""

import json
import sys
from pathlib import Path

import pytest

CONFORMANCE = Path(__file__).resolve().parents[2] / "conformance"
sys.path.insert(0, str(CONFORMANCE))
import script_model  # noqa: E402, F401  (registers the `script` model provider)
from session_support import ScriptedPerson  # noqa: E402

import agent_core  # noqa: E402
from agent_core.contracts.events import ToolReturned  # noqa: E402

INSTANCE = CONFORMANCE / "instance" / "instance.yaml"
ASK = [[["ask", {"question": "Which colour?"}]], [["exit", {"outcome": "done", "outputs": {"colour": "red"}}]]]


@pytest.fixture
async def opened(tmp_path, monkeypatch):
    """`opened(scripts, person, backend="langgraph")`: a harness on the conformance instance, its runs in `tmp_path`. The
    scripts are LangGraph's; the scripted backend is given a directory with none."""
    made = []
    empty = tmp_path / "no-scripts"
    empty.mkdir()
    monkeypatch.setenv("AGENT_CORE_SCRIPTED_SCRIPTS", str(empty))

    def make(scripts, person, backend="langgraph"):
        directory = tmp_path / f"scripts-{len(made)}"
        directory.mkdir()
        for node, steps in scripts.items():
            (directory / f"{node}.json").write_text(json.dumps(steps))
        monkeypatch.setenv("AGENT_CORE_LANGGRAPH_MODEL", f"script:{directory}")
        made.append(agent_core.open(INSTANCE, backend=backend, runs=tmp_path / "runs", person=person))
        return made[-1]

    yield make
    for harness in made:
        await harness.close()


def calls(harness, name):
    return [e for e in harness.events.record() if isinstance(e, ToolReturned) and e.call.name == name]


async def test_calls_made_before_the_question_are_not_made_again(opened):   # E8, PAUSE-2 as Q2 amends it
    lookup = [[["lookup_revision", {}]], [["ask", {"question": "Which one?"}]], [["exit", {"outcome": "done", "outputs": {}}]]]
    scripts = {"@routing": [[["enter", {"node": "lookup", "inputs": {"name": "alpha"}}]]], "lookup": lookup}
    first = opened(scripts, ScriptedPerson(["look up alpha"]))
    left = await first.sessions.start()
    assert left.state == "waiting" and len(calls(first, "lookup_revision")) == 1
    again = ScriptedPerson(["this one", None])
    second = opened(scripts, again)
    resumed = await second.sessions.resume(left.session_id)
    assert [q.text for q in again.asked] == ["Which one?"]   # the ask call is made again, from the checkpoint
    assert calls(second, "lookup_revision") == [] and resumed.facts == {"revision": "r1"}


async def test_the_unit_in_flight_resumes_on_the_backend_that_started_it(opened):   # Review Focus 2, SS-11
    left = await opened({"ask": ASK}, ScriptedPerson([])).sessions.start("ask")
    resumed = await opened({"ask": ASK}, ScriptedPerson(["red", None]), backend="scripted").sessions.resume(left.session_id)
    assert resumed.facts == {"colour": "red"}   # the scripted backend has no script for `ask`: it ran on LangGraph


async def test_a_unit_left_again_after_a_resume_on_another_backend_keeps_its_backend(opened):   # SS-11, final review 1
    left = await opened({"ask": ASK}, ScriptedPerson([])).sessions.start("ask")
    again = await opened({"ask": ASK}, ScriptedPerson([]), backend="scripted").sessions.resume(left.session_id)
    assert again.state == "waiting"
    resumed = await opened({"ask": ASK}, ScriptedPerson(["red", None]), backend="scripted").sessions.resume(left.session_id)
    assert resumed.facts == {"colour": "red"}   # still on LangGraph: the scripted backend has no script for `ask`


ASKING = [[["ask", {"question": "Which?"}]], [["lookup_revision", {}]], [["exit", {"outcome": "done", "outputs": {}}]]]
COUNT = [[["exit", {"outcome": "done", "outputs": {"total": 7}}]]]


@pytest.mark.parametrize("sequence,inputs", [
    ("lookup_then_count", {"name": "alpha"}),   # a node step in flight
    ("singles", {"name": "alpha"}),             # a fragment step in flight
])
async def test_a_sequence_in_flight_resumes_on_the_backend_it_started_with(opened, sequence, inputs):   # ST-4, plan review A3
    scripts = {"@routing": [[["enter", {"node": sequence, "inputs": inputs}]]], "lookup": ASKING, "count": COUNT}
    left = await opened(scripts, ScriptedPerson(["go"])).sessions.start()
    assert left.state == "waiting"
    resumed = await opened(scripts, ScriptedPerson(["this", None]), backend="scripted").sessions.resume(left.session_id)
    assert resumed.facts["total"] == 7   # the scripted backend has no scripts: every unit of the sequence ran on LangGraph
