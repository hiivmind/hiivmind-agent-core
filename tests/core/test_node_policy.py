import inspect
import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Callable

import pytest
from support import FIXTURE, FolderSource

from agent_core.contracts.errors import ToolError, ToolServerError
from agent_core.contracts.events import NodeEnded
from agent_core.contracts.loading import load_module
from agent_core.contracts.policy import NodeState, merge
from agent_core.contracts.values import ModelResponse, ToolCall, ToolSpec
from agent_core.core.policy import ALONE, TOGETHER, VERBS, NodePolicy, verb_spec
from agent_core.core.settings import load_settings

SPECS = {v.name: verb_spec(v) for v in VERBS}
JOB_VERBS = tuple(v.name for v in VERBS if v.in_job)

NOT_RUN = "not run: the node run has ended"


def undeclared(name):
    return f"refused: `{name}` is not declared by the node that is running"


@dataclass(frozen=True)
class Fn:
    """What Task 6's `FunctionTool` is: a name, a spec, a callable and the parameters the harness fills."""

    name: str
    spec: ToolSpec
    fn: Callable
    filled: tuple[str, ...]


def fn_tool(fn, name=None):
    name = name or fn.__name__
    parameters = inspect.signature(fn).parameters
    return Fn(name, ToolSpec(name, name, {"type": "object"}), fn, tuple(n for n in ("settings", "state") if n in parameters))


class Servers:
    """A tool source standing for the instance's servers: a shell, a lookup that fails, and a web server that is gone."""

    def __init__(self):
        self.calls = []

    async def tools(self):
        return ()

    async def close(self):
        pass

    async def call(self, name, args, state):
        self.calls.append((name, args, dict(state)))
        if name == "tools__shell":
            return json.dumps({"stdout": args["command"].removeprefix("echo ") + "\n", "exit": 0})
        if name == "tools__lookup":
            raise ToolError(f"no such key: {args['key']}")
        if name == "web__fetch":
            raise ToolServerError("web", "fetch", "stopped answering")
        raise AssertionError(f"the policy called {name}")


class Answering:
    """A person who answers each question with `answer` and remembers what was asked; None: nobody is there."""

    def __init__(self, answer):
        self.answer, self.asked = answer, []

    async def tell(self, text):
        pass

    async def ask(self, question, label=""):
        self.asked.append((question, label))
        return self.answer


class Events:
    def __init__(self):
        self.seen = []

    def emit(self, event):
        self.seen.append(event)


class Files:
    """Resources that say why they cannot read a path, as a folder of the instance does."""

    def __init__(self):
        self.folder = FolderSource(FIXTURE)

    def read(self, path):
        if path.startswith(".."):
            raise ValueError(f"`{path}` is outside the instance")
        try:
            return self.folder.read(path)
        except FileNotFoundError:
            raise FileNotFoundError(f"no file `{path}`") from None

    def exists(self, path):
        return self.folder.exists(path)


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    directory = tmp_path / "run"
    directory.mkdir()
    monkeypatch.setenv("AGENT_CORE_RUN_DIR", str(directory))
    return directory


def function_calls(run_dir, tool):
    file = run_dir / "function_calls.jsonl"
    return [c for c in map(json.loads, file.read_text().splitlines()) if c["tool"] == tool] if file.exists() else []


@pytest.fixture
def settings(instance):
    return load_settings(instance, [instance.root / "config" / "alpha.yaml"])


