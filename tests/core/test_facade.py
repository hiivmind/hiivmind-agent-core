import asyncio
import json
import os
import re
import sys
import typing
from pathlib import Path
from unittest.mock import ANY

import pytest
from facade_support import Toy, ToyPerson
from support import FIXTURE, FIXTURES, SEQUENCES

import agent_core
from agent_core.contracts import facade
from agent_core.contracts.errors import FeatureNotSupported, RunCannotStart, ToolServerError
from agent_core.contracts.events import Event, ModelResponded, NodeStarted, ToolReturned
from agent_core.contracts.matrix import Entry, Feature
from agent_core.contracts.registry import REGISTERED_BACKENDS
from agent_core.contracts.values import Message, Outcome, Usage
from agent_core.core.registry import BACKENDS

ALPHA = FIXTURE / "config" / "alpha.yaml"
ASK_ALL = """
sequences:
  ask_all:
    description: Ask a colour for each source.
    start: {fan_out: asker, over: names, as: who, into: colours, max_concurrency: 2}
    transitions:
      asker: {done: end, failed: end}
  plain_run:
    description: Run the plain node.
    start: plain
    transitions:
      plain: {done: end, failed: end}
  status_run:
    description: Run the status node.
    start: status
    transitions:
      status: {done: end, failed: end}
"""
ASK = {"asker": [[("ask", {"question": "Which colour?"})], [("exit", {"outcome": "done", "outputs": {"colour": "red"}})]]}
STATUS = {"status": [
    [("tools__shell", {"command": "echo status"})],
    [("exit", {"outcome": "done", "outputs": {"status_report": "ok"}})],
]}
PLAIN = {"plain": [[("exit", {"outcome": "done", "outputs": {"done_work": "plain-work"}})]]}


@pytest.fixture
def toy(monkeypatch):
    """`toy(scripts, **options)`: registers a `Toy` as the backend `toy` and returns it."""

    def make(scripts=None, **options) -> Toy:
        backend = Toy(scripts, **options)
        monkeypatch.setitem(REGISTERED_BACKENDS, "toy", (lambda settings: backend, object))
        return backend

    return make


@pytest.fixture
async def open_harness(tmp_path):
    """`open_harness(instance_dir, **options)`: a harness on the toy backend, closed at the end of the test."""
    made = []

    def make(root, **options):
        options = {"backend": "toy", "runs": tmp_path / "runs", **options}
        harness = agent_core.open(Path(root) / "instance.yaml", **options)
        made.append(harness)
        return harness

    yield make
    for harness in made:
        await harness.close()


def spike(**options):
    return {"settings": [ALPHA], **options}


@pytest.fixture
def copy(broken):
    """A copy of the instance fixture whose servers still start: its `../servers/` becomes where they are."""
    broken("instance.yaml", (broken.root / "instance.yaml").read_text().replace("../servers/", f"{FIXTURES / 'servers'}/"))
    return broken


@pytest.fixture
def asking(copy):
    copy.append("topology.yaml", ASK_ALL)
    return copy


# --- a node run ------------------------------------------------------------------------------------------------------


async def test_a_client_registers_a_tool_and_runs_a_node(toy, open_harness, broken_sequences):   # example 1, FAC-1, FAC-3
    calls = []

    def client_tool(n: int) -> dict:
        """Count one up."""
        calls.append(n)
        return {"count": n + 1}

    broken_sequences.frontmatter("status", **{"allowed-tools": "[client_tool]"})
    backend = toy({"status": [[("client_tool", {"n": 3})], [("exit", {"outcome": "stale", "outputs": {"refresh_needed": True}})]]})
    harness = open_harness(broken_sequences.root)
    harness.tools.register(client_tool)
    outcome = await harness.nodes.run("status", {})
    assert outcome == Outcome("stale", {"refresh_needed": True}, notes=ANY)
    assert calls == [3]
    [unit] = backend.units
    assert (unit.name, unit.intent, unit.thread, unit.run_dir) == ("status", "start", "", None)
    assert unit.tools.specs["client_tool"].description == "Count one up."
    assert {"client_tool", "ready", "refresh_needed"} <= unit.tools.functions   # the client's, and instance.yaml's own (Q2)
    [note] = outcome.notes
    assert (note.label, note.node, note.model_calls) == ("status#1", "status", 2) and note.tools[-1] == "client_tool"


async def test_open_connects_no_server_and_a_run_connects_those_the_instance_declares(toy, open_harness, tmp_path):
    backend = toy({"status": [[("tools__shell", {"command": "echo hi"})], [("exit", {"outcome": "done", "outputs": {"status_report": "ok"}})]]})
    harness = open_harness(FIXTURE, **spike())
    assert backend.served is None                       # open is synchronous: nothing is connected yet
    outcome = await harness.nodes.run("status", {})
    assert outcome.exit == "done" and set(backend.served) == {"tools", "web"}
    called = [json.loads(line) for line in (tmp_path / "runs" / "tool_calls.jsonl").read_text().splitlines()]
    assert [c["args"] for c in called] == [{"command": "echo hi"}]    # the server was given AGENT_CORE_RUN_DIR


