import json
from datetime import datetime, timezone

import pytest
from pydantic import SecretStr

from agent_core.contracts.events import ModelRequested, ModelResponded, NodeEnded, NodeStarted, RequestPart
from agent_core.contracts.facade import RunRecord
from agent_core.contracts.unit import UnitResult
from agent_core.contracts.values import Message, ModelResponse, NodeNote, Usage
from agent_core.core.record import build, failure, masked, notes

PARTS = (("engine: rules", 120), ("node file: nodes/scan.md", 80))


def started(label, node="scan"):
    return NodeStarted(label, node, PARTS, ("exit", "ask"))


def responded(label, sent, read=0, written=0):
    return ModelResponded(label, ModelResponse("", (), Usage(sent, read, written)))


def test_a_note_holds_where_the_parts_came_from_the_tools_and_what_the_responses_cost():  # SCOPE-7
    events = (started("scan#1"), responded("scan#1", 100, 40, 10), responded("scan#1", 150, 90, 0))
    [note] = notes(events, ["scan#1"])
    assert note == NodeNote("scan#1", "scan", PARTS, ("exit", "ask"), 2, Usage(250, 130, 10))


def test_a_count_is_not_known_as_soon_as_one_response_does_not_report_it():  # SCOPE-7
    events = (started("scan#1"), responded("scan#1", 100, 40, 10), responded("scan#1", None, 90, None))
    [note] = notes(events, ["scan#1"])
    assert note.model_calls == 2
    assert note.usage == Usage(None, 130, None)   # never read as zero


def test_a_run_with_no_model_call_cost_nothing():
    [note] = notes((started("scan#1"),), ["scan#1"])
    assert (note.model_calls, note.usage) == (0, Usage(0, 0, 0))


def test_notes_are_those_of_the_labels_asked_for_in_their_order_and_only_of_runs_that_started():
    events = (started("a#1", "a"), started("b#2", "b"), responded("b#2", 5), started("a#3", "a"))
    assert [n.label for n in notes(events, ["a#3", "a#1", "c#4"])] == ["a#3", "a#1"]   # c#4 never started


def test_a_note_keeps_the_kind_and_length_of_each_part_of_each_request_and_never_their_content():  # Q4
    first = ModelRequested("scan#1", (
        RequestPart("instructions", text="be brief"),
        RequestPart("conversation", (Message("user", "a very secret question"),)),
    ))
    second = ModelRequested("scan#1", (
        RequestPart("tools", text='[{"name": "exit"}]'),
        RequestPart("conversation", (Message("call", call_id="c1", name="ask", args={"q": "x"}, result="the answer"),)),
    ))
    events = (started("scan#1"), first, responded("scan#1", 7), second, NodeEnded("scan#1", "scan", "done", None))
    [note] = notes(events, ["scan#1"])
    assert note.parts == PARTS
    assert note.requests == (
        (("instructions", 8), ("conversation", 22)),
        (("tools", 18), ("conversation", len("the answer") + len('{"q": "x"}'))),
    )
    assert "secret" not in repr(note) and "be brief" not in repr(note)


def test_a_run_with_no_request_has_none():
    [note] = notes((started("scan#1"),), ["scan#1"])
    assert note.requests == ()


def test_a_failed_result_is_kept_as_the_node_with_what_the_result_said():  # JOB-9a
    result = UnitResult("failed", {}, reason="needs_input", detail={"question": "Which colour?"})
    assert failure("asker", result) == {
        "node": "asker", "outcome": "failed", "reason": "needs_input", "question": "Which colour?", "outputs": {},
    }
    own = UnitResult("failed", {"reason": "it broke"})
    assert failure("scan", own) == {"node": "scan", "outcome": "failed", "outputs": {"reason": "it broke"}}


def test_a_secret_setting_is_not_written_in_the_params():
    class Settings:
        TOKEN = SecretStr("hunter2")
        NAME = "alpha"

    assert masked({"TOKEN": "hunter2", "NAME": "zeta"}, Settings()) == {"TOKEN": "********", "NAME": "zeta"}
    assert masked({"NAME": "zeta"}, None) == {"NAME": "zeta"}


def record(**given):
    kept = dict(
        params={"NAME": "zeta"}, settings_files=["a.yaml"], backend="toy", attended=False, start="t0", end="t1",
        failures=[], events=(started("scan#1"), responded("scan#1", 3)), labels=["scan#1"], run_id="refresh-1", sequence="refresh",
    )
    return build(**{**kept, **given})


def test_a_sequence_that_ended_done_is_recorded_ok_with_its_steps_and_facts():  # JOB-9a
    steps = [{"step": 1, "name": "scan", "outcome": "done"}]
    result = {"end": "done", "trail": steps, "facts": {"entries": 2}, "summary": "all good"}
    made = record(result=result)
    assert isinstance(made, RunRecord)
    assert (made.params, made.settings_files, made.backend, made.attended) == ({"NAME": "zeta"}, ["a.yaml"], "toy", False)
    assert (made.start, made.end, made.status, made.summary) == ("t0", "t1", "ok", "all good")
    assert (made.run_id, made.end_state, made.steps, made.facts, made.failures) == ("refresh-1", "done", steps, {"entries": 2}, [])
    assert [n.label for n in made.notes] == ["scan#1"]


def test_a_sequence_that_ended_failed_is_recorded_failed():
    made = record(result={"end": "failed", "trail": [], "facts": {}, "summary": "no way on"})
    assert (made.status, made.end_state, made.summary) == ("failed", "failed", "no way on")


def test_a_sequence_that_ended_stopped_is_recorded_ok():  # JOB-17
    made = record(result={"end": "stopped", "trail": [], "facts": {}, "summary": "stop"})
    assert (made.status, made.end_state) == ("ok", "stopped")


def test_a_run_that_raised_is_recorded_failed_with_the_error_and_what_the_walk_had_reached():  # JOB-17, RESUME-2
    steps = [{"step": 1, "name": "scan", "outcome": "done"}, {"step": 2, "name": "index", "outcome": None}]
    made = record(error="ToolServerError: tool server `web` did not answer", progress={"trail": steps, "facts": {"n": 1}})
    assert (made.status, made.end_state, made.summary) == ("failed", "failed", "ToolServerError: tool server `web` did not answer")
    assert (made.steps, made.facts) == (steps, {"n": 1})


def test_a_run_that_raised_before_its_walk_began_has_no_steps_and_no_facts():
    made = record(error="boom", progress={})
    assert (made.steps, made.facts) == ([], None)


def test_a_record_with_a_value_that_is_not_json_names_the_field():                        # E10, Q7
    made = record(result={"end": "done", "trail": [], "facts": {"at": datetime.now(timezone.utc)}, "summary": "s"})
    with pytest.raises(TypeError, match=r"^facts: Object of type datetime is not JSON serializable$"):
        made.to_json()


def test_a_record_serialises_to_json_with_its_notes():                                   # RP-5
    made = record(result={"end": "done", "trail": [], "facts": {}, "summary": "s"})
    assert json.loads(made.to_json())["notes"][0]["label"] == "scan#1"