@pytest.fixture
def made(instance, settings, run_dir):
    """`made(node, inputs, ...)`: a policy of a fixture node and its start state; `.servers`, `.events` are its ports."""
    module = load_module(FIXTURE, "functions")

    def make(node, inputs=None, *, session=None, values=None, person="nobody", label="n#1", extra=(), settings=settings):
        definition = instance.nodes[node]
        functions = {f.name: f for f in (fn_tool(getattr(module, n)) for n in ("count_words", "read_ledger", "locate"))}
        functions.update({f.name: f for f in extra})
        offered = (*JOB_VERBS, *definition.allowed_tools, *(f.name for f in extra))
        specs = tuple(SPECS[n] if n in SPECS else ToolSpec(n, n, {"type": "object"}) for n in offered)
        servers, events = Servers(), Events()
        person = Answering(None) if person == "nobody" else person
        start = NodeState(
            inputs=dict(inputs or {}), values=dict(values or {}), outputs={}, session=dict(session or {}),
            rejections=0, ending=None,
        )
        policy = NodePolicy(
            definition, label=label, instructions="", tools=specs, handover=(), opening="", functions=functions,
            servers=servers, person=person, resources=Files(), settings=settings, events=events, start=start,
        )
        policy.servers, policy.events, policy.person = servers, events, person
        return policy

    return make


@dataclass
class Played:
    state: NodeState
    texts: list          # one per call, in the order given: the refusal, or the call's result text
    errors: list         # one per call: whether it was refused or its result an error
    updates: list        # one per call that ran: its StateUpdate, or None


async def play(policy, responses, *, state=None):
    """Drive the policy as a backend does: review a response, run the calls it did not refuse against the state before
    the response, then merge their updates in the order the calls were given."""
    state = state or policy.initial()
    texts, errors, updates = [], [], []
    for number, calls in enumerate(responses):
        calls = tuple(ToolCall(f"{number}-{i}", name, args) for i, (name, args) in enumerate(calls))
        review = policy.review(ModelResponse("", calls), state)
        results = {}
        for call in calls:
            if call.id in review.refused:
                texts.append(review.refused[call.id])
                errors.append(True)
            else:
                result = await policy.call(call, state)
                results[call.id] = result
                texts.append(result.text)
                errors.append(result.error)
                updates.append(result.update)
        for call in calls:
            if call.id in results and results[call.id].update is not None:
                state = merge(state, results[call.id].update)
    return Played(state, texts, errors, updates)


def exit_with(outcome, outputs):
    return ("exit", {"outcome": outcome, "outputs": outputs})


def shell(command):
    return ("tools__shell", {"command": command})


def set_(key, value):
    return ("state_set", {"key": key, "value": value})


def get(key):
    return ("state_get", {"key": key})


def test_the_verbs_each_have_a_spec_and_three_must_be_alone():
    assert [v.name for v in VERBS] == ["enter", "exit", "ask", "state_set", "state_get", "load"]
    assert all(spec.name == name and spec.description and spec.schema["type"] == "object" for name, spec in SPECS.items())
    assert {v.name for v in VERBS if v.alone} == {"ask", "enter", "exit"}


def test_the_policy_names_its_node_and_starts_from_its_state(made):
    policy = made("refresh", {"sources": "polars"}, label="refresh#3")
    assert policy.node == "refresh" and policy.label == "refresh#3"
    assert policy.initial() == {"inputs": {"sources": "polars"}, "values": {}, "outputs": {}, "session": {},
                                "rejections": 0, "ending": None}
    policy.initial()["inputs"]["x"] = 1
    assert policy.initial()["inputs"] == {"sources": "polars"}  # each run gets its own copy


# --- EXIT -------------------------------------------------------------------------------------------------------


async def test_exit_with_a_wrong_output_is_returned_once_then_accepted(made):          # criterion 3 (b)
    p = await play(made("shape"), [[exit_with("done", {"count": "three"})], [exit_with("done", {"count": 3})]])
    assert p.state["ending"]["outcome"] == "done" and p.state["ending"]["outputs"] == {"count": 3}
    assert p.state["rejections"] == 1 and p.errors == [True, False]
    assert p.texts[0].startswith("the outputs do not match the node's output schema: [")
    assert p.texts[0].endswith("]. Correct them and EXIT again.")
    assert p.updates[0].rejected is True and p.updates[0].ending is None


