"""F6 session persistence: a session is saved through its store as it goes, and resumed where it stopped (SS-3, SS-5,
SS-11; E6, E7, E9). What a unit in flight does on resume is the backend's own, as in F7."""

import pytest
from session_support import ScriptedPerson

from agent_core.contracts.errors import RunCannotStart
from agent_core.contracts.events import ModelRequested

ASK = [[["ask", {"question": "Which colour?"}]], [["exit", {"outcome": "done", "outputs": {"colour": "red"}}]]]
RECORD = [[["exit", {"outcome": "done", "outputs": {"note": "n"}}]]]
LOOKUP = [[["lookup_revision", {}]], [["exit", {"outcome": "done", "outputs": {}}]]]


@pytest.mark.feature("F6")
async def test_a_question_pending_when_the_person_left_is_asked_again_on_resume(harness):   # E6, PAUSE-2 as Q2 amends it
    first = ScriptedPerson([])
    left = await harness({"ask": ASK}, person=first).sessions.start("ask")
    assert left.state == "waiting" and [q.text for q in first.asked] == ["Which colour?"]
    again = ScriptedPerson(["red", None])
    resumed = await harness({"ask": ASK}, person=again).sessions.resume(left.session_id)
    assert [q.text for q in again.asked] == ["Which colour?"]
    assert (resumed.state, resumed.facts) == ("waiting", {"colour": "red"})
    assert resumed.record.notes[0].node == "ask"


@pytest.mark.feature("F6")
async def test_a_person_who_leaves_at_the_first_prompt_gets_a_waiting_session(harness):   # E7, Review Focus 1
    left = await harness({}, person=ScriptedPerson([])).sessions.start()
    assert left.state == "waiting"
    again = ScriptedPerson([None])
    resumed = await harness({}, person=again).sessions.resume(left.session_id)
    assert resumed.state == "waiting" and again.seen == [("heard", None)]


@pytest.mark.feature("F6")
async def test_resume_routes_a_turn_that_was_never_routed(harness):   # design §3.5, first row
    with pytest.raises(FileNotFoundError):   # the routing run has no script: it raises before it enters anything
        await harness({}, person=ScriptedPerson(["look up alpha"])).sessions.start(session_id="session-20261128T000000Z-abc123")
    scripts = {"@routing": [[["enter", {"node": "lookup", "inputs": {"name": "alpha"}}]]], "lookup": LOOKUP}
    h = harness(scripts, person=ScriptedPerson([None]))
    resumed = await h.sessions.resume("session-20261128T000000Z-abc123")
    first = next(e for e in h.events.record() if isinstance(e, ModelRequested) and e.label.startswith("@routing"))
    assert next(p for p in first.parts if p.kind == "conversation").messages[-1].text == "look up alpha"
    assert resumed.facts == {"revision": "r1"}


@pytest.mark.feature("F6")
async def test_resuming_an_ended_session_is_refused(harness, copied):   # E9
    topology = copied / "topology.yaml"
    topology.write_text(topology.read_text().replace("  done: route", "  done: end"))
    ended = await harness({"record": RECORD}, instance=copied, person=ScriptedPerson()).sessions.start("record")
    with pytest.raises(RunCannotStart) as refused:
        await harness({}, instance=copied, person=ScriptedPerson()).sessions.resume(ended.session_id)
    assert str(refused.value) == f"session {ended.session_id} has ended"


@pytest.mark.feature("F6")
async def test_resuming_an_unknown_session_is_refused(harness):   # E9
    with pytest.raises(RunCannotStart) as refused:
        await harness({}, person=ScriptedPerson()).sessions.resume("session-20261128T000000Z-000000")
    assert str(refused.value) == "no session session-20261128T000000Z-000000"


@pytest.mark.feature("F6")
async def test_the_session_keeps_its_record_and_its_state_in_its_directory(harness, tmp_path):   # SS-1, §3.6
    result = await harness({"record": RECORD}, person=ScriptedPerson([None])).sessions.start("record")
    assert result.session_dir == tmp_path / "runs" / result.session_id
    assert (result.session_dir / "session.json").is_file()
    assert (result.record.run_id, result.record.sequence, result.record.end_state) == (result.session_id, None, "waiting")
    assert [note.node for note in result.record.notes] == ["record"] and result.record.facts == {"note": "n"}


@pytest.mark.feature("F6")
async def test_a_session_saved_between_units_resumes_on_the_other_backend(harness, backend_name, tmp_path, monkeypatch):   # P25
    import json

    from agent_core.core.registry import BACKENDS

    other = next(name for name in BACKENDS if name != backend_name)
    scripts = {"record": RECORD, "@routing": ["Done."]}
    directory = tmp_path / "other-scripts"
    directory.mkdir()
    for node, steps in scripts.items():
        (directory / f"{node}.json").write_text(json.dumps(steps))
    monkeypatch.setenv("AGENT_CORE_SCRIPTED_SCRIPTS" if other == "scripted" else "AGENT_CORE_LANGGRAPH_MODEL",
                       str(directory) if other == "scripted" else f"script:{directory}")
    left = await harness(scripts, backend=other, person=ScriptedPerson([None])).sessions.start("record")
    assert left.state == "waiting"   # saved at the person's turn after `record` ended
    h = harness(scripts, person=ScriptedPerson(["thanks", None]))
    resumed = await h.sessions.resume(left.session_id)
    assert [e.label for e in h.events.record() if isinstance(e, ModelRequested)] == ["@routing#1"]
    assert resumed.facts == {"note": "n"}


