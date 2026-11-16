import json
from dataclasses import replace

from agent_core.core.state import HarnessState, Slot, StateView, close_slot, from_dict, record_value, to_dict, view, written


def test_a_name_is_recorded_by_what_kind_of_name_it_is(refresh_node):
    state = HarnessState(session={}, node=Slot("refresh", {}, {}, {}))
    assert record_value(state, state.node, refresh_node, "sources", "polars") == "inputs"
    assert record_value(state, state.node, refresh_node, "branch", "refresh/alpha") == "session"
    assert record_value(state, state.node, refresh_node, "progress", "1 of 8") == "values"
    assert state.node.inputs == {"sources": "polars"} and state.node.values == {"progress": "1 of 8"}
    assert state.session == {"branch": "refresh/alpha"} and state.node.outputs == {"branch": "refresh/alpha"}   # counts on EXIT (JOB-7a)


def test_an_output_that_is_also_an_input_is_recorded_as_the_input(refresh_node):             # §5.5: inputs first
    node = replace(refresh_node, inputs={"branch": "x"})
    state = HarnessState(session={}, node=Slot("refresh", {}, {}, {}))
    assert record_value(state, state.node, node, "branch", "b") == "inputs"
    assert state.node.inputs == {"branch": "b"} and state.session == {} and state.node.outputs == {}


def test_recording_an_input_clears_the_pending_question(refresh_node):
    state = HarnessState(session={}, node=Slot("refresh", {}, {}, {}, pending_question="Which sources should I update?"))
    record_value(state, state.node, refresh_node, "progress", "1 of 8")
    record_value(state, state.node, refresh_node, "branch", "refresh/alpha")
    assert state.node.pending_question == "Which sources should I update?"        # only an input answers the question
    record_value(state, state.node, refresh_node, "sources", "polars")
    assert state.node.pending_question is None


def test_recording_into_the_temporary_slot_leaves_the_node_slot_alone(refresh_node):
    state = HarnessState(session={}, node=Slot("refresh", {}, {}, {}), temporary=Slot("refresh", {}, {}, {}))
    record_value(state, state.temporary, refresh_node, "progress", "2 of 8")
    assert state.temporary.values == {"progress": "2 of 8"} and state.node.values == {}


def test_view_is_a_copy_and_remembers_writes(refresh_node):
    state = HarnessState(session={"a": 1}, node=Slot("refresh", {"sources": "x"}, {"p": 2}, {}))
    v = view(state, state.node)
    v["a"] = 1
    v["new"] = [1]
    assert v.written == {"a", "new"} and state.session == {"a": 1}      # an unchanged value still counts as written
    assert state.node.values == {"p": 2} and state.node.inputs == {"sources": "x"}


def test_view_shows_session_facts_then_working_values_then_inputs():
    state = HarnessState(
        session={"s": "session", "both": "session", "x": "session"},
        node=Slot("n", {"x": "input"}, {"both": "value", "x": "value", "v": "value"}, {}),
    )
    assert view(state, state.node) == {"s": "session", "both": "value", "x": "input", "v": "value"}


def test_view_without_a_slot_is_the_session_facts():
    assert view(HarnessState(session={"a": 1}), None) == {"a": 1}


def test_changing_a_value_in_place_does_not_reach_the_state():
    state = HarnessState(session={"items": [1]}, node=Slot("n", {}, {}, {}))
    view(state, state.node)["items"].append(2)
    assert state.session == {"items": [1]}


def test_update_and_setdefault_record_writes_but_construction_does_not():
    assert StateView({"a": 1}).written == set()
    v = StateView({"a": 1})
    v.update({"b": 2}, c=3)
    v.setdefault("d", 4)
    v |= {"e": 5}
    assert v.written == {"b", "c", "d", "e"} and v == {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}


def test_written_lists_assigned_names_and_values_changed_in_place():
    before = {"a": 1, "items": [1], "same": [0], "gone": 1}
    after = StateView({"a": 1, "items": [1], "same": [0], "gone": 1})
    after["a"] = 1                       # assigned, though unchanged
    after["items"].append(2)             # changed in place, never assigned
    after["new"] = "n"
    assert written(before, after) == [("a", 1), ("items", [1, 2]), ("new", "n")]


def test_written_is_empty_when_nothing_was_touched():
    assert written({"a": 1}, StateView({"a": 1})) == []


def test_closing_merges_declared_outputs_and_clears_the_slot():
    state = HarnessState(session={"branch": "old", "kept": 1}, node=Slot("refresh", {"sources": "x"}, {"p": 2}, {"branch": "new"}))
    close_slot(state, "node", {"branch": "refresh/alpha", "sources_updated": "polars"})
    assert state.session == {"branch": "refresh/alpha", "kept": 1, "sources_updated": "polars"}      # replaces a fact of the same name
    assert state.node is None


def test_closing_the_temporary_slot_leaves_the_active_node_as_it_was():     # ST-2, DIV-4
    node = Slot("refresh", {"sources": "x"}, {"p": 2}, {}, pending_question="Which?")
    state = HarnessState(session={}, node=node, temporary=Slot("improvise", {}, {"q": 1}, {}))
    close_slot(state, "temporary", {"answer": "42"})
    assert state.temporary is None and state.session == {"answer": "42"}
    assert state.node == Slot("refresh", {"sources": "x"}, {"p": 2}, {}, pending_question="Which?")


def test_round_trip_through_a_dict():
    state = HarnessState(
        session={"branch": "b", "items": [1, {"k": None}]},
        node=Slot("refresh", {"sources": "x"}, {"p": 2}, {"branch": "b"}, rejections=1, pending_question="Which?"),
        temporary=Slot("improvise", {}, {}, {}),
        menu_waiting=True,
        transcript=[{"role": "user", "text": "hi"}],
    )
    saved = to_dict(state)
    assert from_dict(json.loads(json.dumps(saved))) == state            # through JSON, as a saving store would
    assert from_dict(saved) == state


def test_round_trip_of_an_empty_state():
    state = HarnessState(session={})
    assert from_dict(to_dict(state)) == state and state.node is None and state.temporary is None
    assert not state.menu_waiting and state.transcript == []


def test_a_saved_dict_shares_nothing_with_the_state():
    state = HarnessState(session={"items": [1]}, node=Slot("n", {}, {}, {}))
    saved = to_dict(state)
    state.session["items"].append(2)
    state.node.values["x"] = 1
    assert saved["session"] == {"items": [1]} and saved["node"]["values"] == {}