async def test_two_wrong_outputs_end_as_invalid_output_with_the_errors(made):          # criterion 3 (c), JOB-7b
    p = await play(made("shape"), [[exit_with("done", {"count": "three"})]] * 2)
    ending = p.state["ending"]
    assert ending["outcome"] == "failed" and ending["reason"] == "invalid_output" and ending["outputs"] == {}
    assert ending["detail"]["errors"] == ["count: 'three' is not of type 'integer'"]
    assert p.state["rejections"] == 1  # the second rejection ends the run; it is not another correction


async def test_done_without_a_required_output_is_sent_back(made):                       # JOB-7a
    p = await play(made("shape"), [[exit_with("done", {})], [exit_with("done", {"count": 3})]])
    assert p.state["ending"]["outputs"] == {"count": 3}
    assert "do not match the node's output schema" in p.texts[0] and "count" in p.texts[0]


async def test_an_output_recorded_by_a_tool_counts_on_exit(made, run_dir):             # JOB-7a, criterion 21
    p = await play(made("locate_quiet", {"source": "polars"}), [[("locate", {"source": "polars"})], [exit_with("done", {})]])
    assert p.state["ending"]["outcome"] == "done"
    assert p.state["ending"]["outputs"] == {"path": "/tmp/spike-corpus-alpha/polars"}


async def test_the_value_on_exit_stands_over_one_that_was_recorded(made, run_dir):     # JOB-7a
    p = await play(made("locate_quiet", {"source": "polars"}), [
        [("locate", {"source": "polars"})], [exit_with("done", {"path": "/elsewhere"})]])
    assert p.state["ending"]["outputs"] == {"path": "/elsewhere"}


async def test_an_outcome_the_node_does_not_declare_is_an_error_and_the_run_goes_on(made):   # JOB-7a
    p = await play(made("shape"), [[exit_with("declined", {})], [exit_with("failed", {})]])
    assert p.texts[0] == "`declined` is not an outcome of `shape`; its outcomes are: done, failed, skipped, stopped"
    assert p.errors[0] is True and p.updates[0] is None and p.state["rejections"] == 0
    assert p.state["ending"]["outcome"] == "failed" and p.state["ending"]["outputs"] == {}


@pytest.mark.parametrize("outcome", ["skipped", "stopped"])
async def test_exit_accepts_skipped_and_stopped_for_any_node(made, outcome):           # SEQ-8
    p = await play(made("shape"), [[exit_with(outcome, {})]])
    assert (p.state["ending"]["outcome"], p.state["ending"]["outputs"]) == (outcome, {})


async def test_another_outcome_may_carry_an_undeclared_reason_and_done_may_not(made):  # JOB-13
    p = await play(made("shape"), [[exit_with("failed", {"reason": "no words"})]])
    assert (p.state["ending"]["outcome"], p.state["ending"]["outputs"]) == ("failed", {"reason": "no words"})
    p = await play(made("shape"), [[exit_with("done", {"count": 3, "reason": "x"})]] * 2)
    assert p.state["ending"]["reason"] == "invalid_output"
    assert any("reason" in e for e in p.state["ending"]["detail"]["errors"])


async def test_an_exit_whose_outputs_are_not_an_object_is_sent_back(made):
    p = await play(made("shape"), [[exit_with("failed", "x")], [exit_with("failed", {})]])
    assert "do not match the node's output schema" in p.texts[0] and p.state["ending"]["outputs"] == {}


# --- calls that must be alone ---------------------------------------------------------------------------------


async def test_a_response_with_exit_and_another_call_refuses_both(made):               # example 8, VERB-6b
    policy = made("refresh", {"sources": "polars"})
    response = ModelResponse("", (ToolCall("1", "shell__run", {}), ToolCall("2", "exit", {"outcome": "done"})))
    assert policy.review(response, policy.initial()).refused == {"1": TOGETHER, "2": TOGETHER}


async def test_a_call_beside_exit_refuses_both_and_runs_neither(made):                 # VERB-6
    policy = made("refresh", {"sources": "polars"})
    p = await play(policy, [[shell("echo both"), exit_with("done", {})]])
    assert p.texts == [TOGETHER, TOGETHER] and p.state["ending"] is None and policy.servers.calls == []