# --- sequences in a session (SS-9, SS-10, SS-16) -----------------------------------------------------------------------

COUNT = [[["exit", {"outcome": "done", "outputs": {"total": 7}}]]]
SESSION = "session-20261128T000000Z-5e5510"


def saved(tmp_path, facts, said):
    """A session saved with `facts`, at a turn of the person's (`said`) that was never routed: resuming routes it."""
    from agent_core.core.session import new_state
    from agent_core.stores.file import FileStore

    state = new_state()
    state["facts"], state["transcript"] = dict(facts), [{"user": said}]
    FileStore(tmp_path / "runs").save(SESSION, state)
    return SESSION


def routed_to(name, inputs):
    return {"@routing": [[["enter", {"node": name, "inputs": inputs}]]]}


def transcript(tmp_path):
    from agent_core.stores.file import FileStore

    return FileStore(tmp_path / "runs").load(SESSION)["transcript"]


@pytest.mark.feature("F6")
async def test_a_sequence_starts_from_its_inputs_not_the_session_facts(harness, tmp_path):   # E11, SS-9
    saved(tmp_path, {"name": "beta"}, "look up alpha and count")
    scripts = {**routed_to("lookup_then_count", {"name": "alpha"}), "lookup": LOOKUP, "count": COUNT}
    resumed = await harness(scripts, person=ScriptedPerson([None])).sessions.resume(SESSION)
    assert resumed.facts["revision"] == "r1"   # alpha's, not beta's


@pytest.mark.feature("F6")
async def test_a_sequence_entered_without_its_input_does_not_take_it_from_the_facts(harness, tmp_path):   # E11, plan review A8
    saved(tmp_path, {"name": "beta"}, "look something up")
    scripts = {**routed_to("lookup_then_count", {}), "lookup": LOOKUP, "count": COUNT}
    resumed = await harness(scripts, person=ScriptedPerson([None])).sessions.resume(SESSION)
    assert "revision" not in resumed.facts
    assert {"sequence": "lookup_then_count", "inputs": {}, "end": "failed"} in transcript(tmp_path)


@pytest.mark.feature("F6")
async def test_only_the_outputs_the_steps_returned_are_merged(harness, tmp_path):   # E11, SS-10
    saved(tmp_path, {"name": "beta"}, "look up alpha and count")
    scripts = {**routed_to("lookup_then_count", {"name": "alpha"}), "lookup": LOOKUP, "count": COUNT}
    resumed = await harness(scripts, person=ScriptedPerson([None])).sessions.resume(SESSION)
    assert resumed.facts == {"name": "beta", "revision": "r1", "total": 7}   # the sequence's input `alpha` is not merged
    assert {"sequence": "lookup_then_count", "inputs": {"name": "alpha"}, "end": "done"} in transcript(tmp_path)


@pytest.mark.feature("F6")
async def test_a_failed_node_inside_a_sequence_is_told_and_is_in_the_transcript(harness, tmp_path):   # CTL-8, plan review A4
    saved(tmp_path, {}, "look up alpha")
    failed = [[["exit", {"outcome": "failed", "outputs": {"reason": "the register is closed"}}]]]
    person = ScriptedPerson([None])
    scripts = {**routed_to("lookup_then_count", {"name": "alpha"}), "lookup": failed, "count": COUNT}
    await harness(scripts, person=person).sessions.resume(SESSION)
    assert any("the register is closed" in text for text in person.told)
    entry = {"node": "lookup", "inputs": {"name": "alpha"}, "outcome": "failed", "reason": "the register is closed"}
    assert entry in transcript(tmp_path)


@pytest.mark.feature("F6")
async def test_a_resumed_sequence_that_waits_again_returns_waiting(harness, tmp_path):   # SS-16, SS-15, D1, plan review A2
    import asyncio

    asking = [[["ask", {"question": "Which?"}]], LOOKUP[0], LOOKUP[1]]
    scripts = {**routed_to("pairs", {"names": ["alpha", "beta"]}), "lookup": asking, "count": COUNT}
    left = await harness(scripts, person=ScriptedPerson(["pair them", None])).sessions.start(session_id=SESSION)
    assert left.state == "waiting"
    again = ScriptedPerson([])
    h = harness(scripts, person=again)
    waiting = await h.sessions.resume(SESSION)   # resumed by the journal, and the person has gone again
    assert waiting.state == "waiting" and [q.text for q in again.asked][:1] == ["Which?"]
    seen = len(h.events.record())
    await asyncio.sleep(0.3)
    assert len(h.events.record()) == seen   # nothing of the fan-out runs on after the session returned
    answered = await harness(scripts, person=ScriptedPerson(["x", "y", None])).sessions.resume(SESSION)
    assert answered.state == "waiting" and answered.facts["total"] == 7
    assert {"sequence": "pairs", "inputs": {"names": ["alpha", "beta"]}, "end": "done"} in transcript(tmp_path)
