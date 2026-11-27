"""A node run in a session (design §3.4): what it is told and offered, what the person hears, and what the session keeps."""

import json
import sys
from pathlib import Path

import pytest

CONFORMANCE = Path(__file__).resolve().parents[1] / "conformance"
sys.path.insert(0, str(CONFORMANCE))
import script_model  # noqa: E402, F401  (registers the `script` model provider)
from session_support import ScriptedPerson  # noqa: E402

import agent_core  # noqa: E402
from agent_core.contracts.errors import SessionWaits  # noqa: E402
from agent_core.contracts.events import ModelRequested, NodeEnded, NodeStarted  # noqa: E402
from agent_core.contracts.unit import UnitResult  # noqa: E402
from agent_core.contracts.values import Message  # noqa: E402
from agent_core.core.session import SessionPort, new_state  # noqa: E402
from agent_core.stores.file import FileStore  # noqa: E402

THREAD = "session-test/1"
ASK = [["ask", {"question": "Which colour?"}]]
EXIT_COLOUR = [["exit", {"outcome": "done", "outputs": {"colour": "red"}}]]
EXIT_NOTE = [["exit", {"outcome": "done", "outputs": {"note": "n"}}]]


class Opened:
    def __init__(self, harness, port, person):
        self.h, self.port, self.person = harness, port, person

    async def begin(self):
        return await self.h.begin(self.h.runs / "session-test", session=self.port)

    async def node(self, name, inputs=None, thread=THREAD, intent="start"):
        run = await self.begin()
        try:
            return await self.h.backend(None).run_node(run.unit(name, dict(inputs or {}), intent, thread))
        finally:
            await run.end()

    def events(self, kind):
        return [e for e in self.h.hub.record() if isinstance(e, kind)]


@pytest.fixture
async def session(tmp_path, monkeypatch):
    """`session(scripts, replies=(), backend="scripted")`: a harness on the conformance instance and a session port on a
    file store, with a person who replies from `replies`."""
    opened = []

    def make(scripts, replies=(), backend="scripted"):
        directory = tmp_path / f"scripts-{len(opened)}"
        directory.mkdir()
        for node, steps in scripts.items():
            (directory / f"{node}.json").write_text(json.dumps(steps))
        monkeypatch.setenv("AGENT_CORE_SCRIPTED_SCRIPTS", str(directory))
        monkeypatch.setenv("AGENT_CORE_LANGGRAPH_MODEL", f"script:{directory}")
        person = ScriptedPerson(replies)
        harness = agent_core.open(CONFORMANCE / "instance" / "instance.yaml", backend=backend, runs=tmp_path / "runs", person=person)
        opened.append(harness)
        return Opened(harness, SessionPort(new_state(), FileStore(tmp_path / "runs"), "session-test", person), person)

    yield make
    for harness in opened:
        await harness.close()


async def test_a_session_node_is_told_to_stay_on_task_and_is_not_offered_enter(session):   # DIV-5, NODE-6a
    s = session({"record": [EXIT_NOTE]})
    await s.node("record")
    await s.h.nodes.run("record")
    in_session, in_job = s.events(NodeStarted)
    assert "engine: staying on the task" in [source for source, _ in in_session.parts]
    assert "engine: staying on the task" not in [source for source, _ in in_job.parts]
    assert in_session.tools == in_job.tools and "enter" not in in_session.tools


async def test_each_response_text_is_told_to_the_person_as_it_arrives(session):   # SS-8
    s = session({"record": ["Updating alpha.", EXIT_NOTE]}, replies=["go on"])
    await s.node("record")
    assert s.person.seen[:2] == [("told", "Updating alpha."), ("heard", "go on")]
    assert s.port.state["transcript"][:2] == [{"agent": "Updating alpha."}, {"user": "go on"}]


async def test_text_and_a_question_in_one_response_are_told_in_order(session):   # Review Focus 5
    step = {"text": "Here is the plan.", "calls": [["ask", {"question": "Go?"}]]}
    s = session({"ask": [step, EXIT_COLOUR]}, replies=["yes"], backend="langgraph")
    result = await s.node("ask")
    assert result.exit == "done"
    assert s.port.state["transcript"][:3] == [{"agent": "Here is the plan."}, {"agent": "Go?"}, {"user": "yes"}]


async def test_the_person_replies_when_the_model_stops(session):   # KIT-10
    s = session({"record": ["Which one?", EXIT_NOTE]}, replies=["alpha"])
    result = await s.node("record")
    assert result.exit == "done"
    second = s.events(ModelRequested)[1]
    conversation = next(p for p in second.parts if p.kind == "conversation").messages
    assert conversation[-1] == Message("user", "alpha")


