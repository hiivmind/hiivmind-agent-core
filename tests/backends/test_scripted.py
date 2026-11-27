import os
import sys
from pathlib import Path

import pytest

from agent_core.backends.scripted import ScriptedBackend, ScriptedSettings
from agent_core.contracts.matrix import Entry, Feature
from agent_core.contracts.policy import CallResult, Review, merge
from agent_core.contracts.registry import REGISTERED_BACKENDS
from agent_core.contracts.unit import Unit, UnitResult
from agent_core.core.registry import backend
from agent_core.helpers.mcp import McpServers


class Replying:
    """A policy that lets everything run and tells the model `reply` when it stops without a call."""

    label, node, instructions, tools, handover, opening = "n#1", "n", "instructions", (), (), "go"

    def __init__(self, reply=None):
        self.reply, self.stops, self.calls, self.seen = reply, [], [], []

    def initial(self):
        return {"inputs": {}, "values": {}, "outputs": {}, "session": {}, "rejections": 0, "ending": None}

    def review(self, response, state):
        return Review({})

    async def call(self, call, state):
        self.calls.append(call.name)
        self.seen.append(("call", call.name))
        return CallResult("ok")

    async def responded(self, response, state):
        self.seen.append(("responded", len(response.calls)))
        if response.calls:
            return None
        self.stops.append(response.text)
        return self.reply

    def finish(self, state, said):
        return UnitResult("done", {"said": said})


class Sink:
    def emit(self, event):
        pass


def unit_of(policy, node="n"):
    async def start(name, inputs, thread):
        return policy

    return Unit(node, {}, "start", "", start, None, Sink(), None, None)


def with_scripts(tmp_path, **scripts):
    import json

    for node, steps in scripts.items():
        (tmp_path / f"{node}.json").write_text(json.dumps(steps))
    return ScriptedBackend(ScriptedSettings(SCRIPTS=tmp_path))


def test_scripted_registers_itself_on_first_use(monkeypatch):
    monkeypatch.delitem(REGISTERED_BACKENDS, "scripted", raising=False)
    monkeypatch.delitem(sys.modules, "agent_core.backends.scripted", raising=False)
    cls, settings = backend("scripted")
    assert (cls.__name__, settings.__name__) == ("ScriptedBackend", "ScriptedSettings")
    assert REGISTERED_BACKENDS["scripted"] == (cls, settings)


def test_the_scripts_directory_is_read_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_CORE_SCRIPTED_SCRIPTS", str(tmp_path))
    assert ScriptedSettings().SCRIPTS == tmp_path


def test_the_matrix_holds_an_entry_for_every_feature_and_builds_what_it_declares():
    matrix = ScriptedBackend(ScriptedSettings()).features()
    assert set(matrix) == set(Feature)
    helpers = {f.id for f, e in matrix.items() if e.state == "helper"}
    assert helpers == {"F1", "F2", "F3", "F4", "F5", "F7", "F8", "F9", "F11", "F15", "F16", "F18", "F21"}
    assert matrix[Feature.F7] == Entry(
        "helper", "macro resume by the core's journal; a unit in flight runs again from its start"
    )
    assert {f.id: e for f, e in matrix.items() if e.state == "not built"} == {
        **{f: Entry("not built", "no model") for f in ("F10", "F12", "F13", "F14", "F20", "F24")},
        "F19": Entry("not built", "deferred: no consumer in this delivery"),
        "F6": Entry("not built", "sessions, step 7"),
        "F17": Entry("not built", "sessions, step 7"),
        "F22": Entry("not built", "reserved"),
        "F23": Entry("not built", "deferred"),
    }


async def test_servers_are_given_the_environment_they_are_made_with(tmp_path):   # RP-1
    servers = ScriptedBackend(ScriptedSettings()).servers({}, tmp_path, {"X": "1"})
    assert isinstance(servers, McpServers) and servers._env == {"X": "1"}
    await servers.close()


async def test_a_string_step_the_policy_answers_goes_on_with_the_next_step(tmp_path):   # KIT-10
    policy = Replying("go on")
    result = await with_scripts(tmp_path, n=["READY?", [["a", {}]], "done saying"]).run_node(unit_of(policy))
    assert (policy.stops, policy.calls) == (["READY?", "done saying"], ["a"])
    assert result.outputs == {"said": "done saying"}


async def test_a_string_step_the_policy_does_not_answer_ends_the_run(tmp_path):
    policy = Replying(None)
    result = await with_scripts(tmp_path, n=["I cannot.", [["never", {}]]]).run_node(unit_of(policy))
    assert policy.calls == [] and result.outputs == {"said": "I cannot."}


async def test_a_node_that_does_not_start_is_not_played(tmp_path):
    async def start(name, inputs, thread):
        return UnitResult("skipped", {})

    result = await ScriptedBackend(ScriptedSettings()).run_node(Unit("n", {}, "start", "", start, None, None, None, None))
    assert result == UnitResult("skipped", {})   # no script, no setting: nothing was needed


async def test_the_script_is_the_file_of_the_node_that_is_running(tmp_path):   # R6, R7
    policy = Replying()
    backend_ = with_scripts(tmp_path, n=[[["from_n", {}]]], other=[[["from_other", {}]]])
    await backend_.run_node(unit_of(policy))
    assert policy.calls == ["from_n"]


async def test_a_missing_script_file_names_the_file(tmp_path):
    with pytest.raises(FileNotFoundError, match=r"n\.json"):
        await ScriptedBackend(ScriptedSettings(SCRIPTS=tmp_path)).run_node(unit_of(Replying()))


async def test_without_the_setting_the_backend_says_so():
    with pytest.raises(ValueError, match="SCRIPTS"):
        await ScriptedBackend(ScriptedSettings()).run_node(unit_of(Replying()))


async def test_each_response_is_given_to_the_policy_once_before_its_calls_run(tmp_path):   # SS-7
    policy = Replying(None)
    await with_scripts(tmp_path, n=[[["a", {}], ["b", {}]], "done"]).run_node(unit_of(policy))
    assert policy.seen == [("responded", 2), ("call", "a"), ("call", "b"), ("responded", 0)]