@pytest.mark.parametrize("alone", [("ask", {"question": "Which?"}), ("enter", {"node": "status"})])
async def test_a_call_beside_ask_or_enter_is_refused_with_it(made, alone):             # VERB-6a, VERB-6b
    policy = made("refresh")
    p = await play(policy, [[alone, shell("echo both")]])
    assert p.texts == [TOGETHER, TOGETHER] and policy.servers.calls == [] and policy.person.asked == []


async def test_a_response_of_calls_that_may_share_one_runs_them_all(made):             # VERB-6
    policy = made("refresh", {"sources": "polars"})
    p = await play(policy, [[shell("echo one"), shell("echo two")]])
    assert [c[1]["command"] for c in policy.servers.calls] == ["echo one", "echo two"]
    assert not any(t.startswith("refused") for t in p.texts)


# --- what a node declares ------------------------------------------------------------------------------------


async def test_an_undeclared_tool_is_refused_with_todays_text(made):                   # example 3, NODE-6b, criterion 14
    policy = made("plain")
    response = ModelResponse("", (ToolCall("1", "shell__run", {}),))
    assert policy.review(response, policy.initial()).refused == {"1": undeclared("shell__run")}
    p = await play(policy, [[shell("echo plain-work")]])
    assert p.texts == [undeclared("tools__shell")] and policy.servers.calls == []


async def test_another_tool_of_a_server_is_refused_too(made):                          # NODE-6b
    policy = made("refresh", {"sources": "polars"})
    p = await play(policy, [[("tools__note", {"text": "x"})]])
    assert p.texts == [undeclared("tools__note")] and policy.servers.calls == []


async def test_a_refusal_names_only_the_calls_refused(made):
    policy = made("refresh")
    response = ModelResponse("", (ToolCall("1", "tools__shell", {}), ToolCall("2", "tools__note", {})))
    assert policy.review(response, policy.initial()).refused == {"2": undeclared("tools__note")}


# --- state_set, state_get, load ---------------------------------------------------------------------------


async def test_state_set_is_recorded_and_says_so(made):                                # SCOPE-4
    p = await play(made("refresh"), [[set_("sources", "polars")]])
    assert p.texts == ['recorded sources = "polars"'] and p.state["inputs"] == {"sources": "polars"}
    assert (p.updates[0].inputs, p.updates[0].values, p.updates[0].outputs, p.updates[0].session) == (
        {"sources": "polars"}, {}, {}, {})


async def test_state_set_goes_where_the_name_belongs(made):                            # ST-4
    p = await play(made("refresh", {"sources": "polars"}), [[set_("branch", "refresh/alpha")], [set_("scratch", [1, 2])]])
    assert p.state["session"] == {"branch": "refresh/alpha"} and p.state["outputs"] == {"branch": "refresh/alpha"}
    assert p.state["values"] == {"scratch": [1, 2]} and p.texts[1] == "recorded scratch = [1, 2]"
    assert p.state["inputs"] == {"sources": "polars"}


async def test_state_get_reads_inputs_values_and_facts_and_says_when_not_set(made):
    p = await play(made("refresh", {"sources": "polars"}, session={"tag": "t"}),
                   [[set_("scratch", {"a": 1})], [get("sources")], [get("scratch")], [get("tag")], [get("nothing")]])
    assert p.texts[1:] == ['"polars"', '{"a": 1}', '"t"', "not set"]


async def test_state_get_lets_an_input_hide_a_value_and_a_value_hide_a_fact(made):     # TOOL-12
    policy = made("refresh", {"sources": "in"}, session={"sources": "fact", "tag": "fact"}, values={"sources": "value", "tag": "value"})
    p = await play(policy, [[get("sources")], [get("tag")]])
    assert p.texts == ['"in"', '"value"']