async def test_a_server_the_client_registers_is_reached_even_after_a_run(toy, open_harness, copy, tmp_path):
    copy.frontmatter("status", **{"allowed-tools": "[extra__shell]"})
    backend = toy({
        **PLAIN,
        "status": [[("extra__shell", {"command": "echo later"})], [("exit", {"outcome": "done", "outputs": {"status_report": "ok"}})]],
    })
    harness = open_harness(copy.root, **spike())
    await harness.nodes.run("plain", {})
    harness.tools.register_server("extra", {"command": "python", "args": [str(FIXTURES / "servers" / "shell_server.py")]})
    outcome = await harness.nodes.run("status", {})
    assert outcome.exit == "done" and "extra__shell" in backend.units[-1].tools.specs
    assert "echo later" in (tmp_path / "runs" / "tool_calls.jsonl").read_text()


async def test_a_node_run_carries_on_after_a_cut_shell_output_and_the_result_says_how_much(toy, open_harness, tmp_path):   # R10
    root = tmp_path / "loud-instance"
    (root / "nodes").mkdir(parents=True)
    (root / "instance.yaml").write_text(
        "name: loud\ncore: 0\nentry: topology.yaml\npolicy: POLICY.md\nbackend: toy\n"
        f"servers:\n  shell: {{command: {sys.executable}, args: [-m, agent_tools.shell_server]}}\n"
    )
    (root / "POLICY.md").write_text("Follow the procedure.\n")
    (root / "topology.yaml").write_text("nodes:\n  - {name: loud, path: nodes/loud.md}\nexits:\n  done: route\n  failed: route\n")
    (root / "nodes" / "loud.md").write_text(
        "---\nname: loud\ndescription: Run a command that prints a lot.\ninputs: {}\n"
        "outputs:\n  said: {type: string, description: what was seen}\nexits: [done, failed]\nallowed-tools: [shell__run]\n---\n"
        "# Loud\n\n## Steps\n\n1. CALL `shell__run` with `command` set to `loud`.\n2. EXIT `done` with output `said` set to `seen`.\n"
    )
    toy({"loud": [
        [("shell__run", {"command": "python -c \"print('x' * 100000 + 'END')\""})],
        [("exit", {"outcome": "done", "outputs": {"said": "seen"}})],
    ]})
    harness = open_harness(root)
    outcome = await harness.nodes.run("loud", {})
    assert outcome.exit == "done" and outcome.outputs == {"said": "seen"}      # the run went on past the cut output
    [returned] = [e for e in harness.events.record() if isinstance(e, ToolReturned) and e.call.name == "shell__run"]
    shown = json.loads(returned.text)                                             # what the model was shown
    assert shown["cut"] >= 80000 and len(shown["stdout"]) <= 20000 and shown["stdout"].rstrip().endswith("END")


async def test_each_node_start_is_labelled_with_the_node_and_its_number_in_the_harness(toy, open_harness):
    toy(PLAIN)
    harness = open_harness(FIXTURE, **spike())
    first, second = await harness.nodes.run("plain", {}), await harness.nodes.run("plain", {})
    assert [o.notes[0].label for o in (first, second)] == ["plain#1", "plain#2"]
    assert [e.label for e in harness.events.record() if isinstance(e, NodeStarted)] == ["plain#1", "plain#2"]


async def test_an_unknown_node_is_refused_listing_the_nodes(toy, open_harness):
    backend = toy()
    harness = open_harness(FIXTURE, **spike())
    with pytest.raises(ValueError, match=r"^no node `nope`; the nodes are: refresh, status, survey, shape,"):
        await harness.nodes.run("nope", {})
    assert backend.units == []


async def test_an_undeclared_input_raises_before_a_model_call(toy, open_harness):          # NODE-8a
    backend = toy()
    harness = open_harness(FIXTURE, **spike())
    with pytest.raises(ValueError) as e:
        await harness.nodes.run("refresh", {"sources": "polars", "bogus": 1})
    assert str(e.value) == "`refresh` has no input `bogus`; its inputs are: sources"
    with pytest.raises(ValueError) as e:
        await harness.nodes.run("status", {"bogus": 1})
    assert str(e.value) == "`status` has no input `bogus`; it takes no inputs"
    assert backend.units == [] and harness.events.record() == ()


# --- the node start --------------------------------------------------------------------------------------------------