async def test_a_question_is_pending_while_it_is_asked(session):   # VERB-5, ST-1
    s = session({"ask": [ASK, EXIT_COLOUR]}, replies=["red"])
    pending = []
    s.person.on_ask = lambda question: pending.append(s.port.unit(THREAD)["pending"])
    await s.node("ask")
    assert pending == ["Which colour?"]
    assert s.port.unit(THREAD) is None   # the run ended: its entry is gone


async def test_a_person_who_has_gone_stops_the_run_unrecorded(session):   # SS-5
    s = session({"ask": [ASK, EXIT_COLOUR]}, replies=[])
    with pytest.raises(SessionWaits):
        await s.node("ask")
    assert s.port.left.is_set() and s.events(NodeEnded) == []
    assert s.port.unit(THREAD)["pending"] == "Which colour?"


async def test_a_continued_unit_keeps_its_first_brief(session):   # SS-14
    s = session({"record": [EXIT_NOTE]})
    s.port.save_unit(THREAD, {"instructions": "X", "handover": [], "node": "record", "inputs": {}, "backend": "scripted"})
    s.port.state["facts"]["note"] = "changed since"
    run = await s.begin()
    try:
        policy = await run.start("record", {}, THREAD)
    finally:
        await run.end()
    assert policy.instructions == "X"


async def test_checks_made_by_routing_are_not_made_again(session):   # NODE-11, design §3.3
    s = session({"lookup": [EXIT_NOTE]})
    s.port.save_unit(THREAD, {"checked": {"k": 1}})
    run = await s.begin()
    try:
        policy = await run.start("lookup", {"name": "nope"}, THREAD)   # its own check would refuse `nope`
    finally:
        await run.end()
    assert not isinstance(policy, UnitResult)
    assert policy.initial()["values"]["k"] == 1


async def test_a_session_node_that_fails_tells_the_person_and_is_in_the_transcript(session):   # CTL-8, NODE-9
    bad = [["exit", {"outcome": "done", "outputs": {"note": 5}}]]
    s = session({"record": [bad, bad]})
    result = await s.node("record")
    assert (result.exit, result.reason) == ("failed", "invalid_output")
    assert any("note" in text and "is not of type 'string'" in text for text in s.person.told)
    assert s.port.state["transcript"][-1] == {"node": "record", "inputs": {}, "outcome": "failed", "reason": "invalid_output"}
    assert s.port.recorded[THREAD] == {}


async def test_two_equal_texts_in_a_row_are_both_in_the_transcript(session):   # plan review C1
    s = session({})
    await s.port.person.tell("Working.")
    await s.port.person.tell("Working.")
    assert s.port.state["transcript"] == [{"agent": "Working."}, {"agent": "Working."}]


async def test_a_text_told_again_on_resume_is_not_added_twice(session):   # design §3.6
    s = session({})
    s.port.state["transcript"] = [{"user": "go"}, {"agent": "Which colour?"}]
    s.port.replaying = True
    await s.port.person.tell("Which colour?")
    assert s.port.state["transcript"] == [{"user": "go"}, {"agent": "Which colour?"}] and s.port.replaying
    await s.port.person.tell("Next.")
    assert s.port.state["transcript"][-1] == {"agent": "Next."} and not s.port.replaying


class _GoneOnce:
    """The run's tool servers, but the first call finds the server gone; the next is answered `ok`."""

    def __init__(self, inner):
        self.inner, self.calls = inner, 0

    async def tools(self):
        return await self.inner.tools()

    async def call(self, name, args, state):
        from agent_core.contracts.errors import ToolServerError

        self.calls += 1
        if self.calls == 1:
            raise ToolServerError("shell", "run", "it stopped answering")
        return "ok"

    async def close(self):
        await self.inner.close()


async def test_a_server_that_cannot_be_reached_waits_for_the_person(session, monkeypatch):   # TOOL-11f, E13
    from agent_core.backends.scripted import ScriptedBackend
    from agent_core.contracts.events import ToolReturned

    real = ScriptedBackend.servers
    monkeypatch.setattr(ScriptedBackend, "servers", lambda self, *a: _GoneOnce(real(self, *a)))
    count = [[["shell__run", {"command": "echo 1"}]], [["exit", {"outcome": "done", "outputs": {"total": 1}}]]]
    s = session({"count": count}, replies=["it is back"])
    result = await s.node("count", {"revisions": "r1"})
    assert result.exit == "done"
    [told] = s.person.told
    assert "`shell`" in told and "`run`" in told
    returned = [(e.text, e.error) for e in s.events(ToolReturned) if e.call.name == "shell__run"]
    assert returned == [("ok", False)]