async def test_load_reads_a_file_of_the_instance_and_says_when_it_cannot(made):
    p = await play(made("refresh"), [[("load", {"path": "includes/safety.md"})], [("load", {"path": "nothing.md"})],
                                     [("load", {"path": "../outside.md"})]])
    assert p.texts[0] == Files().read("includes/safety.md") and p.errors == [False, True, True]
    assert p.texts[1] == "error: no file `nothing.md`" and p.texts[2] == "error: `../outside.md` is outside the instance"


# --- tools -------------------------------------------------------------------------------------------------------


async def test_a_function_is_given_the_state_and_what_it_wrote_is_recorded_and_listed(made, run_dir):   # TOOL-12
    p = await play(made("locate", {"source": "polars"}), [[("locate", {"source": "polars"})]])
    path = "/tmp/spike-corpus-alpha/polars"
    assert p.texts == [f'{{"path": "{path}"}}\n\n(recorded by this call: path = "{path}", last_located = "polars")']
    assert p.state["session"] == {"path": path} and p.state["outputs"] == {"path": path}
    assert p.state["values"] == {"last_located": "polars"}
    assert function_calls(run_dir, "locate")[0]["args"]["state"] == {"source": "polars"}


async def test_a_function_that_raises_records_nothing_and_the_model_is_told(made):      # TOOL-12, TOOL-11a
    p = await play(made("ledger"), [[("read_ledger", {"name": "main"})]])
    assert p.texts == ["error: read_ledger raised FileNotFoundError: no ledger named main"] and p.errors == [True]
    assert p.updates == [None] and p.state["values"] == {} and p.state["session"] == {}


async def test_a_function_that_writes_nothing_has_nothing_listed(made, run_dir):
    p = await play(made("tally"), [[("count_words", {"text": "one two three"})]])
    assert p.texts == ['{"words": 3}'] and p.updates == [None]


async def test_a_function_gets_the_settings_the_policy_was_made_with(made):            # TOOL-12
    def whose(settings, state):
        return settings.CORPUS_NAME

    extra = (fn_tool(whose),)
    for name in ("alpha", "beta"):
        policy = made("plain", extra=extra, settings=SimpleNamespace(CORPUS_NAME=name))
        p = await play(policy, [[("whose", {})]])
        assert p.texts == [name]


async def test_a_servers_own_error_goes_to_the_model_as_its_message(made):             # TOOL-11a
    p = await play(made("consult"), [[("tools__lookup", {"key": "motto"})]])
    assert p.texts == ["error: no such key: motto"] and p.errors == [True] and p.state["ending"] is None


async def test_a_servers_text_is_the_result_and_is_called_with_no_state(made):
    policy = made("refresh", {"sources": "polars"})
    p = await play(policy, [[shell("echo hi")]])
    assert '"stdout": "hi\\n"' in p.texts[0] and not p.errors[0]
    assert policy.servers.calls == [("tools__shell", {"command": "echo hi"}, {})]


async def test_a_server_that_stops_answering_raises_tool_server_error(made):           # TOOL-11e
    policy = made("fetcher")
    with pytest.raises(ToolServerError, match="web"):
        await policy.call(ToolCall("1", "web__fetch", {"url": "https://example.org/a"}), policy.initial())


# --- one response ---------------------------------------------------------------------------------------------


async def test_a_failed_calls_writes_are_dropped_and_the_others_applied_in_order(made):   # Review Focus 3, CTL-5
    def f_ok(state):
        state["a"] = 1
        return "ok"

    def g_raise(state):
        state["b"] = 2
        raise RuntimeError("after writing")

    policy = made("plain", extra=(fn_tool(f_ok), fn_tool(g_raise)))
    p = await play(policy, [[("f_ok", {}), ("g_raise", {})]])
    assert p.texts == ["ok\n\n(recorded by this call: a = 1)", "error: g_raise raised RuntimeError: after writing"]
    assert p.state["values"] == {"a": 1}