async def test_a_declared_check_that_is_not_met_stops_the_node_before_a_model_call(toy, open_harness):   # NODE-13, NODE-13a
    backend = toy({"gated": [[("exit", {"outcome": "done"})]]})
    harness = open_harness(FIXTURE, **spike())
    shell = await harness.nodes.run("gated", {})
    assert shell == Outcome(
        "failed", {}, "precondition_unmet", {"message": "The corpus alpha is not ready: there is no alpha.ready file."}, ANY
    )
    function = await harness.nodes.run("gated_fn", {})
    assert (function.exit, function.reason) == ("failed", "precondition_unmet")
    routed = await harness.nodes.run("gated_route", {})
    assert routed == Outcome("v1", {}, None, {"message": "The corpus alpha has a v1 index."}, ANY)
    assert not [e for e in harness.events.record() if isinstance(e, (NodeStarted, ModelResponded))]
    assert backend.briefs == []


async def test_a_check_that_is_met_leaves_its_facts_for_the_node(toy, open_harness):       # NODE-11
    backend = toy({"gated_rec": [[("exit", {"outcome": "done", "outputs": {}})]]})
    harness = open_harness(FIXTURE, **spike())
    outcome = await harness.nodes.run("gated_rec", {})
    assert (outcome.exit, outcome.outputs) == ("done", {"stamp": "ready-alpha"})           # recorded before the node started
    assert "Checked by: the harness." in backend.briefs[0]                                  # a working value, in the brief


async def test_a_check_that_cannot_be_run_is_an_error_not_an_unmet_precondition(toy, open_harness):   # NODE-12
    backend = toy()
    harness = open_harness(FIXTURE, **spike())
    with pytest.raises(ValueError, match="the precondition check for `gated_missing` could not be run: no tool `nosuchtool`"):
        await harness.nodes.run("gated_missing", {})
    with pytest.raises(ValueError, match="the precondition check for `gated_broken` could not be run: broken_check raised RuntimeError"):
        await harness.nodes.run("gated_broken", {})
    assert backend.briefs == []


async def test_a_template_failure_is_a_failed_result_with_the_reason_unknown_placeholder(toy, open_harness, copy):   # TPL-2b, TPL-6b
    copy.append("nodes/plain.md", "\n{{settings.NOPE}}\n")
    backend = toy()
    harness = open_harness(copy.root, **spike())
    outcome = await harness.nodes.run("plain", {})
    assert outcome == Outcome(
        "failed", {}, "unknown_placeholder", {"detail": "unknown placeholder {{settings.NOPE}} in nodes/plain.md"}, ANY
    )
    assert backend.briefs == []


async def test_a_node_that_declares_a_tool_no_source_offers_fails_before_any_check_runs(toy, open_harness, copy):
    copy.frontmatter("gated", **{"allowed-tools": "[nowhere]"})
    toy()
    harness = open_harness(copy.root, **spike())
    with pytest.raises(ValueError, match="`gated` declares the tool `nowhere`, which no tool source offers"):
        await harness.nodes.run("gated", {})


async def test_a_job_node_is_given_the_hand_over_of_the_context_strategy(toy, open_harness):   # CTX-3
    backend = toy(PLAIN)
    harness = open_harness(FIXTURE, **spike())
    seen = {}

    class Earlier:
        async def build(self, request):
            seen["request"] = request
            return (Message("user", "earlier talk"),)

    harness.extensions.register("context", "none", Earlier)
    await harness.nodes.run("plain", {})
    assert backend.handovers == [(Message("user", "earlier talk"),)]
    request = seen["request"]
    assert (request.node, request.inputs, request.facts, request.transcript) == ("plain", {}, {}, ())
    assert request.contract.name == "plain"


# --- settings, backends, resources and the person ---------------------------------------------------------------------


async def test_two_harnesses_with_different_settings_give_a_function_their_own(toy, open_harness, tmp_path):   # Review Focus 1, TOOL-12
    zeta = tmp_path / "zeta.yaml"
    zeta.write_text("CORPUS_NAME: zeta\nCORPUS_PATH: /tmp/spike-corpus-zeta\nCORPUS_REPO: example/corpus-zeta\n")
    toy({"locate": [[("locate", {"source": "polars"})], [("exit", {"outcome": "done", "outputs": {}})]]})
    one, other = open_harness(FIXTURE, **spike()), open_harness(FIXTURE, settings=[zeta])
    first, second = await asyncio.gather(one.nodes.run("locate", {"source": "polars"}), other.nodes.run("locate", {"source": "polars"}))
    assert first.outputs == {"path": "/tmp/spike-corpus-alpha/polars"}
    assert second.outputs == {"path": "/tmp/spike-corpus-zeta/polars"}


async def test_an_unknown_backend_override_stops_before_any_model_call(toy, open_harness):   # INST-1a
    backend = toy(PLAIN)
    harness = open_harness(FIXTURE, **spike())
    with pytest.raises(RunCannotStart, match=r"no backend `nope`; backends are: scripted"):
        await harness.nodes.run("plain", {}, backend="nope")
    assert backend.units == [] and backend.served is None