async def test_each_call_of_a_response_sees_the_state_before_it(made):                  # CTL-5, TOOL-12
    def reads(state):
        return json.dumps(state.get("x", "not set"))

    policy = made("plain", extra=(fn_tool(reads),))
    p = await play(policy, [[set_("x", 1), ("reads", {}), get("x")]])
    assert p.texts == ['recorded x = 1', '"not set"', "not set"] and p.state["values"] == {"x": 1}
    p = await play(policy, [[set_("x", 1)], [("reads", {})]])
    assert p.texts[1] == "1"  # a value set in an earlier response is seen


async def test_what_the_calls_of_a_response_wrote_is_applied_in_its_order(made):       # CTL-5, VERB-6c
    p = await play(made("locate", {"source": "polars"}), [[set_("phase", "first"), get("phase"), set_("phase", "second"), get("phase")]])
    assert p.texts == ['recorded phase = "first"', "not set", 'recorded phase = "second"', "not set"]
    assert p.state["values"] == {"phase": "second"}


# --- ask --------------------------------------------------------------------------------------------------------


async def test_ask_with_nobody_there_ends_needs_input(made):                           # JOB-6, criterion 3 (a)
    p = await play(made("refresh"), [[("ask", {"question": "Which sources should I update?"})]])
    ending = p.state["ending"]
    assert (ending["outcome"], ending["reason"], ending["outputs"]) == ("failed", "needs_input", {})
    assert ending["detail"] == {"question": "Which sources should I update?"}


async def test_a_person_answers_with_the_run_label_given_and_the_answer_is_the_result(made):   # JOB-6
    person = Answering("polars")
    p = await play(made("refresh", person=person, label="refresh#3"),
                   [[("ask", {"question": "Which sources should I update?"})], [set_("sources", "polars")]])
    assert person.asked == [("Which sources should I update?", "refresh#3")]
    assert p.texts[0] == "polars" and p.state["ending"] is None and p.updates[0] is None


# --- the end of the run ---------------------------------------------------------------------------------------


async def test_after_the_run_has_ended_a_call_is_refused_and_not_run(made):            # CTL-7, VERB-6a
    policy = made("refresh", {"sources": "polars"})
    p = await play(policy, [[exit_with("failed", {})], [shell("echo late"), set_("late", 1)]])
    assert p.texts[1:] == [NOT_RUN, NOT_RUN] and p.errors[1:] == [True, True]
    assert policy.servers.calls == [] and "late" not in p.state["values"]
    assert p.state["ending"]["outcome"] == "failed" and p.state["ending"]["outputs"] == {}


async def test_the_model_stopping_ends_a_job_without_a_reply(made):                    # JOB-12
    policy = made("silent")
    assert policy.stopped("I will not exit.", policy.initial()) is None


async def test_finish_turns_an_ending_into_a_unit_result(made):
    policy = made("shape")
    p = await play(policy, [[exit_with("done", {"count": 3})]])
    result = policy.finish(p.state, "")
    assert (result.exit, result.outputs, result.reason, result.detail) == ("done", {"count": 3}, None, {})


async def test_finish_carries_a_harness_reason_beside_the_outputs(made):
    policy = made("shape")
    p = await play(policy, [[exit_with("done", {"count": "three"})]] * 2)
    result = policy.finish(p.state, "")
    assert (result.exit, result.outputs, result.reason) == ("failed", {}, "invalid_output")
    assert result.detail["errors"]


async def test_finish_without_an_ending_is_no_exit_with_what_the_model_said(made):     # JOB-12
    policy = made("silent")
    result = policy.finish(policy.initial(), "I will not exit.")
    assert (result.exit, result.outputs, result.reason, result.detail) == ("failed", {}, "no_exit", {"said": "I will not exit."})


async def test_finish_emits_node_ended(made):
    policy = made("shape", label="shape#2")
    p = await play(policy, [[exit_with("done", {"count": 3})]])
    policy.finish(p.state, "")
    ended = made("silent", label="silent#1")
    ended.finish(ended.initial(), "")
    assert policy.events.seen == [NodeEnded("shape#2", "shape", "done", None)]
    assert ended.events.seen == [NodeEnded("silent#1", "silent", "failed", "no_exit")]