async def test_a_known_backend_that_is_not_installed_stops_the_run_naming_the_package(toy, open_harness, monkeypatch):   # INST-1b
    monkeypatch.setitem(BACKENDS, "openai", ("agent_core.backends.openai", "openai-agents"))
    backend = toy(PLAIN)
    harness = open_harness(FIXTURE, **spike())
    with pytest.raises(RunCannotStart) as e:
        await harness.nodes.run("plain", {}, backend="openai")
    assert str(e.value) == "backend `openai` needs the package `openai-agents`, which is not installed"
    assert backend.units == []


async def test_a_backend_registered_through_extensions_runs_one_unit_and_the_default_the_rest(toy, open_harness):   # REG-2, FAC-3
    default = toy(PLAIN)
    other = Toy({"plain": [[("exit", {"outcome": "failed", "outputs": {"reason": "other"}})]]})
    harness = open_harness(FIXTURE, **spike())
    harness.extensions.register("backend", "other", (lambda settings: other, object))
    assert (await harness.nodes.run("plain", {}, backend="other")).outputs == {"reason": "other"}
    assert (await harness.nodes.run("plain", {})).outputs == {"done_work": "plain-work"}
    assert ([u.name for u in other.units], [u.name for u in default.units]) == (["plain"], ["plain"])
    with pytest.raises(RunCannotStart, match=r"backends are: other, scripted, toy"):
        await harness.nodes.run("plain", {}, backend="nope")


async def test_open_stops_with_run_cannot_start_for_what_it_cannot_load(toy):
    toy()
    runs = {"backend": "toy"}
    with pytest.raises(RunCannotStart, match="instance.yaml: no such file"):
        agent_core.open(FIXTURE.parent / "nowhere" / "instance.yaml", **runs)
    with pytest.raises(RunCannotStart, match="settings: missing or invalid: CORPUS_REPO"):
        agent_core.open(FIXTURE / "instance.yaml", **runs)
    with pytest.raises(RunCannotStart, match=r"no backend `nope`; backends are: scripted, toy"):
        agent_core.open(FIXTURE / "instance.yaml", settings=[ALPHA], backend="nope")
    with pytest.raises(RunCannotStart, match="settings: no setting named `BOGUS`"):
        agent_core.open(FIXTURE / "instance.yaml", settings=[ALPHA], params={"BOGUS": "1"}, **runs)


async def test_open_and_close_bring_the_instances_directory_onto_the_path_and_back(toy, open_harness):
    toy()
    root = str(FIXTURE.resolve())
    before = list(sys.path)
    with pytest.raises(RunCannotStart):
        agent_core.open(FIXTURE / "instance.yaml", backend="toy")
    assert sys.path == before
    harness = open_harness(FIXTURE, **spike())
    assert sys.path[0] == root
    await harness.close()
    assert sys.path == before


async def test_a_run_sets_the_instance_and_run_directory_and_gives_them_back_when_it_ends(toy, open_harness, tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_CORE_RUN_DIR", raising=False)
    monkeypatch.setenv("AGENT_CORE_INSTANCE", "before")
    backend = toy(PLAIN, raises={"locate": RuntimeError("boom")})
    harness = open_harness(FIXTURE, **spike())
    await harness.nodes.run("plain", {})
    assert backend.environment == [
        {"AGENT_CORE_INSTANCE": str(FIXTURE.resolve()), "AGENT_CORE_RUN_DIR": str(tmp_path / "runs")}
    ]
    assert os.environ["AGENT_CORE_INSTANCE"] == "before" and "AGENT_CORE_RUN_DIR" not in os.environ
    with pytest.raises(RuntimeError):   # a run that raises gives them back too
        await harness.nodes.run("locate", {"source": "polars"})
    assert os.environ["AGENT_CORE_INSTANCE"] == "before" and "AGENT_CORE_RUN_DIR" not in os.environ


async def test_a_harness_that_closes_after_another_opened_leaves_that_harness_its_own_run_directory(toy, open_harness, tmp_path):
    toy({**PLAIN, **STATUS})
    first = open_harness(FIXTURE, **spike(runs=tmp_path / "a"))
    await first.nodes.run("plain", {})
    second = open_harness(FIXTURE, **spike(runs=tmp_path / "b"))
    await first.close()
    await second.nodes.run("status", {})
    assert "echo status" in (tmp_path / "b" / "tool_calls.jsonl").read_text()
    assert not (tmp_path / "a" / "tool_calls.jsonl").exists()


async def test_each_run_holds_its_own_servers_which_work_in_its_own_directory_and_close_when_it_ends(toy, open_harness, asking, tmp_path):   # TOOL-15
    backend = toy(STATUS)
    harness = open_harness(asking.root, **spike())
    first, second = await harness.sequences.run("status_run", {}), await harness.sequences.run("status_run", {})
    assert first.end == second.end == "done" and first.run_id != second.run_id
    for result in (first, second):
        lines = (tmp_path / "runs" / result.run_id / "tool_calls.jsonl").read_text().splitlines()
        assert [json.loads(line)["args"] for line in lines] == [{"command": "echo status"}]   # this run's server, this run's dir
    assert len(backend.sources) == 2 and all(source.closed for source in backend.sources)


async def test_the_servers_of_a_node_run_that_raises_are_closed_and_the_next_run_makes_its_own(toy, open_harness):
    backend = toy(PLAIN, raises={"locate": RuntimeError("boom")})
    harness = open_harness(FIXTURE, **spike())
    with pytest.raises(RuntimeError):
        await harness.nodes.run("locate", {"source": "polars"})
    assert [source.closed for source in backend.sources] == [True]
    await harness.nodes.run("plain", {})
    assert [source.closed for source in backend.sources] == [True, True]


async def test_a_setting_changed_between_two_runs_reaches_the_second_run(toy, open_harness, tmp_path):   # TOOL-12
    file = tmp_path / "now.yaml"
    file.write_text("CORPUS_NAME: one\nCORPUS_PATH: /tmp/one\nCORPUS_REPO: example/one\n")
    toy({"locate": [[("locate", {"source": "polars"})], [("exit", {"outcome": "done", "outputs": {}})]]})
    harness = open_harness(FIXTURE, settings=[file])
    assert (await harness.nodes.run("locate", {"source": "polars"})).outputs == {"path": "/tmp/one/polars"}
    file.write_text("CORPUS_NAME: two\nCORPUS_PATH: /tmp/two\nCORPUS_REPO: example/two\n")
    assert (await harness.nodes.run("locate", {"source": "polars"})).outputs == {"path": "/tmp/two/polars"}
    file.write_text("CORPUS_NAME: three\n")   # a file that no longer gives every setting: the run cannot start
    with pytest.raises(RunCannotStart, match="settings: missing or invalid: CORPUS_REPO"):
        await harness.nodes.run("locate", {"source": "polars"})


async def test_close_closes_the_backends_it_made_and_the_servers(toy, open_harness):
    backend = toy(PLAIN)
    other = Toy(PLAIN)
    harness = open_harness(FIXTURE, **spike())
    harness.extensions.register("backend", "other", (lambda settings: other, object))
    await harness.nodes.run("plain", {})
    await harness.nodes.run("plain", {}, backend="other")
    await harness.close()
    await harness.close()   # once only
    assert backend.closed and other.closed


async def test_a_resource_source_registered_through_extensions_serves_the_load_verb(toy, open_harness):   # FAC-3
    toy({"plain": [[("load", {"path": "anything.md"})], [("exit", {"outcome": "done", "outputs": {"done_work": "x"}})]]})
    asked = []

    class Client:
        def __init__(self, root):
            asked.append(root)

        def read(self, path):
            return f"the client's {path}"

        def exists(self, path):
            return True

    harness = open_harness(FIXTURE, **spike())
    harness.extensions.register("resources", "folder", Client)
    await harness.nodes.run("plain", {})
    [returned, _] = [e for e in harness.events.record() if isinstance(e, ToolReturned)]
    assert returned.text == "the client's anything.md" and asked == [FIXTURE.resolve()]


async def test_a_person_is_a_person_or_a_name_the_registry_knows_checked_when_the_harness_opens(toy, open_harness):
    toy({"asker": ASK["asker"]})
    person = ToyPerson("blue", pause=0)
    by_object = open_harness(FIXTURE, **spike(person=person))
    assert (await by_object.nodes.run("asker", {"who": "polars"})).exit == "done"
    assert person.asked == [("asker#1 polars", "Which colour?")]
    with pytest.raises(RunCannotStart, match="no person `ghost`; persons are: nobody, terminal"):
        open_harness(FIXTURE, **spike(person="ghost"))


async def test_a_person_a_client_registers_under_a_known_name_is_the_one_the_next_run_asks(toy, open_harness):   # FAC-3
    toy({"asker": ASK["asker"]})
    named = open_harness(FIXTURE, **spike(person="nobody"))
    other = ToyPerson("green", pause=0)
    named.extensions.register("person", "nobody", lambda: other)
    await named.nodes.run("asker", {"who": "ibis"})
    assert other.asked == [("asker#1 ibis", "Which colour?")]


async def test_an_extension_of_an_unknown_kind_is_refused(toy, open_harness):
    toy()
    harness = open_harness(FIXTURE, **spike())
    with pytest.raises(ValueError, match="no extension kind `tool_source`; the kinds are: backend, context, person, resources, journal"):
        harness.extensions.register("tool_source", "x", object)


# --- features a backend does not carry out -----------------------------------------------------------------------------


async def test_sessions_are_not_built(toy, open_harness):                                  # FAC-5, example 6
    toy()
    harness = open_harness(FIXTURE, **spike())
    with pytest.raises(FeatureNotSupported) as e:
        harness.sessions
    assert str(e.value) == "session persistence is not built on backend toy: sessions, step 7"
    assert (e.value.feature, e.value.backend, e.value.entry) == (Feature.F6, "toy", Entry("not built", "sessions, step 7"))


async def test_sessions_raise_whatever_the_backend_says_of_them_for_none_is_built_in_this_delivery(toy, open_harness):
    toy(entries={Feature.F6: Entry("native", "the SDK's checkpointer")})
    harness = open_harness(FIXTURE, **spike())
    with pytest.raises(FeatureNotSupported, match="sessions, step 7"):
        harness.sessions


async def test_the_event_record_is_refused_where_tracing_is_divergent_or_not_built(toy, open_harness):   # FAC-5, example 6
    toy(entries={Feature.F15: Entry("divergent", "its SDK has no tracing")})
    harness = open_harness(FIXTURE, **spike())
    with pytest.raises(FeatureNotSupported) as e:
        harness.events.record()
    assert str(e.value) == "tracing is divergent on backend toy: its SDK has no tracing"
    toy(entries={Feature.F15: Entry("not built", "later")})
    with pytest.raises(FeatureNotSupported, match="tracing is not built on backend toy: later"):
        open_harness(FIXTURE, **spike()).events.record()


async def test_a_divergent_feature_does_not_stop_the_run_only_the_call_to_it(toy, open_harness):   # KIT-12
    toy(PLAIN, entries={Feature.F15: Entry("divergent", "its SDK has no tracing")})
    harness = open_harness(FIXTURE, **spike())
    assert (await harness.nodes.run("plain", {})).exit == "done"


# --- usage and the run record ------------------------------------------------------------------------------------------


async def test_the_record_counts_tokens_or_says_not_reported(toy, open_harness):              # SCOPE-7
    two = [[("state_get", {"key": "x"})], [("exit", {"outcome": "done", "outputs": {"done_work": "w"}})]]
    backend = toy({"plain": two}, usage=lambda n: Usage(100 * n, 10, 0))
    harness = open_harness(FIXTURE, **spike())
    [note] = (await harness.nodes.run("plain", {})).notes
    assert (note.model_calls, note.usage) == (2, Usage(300, 20, 0))
    backend.usage = lambda n: Usage(None if n == 2 else 5, 1, None)
    [note] = (await harness.nodes.run("plain", {})).notes
    assert (note.label, note.model_calls, note.usage) == ("plain#2", 2, Usage(None, 2, None))   # not known, not zero


async def test_the_harness_implements_the_facade_contract(toy, open_harness):                # FAC-2
    toy(PLAIN)
    harness = open_harness(FIXTURE, **spike())
    assert isinstance(harness, facade.Harness)
    for held, protocol in ((harness.nodes, facade.Nodes), (harness.sequences, facade.Sequences), (harness.tools, facade.Tools),
                           (harness.events, facade.Events), (harness.extensions, facade.Extensions)):
        assert isinstance(held, protocol)
        for method in (m for m in vars(protocol) if not m.startswith("_")):   # each public return type is the contract's
            ours = typing.get_type_hints(getattr(type(held), method)).get("return")
            assert ours == typing.get_type_hints(getattr(protocol, method)).get("return"), (protocol, method)
    outcome = await harness.nodes.run("plain", {})
    assert isinstance(outcome, Outcome)
    assert harness.events.record() and all(isinstance(e, Event) for e in harness.events.record())


# --- a sequence run ------------------------------------------------------------------------------------------------------


async def test_a_sequence_run_gives_its_result_and_the_record_of_the_run(toy, open_harness, asking, tmp_path):   # JOB-9a, ORC-6
    backend = toy(PLAIN)
    harness = open_harness(asking.root, **spike(params={"GITHUB_TOKEN": "hunter2", "CORPUS_NAME": "zeta"}))
    result = await harness.sequences.run("plain_run", {})
    assert isinstance(result, facade.SequenceResult) and isinstance(result.record, facade.RunRecord)
    assert re.fullmatch(r"plain_run-\d{8}T\d{6}Z-[0-9a-f]{6}", result.run_id)
    assert result == facade.SequenceResult(
        "done", {"done_work": "plain-work"}, [{"step": 1, "name": "plain", "outcome": "done"}], result.run_id,
        {"done_work": "plain-work"}, result.record,
    )
    run_dir = tmp_path / "runs" / result.run_id
    assert run_dir.is_dir() and (tmp_path / "runs" / "journal.sqlite").is_file()
    [unit] = backend.units
    assert (unit.intent, unit.thread, unit.run_dir) == ("start", f"{result.run_id}/1/0/1", run_dir)
    record = result.record
    assert (record.params, record.settings_files, record.backend, record.attended) == (
        {"GITHUB_TOKEN": "********", "CORPUS_NAME": "zeta"}, [str(ALPHA)], "toy", False,
    )
    assert record.start <= record.end and record.start.endswith("+00:00")
    assert (record.run_id, record.end_state, record.status, record.failures, record.facts) == (
        result.run_id, "done", "ok", [], {"done_work": "plain-work"},
    )
    assert record.steps == result.steps and [(n.label, n.node, n.model_calls) for n in record.notes] == [("plain#1", "plain", 1)]


async def test_a_given_run_id_names_the_run(toy, open_harness, asking, tmp_path):
    toy(PLAIN)
    result = await open_harness(asking.root, **spike()).sequences.run("plain_run", {}, run_id="mine")
    assert result.run_id == "mine" and (tmp_path / "runs" / "mine").is_dir()


async def test_a_sequence_the_instance_does_not_have_cannot_start(toy, open_harness, asking):
    backend = toy()
    harness = open_harness(asking.root, **spike())
    with pytest.raises(RunCannotStart) as e:
        await harness.sequences.run("nope", {})
    assert str(e.value) == "no sequence `nope`; the sequences are: ask_all, plain_run, status_run"
    assert backend.units == []


async def test_a_failed_node_is_recorded_as_a_failure_and_ends_the_sequence_failed(toy, open_harness, asking):   # JOB-9a, JOB-9b
    toy({"plain": [[("exit", {"outcome": "failed", "outputs": {"reason": "bad"}})]]})
    result = await open_harness(asking.root, **spike()).sequences.run("plain_run", {})
    assert (result.end, result.record.status, result.record.end_state) == ("failed", "failed", "failed")
    assert result.record.failures == [{"node": "plain", "outcome": "failed", "outputs": {"reason": "bad"}}]


async def test_a_run_that_raises_ends_failed_with_the_error_in_the_record(toy, open_harness, asking):   # JOB-17
    toy(raises={"plain": RuntimeError("boom")})
    result = await open_harness(asking.root, **spike()).sequences.run("plain_run", {})
    assert (result.end, result.summary, result.facts) == ("failed", "RuntimeError: boom", {})
    assert result.steps == [{"step": 1, "name": "plain", "outcome": None}]   # the step that was running
    assert (result.record.status, result.record.end_state, result.record.summary) == ("failed", "failed", "RuntimeError: boom")


async def test_a_run_that_raised_keeps_the_steps_it_took_and_the_facts_it_had(toy, open_harness):   # RESUME-2, v0's regression
    toy({
        "migrate": [[("exit", {"outcome": "done", "outputs": {"entry_count": 3}})]],
        "index": [[("exit", {"outcome": "done", "outputs": {"entries": ["e1"]}})]],
    }, raises={"verify": RuntimeError("boom")})
    result = await open_harness(SEQUENCES).sequences.run("chain", {"scan_results": [["e1"]]})
    steps = [{"step": 1, "name": "migrate", "outcome": "done"}, {"step": 2, "name": "index", "outcome": "done"},
             {"step": 3, "name": "verify", "outcome": None}]
    facts = {"scan_results": [["e1"]], "entry_count": 3, "entries": ["e1"]}
    assert (result.end, result.summary, result.steps, result.facts) == ("failed", "RuntimeError: boom", steps, facts)
    assert (result.record.steps, result.record.facts, result.record.status) == (steps, facts, "failed")


async def test_an_unreachable_tool_server_raises_from_a_node_run_and_is_named_in_the_record_of_a_sequence(toy, open_harness, asking):   # TOOL-11e
    gone = ToolServerError("web", "fetch", "it stopped answering")
    toy(raises={"plain": gone})
    harness = open_harness(asking.root, **spike())
    with pytest.raises(ToolServerError) as e:
        await harness.nodes.run("plain", {})
    assert e.value is gone
    result = await harness.sequences.run("plain_run", {})
    assert result.record.failures == [{"node": "plain", "error": f"ToolServerError: {gone}"}]
    assert result.summary == f"ToolServerError: {gone}" and result.end == "failed"


async def test_rerun_runs_the_steps_from_the_one_named_under_a_new_id(toy, open_harness):   # RESUME-5
    backend = toy({
        "migrate": [[("exit", {"outcome": "done", "outputs": {"entry_count": 3}})]],
        "index": [[("exit", {"outcome": "done", "outputs": {"entries": ["e1"]}})]],
        "verify": [[("exit", {"outcome": "done", "outputs": {"drift": 0}})]],
    })
    harness = open_harness(SEQUENCES)
    first = await harness.sequences.run("chain", {"scan_results": [["e1"]]})
    again = await harness.sequences.rerun(first.run_id, 2)
    assert first.end == again.end == "done" and again.run_id != first.run_id and again.run_id.startswith("chain-")
    assert [u.name for u in backend.units] == ["migrate", "index", "verify", "index", "verify"]
    assert [u.thread for u in backend.units[3:]] == [f"{again.run_id}/2/0/1", f"{again.run_id}/3/0/1"]
    assert again.steps == first.steps


async def test_a_resume_of_a_run_the_journal_does_not_know_ends_failed(toy, open_harness):   # RESUME-3
    toy()
    result = await open_harness(SEQUENCES).sequences.resume("nothing-20260101T000000Z-abcdef")
    assert (result.end, result.record.status) == ("failed", "failed") and result.run_id == "nothing-20260101T000000Z-abcdef"


async def test_the_journal_a_client_registers_is_the_one_a_run_uses(toy, open_harness, asking):
    from agent_core.journals.none import NoJournal

    made = []

    def journal(file, name, run_id):
        made.append((Path(file).name, name, run_id))
        return NoJournal()

    toy(PLAIN)
    harness = open_harness(asking.root, **spike())
    harness.extensions.register("journal", "dbos", journal)
    result = await harness.sequences.run("plain_run", {}, run_id="mine")
    assert result.end == "done" and made == [("journal.sqlite", "spike-corpus", "mine")]


async def test_two_fan_out_runs_that_ask_are_put_one_question_at_a_time_with_their_labels(toy, open_harness, asking):   # Review Focus 4, JOB-6
    toy(ASK)
    person = ToyPerson("red")
    harness = open_harness(asking.root, **spike(person=person))
    result = await harness.sequences.run("ask_all", {"names": ["polars", "ibis"]})
    assert result.end == "done" and result.facts["colours"] == [{"colour": "red"}, {"colour": "red"}]
    assert person.most == 1                                                      # never two questions open at once
    labels = [label.split(" ") for label, _ in person.asked]   # each question with its run's label and its input
    assert sorted(l[0] for l in labels) == ["asker#1", "asker#2"] and sorted(l[1] for l in labels) == ["ibis", "polars"]
    assert [q for _, q in person.asked] == ["Which colour?", "Which colour?"]
    assert result.record.attended is True


async def test_a_fan_out_that_asks_with_nobody_there_ends_needs_input(toy, open_harness, asking):   # JOB-6
    toy(ASK)
    harness = open_harness(asking.root, **spike())
    result = await harness.sequences.run("ask_all", {"names": ["polars", "ibis"]})
    assert result.end == "failed" and result.facts["colours"] == []
    assert [f["reason"] for f in result.facts["colours_failures"]] == ["needs_input", "needs_input"]
    assert [f["reason"] for f in result.record.failures] == ["needs_input", "needs_input"]
    assert result.record.attended is False


async def test_a_node_run_on_another_backend_resolves_its_servers_through_that_backend(toy, open_harness):
    default = toy(PLAIN)
    other = Toy(PLAIN)
    harness = open_harness(FIXTURE, **spike())
    harness.extensions.register("backend", "other", (lambda settings: other, object))
    await harness.nodes.run("plain", {}, backend="other")
    assert default.served is None and set(other.served) == {"tools", "web"}   # the selected backend's `servers` was called
    await harness.nodes.run("plain", {})
    assert set(default.served) == {"tools", "web"}


async def test_a_relative_runs_directory_is_resolved_at_the_boundary_so_a_server_writes_into_it(toy, open_harness, tmp_path, monkeypatch):
    toy({"status": [[("tools__shell", {"command": "echo hi"})], [("exit", {"outcome": "done", "outputs": {"status_report": "ok"}})]]})
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)   # not the instance's directory, where the servers start
    harness = open_harness(FIXTURE, **spike(runs=Path("output")))
    assert harness.runs == elsewhere / "output"
    await harness.nodes.run("status", {})
    assert (elsewhere / "output" / "tool_calls.jsonl").is_file()
    assert not (FIXTURE / "output").exists()


async def test_a_relative_run_directory_of_a_rerun_is_resolved_before_the_environment_is_exported(toy, open_harness, tmp_path, monkeypatch):
    backend = toy({
        "migrate": [[("exit", {"outcome": "done", "outputs": {"entry_count": 3}})]],
        "index": [[("exit", {"outcome": "done", "outputs": {"entries": ["e1"]}})]],
        "verify": [[("exit", {"outcome": "done", "outputs": {"drift": 0}})]],
    })
    harness = open_harness(SEQUENCES)
    first = await harness.sequences.run("chain", {"scan_results": [["e1"]]})
    monkeypatch.chdir(tmp_path)
    await harness.sequences.rerun(first.run_id, 2, run_dir=Path("again"))
    assert backend.environment[-1]["AGENT_CORE_RUN_DIR"] == str(tmp_path / "again") and (tmp_path / "again").is_dir()


async def test_the_record_names_the_sequence_run_fresh_resumed_and_rerun(toy, open_harness):   # JOB-9a
    toy({
        "migrate": [[("exit", {"outcome": "done", "outputs": {"entry_count": 3}})]],
        "index": [[("exit", {"outcome": "done", "outputs": {"entries": ["e1"]}})]],
        "verify": [[("exit", {"outcome": "done", "outputs": {"drift": 0}})]],
    })
    harness = open_harness(SEQUENCES)
    # a run id that does not carry the sequence's name: the name comes from the journal's stored workflow
    first = await harness.sequences.run("chain", {"scan_results": [["e1"]]}, run_id="mine")
    resumed = await harness.sequences.resume("mine")
    again = await harness.sequences.rerun("mine", 2, new_run_id="other")
    assert [r.record.sequence for r in (first, resumed, again)] == ["chain", "chain", "chain"]
